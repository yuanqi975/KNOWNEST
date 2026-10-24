"""Opt-in real PostgreSQL/pgvector + Redis checks. Creates and drops only a unique test DB."""
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pathlib import Path
from fastapi import HTTPException
from redis import Redis
from sqlalchemy import create_engine, text, select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.models.models import User, Workspace, KnowledgeBase, ChatSession, ChatMessage, MemoryEmbedding, BackgroundJob
from app.schemas import MessageRequest
from app.services import memory, chat_runs, background, context_cache

pytestmark = pytest.mark.skipif(not os.environ.get("CONTEXT_TEST_DATABASE_URL"), reason="Set CONTEXT_TEST_DATABASE_URL for isolated real-storage tests")


@pytest.fixture
def storage(monkeypatch):
    url = os.environ["CONTEXT_TEST_DATABASE_URL"]
    admin = create_engine(url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5})
    name = "knownest_context_test_" + uuid4().hex
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(admin.url.set(database=name), connect_args={"connect_timeout": 5})
    try:
        # Exercise adoption of an actual pre-migration history, including tied timestamps.
        with engine.begin() as connection:
            connection.execute(text("""CREATE TABLE chat_sessions (
                id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL, workspace_id VARCHAR(36) NOT NULL,
                knowledge_base_id VARCHAR(36), model_id VARCHAR(36), mode VARCHAR(16) NOT NULL,
                title VARCHAR(255) NOT NULL, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL)"""))
            connection.execute(text("""CREATE TABLE chat_messages (
                id VARCHAR(36) PRIMARY KEY, session_id VARCHAR(36) REFERENCES chat_sessions(id) ON DELETE CASCADE,
                role VARCHAR(20) NOT NULL, content TEXT NOT NULL, provider VARCHAR(30), latency_ms INTEGER,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL)"""))
            connection.execute(text("INSERT INTO chat_sessions (id,user_id,workspace_id,mode,title) VALUES ('legacy','u','w','rag','old')"))
            connection.execute(text("INSERT INTO chat_messages (id,session_id,role,content) VALUES ('a','legacy','user','old question'),('b','legacy','assistant','old answer')"))
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            command.upgrade(config, "head")
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as db:
            db.add(User(id="u", username="integration", password_hash="unused")); db.flush()
            db.add(Workspace(id="w", owner_id="u", name="workspace")); db.flush()
            db.add_all([KnowledgeBase(id="kb", workspace_id="w", name="kb"), KnowledgeBase(id="kb2", workspace_id="w", name="kb2")]); db.flush()
            db.add(ChatSession(id="s", user_id="u", workspace_id="w", knowledge_base_id="kb", mode="conversation"))
            db.commit()
        redis = Redis.from_url(os.environ.get("CONTEXT_TEST_REDIS_URL", "redis://127.0.0.1:6379/15"), decode_responses=True,
                               socket_connect_timeout=1, socket_timeout=1)
        redis.ping()
        prefix = name + ":"
        monkeypatch.setattr(context_cache, "client", lambda: redis)
        monkeypatch.setattr(context_cache, "key", lambda value: prefix + value)
        monkeypatch.setattr(get_settings(), "context_cache_enabled", True)
        yield factory, redis, prefix
        keys = list(redis.scan_iter(match=prefix + "*"))
        if keys:
            redis.delete(*keys)
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid <> pg_backend_pid()"), {"name": name})
            connection.execute(text(f'DROP DATABASE "{name}"'))
        admin.dispose()


def test_real_migration_vector_recall_cache_and_deletion(storage, monkeypatch):
    factory, redis, prefix = storage
    vector = [1.0] + [0.0] * 4095
    async def embed(self, values):
        return [vector for _ in values]
    monkeypatch.setattr(memory.EmbeddingProvider, "embed", embed)
    with factory() as db:
        assert [m.sequence for m in db.scalars(select(ChatMessage).where(ChatMessage.session_id == "legacy").order_by(ChatMessage.sequence))] == [1, 2]
        assert db.get(ChatSession, "legacy").next_sequence == 3
        item = memory.create(db, "u", "w", "Redis 缓存是可重建的", kb_id="kb")
        hidden = memory.create(db, "u", "w", "另一知识库不可见", "preference", kb_id="kb2")
        db.commit()
        job = db.scalar(select(BackgroundJob).where(BackgroundJob.memory_id == item.id))
        asyncio.run(background.process(db, job.id))
        assert db.get(MemoryEmbedding, item.id).dimension == 4096
        hits, degraded = asyncio.run(memory.recall(db, db.get(ChatSession, "s"), "可重建缓存"))
        assert not degraded and item.id in [m.id for m in hits]
        assert hidden.id not in [m.id for m in hits]
        assert list(redis.scan_iter(match=prefix + "mem:*"))
        def unavailable():
            raise ConnectionError("Redis unavailable")
        monkeypatch.setattr(context_cache, "client", unavailable)
        fallback, _ = asyncio.run(memory.recall(db, db.get(ChatSession, "s"), "Redis 可重建缓存"))
        assert item.id in [m.id for m in fallback]
        memory.remove(db, item); db.commit()
        hits, _ = asyncio.run(memory.recall(db, db.get(ChatSession, "s"), "可重建缓存"))
        assert not hits
        assert db.get(MemoryEmbedding, item.id) is None


def test_real_concurrent_start_and_cross_connection_cancellation(storage):
    factory, _, _ = storage
    barrier = Barrier(2)
    def start(request_id):
        with factory() as db:
            session = db.get(ChatSession, "s")
            barrier.wait(timeout=5)
            try:
                run, _ = chat_runs.start(db, session, MessageRequest(content="question", client_request_id=request_id), "agent")
                return run.id
            except HTTPException as exc:
                assert exc.status_code == 409
                return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(start, ["one", "two"]))
    ids = [r for r in results if r]
    assert len(ids) == 1
    with factory() as reader, factory() as writer:
        assert chat_runs.alive(reader, ids[0])
        chat_runs.cancel(writer, "s")
        assert not chat_runs.alive(reader, ids[0])
        with pytest.raises(ValueError):
            chat_runs.finish(reader, ids[0], "cancelled", "fake", [])


def test_real_redis_broker_worker_processes_durable_job(storage):
    import time
    from celery import Celery
    from celery.contrib.testing.worker import start_worker
    factory, _, prefix = storage
    app = Celery("context-integration", broker=os.environ.get("CONTEXT_TEST_REDIS_URL", "redis://127.0.0.1:6379/15"))
    queue = prefix + "queue"
    app.conf.update(task_default_queue=queue, task_ignore_result=True,
                    broker_transport_options={"global_keyprefix": prefix}, worker_prefetch_multiplier=1)
    @app.task(name="context-integration.process")
    def process_job(job_id):
        with factory() as db:
            asyncio.run(background.process(db, job_id))
    with factory() as db:
        job = BackgroundJob(workspace_id="w", session_id="s", kind="cache", dedupe_key="broker-smoke",
                            payload={"run_id": "broker-smoke"})
        db.add(job); db.commit(); job_id = job.id
    with start_worker(app, pool="solo", concurrency=1, perform_ping_check=False, queues=[queue], shutdown_timeout=10):
        with factory() as db:
            background.dispatch(db, lambda id_, queue: process_job.apply_async(args=[id_], queue=app.conf.task_default_queue))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with factory() as db:
                job = db.get(BackgroundJob, job_id)
                if job.status == "done":
                    assert job.attempts == 1
                    break
            time.sleep(0.1)
        else:
            pytest.fail("Real Celery worker did not complete the database outbox job")
    app.close()

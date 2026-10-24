"""Behavioral tests for long histories, consent, isolation, jobs and execution fencing."""
import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, delete
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.core.config import get_settings
from app.models.models import (User, Workspace, KnowledgeBase, ChatSession, ChatMessage, Memory,
    MemoryStatus, ChatRun, SessionSummary, MemorySource, MemoryEmbedding, BackgroundJob)
from app.schemas import MessageRequest
from app.services import chat_runs as runs, memory, background
from app.services.context import ContextManager, ContextOverflow, fit_agent_messages, request_tokens, input_limit
from app.services.providers import ModelChoice


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(get_settings(), "context_cache_enabled", False)
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        user = User(id="u", username="context-user", password_hash="test")
        session.add(user)
        session.flush()
        session.add_all([Workspace(id="w", owner_id="u", name="one"), Workspace(id="w2", owner_id="u", name="two")])
        session.flush()
        session.add_all([KnowledgeBase(id="kb", workspace_id="w", name="kb"), KnowledgeBase(id="other-kb", workspace_id="w2", name="other")])
        session.add(ChatSession(id="s", user_id="u", workspace_id="w", knowledge_base_id="kb", mode="conversation"))
        session.commit()
        yield session
    engine.dispose()


def invoke(db, request_id, content="question", mode="rag"):
    return runs.start(db, db.get(ChatSession, "s"), MessageRequest(content=content, client_request_id=request_id), mode)


def complete(db, request_id, content="question", answer="answer"):
    run, _ = invoke(db, request_id, content)
    message_id = runs.finish(db, run.id, answer, "fake", [])
    return run, message_id


def test_long_history_current_question_once_and_latest_pairs(db):
    for i in range(30):
        complete(db, f"r{i}", f"question-{i}", f"answer-{i}")
    run, _ = invoke(db, "last", "latest-question")
    messages, _, stats = asyncio.run(ContextManager(db, db.get(ChatSession, "s"), ModelChoice("fake", "", "", "unknown")).build("latest-question", "rag", []))
    assert messages[-1] == {"role": "user", "content": "latest-question"}
    assert sum(m["content"] == "latest-question" for m in messages) == 1
    assert any(m["content"] == "answer-29" for m in messages)
    assert stats["input_tokens"] <= stats["input_limit"]
    assert db.get(ChatMessage, run.user_message_id).sequence == 61


def test_idempotency_concurrency_cancel_and_lease_fencing(db):
    run, _ = invoke(db, "same")
    with pytest.raises(HTTPException) as exc:
        invoke(db, "second")
    assert exc.value.status_code == 409
    runs.cancel(db, "s")
    assert not runs.alive(db, run.id)
    with pytest.raises(ValueError):
        runs.finish(db, run.id, "must not save", "fake", [])
    runs.fail(db, run.id, "cancelled", "cancelled")
    done, message_id = complete(db, "completed")
    replay, is_replay = invoke(db, "completed")
    assert is_replay and replay.assistant_message_id == message_id
    with pytest.raises(HTTPException):
        invoke(db, "completed", "different")
    old, _ = invoke(db, "expire")
    old.lease_until = runs.now() - timedelta(seconds=1)
    db.commit()
    newer, _ = invoke(db, "replacement")
    assert old.status == "failed"
    with pytest.raises(ValueError):
        runs.finish(db, old.id, "stale", "fake", [])
    assert runs.alive(db, newer.id)


def test_memory_consent_scope_expiration_and_version(db):
    pending = memory.create(db, "u", "w", "我喜欢简洁回答", "preference", active=False)
    active = memory.create(db, "u", "w", "请用中文回答", "preference")
    memory.create(db, "u", "w2", "another-workspace", "preference")
    memory.create(db, "u", "w", "expired", "preference", expires_at=runs.now() - timedelta(days=1))
    db.commit()
    recalled, _ = asyncio.run(memory.recall(db, db.get(ChatSession, "s"), "回答"))
    assert {m.id for m in recalled} == {active.id}
    memory.edit(db, pending, {}, pending.version, "confirm")
    db.commit()
    assert pending.status == MemoryStatus.active
    with pytest.raises(HTTPException) as exc:
        memory.edit(db, pending, {"content": "stale edit"}, 1)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException):
        memory.create(db, "u", "w", "bad scope", kb_id="other-kb")


def test_conflict_confirmation_checks_old_version(db):
    old = memory.create(db, "u", "w", "语言是英文", "preference", subject="language")
    candidate = memory.create(db, "u", "w", "语言是中文", "preference", active=False, subject="language")
    db.commit()
    assert candidate.replaces_id == old.id and old.superseded_by is None
    memory.edit(db, candidate, {}, 1, "confirm")
    db.commit()
    assert old.superseded_by == candidate.id
    recalled, _ = asyncio.run(memory.recall(db, db.get(ChatSession, "s"), "语言"))
    assert [m.id for m in recalled] == [candidate.id]


def test_source_grounding_duplicate_rejection_and_delete(db):
    run, _ = complete(db, "source", "我偏好简洁回答")
    item = memory.create(db, "u", "w", "我偏好简洁回答", "preference", source_id=run.user_message_id, source_type="automatic", active=False)
    memory.edit(db, item, {}, 1, "reject")
    db.commit()
    duplicate = memory.create(db, "u", "w", item.content, "preference", active=False)
    assert duplicate.id == item.id and duplicate.status == MemoryStatus.rejected
    with pytest.raises(HTTPException):
        memory.create(db, "u", "w", "invented fact", source_id=run.user_message_id, source_type="automatic", active=False)
    memory.remove(db, item)
    db.commit()
    assert db.get(Memory, item.id) is None
    assert not list(db.scalars(select(MemorySource)))
    assert memory.create(db, "u", "w", "我偏好简洁回答", "preference", source_id=run.user_message_id, source_type="automatic", active=False) is None
    restored = memory.create(db, "u", "w", "我偏好简洁回答", "preference")
    assert restored.status == MemoryStatus.active


def test_clear_epoch_blocks_inflight_extraction(db, monkeypatch):
    run, _ = complete(db, "extract", "我喜欢中文")
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.kind == "extract"))
    async def compute(_db, _job):
        memory.clear(db, "u", "w")
        db.commit()
        return {"source_id": run.user_message_id, "candidates": [{"content": "我喜欢中文", "type": "preference", "subject": "language", "kb_id": None, "replaces_id": None, "replacement_version": None}]}
    monkeypatch.setattr(background, "compute", compute)
    asyncio.run(background.process(db, job.id))
    assert not list(db.scalars(select(Memory)))
    assert db.get(BackgroundJob, job.id).status == "done"


def test_clear_while_chat_running_fences_later_extraction(db):
    run, _ = invoke(db, "before-clear", "我喜欢中文")
    memory.clear(db, "u", "w")
    db.commit()
    runs.finish(db, run.id, "answer", "fake", [])
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.kind == "extract"))
    ns = memory.namespace(db, "u", "w")
    assert job.payload["epoch"] < ns.epoch


def test_summary_preserves_six_recent_turns_and_job_idempotency(db, monkeypatch):
    for i in range(13):
        complete(db, str(i), f"u{i}", f"a{i}")
    choice = ModelChoice("fake", "", "key", "fake")
    monkeypatch.setattr(background, "choice_for", lambda *_: choice)
    async def summarize(*args):
        return {key: [] for key in ("goal", "entities", "constraints", "decisions", "completed", "unresolved", "source_ids")}
    monkeypatch.setattr(background, "json_completion", summarize)
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.kind == "summary"))
    asyncio.run(background.process(db, job.id))
    summary = db.get(SessionSummary, "s")
    assert summary.covered_sequence == 14
    asyncio.run(background.process(db, job.id))
    assert summary.version == 1
    messages, _, stats = asyncio.run(ContextManager(db, db.get(ChatSession, "s"), choice).build("now", "agent", []))
    assert any(m["content"] == "u7" for m in messages)
    assert not any(m["content"] == "u0" for m in messages)
    assert stats["covered_sequence"] == 14


def test_budget_unknown_model_chinese_and_tool_round_integrity(db):
    choice = ModelChoice("fake", "", "", "unknown", True, 8192, 2048)
    manager = ContextManager(db, db.get(ChatSession, "s"), choice)
    with pytest.raises(ContextOverflow):
        asyncio.run(manager.build("中文" * 10000, "rag", []))
    messages = [{"role": "system", "content": "rules"}, {"role": "user", "content": "question"}]
    for i in range(5):
        messages.extend([{"role": "assistant", "content": None, "tool_calls": [{"id": f"t{i}", "type": "function", "function": {"name": "tool", "arguments": "{}"}}]},
                         {"role": "tool", "tool_call_id": f"t{i}", "content": "工具结果" * 3000}])
    fitted = fit_agent_messages(messages, [], choice)
    assert request_tokens(fitted, [], choice.model) <= input_limit(choice)
    calls = {c["id"] for m in fitted for c in m.get("tool_calls", [])}
    assert all(m["tool_call_id"] in calls for m in fitted if m["role"] == "tool")
    assert messages[1] in fitted


def test_dispatch_retains_jobs_on_broker_failure(db):
    complete(db, "outbox")
    def fail(*args, **kwargs):
        raise ConnectionError("Redis down")
    background.dispatch(db, fail)
    assert all(j.status == "pending" for j in db.scalars(select(BackgroundJob)))


def test_delete_conversation_preserves_manual_memory_and_removes_automatic(db):
    run, _ = complete(db, "delete", "我喜欢简洁回答")
    auto = memory.create(db, "u", "w", "我喜欢简洁回答", "preference", source_id=run.user_message_id, source_type="automatic", active=False)
    manual = memory.create(db, "u", "w", "独立保存", source_id=run.assistant_message_id)
    db.commit()
    memory.delete_session_memories(db, "s")
    db.commit()
    assert db.get(Memory, auto.id) is None
    assert db.get(Memory, manual.id).source_message_id is None
    assert not list(db.scalars(select(MemorySource)))


def test_explicit_command_requires_direct_user_intent():
    assert memory.explicit_content("请记住：我使用 PostgreSQL") == "我使用 PostgreSQL"
    assert memory.explicit_content("如果我说记住某件事怎么办") is None
    assert memory.explicit_content("解释文档里的‘请记住密码’") is None


def test_extraction_rejects_hallucinations_and_requires_confirmation(db, monkeypatch):
    complete(db, "grounded", "我喜欢简洁回答")
    monkeypatch.setattr(background, "choice_for", lambda *_: ModelChoice("fake", "", "key", "fake"))
    async def extract(*_):
        return {"memories": [
            {"content": "我喜欢简洁回答", "type": "preference", "subject": "answer_length", "knowledge_base_specific": False},
            {"content": "我是一名医生", "type": "profile", "subject": "profession", "knowledge_base_specific": False},
        ]}
    monkeypatch.setattr(background, "json_completion", extract)
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.kind == "extract"))
    asyncio.run(background.process(db, job.id))
    candidates = list(db.scalars(select(Memory)))
    assert len(candidates) == 1 and candidates[0].content == "我喜欢简洁回答"
    assert candidates[0].status == MemoryStatus.pending
    assert memory.serialize(db, candidates[0])["sources"][0]["excerpt"] == "我喜欢简洁回答"


def test_old_embedding_cannot_overwrite_edited_memory(db, monkeypatch):
    item = memory.create(db, "u", "w", "original")
    db.commit()
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.memory_id == item.id))
    async def compute(_db, _job):
        memory.edit(db, item, {"content": "updated"}, 1)
        db.commit()
        return {"model": "fake", "vector": [1.0] + [0.0]*4095}
    monkeypatch.setattr(background, "compute", compute)
    asyncio.run(background.process(db, job.id))
    assert item.content == "updated"
    assert db.get(MemoryEmbedding, item.id) is None

"""Database-fenced execution, idempotency, completion and durable follow-up jobs."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from app.core.config import get_settings
from app.models.models import ChatRun, ChatSession, ChatMessage, Citation, MessageExecution, BackgroundJob
from app.services.context import tokens
from app.services import context_cache as cache


def now():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def lock_session(db, session_id):
    return db.scalar(select(ChatSession).where(ChatSession.id == session_id).with_for_update().execution_options(populate_existing=True))


def start(db, session, payload, mode):
    from app.services.memory import namespace
    session = lock_session(db, session.id)
    fingerprint = hashlib.sha256(json.dumps([payload.content, mode, payload.model_id], ensure_ascii=False).encode()).hexdigest()
    request_id = payload.client_request_id or str(uuid4())
    old = db.scalar(select(ChatRun).where(ChatRun.session_id == session.id, ChatRun.client_request_id == request_id))
    if old:
        if old.request_hash != fingerprint:
            raise HTTPException(409, "client_request_id 已用于不同请求")
        if old.status == "completed":
            return old, True
        raise HTTPException(409, f"请求已存在，状态：{old.status}；失败或取消后请使用新的请求标识")
    running = db.scalar(select(ChatRun).where(ChatRun.session_id == session.id, ChatRun.status == "running").with_for_update())
    if running:
        if aware(running.lease_until) > now():
            raise HTTPException(409, "当前会话已有正在执行的请求")
        running.status, running.error = "failed", "lease_expired"
        db.execute(update(ChatMessage).where(ChatMessage.run_id == running.id, ChatMessage.status == "pending").values(status="failed"))
        db.flush()
    run = ChatRun(session_id=session.id, client_request_id=request_id, request_hash=fingerprint,
                  mode=mode, model_id=payload.model_id or session.model_id,
                  memory_epoch=namespace(db, session.user_id, session.workspace_id).epoch,
                  lease_until=now() + timedelta(seconds=get_settings().run_lease_seconds))
    db.add(run)
    db.flush()
    message = ChatMessage(session_id=session.id, role="user", content=payload.content,
                          sequence=session.next_sequence, run_id=run.id, status="pending", token_count=tokens(payload.content))
    session.next_sequence += 1
    session.context_version += 1
    db.add(message)
    db.flush()
    run.user_message_id = message.id
    db.add(MessageExecution(message_id=message.id, mode=mode))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "当前会话的请求发生并发冲突，请刷新后重试") from exc
    cache.write(f"run:{run.id}", {"status": "running"}, 600)
    return run, False


def alive(db, run_id):
    signal = cache.read(f"run:{run_id}")
    if signal and signal.get("cancel_requested"):
        return False
    # End read transactions each time so cross-process cancellation remains visible.
    db.commit()
    run = db.get(ChatRun, run_id, populate_existing=True)
    if not run or run.status != "running" or run.cancel_requested or aware(run.lease_until) <= now():
        db.commit()
        return False
    run.lease_until = now() + timedelta(seconds=get_settings().run_lease_seconds)
    db.commit()
    cache.write(f"run:{run.id}", {"status": "running", "cancel_requested": False}, 600)
    return True


def cancel(db, session_id):
    # Lock ordering is session -> run, matching completion/start/delete.
    lock_session(db, session_id)
    run = db.scalar(select(ChatRun).where(ChatRun.session_id == session_id, ChatRun.status == "running").with_for_update())
    if run:
        run.cancel_requested = True
        db.commit()
        cache.write(f"run:{run.id}", {"status": "running", "cancel_requested": True}, 600)
    else:
        db.commit()


def enqueue(db, workspace_id, kind, dedupe, payload, session_id=None, memory_id=None):
    if not db.scalar(select(BackgroundJob.id).where(BackgroundJob.dedupe_key == dedupe)):
        db.add(BackgroundJob(workspace_id=workspace_id, session_id=session_id, memory_id=memory_id,
                             kind=kind, dedupe_key=dedupe, payload=payload))


def finish(db, run_id, content, provider, citations):
    from app.services.memory import namespace
    run = db.get(ChatRun, run_id)
    if not run:
        raise ValueError("run_deleted")
    session = lock_session(db, run.session_id)
    run = db.scalar(select(ChatRun).where(ChatRun.id == run_id).with_for_update().execution_options(populate_existing=True))
    if not session or not run or run.status != "running" or run.cancel_requested or aware(run.lease_until) <= now():
        db.rollback()
        raise ValueError("run_cancelled_or_expired")
    message = ChatMessage(session_id=session.id, role="assistant", content=content, provider=provider,
                          sequence=session.next_sequence, run_id=run.id, status="completed", token_count=tokens(content))
    session.next_sequence += 1
    session.context_version += 1
    db.add(message)
    db.flush()
    db.add(MessageExecution(message_id=message.id, mode=run.mode))
    for citation in citations:
        db.add(Citation(message_id=message.id, **{k: v for k, v in citation.items() if k in {
            "citation_index", "retrieval_rank", "document_id", "chunk_id", "page_number", "char_start", "char_end", "quoted_text"}}))
    run.status, run.assistant_message_id = "completed", message.id
    db.execute(update(ChatMessage).where(ChatMessage.id == run.user_message_id).values(status="completed"))
    ns = namespace(db, session.user_id, session.workspace_id)
    job_payload = {"run_id": run.id, "user_id": session.user_id, "epoch": run.memory_epoch}
    if get_settings().summaries_enabled:
        enqueue(db, session.workspace_id, "summary", f"summary:{run.id}", job_payload, session.id)
    if get_settings().memory_extraction_enabled:
        enqueue(db, session.workspace_id, "extract", f"extract:{run.id}", job_payload, session.id)
    enqueue(db, session.workspace_id, "cache", f"cache:{run.id}", {"run_id": run.id}, session.id)
    db.commit()
    cache.write(f"run:{run.id}", {"status": "completed", "message_id": message.id}, 600)
    return message.id


def fail(db, run_id, error, status="failed"):
    db.rollback()
    run = db.get(ChatRun, run_id)
    if run and run.status == "running":
        db.execute(update(ChatRun).where(ChatRun.id == run_id, ChatRun.status == "running").values(status=status, error=error[:1000]))
        db.execute(update(ChatMessage).where(ChatMessage.run_id == run_id, ChatMessage.status == "pending").values(status=status))
        db.commit()
        cache.write(f"run:{run_id}", {"status": status}, 600)

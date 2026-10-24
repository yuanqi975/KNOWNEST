"""Workspace-scoped memory lifecycle. Every mutation fences old worker results."""
from __future__ import annotations
import asyncio
import hashlib
import json
import re
import logging
import time
from datetime import datetime, timezone
from sqlalchemy import delete, or_, select, text
from fastapi import HTTPException
from app.core.config import get_settings
from app.models.models import (Memory, MemoryStatus, MemoryNamespace, MemorySource, MemoryEvent,
                               MemoryEmbedding, ChatMessage, ChatSession, KnowledgeBase, BackgroundJob)
from app.services import context_cache as cache
from app.services.retrieval import lexical_terms, bm25_scores
from app.services.providers import EmbeddingProvider

TYPES = {"profile", "preference", "fact", "task", "interest"}
log = logging.getLogger(__name__)


def fingerprint(content):
    return hashlib.sha256(" ".join(content.lower().split()).encode()).hexdigest()


def namespace(db, user_id, workspace_id):
    db.flush()
    values = dict(user_id=user_id, workspace_id=workspace_id, version=1, epoch=1, blocked_fingerprints=[])
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    db.execute(insert(MemoryNamespace).values(**values).on_conflict_do_nothing())
    return db.scalar(select(MemoryNamespace).where(
        MemoryNamespace.user_id == user_id, MemoryNamespace.workspace_id == workspace_id,
    ).with_for_update().execution_options(populate_existing=True))


def validate_scope(db, workspace_id, kb_id):
    if kb_id and not db.scalar(select(KnowledgeBase.id).where(KnowledgeBase.id == kb_id, KnowledgeBase.workspace_id == workspace_id)):
        raise HTTPException(400, "知识库不属于当前工作空间")


def record(db, item, action, ns):
    ns.version += 1
    db.add(MemoryEvent(memory_id=item.id, action=action, version=item.version))
    db.execute(delete(MemoryEmbedding).where(MemoryEmbedding.memory_id == item.id))
    if item.status == MemoryStatus.active and not item.superseded_by:
        from app.services.chat_runs import enqueue
        enqueue(db, item.workspace_id, "embed", f"embed:{item.id}:{item.version}",
                {"user_id": item.user_id, "version": item.version, "epoch": ns.epoch}, memory_id=item.id)


def serialize(db, item):
    sources = list(db.scalars(select(MemorySource).where(MemorySource.memory_id == item.id)))
    old = db.get(Memory, item.replaces_id) if item.replaces_id else None
    return {"id": item.id, "type": item.type, "content": item.content, "status": item.status.value,
            "confidence": item.confidence, "version": item.version, "knowledge_base_id": item.knowledge_base_id,
            "source_type": item.source_type, "expires_at": item.expires_at, "superseded_by": item.superseded_by,
            "replaces_id": item.replaces_id, "conflict_version": item.conflict_version,
            "conflict": {"id": old.id, "content": old.content, "version": old.version} if old else None,
            "sources": [{"message_id": s.message_id, "excerpt": s.excerpt} for s in sources]}


def create(db, user_id, workspace_id, content, type_="fact", kb_id=None, source_id=None,
           source_type="manual", active=True, expires_at=None, replaces_id=None, subject=None, expected_epoch=None):
    validate_scope(db, workspace_id, kb_id)
    if type_ not in TYPES or not content.strip() or len(content) > 2000:
        raise HTTPException(422, "记忆类型或长度无效")
    ns = namespace(db, user_id, workspace_id)
    if expected_epoch is not None and ns.epoch != expected_epoch:
        return None
    if source_type == "automatic" and f"source:{source_id}" in (ns.blocked_fingerprints or []):
        return None
    source = db.get(ChatMessage, source_id) if source_id else None
    if source_id:
        session = db.get(ChatSession, source.session_id) if source else None
        if not session or session.user_id != user_id or session.workspace_id != workspace_id:
            raise HTTPException(404, "来源消息不存在")
        if kb_id and session.knowledge_base_id != kb_id:
            raise HTTPException(400, "来源知识库不匹配")
        if source_type == "automatic" and (source.role != "user" or content not in source.content):
            raise HTTPException(422, "候选记忆必须有用户原文依据")
    fp = fingerprint(content)
    blocked_key = f"{kb_id or '*'}:{fp}"
    blocked = ns.blocked_fingerprints or []
    if source_type == "automatic" and blocked_key in blocked:
        return None
    if active and blocked_key in blocked:
        ns.blocked_fingerprints = [x for x in blocked if x != blocked_key]
    existing = db.scalar(select(Memory).where(Memory.user_id == user_id, Memory.workspace_id == workspace_id,
                         Memory.knowledge_base_id == kb_id, Memory.fingerprint == fp))
    if existing:
        if active and existing.superseded_by:
            raise HTTPException(409, "该内容已被后续记忆替代，请核对当前有效记忆")
        # Rejected candidates are not offered again. Explicit saving can restore them.
        if active and existing.status != MemoryStatus.active:
            existing.status, existing.version = MemoryStatus.active, existing.version + 1
            existing.source_type = source_type
            record(db, existing, "restore", ns)
        return existing
    old = None
    if replaces_id:
        old = db.get(Memory, replaces_id)
        if not old or old.user_id != user_id or old.workspace_id != workspace_id or old.knowledge_base_id != kb_id:
            raise HTTPException(400, "被替代记忆不属于相同范围")
    elif subject:
        old = db.scalar(select(Memory).where(Memory.user_id == user_id, Memory.workspace_id == workspace_id,
                          Memory.knowledge_base_id == kb_id, Memory.subject == subject,
                          Memory.status == MemoryStatus.active, Memory.superseded_by.is_(None)))
    item = Memory(user_id=user_id, workspace_id=workspace_id, type=type_, content=content.strip(),
                  status=MemoryStatus.active if active else MemoryStatus.pending,
                  confidence=1.0 if active else 0.5, knowledge_base_id=kb_id, source_message_id=source_id,
                  source_type=source_type, fingerprint=fp, version=1, expires_at=expires_at,
                  replaces_id=old.id if old else None, conflict_version=old.version if old else None, subject=subject)
    db.add(item)
    db.flush()
    if source:
        db.add(MemorySource(memory_id=item.id, message_id=source.id, excerpt=content if source.role == "user" else source.content[:2000]))
    if active and old:
        old.superseded_by, old.version = item.id, old.version + 1
        record(db, old, "superseded", ns)
    record(db, item, "create", ns)
    return item


def edit(db, item, changes, expected_version=None, decision=None):
    ns = namespace(db, item.user_id, item.workspace_id)
    db.refresh(item)
    if expected_version is not None and item.version != expected_version:
        raise HTTPException(409, "记忆已被更新，请刷新后重试")
    if item.superseded_by and decision == "confirm":
        raise HTTPException(409, "该记忆已被替代")
    validate_scope(db, item.workspace_id, changes.get("knowledge_base_id", item.knowledge_base_id))
    if changes.get("content") is None and "content" in changes or changes.get("type") is None and "type" in changes:
        raise HTTPException(422, "内容与类型不能为空")
    if "content" in changes:
        fp = fingerprint(changes["content"])
        duplicate = db.scalar(select(Memory.id).where(Memory.user_id == item.user_id, Memory.workspace_id == item.workspace_id,
            Memory.knowledge_base_id == changes.get("knowledge_base_id", item.knowledge_base_id), Memory.fingerprint == fp, Memory.id != item.id))
        if duplicate:
            raise HTTPException(409, "相同范围已有该记忆")
        item.fingerprint = fp
    for k, v in changes.items():
        setattr(item, k, v)
    if decision == "confirm":
        if item.replaces_id:
            old = db.get(Memory, item.replaces_id)
            if not old or old.version != item.conflict_version or old.superseded_by:
                raise HTTPException(409, "冲突的旧记忆已变更，请重新核对")
            if old.user_id != item.user_id or old.workspace_id != item.workspace_id or old.knowledge_base_id != item.knowledge_base_id:
                raise HTTPException(409, "冲突记忆范围已变化")
            old.superseded_by, old.version = item.id, old.version + 1
            record(db, old, "superseded", ns)
        item.status = MemoryStatus.active
    elif decision == "reject":
        item.status = MemoryStatus.rejected
    item.version += 1
    record(db, item, decision or "edit", ns)
    return item


def remove(db, item):
    ns = namespace(db, item.user_id, item.workspace_id)
    ns.version += 1
    # A content hash (without plaintext) prevents an already-running extraction
    # from resurrecting a physically deleted memory. Explicit saving may undo it.
    blocked_key = f"{item.knowledge_base_id or '*'}:{item.fingerprint or fingerprint(item.content)}"
    sources = list(db.scalars(select(MemorySource.message_id).where(MemorySource.memory_id == item.id)))
    if item.source_message_id:
        sources.append(item.source_message_id)
    ns.blocked_fingerprints = list(set((ns.blocked_fingerprints or []) + [blocked_key] + [f"source:{id_}" for id_ in sources]))
    # Explicit deletion is physical, including audit metadata and pending vector tasks.
    for model in (MemorySource, MemoryEmbedding, MemoryEvent, BackgroundJob):
        db.execute(delete(model).where(model.memory_id == item.id))
    db.delete(item)


def clear(db, user_id, workspace_id):
    ns = namespace(db, user_id, workspace_id)
    ns.version += 1
    ns.epoch += 1
    ids = select(Memory.id).where(Memory.user_id == user_id, Memory.workspace_id == workspace_id)
    for model in (MemorySource, MemoryEmbedding, MemoryEvent, BackgroundJob):
        db.execute(delete(model).where(model.memory_id.in_(ids)))
    db.execute(delete(Memory).where(Memory.user_id == user_id, Memory.workspace_id == workspace_id))


def delete_session_memories(db, session_id, include_saved=False):
    ids = select(ChatMessage.id).where(ChatMessage.session_id == session_id)
    memory_ids = set(db.scalars(select(MemorySource.memory_id).where(MemorySource.message_id.in_(ids))))
    memory_ids.update(db.scalars(select(Memory.id).where(Memory.source_message_id.in_(ids))))
    for item in db.scalars(select(Memory).where(Memory.id.in_(memory_ids))):
        if include_saved or item.source_type == "automatic":
            remove(db, item)
        else:
            item.source_message_id = None
            db.execute(delete(MemorySource).where(MemorySource.memory_id == item.id, MemorySource.message_id.in_(ids)))
    # Also purge full tool payloads and pending postprocessing on deleted runs.
    db.execute(delete(BackgroundJob).where(BackgroundJob.session_id == session_id))


def explicit_content(content):
    match = re.fullmatch(r"\s*(?:请记住|记住|帮我记住|remember(?:\s+that)?)\s*[：:,，]?\s*(.+)", content, re.I | re.S)
    if not match:
        return None
    body = match.group(1).strip()
    # Only an unambiguous direct command; quotations/conditions remain candidates.
    if not body or len(body) > 2000 or any(x in body for x in ("如果", "不要记", "```", "请问")):
        return None
    return body


def active_query(session):
    return select(Memory).where(Memory.user_id == session.user_id, Memory.workspace_id == session.workspace_id,
        or_(Memory.knowledge_base_id.is_(None), Memory.knowledge_base_id == session.knowledge_base_id),
        Memory.status == MemoryStatus.active, Memory.superseded_by.is_(None),
        or_(Memory.expires_at.is_(None), Memory.expires_at > datetime.now(timezone.utc)))


async def recall(db, session, query):
    started = time.monotonic()
    ns = db.get(MemoryNamespace, (session.user_id, session.workspace_id))
    version = ns.version if ns else 0
    name = f"mem:{session.user_id}:{session.workspace_id}:{session.knowledge_base_id}:v{version}:{fingerprint(query)}"
    cached = cache.read(name)
    rows = list(db.scalars(active_query(session)))
    if cached is not None:
        valid = {m.id: m for m in rows}
        selected = [valid[x["id"]] for x in cached if x["id"] in valid and valid[x["id"]].version == x["version"]]
        log.info("memory_recall cache_hit=true count=%s duration_ms=%s", len(selected), int((time.monotonic()-started)*1000))
        return selected, False
    if not rows:
        return [], False
    lexical = bm25_scores(query, rows)
    ranked, degraded = {}, False
    for rank, (id_, _) in enumerate(lexical[:24], 1):
        ranked[id_] = 1 / (60 + rank)
    if db.bind.dialect.name == "postgresql":
        try:
            vector = (await asyncio.wait_for(EmbeddingProvider().embed([query]), get_settings().memory_embedding_timeout_seconds))[0]
            if len(vector) != 4096:
                raise ValueError("Memory embeddings require 4096 dimensions")
            # Restrict authorization/scope BEFORE ordering. No ANN index is used.
            with db.begin_nested():
                result = list(db.execute(text("""
                SELECT m.id, e.embedding <=> CAST(:vector AS vector) AS distance
                FROM memories m JOIN memory_embeddings e ON e.memory_id = m.id AND e.version = m.version
                WHERE m.user_id = :uid AND m.workspace_id = :wid AND m.status = 'active'
                  AND m.superseded_by IS NULL AND (m.expires_at IS NULL OR m.expires_at > CURRENT_TIMESTAMP)
                  AND (m.knowledge_base_id IS NULL OR m.knowledge_base_id = :kb)
                  AND e.model = :model AND e.dimension = 4096
                ORDER BY distance LIMIT 24
            """), {"vector": json.dumps(vector), "uid": session.user_id, "wid": session.workspace_id,
                   "kb": session.knowledge_base_id, "model": get_settings().embedding_model}))
            for rank, (id_, distance) in enumerate(result, 1):
                if distance is not None and distance <= 0.65:
                    ranked[id_] = ranked.get(id_, 0) + 1 / (60 + rank)
        except Exception:
            degraded = True
    for m in rows:
        if m.type in {"preference", "profile"}:
            ranked[m.id] = ranked.get(m.id, 0) + 0.01
    by_id = {m.id: m for m in rows}
    selected = [by_id[id_] for id_ in sorted(ranked, key=lambda x: ranked[x], reverse=True)[:8]]
    cache.write(name, [{"id": m.id, "version": m.version} for m in selected], 300)
    log.info("memory_recall cache_hit=false count=%s degraded=%s duration_ms=%s", len(selected), degraded, int((time.monotonic()-started)*1000))
    return selected, degraded

from __future__ import annotations
import json
import os
import shutil
import time
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.db import get_db
from app.models.models import ChatMessage, ChatSession, Citation, Document, DocumentChunk, Folder, IngestionJob, JobStatus, KnowledgeBase, McpCallAudit, McpServer, McpTool, Memory, MemoryStatus, MessageExecution, ModelProfile, User, Workspace
from app.schemas import *
from app.services.agent import agent_events, request_cancel
from app.services.auth import bootstrap_user, get_current_user, token_for, verify_password
from app.services.ingestion import process_document, process_document_in_worker
from app.services.parser import ChunkingConfig, approximate_tokens, extract_text, normalize_text, sha256_file, split_document
from app.services.providers import ChatProvider, ModelChoice
from app.services.retrieval import _evaluation_trace_enabled, format_retrieval_context, hybrid_search, plan_query
from app.services.vector_store import VectorStore
from app.core.secrets import encrypt, decrypt
from app.services.mcp import McpClientManager, get_mcp_manager, model_tool_name, validate_endpoint

router = APIRouter()
settings = get_settings()
vector_store = VectorStore()
mcp_manager = get_mcp_manager()


def user(request: Request, db: Session) -> User:
    return get_current_user(request, db)


def owned_workspace(db: Session, workspace_id: str, current: User) -> Workspace:
    workspace = db.scalar(select(Workspace).where(Workspace.id == workspace_id, Workspace.owner_id == current.id))
    if not workspace:
        raise HTTPException(404, "Workspace not found")
    return workspace


def owned_kb(db: Session, kb_id: str, current: User) -> KnowledgeBase:
    kb = db.scalar(select(KnowledgeBase).join(Workspace).where(KnowledgeBase.id == kb_id, Workspace.owner_id == current.id))
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    return kb


def delete_workspace_vectors(db: Session, workspace_id: str) -> None:
    chunk_ids = list(db.scalars(select(DocumentChunk.id).where(DocumentChunk.workspace_id == workspace_id)))
    vector_store.delete(chunk_ids)


@router.get("/health")
def health():
    return {"status": "ok", "service": "knownest-python"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    db.execute(select(func.count(User.id)))
    return {"status": "ready"}


@router.get("/auth/setup-status")
def setup_status(db: Session = Depends(get_db)):
    return {"initialized": bool(db.scalar(select(func.count(User.id))))}


@router.post("/auth/setup")
def setup(payload: SetupRequest, db: Session = Depends(get_db)):
    try:
        created, workspace = bootstrap_user(db, payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"token": token_for(created), "user": {"id": created.id, "username": created.username}, "workspace": {"id": workspace.id, "name": workspace.name}}


@router.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    current = db.scalar(select(User).where(User.username == payload.username))
    if not current or not verify_password(payload.password, current.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    return {"token": token_for(current), "user": {"id": current.id, "username": current.username}}


@router.get("/auth/me")
def me(request: Request, db: Session = Depends(get_db)):
    current = user(request, db)
    return {"id": current.id, "username": current.username}


@router.get("/workspaces")
def list_workspaces(request: Request, db: Session = Depends(get_db)):
    current = user(request, db)
    return [{"id": item.id, "name": item.name, "description": item.description} for item in db.scalars(select(Workspace).where(Workspace.owner_id == current.id).order_by(Workspace.created_at))]


@router.post("/workspaces")
def create_workspace(payload: WorkspaceCreate, request: Request, db: Session = Depends(get_db)):
    current = user(request, db)
    item = Workspace(owner_id=current.id, name=payload.name, description=payload.description)
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "name": item.name, "description": item.description}


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str, request: Request, db: Session = Depends(get_db)):
    item = owned_workspace(db, workspace_id, user(request, db))
    return {"id": item.id, "name": item.name, "description": item.description}


@router.patch("/workspaces/{workspace_id}")
def update_workspace(workspace_id: str, payload: WorkspaceUpdate, request: Request, db: Session = Depends(get_db)):
    item = owned_workspace(db, workspace_id, user(request, db))
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(item, key, value)
    db.commit(); db.refresh(item)
    return {"id": item.id, "name": item.name, "description": item.description}


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: str, request: Request, db: Session = Depends(get_db)):
    item = owned_workspace(db, workspace_id, user(request, db))
    delete_workspace_vectors(db, item.id)
    storage = Path(settings.storage_path) / item.id
    db.delete(item); db.commit()
    if storage.exists(): shutil.rmtree(storage)


@router.get("/knowledge-bases")
def list_kbs(workspace_id: str, request: Request, db: Session = Depends(get_db)):
    owned_workspace(db, workspace_id, user(request, db))
    return [{"id": item.id, "name": item.name, "description": item.description} for item in db.scalars(select(KnowledgeBase).where(KnowledgeBase.workspace_id == workspace_id).order_by(KnowledgeBase.created_at))]


@router.post("/knowledge-bases")
def create_kb(payload: KnowledgeBaseCreate, request: Request, db: Session = Depends(get_db)):
    owned_workspace(db, payload.workspace_id, user(request, db))
    item = KnowledgeBase(workspace_id=payload.workspace_id, name=payload.name, description=payload.description, chunking_config=(payload.chunking_config.model_dump() if payload.chunking_config else ChunkingConfig().model_dump()))
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "workspace_id": item.workspace_id, "name": item.name, "description": item.description, "chunking_config": item.chunking_config}


@router.get("/knowledge-bases/{kb_id}")
def get_kb(kb_id: str, request: Request, db: Session = Depends(get_db)):
    item = owned_kb(db, kb_id, user(request, db))
    count = db.scalar(select(func.count(Document.id)).where(Document.knowledge_base_id == kb_id)) or 0
    return {"id": item.id, "workspace_id": item.workspace_id, "name": item.name, "description": item.description, "document_count": count, "chunking_config": item.chunking_config or ChunkingConfig().model_dump(), "chunking_config_version": item.chunking_config_version, "chunking_needs_reindex": item.chunking_needs_reindex}


@router.get("/knowledge-bases/{kb_id}/chunking-config")
def get_chunking_config(kb_id: str, request: Request, db: Session = Depends(get_db)):
    item = owned_kb(db, kb_id, user(request, db))
    config = ChunkingConfig.model_validate(item.chunking_config or {})
    return {"knowledge_base_id": item.id, "chunking_config": config.model_dump(), "version": item.chunking_config_version, "needs_reindex": item.chunking_needs_reindex}


@router.put("/knowledge-bases/{kb_id}/chunking-config")
def update_chunking_config(kb_id: str, payload: ChunkingConfigRequest, request: Request, db: Session = Depends(get_db)):
    item = owned_kb(db, kb_id, user(request, db))
    item.chunking_config = payload.model_dump()
    item.chunking_config_version = (item.chunking_config_version or 0) + 1
    stale_documents = db.scalar(
        select(func.count(Document.id)).where(
            Document.knowledge_base_id == item.id,
            Document.chunking_config_version < item.chunking_config_version,
        )
    ) or 0
    item.chunking_needs_reindex = stale_documents > 0
    db.commit(); db.refresh(item)
    return {"knowledge_base_id": item.id, "chunking_config": item.chunking_config, "version": item.chunking_config_version, "needs_reindex": item.chunking_needs_reindex}


@router.post("/chunker/preview")
def preview_chunks(payload: ChunkerPreviewRequest, request: Request, db: Session = Depends(get_db)):
    user(request, db)
    chunks, stats = split_document(payload.text, payload.chunking_config)
    stats["chunks"] = [{"sequence": chunk.sequence, "content": chunk.content, "char_start": chunk.char_start, "char_end": chunk.char_end, "heading_path": chunk.heading_path, "strategy": chunk.strategy, "approx_tokens": approximate_tokens(chunk.content)} for chunk in chunks]
    return stats


@router.patch("/knowledge-bases/{kb_id}")
def update_kb(kb_id: str, payload: WorkspaceUpdate, request: Request, db: Session = Depends(get_db)):
    item = owned_kb(db, kb_id, user(request, db))
    if payload.name is not None: item.name = payload.name
    item.description = payload.description if payload.description is not None else item.description
    db.commit(); db.refresh(item)
    return {"id": item.id, "name": item.name, "description": item.description}


@router.delete("/knowledge-bases/{kb_id}", status_code=204)
def delete_kb(kb_id: str, request: Request, db: Session = Depends(get_db)):
    item = owned_kb(db, kb_id, user(request, db))
    chunk_ids = list(db.scalars(select(DocumentChunk.id).where(DocumentChunk.knowledge_base_id == item.id)))
    vector_store.delete(chunk_ids)
    storage = Path(settings.storage_path) / item.workspace_id / item.id
    db.delete(item); db.commit()
    if storage.exists(): shutil.rmtree(storage)


def folder_tree(items: list[Folder], parent_id: str | None = None):
    return [{"id": item.id, "name": item.name, "path": item.path, "children": folder_tree(items, item.id)} for item in items if item.parent_id == parent_id]


@router.get("/knowledge-bases/{kb_id}/folders/tree")
def folders(kb_id: str, request: Request, db: Session = Depends(get_db)):
    owned_kb(db, kb_id, user(request, db))
    return folder_tree(list(db.scalars(select(Folder).where(Folder.knowledge_base_id == kb_id).order_by(Folder.sort_order, Folder.name))))


@router.post("/knowledge-bases/{kb_id}/folders")
def create_folder(kb_id: str, payload: FolderCreate, request: Request, db: Session = Depends(get_db)):
    kb = owned_kb(db, kb_id, user(request, db)); parent = db.get(Folder, payload.parent_id) if payload.parent_id else None
    if parent and parent.knowledge_base_id != kb.id: raise HTTPException(400, "Invalid parent folder")
    path = f"{parent.path.rstrip('/')}/{payload.name}" if parent else f"/{payload.name}"
    item = Folder(workspace_id=kb.workspace_id, knowledge_base_id=kb.id, parent_id=payload.parent_id, name=payload.name, path=path, depth=(parent.depth + 1 if parent else 0))
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "name": item.name, "path": item.path, "parent_id": item.parent_id}


@router.patch("/folders/{folder_id}")
def update_folder(folder_id: str, payload: FolderUpdate, request: Request, db: Session = Depends(get_db)):
    item = db.get(Folder, folder_id)
    if not item or not owned_kb(db, item.knowledge_base_id, user(request, db)): raise HTTPException(404, "Folder not found")
    if payload.name: item.name = payload.name
    if payload.parent_id is not None: item.parent_id = payload.parent_id
    db.commit(); db.refresh(item)
    return {"id": item.id, "name": item.name, "parent_id": item.parent_id}


@router.delete("/folders/{folder_id}", status_code=204)
def delete_folder(folder_id: str, request: Request, db: Session = Depends(get_db)):
    item = db.get(Folder, folder_id)
    if not item or not owned_kb(db, item.knowledge_base_id, user(request, db)): raise HTTPException(404, "Folder not found")
    if db.scalar(select(func.count(Folder.id)).where(Folder.parent_id == folder_id)) or db.scalar(select(func.count(Document.id)).where(Document.folder_id == folder_id)):
        raise HTTPException(409, "Folder is not empty")
    db.delete(item); db.commit()


@router.post("/knowledge-bases/{kb_id}/documents")
async def upload_document(kb_id: str, request: Request, filename: str | None = None, folder_id: str | None = None, db: Session = Depends(get_db)):
    kb = owned_kb(db, kb_id, user(request, db))
    # Raw binary upload keeps the runtime dependency-free. Clients send the
    # original name in X-Filename (or the filename query parameter) and the
    # file bytes as the request body. This is also friendlier to CLI/curl.
    original_name = request.headers.get("x-filename") or filename or "upload.bin"
    suffix = Path(original_name).suffix.lower()
    if suffix not in {".pdf", ".md", ".markdown", ".txt", ".docx"}: raise HTTPException(400, "Only PDF, Markdown, TXT and DOCX are supported")
    if folder_id and not db.scalar(select(Folder).where(Folder.id == folder_id, Folder.knowledge_base_id == kb.id)): raise HTTPException(400, "Invalid folder")
    base = Path(settings.storage_path) / kb.workspace_id / kb.id
    base.mkdir(parents=True, exist_ok=True)
    document_id = str(uuid4()); path = base / f"{document_id}{suffix}"
    max_bytes = settings.max_upload_mb * 1024 * 1024
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > max_bytes:
        raise HTTPException(413, f"File exceeds the {settings.max_upload_mb} MB upload limit")
    written = 0
    try:
        with path.open("wb") as target:
            async for block in request.stream():
                written += len(block)
                if written > max_bytes:
                    raise HTTPException(413, f"File exceeds the {settings.max_upload_mb} MB upload limit")
                target.write(block)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise
    except Exception:
        path.unlink(missing_ok=True)
        raise
    content_hash, file_size = sha256_file(path)
    document = Document(id=document_id, workspace_id=kb.workspace_id, knowledge_base_id=kb.id, folder_id=folder_id, filename=original_name, file_type=suffix, storage_path=str(path), file_size=file_size, content_hash=content_hash)
    job = IngestionJob(document_id=document.id)
    db.add_all([document, job]); db.commit()
    try:
        from app.workers import ingest_document
        ingest_document.delay(document.id)
    except Exception:
        await asyncio.to_thread(process_document_in_worker, document.id)
    return {"document_id": document.id, "job_id": job.id, "status": "pending"}


@router.get("/knowledge-bases/{kb_id}/documents")
def documents(kb_id: str, request: Request, db: Session = Depends(get_db)):
    owned_kb(db, kb_id, user(request, db))
    return [{"id": item.id, "filename": item.filename, "file_type": item.file_type, "folder_id": item.folder_id, "status": item.parse_status.value} for item in db.scalars(select(Document).where(Document.knowledge_base_id == kb_id).order_by(Document.created_at.desc()))]


@router.get("/documents/{document_id}")
def get_document(document_id: str, request: Request, db: Session = Depends(get_db)):
    current = user(request, db); item = db.get(Document, document_id)
    if not item or not db.scalar(select(Workspace).where(Workspace.id == item.workspace_id, Workspace.owner_id == current.id)): raise HTTPException(404, "Document not found")
    return {"id": item.id, "filename": item.filename, "file_type": item.file_type, "folder_id": item.folder_id, "status": item.parse_status.value, "parse_error": item.parse_error, "file_size": item.file_size, "created_at": item.created_at, "updated_at": item.updated_at}


@router.get("/documents/{document_id}/preview")
def preview_document(document_id: str, request: Request, db: Session = Depends(get_db)):
    current = user(request, db); item = db.get(Document, document_id)
    if not item or not db.scalar(select(Workspace).where(Workspace.id == item.workspace_id, Workspace.owner_id == current.id)): raise HTTPException(404, "Document not found")
    from app.services.parser import extract_text
    return {"document_id": item.id, "filename": item.filename, "content": normalize_text(extract_text(Path(item.storage_path), item.file_type))}


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, request: Request, db: Session = Depends(get_db)):
    current = user(request, db); item = db.get(Document, document_id)
    if not item or not db.scalar(select(Workspace).where(Workspace.id == item.workspace_id, Workspace.owner_id == current.id)): raise HTTPException(404, "Document not found")
    vector_store.delete([chunk.id for chunk in item.chunks]); storage = Path(item.storage_path)
    db.delete(item); db.commit()
    if storage.exists(): storage.unlink()


@router.post("/documents/{document_id}/reindex", status_code=202)
def reindex_document(document_id: str, request: Request, db: Session = Depends(get_db)):
    current = user(request, db); item = db.get(Document, document_id)
    if not item or not db.scalar(select(Workspace).where(Workspace.id == item.workspace_id, Workspace.owner_id == current.id)): raise HTTPException(404, "Document not found")
    process_document(db, document_id)
    return {"document_id": document_id, "status": "indexed"}


@router.get("/documents/{document_id}/chunks")
def document_chunks(document_id: str, request: Request, db: Session = Depends(get_db)):
    current = user(request, db); item = db.get(Document, document_id)
    if not item or not db.scalar(select(Workspace).where(Workspace.id == item.workspace_id, Workspace.owner_id == current.id)): raise HTTPException(404, "Document not found")
    return [{"id": chunk.id, "sequence": chunk.sequence, "content": chunk.content, "version": chunk.version, "page_number": chunk.page_number, "char_start": chunk.char_start, "char_end": chunk.char_end, "heading_path": chunk.heading_path, "chunking_strategy": chunk.chunking_strategy, "chunk_level": chunk.chunk_level, "parent_chunk_id": chunk.parent_chunk_id, "index_status": chunk.index_status} for chunk in db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document_id).order_by(DocumentChunk.sequence, DocumentChunk.chunk_level))]


@router.get("/chunks/{chunk_id}/citation")
def citation_context(chunk_id: str, request: Request, db: Session = Depends(get_db)):
    chunk = db.get(DocumentChunk, chunk_id)
    document = db.get(Document, chunk.document_id) if chunk else None
    current = user(request, db)
    if not chunk or not document or not db.scalar(select(Workspace).where(Workspace.id == document.workspace_id, Workspace.owner_id == current.id)):
        raise HTTPException(404, "Citation not found")
    return {
        "chunk_id": chunk.id,
        "document_id": document.id,
        "filename": document.filename,
        "content": chunk.content,
        "page_number": chunk.page_number,
        "paragraph_index": chunk.paragraph_index,
        "heading_path": chunk.heading_path,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
    }


@router.patch("/chunks/{chunk_id}")
def update_chunk(chunk_id: str, payload: ChunkUpdate, request: Request, db: Session = Depends(get_db)):
    current = user(request, db); chunk = db.get(DocumentChunk, chunk_id)
    document = db.get(Document, chunk.document_id) if chunk else None
    if not chunk or not document or not db.scalar(select(Workspace).where(Workspace.id == document.workspace_id, Workspace.owner_id == current.id)): raise HTTPException(404, "Chunk not found")
    if chunk.version != payload.version: raise HTTPException(409, "Chunk version conflict")
    chunk.content = payload.content; chunk.content_hash = __import__('hashlib').sha256(payload.content.encode()).hexdigest(); chunk.version += 1; chunk.index_status = "pending"
    db.commit(); process_document(db, document.id)
    return {"id": chunk_id, "version": chunk.version, "index_status": "indexed"}


@router.post("/chunks/{chunk_id}/reindex", status_code=202)
def reindex_chunk(chunk_id: str, request: Request, db: Session = Depends(get_db)):
    current = user(request, db); chunk = db.get(DocumentChunk, chunk_id); document = db.get(Document, chunk.document_id) if chunk else None
    if not chunk or not document or not db.scalar(select(Workspace).where(Workspace.id == document.workspace_id, Workspace.owner_id == current.id)): raise HTTPException(404, "Chunk not found")
    process_document(db, document.id)
    return {"chunk_id": chunk_id, "status": "indexed"}


@router.post("/documents/{document_id}/move")
def move_document(document_id: str, folder_id: str | None, request: Request, db: Session = Depends(get_db)):
    current = user(request, db); item = db.get(Document, document_id)
    if not item or not db.scalar(select(Workspace).where(Workspace.id == item.workspace_id, Workspace.owner_id == current.id)): raise HTTPException(404, "Document not found")
    if folder_id and not db.scalar(select(Folder).where(Folder.id == folder_id, Folder.knowledge_base_id == item.knowledge_base_id)): raise HTTPException(400, "Invalid folder")
    item.folder_id = folder_id; db.commit(); return {"document_id": item.id, "folder_id": item.folder_id}


@router.get("/jobs/{job_id}")
def job(job_id: str, request: Request, db: Session = Depends(get_db)):
    current = user(request, db); item = db.get(IngestionJob, job_id)
    if not item or not db.scalar(select(Document).join(Workspace).where(Document.id == item.document_id, Workspace.owner_id == current.id)): raise HTTPException(404, "Job not found")
    return {"id": item.id, "status": item.status.value, "progress": item.progress, "error": item.error}


@router.post("/knowledge-bases/{kb_id}/search")
async def search(kb_id: str, payload: SearchRequest, request: Request, db: Session = Depends(get_db)):
    kb = owned_kb(db, kb_id, user(request, db))
    if payload.workspace_id != kb.workspace_id: raise HTTPException(400, "Workspace mismatch")
    hits = await hybrid_search(db, vector_store, kb.workspace_id, kb.id, payload.query, payload.top_k, payload.folder_id)
    response = {"query": payload.query, "results": [{"chunk_id": item["chunk"].id, "document_id": item["chunk"].document_id, "content": item["chunk"].content, "context_content": (item.get("context_chunk") or item["chunk"]).content, "rerank_score": item.get("rerank_score"), "rank": item["rank"], "page_number": item["chunk"].page_number, "heading_path": item["chunk"].heading_path} for item in hits]}
    if _evaluation_trace_enabled():
        response["diagnostics"] = hits[0].get("retrieval_meta", {}) if hits else {"candidate_count": 0, "final_count": 0, "embedding_used": False, "rerank_used": False, "candidate_trace": []}
    return response


@router.post("/chat/{mode}/sessions")
def create_session(mode: str, payload: SessionCreate, request: Request, db: Session = Depends(get_db)):
    if mode not in {"rag", "agent"}: raise HTTPException(400, "Invalid mode")
    current = user(request, db); owned_workspace(db, payload.workspace_id, current)
    if payload.knowledge_base_id:
        kb = owned_kb(db, payload.knowledge_base_id, current)
        if kb.workspace_id != payload.workspace_id:
            raise HTTPException(400, "Knowledge base workspace mismatch")
    if payload.model_id:
        model = db.get(ModelProfile, payload.model_id)
        if not model or model.workspace_id != payload.workspace_id:
            raise HTTPException(404, "Model not found in this workspace")
    item = ChatSession(user_id=current.id, workspace_id=payload.workspace_id, knowledge_base_id=payload.knowledge_base_id, model_id=payload.model_id, mode=mode)
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "mode": item.mode, "workspace_id": item.workspace_id, "knowledge_base_id": item.knowledge_base_id, "model_id": item.model_id}


@router.post("/rag/sessions")
def create_rag_session(payload: SessionCreate, request: Request, db: Session = Depends(get_db)):
    return create_session("rag", payload, request, db)


@router.post("/agent/sessions")
def create_agent_session(payload: SessionCreate, request: Request, db: Session = Depends(get_db)):
    return create_session("agent", payload, request, db)


def serialize_messages(db: Session, stored_messages: list[ChatMessage], default_mode: str | None = None) -> list[dict]:
    message_ids = [message.id for message in stored_messages]
    citations_by_message: dict[str, list[dict]] = {message_id: [] for message_id in message_ids}
    modes = {
        execution.message_id: execution.mode
        for execution in db.scalars(select(MessageExecution).where(MessageExecution.message_id.in_(message_ids)))
    } if message_ids else {}
    if message_ids:
        citations = list(db.scalars(select(Citation).where(Citation.message_id.in_(message_ids)).order_by(Citation.citation_index)))
        document_ids = {citation.document_id for citation in citations}
        filenames = {
            document.id: document.filename
            for document in db.scalars(select(Document).where(Document.id.in_(document_ids)))
        } if document_ids else {}
        for citation in citations:
            citations_by_message[citation.message_id].append({
                "citation_index": citation.citation_index,
                "rank": citation.retrieval_rank,
                "chunk_id": citation.chunk_id,
                "document_id": citation.document_id,
                "filename": filenames.get(citation.document_id, "Unknown document"),
                "page_number": citation.page_number,
                "char_start": citation.char_start,
                "char_end": citation.char_end,
                "quoted_text": citation.quoted_text,
            })
    return [
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "created_at": message.created_at,
            "mode": modes.get(message.id, default_mode),
            "citations": citations_by_message[message.id],
        }
        for message in stored_messages
    ]


def conversation_session(db: Session, conversation_id: str, current: User) -> ChatSession:
    item = db.get(ChatSession, conversation_id)
    if not item or item.user_id != current.id or item.mode not in {"conversation", "rag", "agent"}:
        raise HTTPException(404, "Conversation not found")
    return item


@router.post("/conversations")
def create_conversation(payload: SessionCreate, request: Request, db: Session = Depends(get_db)):
    current = user(request, db); owned_workspace(db, payload.workspace_id, current)
    if payload.knowledge_base_id:
        kb = owned_kb(db, payload.knowledge_base_id, current)
        if kb.workspace_id != payload.workspace_id:
            raise HTTPException(400, "Knowledge base workspace mismatch")
    if payload.model_id:
        model = db.get(ModelProfile, payload.model_id)
        if not model or model.workspace_id != payload.workspace_id:
            raise HTTPException(404, "Model not found in this workspace")
    item = ChatSession(
        user_id=current.id,
        workspace_id=payload.workspace_id,
        knowledge_base_id=payload.knowledge_base_id,
        model_id=payload.model_id,
        mode="conversation",
    )
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "title": item.title, "workspace_id": item.workspace_id, "knowledge_base_id": item.knowledge_base_id, "model_id": item.model_id}


@router.get("/conversations")
def list_conversations(request: Request, workspace_id: str, knowledge_base_id: str | None = None, db: Session = Depends(get_db)):
    current = user(request, db); owned_workspace(db, workspace_id, current)
    statement = select(ChatSession).where(ChatSession.workspace_id == workspace_id, ChatSession.user_id == current.id, ChatSession.mode.in_(["conversation", "rag", "agent"]))
    if knowledge_base_id:
        statement = statement.where(ChatSession.knowledge_base_id == knowledge_base_id)
    return [
        {"id": item.id, "title": item.title, "mode": item.mode, "workspace_id": item.workspace_id, "knowledge_base_id": item.knowledge_base_id, "created_at": item.created_at}
        for item in db.scalars(statement.order_by(ChatSession.created_at.desc()))
    ]


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, request: Request, db: Session = Depends(get_db)):
    item = conversation_session(db, conversation_id, user(request, db))
    stored_messages = list(db.scalars(select(ChatMessage).where(ChatMessage.session_id == item.id).order_by(ChatMessage.sequence.asc().nulls_last(), ChatMessage.created_at, ChatMessage.id)))
    return {"id": item.id, "title": item.title, "mode": item.mode, "legacy_mode": item.mode if item.mode != "conversation" else None, "workspace_id": item.workspace_id, "knowledge_base_id": item.knowledge_base_id, "model_id": item.model_id, "messages": serialize_messages(db, stored_messages, item.mode if item.mode != "conversation" else None)}


@router.patch("/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, payload: ConversationUpdate, request: Request, db: Session = Depends(get_db)):
    item = conversation_session(db, conversation_id, user(request, db))
    item.title = payload.title
    db.commit()
    return {"id": item.id, "title": item.title}


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, request: Request, include_saved_memories: bool = False, db: Session = Depends(get_db)):
    item = conversation_session(db, conversation_id, user(request, db))
    from app.services.chat_runs import lock_session
    from app.services.memory import delete_session_memories
    from app.models.models import ChatRun, SessionSummary
    lock_session(db, item.id)
    delete_session_memories(db, item.id, include_saved_memories)
    db.execute(delete(ChatRun).where(ChatRun.session_id == item.id))
    db.execute(delete(SessionSummary).where(SessionSummary.session_id == item.id))
    message_ids = select(ChatMessage.id).where(ChatMessage.session_id == item.id)
    db.execute(delete(Citation).where(Citation.message_id.in_(message_ids)))
    db.execute(delete(MessageExecution).where(MessageExecution.message_id.in_(message_ids)))
    db.execute(delete(ChatMessage).where(ChatMessage.session_id == item.id))
    db.delete(item)
    db.commit()


@router.get("/{mode}/sessions")
def list_sessions(mode: str, workspace_id: str, request: Request, db: Session = Depends(get_db)):
    if mode not in {"rag", "agent"}: raise HTTPException(400, "Invalid mode")
    current = user(request, db); owned_workspace(db, workspace_id, current)
    return [{"id": item.id, "title": item.title, "mode": item.mode, "knowledge_base_id": item.knowledge_base_id, "created_at": item.created_at} for item in db.scalars(select(ChatSession).where(ChatSession.workspace_id == workspace_id, ChatSession.user_id == current.id, ChatSession.mode == mode).order_by(ChatSession.created_at.desc()))]


@router.get("/{mode}/sessions/{session_id}")
def get_session(mode: str, session_id: str, request: Request, db: Session = Depends(get_db)):
    current = user(request, db); item = db.get(ChatSession, session_id)
    if not item or item.user_id != current.id or item.mode != mode: raise HTTPException(404, "Session not found")
    stored_messages = list(db.scalars(select(ChatMessage).where(ChatMessage.session_id == item.id).order_by(ChatMessage.sequence.asc().nulls_last(), ChatMessage.created_at, ChatMessage.id)))
    messages = serialize_messages(db, stored_messages, item.mode)
    return {"id": item.id, "title": item.title, "mode": item.mode, "workspace_id": item.workspace_id, "knowledge_base_id": item.knowledge_base_id, "model_id": item.model_id, "messages": messages}


@router.post("/agent/sessions/{session_id}/cancel", status_code=202)
def cancel_agent(session_id: str, request: Request, db: Session = Depends(get_db)):
    current = user(request, db); item = db.get(ChatSession, session_id)
    if not item or item.user_id != current.id or item.mode != "agent": raise HTTPException(404, "Session not found")
    from app.services.chat_runs import cancel
    cancel(db, session_id)
    return {"session_id": session_id, "status": "cancel_requested"}


def sse(events):
    async def iterator():
        async for event in events:
            yield f"event: {event.get('type', 'message')}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
    return StreamingResponse(iterator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def chat_stream(mode: str, session_id: str, payload: MessageRequest, request: Request, db: Session, shared_conversation: bool | None = None):
    from app.services import chat_runs as runs
    from app.services.context import ContextManager, ContextOverflow
    from app.services.memory import create as save_memory, explicit_content, serialize as serialize_memory
    from app.services.agent import built_in_schemas
    current = user(request, db)
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != current.id or (shared_conversation is not True and session.mode not in {mode, "conversation"}):
        raise HTTPException(404, "Session not found")
    owned_workspace(db, session.workspace_id, current)
    if session.knowledge_base_id:
        kb = owned_kb(db, session.knowledge_base_id, current)
        if kb.workspace_id != session.workspace_id:
            raise HTTPException(400, "Knowledge base workspace mismatch")
    model_id = payload.model_id or session.model_id
    selected = db.get(ModelProfile, model_id) if model_id else None
    if model_id and (not selected or selected.workspace_id != session.workspace_id):
        raise HTTPException(404, "Model not found in this workspace")
    choice = ModelChoice(selected.provider, selected.base_url, decrypt(selected.api_key_encrypted), selected.model_name,
                         selected.supports_tools, selected.context_window_tokens, selected.max_output_tokens) if selected else ModelChoice(
        "openai", settings.openai_base_url, settings.openai_api_key, settings.openai_model, True,
        settings.context_window_tokens, settings.max_output_tokens)
    provider = ChatProvider(choice)
    run, replay = runs.start(db, session, payload, mode)
    if replay:
        async def replay_events():
            answer = db.get(ChatMessage, run.assistant_message_id)
            yield {"type": "run_started", "run_id": run.id, "replayed": True}
            if answer:
                for citation in serialize_messages(db, [answer])[0]["citations"]:
                    yield {"type": "citation", **citation}
                yield {"type": "message_complete" if mode == "rag" else "agent_complete", "content": answer.content,
                       "message_id": answer.id, "run_id": run.id, "replayed": True}
        return replay_events()
    remembered = None
    try:
        body = explicit_content(payload.content)
        if body:
            preference = any(word in body for word in ("偏好", "回答", "称呼", "叫我"))
            item = save_memory(db, current.id, session.workspace_id, body, "preference" if preference else "fact",
                               kb_id=None if preference else session.knowledge_base_id,
                               source_id=run.user_message_id, source_type="explicit", active=True)
            db.commit()
            remembered = serialize_memory(db, item)
        remote_tools, remote_servers = [], {}
        if mode == "agent":
            for server in db.scalars(select(McpServer).where(McpServer.workspace_id == session.workspace_id, McpServer.enabled, McpServer.status == "connected")):
                for tool in db.scalars(select(McpTool).where(McpTool.server_id == server.id, McpTool.enabled)):
                    base = model_tool_name(server.name, tool.tool_name)
                    name, suffix = base, 2
                    while name in remote_servers:
                        name = f"{base[:88]}_{suffix}"
                        suffix += 1
                    remote_tools.append({"type": "function", "function": {"name": name, "description": tool.description or tool.tool_name, "parameters": tool.input_schema or {"type": "object"}}})
                    remote_servers[name] = (server, tool.tool_name, tool)
        query_plan = plan_query(payload.content)
        hits = await hybrid_search(db, vector_store, session.workspace_id, session.knowledge_base_id, payload.content, query_plan.top_k, query_plan=query_plan) if session.knowledge_base_id else []
        all_tools = built_in_schemas() + remote_tools if mode == "agent" and getattr(provider.choice, "supports_tools", True) else None
        manager = ContextManager(db, session, provider.choice)
        messages, hits, stats = await manager.build(payload.content, mode, hits, all_tools)
        run.context_stats = stats
        db.commit()
    except Exception as exc:
        runs.fail(db, run.id, str(exc))
        if isinstance(exc, ContextOverflow):
            raise HTTPException(422, str(exc)) from exc
        raise

    async def generate():
        yield {"type": "run_started", "run_id": run.id, "client_request_id": run.client_request_id}
        if remembered:
            yield {"type": "memory_saved", "memory": remembered}
        yield {"type": "context_ready", "run_id": run.id, **stats}
        for reason in stats["degraded"]:
            yield {"type": "context_degraded", "reason": reason}
        yield {"type": "retrieval_started", "mode": mode}
        yield {"type": "query_plan", "complexity": query_plan.complexity, "top_k": query_plan.top_k, "requires_research": query_plan.requires_research}
        if hits and hits[0].get("retrieval_degraded"):
            yield {"type": "retrieval_degraded", "message": "Reranking is unavailable; showing fused retrieval candidates."}
        if mode == "agent":
            async for event in agent_events(db, vector_store, provider, messages, session.workspace_id, session.knowledge_base_id,
                                            remote_tools, remote_servers, session.id, hits, mode, run.id):
                yield event
            return
        citations = []
        for index, item in enumerate(hits, 1):
            chunk = item["chunk"]
            document = db.get(Document, chunk.document_id)
            citations.append({"citation_index": index, "rank": item.get("rank", index),
                "document_id": chunk.document_id, "filename": document.filename if document else "Unknown document",
                "chunk_id": chunk.id, "page_number": chunk.page_number, "char_start": chunk.char_start,
                "char_end": chunk.char_end, "heading_path": chunk.heading_path, "quoted_text": chunk.content[:500],
                "quote_truncated": len(chunk.content) > 500, "rerank_score": item.get("rerank_score"),
                "retrieval_degraded": item.get("retrieval_degraded", False)})
        yield {"type": "retrieval_result", "results": citations, "diagnostics": hits[0].get("retrieval_meta", {}) if hits else {"candidate_count": 0, "final_count": 0}}
        for citation in citations:
            yield {"type": "citation", **citation}
        answer = ""
        async with asyncio.timeout(60):
            async for event in provider.stream(messages):
                if event.get("type") == "token":
                    answer += event.get("content", "")
                    yield event
        stored = [{**c, "retrieval_rank": c["rank"]} for c in citations]
        message_id = runs.finish(db, run.id, answer, provider.choice.provider, stored)
        yield {"type": "message_complete", "content": answer, "message_id": message_id, "run_id": run.id}

    async def managed():
        iterator = generate().__aiter__()
        task = None
        completed = False
        last_check = 0.0
        try:
            while True:
                if time.monotonic() - last_check >= 1:
                    if not runs.alive(db, run.id):
                        runs.fail(db, run.id, "cancelled_or_expired", "cancelled")
                        yield {"type": "error", "code": "cancelled", "message": "请求已取消或租约已失效", "run_id": run.id}
                        return
                    last_check = time.monotonic()
                if task is None:
                    task = asyncio.create_task(anext(iterator))
                done, _ = await asyncio.wait({task}, timeout=1)
                if not done:
                    continue
                try:
                    event = task.result()
                except StopAsyncIteration:
                    break
                task = None
                if event.get("type") in {"error", "agent_error"}:
                    runs.fail(db, run.id, event.get("message", "run_failed"),
                              "cancelled" if event.get("code") == "cancelled" else "failed")
                    yield event
                    return
                completed = event.get("type") in {"message_complete", "agent_complete"}
                yield event
                if completed:
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            runs.fail(db, run.id, str(exc))
            yield {"type": "error", "code": "run_failed", "message": str(exc)[:500], "run_id": run.id}
        finally:
            if task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, StopAsyncIteration):
                    pass
            await iterator.aclose()
            if not completed:
                runs.fail(db, run.id, "stream_closed", "cancelled")
    return managed()


@router.post("/rag/sessions/{session_id}/messages")
async def rag_message(session_id: str, payload: MessageRequest, request: Request, db: Session = Depends(get_db)):
    return sse(await chat_stream("rag", session_id, payload, request, db))


@router.post("/agent/sessions/{session_id}/messages")
async def agent_message(session_id: str, payload: MessageRequest, request: Request, db: Session = Depends(get_db)):
    return sse(await chat_stream("agent", session_id, payload, request, db))


@router.post("/conversations/{conversation_id}/messages")
async def conversation_message(conversation_id: str, payload: ConversationMessageRequest, request: Request, db: Session = Depends(get_db)):
    conversation_session(db, conversation_id, user(request, db))
    return sse(await chat_stream(payload.mode, conversation_id, payload, request, db, shared_conversation=True))


@router.post("/conversations/{conversation_id}/cancel", status_code=202)
def cancel_conversation(conversation_id: str, request: Request, db: Session = Depends(get_db)):
    conversation_session(db, conversation_id, user(request, db))
    from app.services.chat_runs import cancel
    cancel(db, conversation_id)
    return {"conversation_id": conversation_id, "status": "cancel_requested"}


@router.get("/conversations/{conversation_id}/context")
def conversation_context(conversation_id: str, request: Request, db: Session = Depends(get_db)):
    from app.models.models import ChatRun
    from app.services.memory import serialize
    conversation_session(db, conversation_id, user(request, db))
    run = db.scalar(select(ChatRun).where(ChatRun.session_id == conversation_id).order_by(ChatRun.created_at.desc(), ChatRun.id.desc()))
    stats = dict(run.context_stats or {}) if run else {}
    ids = stats.get("memory_ids", [])
    stats["memories"] = [serialize(db, m) for m in db.scalars(select(Memory).where(Memory.id.in_(ids)))]
    return {"run_id": run.id if run else None, "status": run.status if run else None, **stats}


@router.get("/workspaces/{workspace_id}/memories")
def memories(workspace_id: str, request: Request, db: Session = Depends(get_db)):
    from app.services.memory import serialize
    current = user(request, db)
    owned_workspace(db, workspace_id, current)
    return [serialize(db, m) for m in db.scalars(select(Memory).where(Memory.workspace_id == workspace_id, Memory.user_id == current.id).order_by(Memory.created_at.desc()))]


@router.post("/workspaces/{workspace_id}/memories")
def create_memory(workspace_id: str, payload: MemoryCreate, request: Request, db: Session = Depends(get_db)):
    from app.services.memory import create, serialize
    current = user(request, db)
    owned_workspace(db, workspace_id, current)
    if payload.workspace_id != workspace_id:
        raise HTTPException(400, "Workspace mismatch")
    item = create(db, current.id, workspace_id, payload.content, payload.type, payload.knowledge_base_id,
                  payload.source_message_id, "manual", True, payload.expires_at, payload.replaces_id)
    db.commit()
    return serialize(db, item)


def owned_memory(db, memory_id, current):
    item = db.get(Memory, memory_id)
    if not item or item.user_id != current.id:
        raise HTTPException(404, "Memory not found")
    owned_workspace(db, item.workspace_id, current)
    return item


@router.patch("/memories/{memory_id}")
def update_memory(memory_id: str, payload: MemoryUpdate, request: Request, db: Session = Depends(get_db)):
    from app.services.memory import edit, serialize
    item = owned_memory(db, memory_id, user(request, db))
    changes = payload.model_dump(exclude_unset=True, exclude={"version"})
    item = edit(db, item, changes, payload.version)
    db.commit()
    return serialize(db, item)


@router.post("/memories/{memory_id}/confirm")
def confirm_memory(memory_id: str, request: Request, payload: MemoryDecision | None = None, db: Session = Depends(get_db)):
    from app.services.memory import edit, serialize
    item = owned_memory(db, memory_id, user(request, db))
    item = edit(db, item, {}, payload.version if payload else None, "confirm")
    db.commit()
    return serialize(db, item)


@router.post("/memories/{memory_id}/reject")
def reject_memory(memory_id: str, request: Request, payload: MemoryDecision | None = None, db: Session = Depends(get_db)):
    from app.services.memory import edit, serialize
    item = owned_memory(db, memory_id, user(request, db))
    item = edit(db, item, {}, payload.version if payload else None, "reject")
    db.commit()
    return serialize(db, item)


@router.delete("/workspaces/{workspace_id}/memories", status_code=204)
def clear_memories(workspace_id: str, request: Request, db: Session = Depends(get_db)):
    from app.services.memory import clear
    current = user(request, db)
    owned_workspace(db, workspace_id, current)
    clear(db, current.id, workspace_id)
    db.commit()


@router.delete("/memories/{memory_id}", status_code=204)
def delete_memory(memory_id: str, request: Request, db: Session = Depends(get_db)):
    from app.services.memory import remove
    remove(db, owned_memory(db, memory_id, user(request, db)))
    db.commit()


@router.get("/workspaces/{workspace_id}/models")
def models(workspace_id: str, request: Request, db: Session = Depends(get_db)):
    owned_workspace(db, workspace_id, user(request, db))
    return [{"id": item.id, "provider": item.provider, "model_name": item.model_name, "is_default_rag": item.is_default_rag, "is_default_agent": item.is_default_agent, "context_window_tokens": item.context_window_tokens, "max_output_tokens": item.max_output_tokens} for item in db.scalars(select(ModelProfile).where(ModelProfile.workspace_id == workspace_id))]


@router.post("/workspaces/{workspace_id}/models")
def create_model(workspace_id: str, payload: ModelProfileCreate, request: Request, db: Session = Depends(get_db)):
    owned_workspace(db, workspace_id, user(request, db))
    item = ModelProfile(workspace_id=workspace_id, provider=payload.provider, base_url=payload.base_url, model_name=payload.model_name, api_key_encrypted=encrypt(payload.api_key), supports_tools=payload.supports_tools, context_window_tokens=payload.context_window_tokens, max_output_tokens=payload.max_output_tokens, supports_reasoning=payload.supports_reasoning, is_default_rag=payload.is_default_rag, is_default_agent=payload.is_default_agent)
    if payload.is_default_rag: db.query(ModelProfile).filter(ModelProfile.workspace_id == workspace_id).update({"is_default_rag": False})
    if payload.is_default_agent: db.query(ModelProfile).filter(ModelProfile.workspace_id == workspace_id).update({"is_default_agent": False})
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "provider": item.provider, "model_name": item.model_name, "is_default_rag": item.is_default_rag, "is_default_agent": item.is_default_agent, "context_window_tokens": item.context_window_tokens, "max_output_tokens": item.max_output_tokens}


@router.post("/models/{model_id}/test")
async def test_model(model_id: str, request: Request, db: Session = Depends(get_db)):
    current = user(request, db); item = db.get(ModelProfile, model_id)
    if not item or not owned_workspace(db, item.workspace_id, current): raise HTTPException(404, "Model profile not found")
    provider = ChatProvider(ModelChoice(item.provider, item.base_url, decrypt(item.api_key_encrypted), item.model_name))
    output = []
    async for event in provider.stream([{"role": "user", "content": "Reply with OK"}]):
        if event.get("type") == "token": output.append(event.get("content", ""))
    return {"ok": True, "provider": item.provider, "model": item.model_name, "response": "".join(output)}


@router.post("/workspaces/{workspace_id}/mcp-servers")
def create_mcp(workspace_id: str, payload: McpServerCreate, request: Request, db: Session = Depends(get_db)):
    owned_workspace(db, workspace_id, user(request, db))
    if payload.endpoint:
        try:
            validate_endpoint(payload.endpoint)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if payload.transport == "stdio" and not settings.mcp_allow_stdio:
        raise HTTPException(400, "stdio MCP transport is disabled by server policy")
    item = McpServer(workspace_id=workspace_id, name=payload.name, transport=payload.transport, command=payload.command, args_json=payload.args, endpoint=payload.endpoint, auth_type=payload.auth_type, auth_secret_encrypted=encrypt(payload.auth_secret), enabled=payload.enabled, timeout_seconds=payload.timeout_seconds)
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "name": item.name, "transport": item.transport, "enabled": item.enabled, "status": item.status}


@router.get("/workspaces/{workspace_id}/mcp-servers")
def mcp_servers(workspace_id: str, request: Request, db: Session = Depends(get_db)):
    owned_workspace(db, workspace_id, user(request, db))
    return [{"id": item.id, "name": item.name, "transport": item.transport, "enabled": item.enabled, "status": item.status, "last_error": item.last_error, "last_discovered_at": item.last_discovered_at} for item in db.scalars(select(McpServer).where(McpServer.workspace_id == workspace_id))]


@router.get("/mcp-servers/{server_id}")
def get_mcp(server_id: str, request: Request, db: Session = Depends(get_db)):
    item = db.get(McpServer, server_id); current = user(request, db)
    if not item or not owned_workspace(db, item.workspace_id, current): raise HTTPException(404, "MCP server not found")
    return {"id": item.id, "name": item.name, "transport": item.transport, "command": item.command, "args": item.args_json, "endpoint": item.endpoint, "auth_type": item.auth_type, "enabled": item.enabled, "timeout_seconds": item.timeout_seconds, "status": item.status, "last_error": item.last_error, "last_discovered_at": item.last_discovered_at}


@router.patch("/mcp-servers/{server_id}")
async def update_mcp(server_id: str, payload: McpServerCreate, request: Request, db: Session = Depends(get_db)):
    item = db.get(McpServer, server_id); current = user(request, db)
    if not item or not owned_workspace(db, item.workspace_id, current): raise HTTPException(404, "MCP server not found")
    if payload.endpoint:
        try:
            validate_endpoint(payload.endpoint)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if payload.transport == "stdio" and not settings.mcp_allow_stdio:
        raise HTTPException(400, "stdio MCP transport is disabled by server policy")
    fields = payload.model_dump(exclude_unset=True)
    item.name = payload.name
    item.transport = payload.transport
    if "command" in fields: item.command = payload.command
    if "args" in fields: item.args_json = payload.args
    if "endpoint" in fields: item.endpoint = payload.endpoint
    if "auth_type" in fields: item.auth_type = payload.auth_type
    item.enabled = payload.enabled
    item.timeout_seconds = payload.timeout_seconds
    item.status = "disconnected"
    item.last_error = None
    # A changed endpoint/transport must not reuse an old initialized session.
    await mcp_manager.disconnect(item.id)
    if "auth_secret" in fields: item.auth_secret_encrypted = encrypt(payload.auth_secret)
    db.commit(); db.refresh(item)
    return {"id": item.id, "name": item.name, "transport": item.transport, "enabled": item.enabled, "status": item.status}


@router.delete("/mcp-servers/{server_id}", status_code=204)
async def delete_mcp(server_id: str, request: Request, db: Session = Depends(get_db)):
    item = db.get(McpServer, server_id); current = user(request, db)
    if not item or not owned_workspace(db, item.workspace_id, current): raise HTTPException(404, "MCP server not found")
    await mcp_manager.disconnect(item.id)
    db.delete(item); db.commit()


@router.get("/mcp-servers/{server_id}/tools")
def mcp_tools(server_id: str, request: Request, db: Session = Depends(get_db)):
    item = db.get(McpServer, server_id); current = user(request, db)
    if not item or not owned_workspace(db, item.workspace_id, current): raise HTTPException(404, "MCP server not found")
    return [{"id": tool.id, "tool_name": tool.tool_name, "description": tool.description, "input_schema": tool.input_schema, "output_schema": tool.output_schema, "enabled": tool.enabled, "stale": tool.stale, "last_discovered_at": tool.last_discovered_at} for tool in db.scalars(select(McpTool).where(McpTool.server_id == server_id))]


@router.post("/mcp-servers/{server_id}/connect")
async def connect_mcp(server_id: str, request: Request, db: Session = Depends(get_db)):
    item = db.get(McpServer, server_id); current = user(request, db)
    if not item or not owned_workspace(db, item.workspace_id, current): raise HTTPException(404, "MCP server not found")
    item.enabled = True
    item.status = "connecting"
    item.last_error = None
    db.commit()
    try:
        await mcp_manager.connect(item)
    except Exception as exc:
        item.status = "error"
        item.last_error = str(exc)[:1000]
        db.commit()
        raise HTTPException(502, f"MCP connection failed: {item.last_error}") from exc
    item.status = "connected"
    item.connected_at = datetime.now(timezone.utc)
    db.commit()
    return {"server_id": server_id, "status": item.status}


@router.post("/mcp-servers/{server_id}/discover")
async def discover_mcp(server_id: str, request: Request, db: Session = Depends(get_db)):
    item = db.get(McpServer, server_id); current = user(request, db)
    if not item or not owned_workspace(db, item.workspace_id, current): raise HTTPException(404, "MCP server not found")
    item.enabled = True
    item.status = "connecting"
    db.commit()
    try:
        discovered = await mcp_manager.discover(item)
    except Exception as exc:
        item.status = "error"
        item.last_error = str(exc)[:1000]
        db.commit()
        raise HTTPException(502, f"MCP discovery failed: {item.last_error}") from exc
    existing = {tool.tool_name: tool for tool in db.scalars(select(McpTool).where(McpTool.server_id == item.id))}
    seen: set[str] = set()
    records = []
    now = datetime.now(timezone.utc)
    for tool in discovered:
        tool_name = tool.get("name", "unknown")
        record = existing.get(tool_name)
        if record is None:
            record = McpTool(server_id=item.id, tool_name=tool_name, enabled=False)
            db.add(record)
        record.description = tool.get("description")
        record.input_schema = tool.get("inputSchema") or tool.get("input_schema") or {"type": "object"}
        record.output_schema = tool.get("outputSchema") or tool.get("output_schema")
        record.last_discovered_at = now
        record.stale = False
        records.append(record)
        seen.add(tool_name)
    for record in existing.values():
        if record.tool_name not in seen:
            record.stale = True
            record.enabled = False
    item.status = "connected"
    item.last_error = None
    item.connected_at = item.connected_at or now
    item.last_discovered_at = now
    db.commit()
    return {"server_id": server_id, "status": item.status, "tools": [{"id": record.id, "tool_name": record.tool_name, "description": record.description, "enabled": record.enabled, "stale": record.stale} for record in records]}


@router.patch("/mcp-tools/{tool_id}")
def update_mcp_tool(tool_id: str, enabled: bool, request: Request, db: Session = Depends(get_db)):
    item = db.get(McpTool, tool_id); current = user(request, db)
    server = db.get(McpServer, item.server_id) if item else None
    if not item or not server or not owned_workspace(db, server.workspace_id, current): raise HTTPException(404, "MCP tool not found")
    item.enabled = enabled; db.commit(); return {"id": item.id, "enabled": item.enabled}

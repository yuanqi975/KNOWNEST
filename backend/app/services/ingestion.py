from __future__ import annotations
import asyncio
from pathlib import Path
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.models.models import Document, DocumentChunk, IngestionJob, JobStatus, KnowledgeBase
from app.services.parser import ChunkingConfig, extract_text, split_document
from app.services.providers import EmbeddingProvider
from app.services.vector_store import VectorStore


def refresh_chunking_reindex_state(db: Session, knowledge_base: KnowledgeBase) -> None:
    stale_documents = db.scalar(
        select(func.count(Document.id)).where(
            Document.knowledge_base_id == knowledge_base.id,
            Document.chunking_config_version < knowledge_base.chunking_config_version,
        )
    ) or 0
    knowledge_base.chunking_needs_reindex = stale_documents > 0


def process_document(db: Session, document_id: str) -> None:
    document = db.get(Document, document_id)
    if not document:
        return
    job = db.query(IngestionJob).filter(IngestionJob.document_id == document_id).order_by(IngestionJob.created_at.desc()).first()
    document.parse_status = JobStatus.processing
    if job:
        job.status = JobStatus.processing
        job.progress = 10
    db.commit()
    try:
        text = extract_text(Path(document.storage_path), document.file_type)
        knowledge_base = db.get(KnowledgeBase, document.knowledge_base_id)
        config = ChunkingConfig.model_validate((knowledge_base.chunking_config if knowledge_base else None) or {})
        parsed, _stats = split_document(text, config)
        store = VectorStore()
        previous_chunk_ids = list(db.scalars(select(DocumentChunk.id).where(DocumentChunk.document_id == document_id)))
        store.delete(previous_chunk_ids)
        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        chunks: list[DocumentChunk] = []
        if config.enable_parent_child and parsed:
            parent_config = config.model_copy(update={"chunk_size": config.parent_chunk_size, "chunk_overlap": min(config.chunk_overlap, max(0, config.parent_chunk_size - 1)), "enable_parent_child": False})
            parents, _ = split_document(text, parent_config)
            for parent in parents:
                chunks.append(DocumentChunk(workspace_id=document.workspace_id, knowledge_base_id=document.knowledge_base_id, document_id=document.id, sequence=parent.sequence, content=parent.content, content_hash=__import__('hashlib').sha256(parent.content.encode()).hexdigest(), page_number=parent.page_number, paragraph_index=parent.paragraph_index, char_start=parent.char_start, char_end=parent.char_end, heading_path=parent.heading_path, chunking_strategy=parent.strategy, chunk_level="parent", index_status="context"))
            db.add_all(chunks); db.flush()
            for item in parsed:
                parent = next((candidate for candidate in chunks if candidate.char_start is not None and candidate.char_end is not None and item.char_start is not None and candidate.char_start <= item.char_start < candidate.char_end), chunks[min(item.sequence, len(chunks) - 1)])
                chunks.append(DocumentChunk(workspace_id=document.workspace_id, knowledge_base_id=document.knowledge_base_id, document_id=document.id, sequence=item.sequence, content=item.content, content_hash=__import__('hashlib').sha256(item.content.encode()).hexdigest(), page_number=item.page_number, paragraph_index=item.paragraph_index, char_start=item.char_start, char_end=item.char_end, heading_path=item.heading_path, chunking_strategy=item.strategy, chunk_level="child", parent_chunk_id=parent.id, index_status="embedding"))
        else:
            chunks = [DocumentChunk(workspace_id=document.workspace_id, knowledge_base_id=document.knowledge_base_id, document_id=document.id, sequence=item.sequence, content=item.content, content_hash=__import__('hashlib').sha256(item.content.encode()).hexdigest(), page_number=item.page_number, paragraph_index=item.paragraph_index, char_start=item.char_start, char_end=item.char_end, heading_path=item.heading_path, chunking_strategy=item.strategy, chunk_level="single", index_status="embedding") for item in parsed]
        db.add_all(chunks)
        document.parse_status = JobStatus.embedding
        if job: job.status, job.progress = JobStatus.embedding, 40
        db.commit()
        embeddable = [chunk for chunk in chunks if chunk.chunk_level in {"single", "child"}]
        vectors = asyncio.run(EmbeddingProvider().embed([chunk.content for chunk in embeddable])) if embeddable else []
        if embeddable:
            store.upsert([{ "id": chunk.id, "vector": vector, "workspace_id": chunk.workspace_id, "knowledge_base_id": chunk.knowledge_base_id, "document_id": chunk.document_id, "chunk_id": chunk.id, "entity_type": "chunk", "content_hash": chunk.content_hash } for chunk, vector in zip(embeddable, vectors)])
        for chunk in embeddable: chunk.index_status = "indexed"
        if knowledge_base:
            document.chunking_config_version = knowledge_base.chunking_config_version
            refresh_chunking_reindex_state(db, knowledge_base)
        document.parse_status = JobStatus.indexed
        if job: job.status, job.progress = JobStatus.indexed, 100
        db.commit()
    except Exception as exc:
        document.parse_status = JobStatus.failed
        document.parse_error = str(exc)
        if job: job.status, job.error = JobStatus.failed, str(exc)
        db.commit()
        raise


def process_document_in_worker(document_id: str) -> None:
    """Run ingestion with a session local to the worker thread/process."""
    from app.core.db import SessionLocal
    db = SessionLocal()
    try:
        process_document(db, document_id)
    finally:
        db.close()

from __future__ import annotations

import asyncio
import math
import os
import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import DocumentChunk
from app.services.providers import EmbeddingProvider, RerankProvider
from app.services.vector_store import VectorStore


EMBED_TIMEOUT_SECONDS = 15
RERANK_TIMEOUT_SECONDS = 8
# Keep a wider final set for evidence-heavy evaluation and technical queries.
# The caller's query plan still caps this per complexity below.
FINAL_RESULT_COUNT = 10
MAX_FINAL_RESULT_COUNT = 50
CANDIDATE_COUNT = 24


def _evaluation_trace_enabled() -> bool:
    return os.getenv("KNOWNEST_EVAL_ENV") == "isolated"


@dataclass(frozen=True)
class QueryPlan:
    """Small, deterministic first-stage plan used by RAG and Agent routes.

    It deliberately does not call an LLM: planning must remain available when
    the chat provider is degraded, and the same plan should be reproducible in
    logs and tests.
    """

    original_query: str
    search_query: str
    complexity: str
    top_k: int
    requires_research: bool


def plan_query(query: str) -> QueryPlan:
    text = " ".join(query.split())
    composite_markers = ("比较", "对比", "分别", "总结", "所有", "哪些", "流程", "步骤", "原因", "以及", "同时", "compare", "summarize", "all ")
    research_markers = ("计算", "算一下", "调用", "查询系统", "最新", "外部", "calculate", "mcp", "tool")
    composite = len(text) > 120 or any(marker in text.lower() for marker in composite_markers)
    research = any(marker in text.lower() for marker in research_markers)
    complexity = "research" if research else "composite" if composite else "simple"
    top_k = 12 if composite or research else FINAL_RESULT_COUNT
    return QueryPlan(text, text, complexity, top_k, research)


def lexical_terms(text: str) -> list[str]:
    """Produce useful lexical terms for both whitespace and Chinese queries."""
    words = [word.lower() for word in re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]+", text)]
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    if len(chinese) > 1:
        words.extend(chinese[index:index + 2] for index in range(len(chinese) - 1))
    return words


def bm25_scores(query: str, chunks: list[DocumentChunk]) -> list[tuple[str, float]]:
    terms = lexical_terms(query)
    if not terms or not chunks:
        return []
    documents = [(chunk.id, lexical_terms(chunk.content)) for chunk in chunks]
    document_frequency = Counter(term for _, tokens in documents for term in set(tokens))
    average_length = sum(len(tokens) for _, tokens in documents) / len(documents) or 1
    scores: list[tuple[str, float]] = []
    for chunk_id, tokens in documents:
        counts = Counter(tokens)
        score = 0.0
        for term in terms:
            frequency = counts[term]
            if not frequency:
                continue
            idf = math.log(1 + (len(documents) - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
            score += idf * (frequency * 2.2) / (frequency + 1.2 * (1 - 0.75 + 0.75 * len(tokens) / average_length))
        if score:
            scores.append((chunk_id, score))
    return sorted(scores, key=lambda pair: pair[1], reverse=True)


def _attach_parent_context(db: Session, hits: list[dict]) -> list[dict]:
    parent_ids = {
        item["chunk"].parent_chunk_id
        for item in hits
        if item["chunk"].chunk_level == "child" and item["chunk"].parent_chunk_id
    }
    parents = {
        parent.id: parent
        for parent in db.scalars(
            select(DocumentChunk).where(
                DocumentChunk.id.in_(parent_ids),
                DocumentChunk.chunk_level == "parent",
            )
        )
    } if parent_ids else {}
    for item in hits:
        chunk = item["chunk"]
        item["context_chunk"] = parents.get(chunk.parent_chunk_id, chunk)
    return hits


def format_retrieval_context(hits: list[dict]) -> str:
    """Render matched children for citation and each parent once for context."""
    groups: dict[str, dict] = {}
    for item in hits:
        chunk = item["chunk"]
        context_chunk = item.get("context_chunk") or chunk
        group = groups.setdefault(context_chunk.id, {"context": context_chunk, "sources": []})
        group["sources"].append(chunk)

    sections = []
    for group in groups.values():
        source_text = "\n\n".join(
            f"[source:{chunk.id}]\n{chunk.content}" for chunk in group["sources"]
        )
        context_chunk = group["context"]
        if context_chunk.id != group["sources"][0].id:
            source_text += (
                "\n\n[broader context for the retrieved sources above; cite only their source IDs]\n"
                + context_chunk.content
            )
        sections.append(source_text)
    return "\n\n---\n\n".join(sections)


async def hybrid_search(
    db: Session,
    vector_store: VectorStore,
    workspace_id: str,
    kb_id: str,
    query: str,
    top_k: int = FINAL_RESULT_COUNT,
    folder_id: str | None = None,
    query_plan: QueryPlan | None = None,
) -> list[dict]:
    """Return one final ranked result set used by prompts, SSE, and citations."""
    plan = query_plan or plan_query(query)
    search_query = plan.search_query or query
    final_count = max(1, min(query_plan.top_k if query_plan else top_k, MAX_FINAL_RESULT_COUNT))
    try:
        vectors = await asyncio.wait_for(EmbeddingProvider().embed([search_query]), timeout=EMBED_TIMEOUT_SECONDS)
        vector = vectors[0] if vectors else None
    except Exception:
        vector = None

    dense = vector_store.search(vector, workspace_id, kb_id, CANDIDATE_COUNT) if vector else []
    statement = select(DocumentChunk).where(
        DocumentChunk.workspace_id == workspace_id,
        DocumentChunk.knowledge_base_id == kb_id,
        DocumentChunk.chunk_level.in_(("single", "child")),
        DocumentChunk.index_status == "indexed",
    )
    if folder_id:
        from app.models.models import Document
        statement = statement.join(Document, Document.id == DocumentChunk.document_id).where(Document.folder_id == folder_id)
    chunks = list(db.scalars(statement))
    by_id = {chunk.id: chunk for chunk in chunks}
    stale_vector_ids = [hit.id for hit in dense if hit.id not in by_id]
    if stale_vector_ids:
        vector_store.delete(stale_vector_ids)
    dense = [hit for hit in dense if hit.id in by_id]
    lexical = bm25_scores(search_query, chunks)
    dense_ranks = {hit.id: index + 1 for index, hit in enumerate(dense)}
    lexical_ranks = {chunk_id: index + 1 for index, (chunk_id, _) in enumerate(lexical)}

    # RRF only chooses reranking candidates; it is not a relevance score.
    ranked = []
    for chunk_id in set(dense_ranks) | set(lexical_ranks):
        chunk = by_id.get(chunk_id)
        if not chunk:
            continue
        fusion_score = (
            (0.6 / (60 + dense_ranks[chunk_id]) if chunk_id in dense_ranks else 0)
            + (0.4 / (60 + lexical_ranks[chunk_id]) if chunk_id in lexical_ranks else 0)
        )
        ranked.append({
            "chunk": chunk,
            "fusion_score": fusion_score,
            "dense_rank": dense_ranks.get(chunk_id),
            "lexical_rank": lexical_ranks.get(chunk_id),
        })
    ranked.sort(key=lambda item: item["fusion_score"], reverse=True)
    candidates = ranked[:CANDIDATE_COUNT]
    evaluation_trace = _evaluation_trace_enabled()

    try:
        reranked = await asyncio.wait_for(
            RerankProvider().rerank(search_query, [item["chunk"].content for item in candidates], len(candidates) if evaluation_trace else final_count),
            timeout=RERANK_TIMEOUT_SECONDS,
        )
    except Exception:
        reranked = []

    # Keep a compact, evidence-safe trace so evaluation can distinguish
    # candidate recall failures from reranker ordering failures. The trace is
    # attached to the retrieval metadata and is intentionally capped to the
    # fixed candidate set.
    rerank_rank_by_index = {
        index: rank
        for rank, (index, _score) in enumerate(sorted(reranked, key=lambda pair: pair[1], reverse=True), start=1)
        if index in {candidate_index for candidate_index, _ in reranked}
    }
    rerank_score_by_index = {index: score for index, score in reranked}
    trace_meta = {"candidate_count": len(candidates)}
    if evaluation_trace:
        trace_meta["candidate_trace"] = [
            {
                "chunk_id": item["chunk"].id,
                "document_id": item["chunk"].document_id,
                "content": item["chunk"].content,
                "fusion_rank": rank,
                "dense_rank": item.get("dense_rank"),
                "lexical_rank": item.get("lexical_rank"),
                "rerank_rank": rerank_rank_by_index.get(index),
                "rerank_score": rerank_score_by_index.get(index),
            }
            for index, (rank, item) in enumerate(zip(range(1, len(candidates) + 1), candidates))
        ]

    if reranked:
        by_index = {index: candidates[index] for index in range(len(candidates))}
        final = []
        for index, score in sorted(reranked, key=lambda pair: pair[1], reverse=True):
            if index not in by_index:
                continue
            item = dict(by_index[index])
            item["rerank_score"] = score
            item["rank"] = len(final) + 1
            item["retrieval_degraded"] = False
            item["retrieval_meta"] = {**trace_meta, "final_count": final_count, "embedding_used": vector is not None, "rerank_used": True, "query_plan": plan.complexity}
            final.append(item)
            if len(final) == final_count:
                break
        if final:
            return _attach_parent_context(db, final)

    fallback = [
        {**item, "rank": index, "retrieval_degraded": True, "retrieval_meta": {**trace_meta, "final_count": min(len(candidates), final_count), "embedding_used": vector is not None, "rerank_used": False, "query_plan": plan.complexity}}
        for index, item in enumerate(candidates[:final_count], start=1)
    ]
    return _attach_parent_context(db, fallback)

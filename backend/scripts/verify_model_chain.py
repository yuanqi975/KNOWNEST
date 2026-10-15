"""Probe actual model providers without printing credentials or using user data."""
import asyncio
import hashlib
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.db import Base
from app.models.models import DocumentChunk
from app.services.providers import ChatProvider, EmbeddingProvider, RerankProvider, configured_choice
from app.services.retrieval import hybrid_search
from app.services.vector_store import VectorStore


async def chat(provider, messages):
    if not provider.choice.api_key:
        raise ValueError("Chat credential missing; development fallback is not a pass")
    answer = ""
    async for event in provider.stream(messages):
        if event.get("type") == "token":
            answer += event.get("content", "")
    if not answer.strip():
        raise ValueError("Chat returned no text tokens")
    return answer


async def main():
    settings = get_settings()
    results = {}

    async def check(name, operation):
        start = time.monotonic()
        try:
            value = await asyncio.wait_for(operation(), timeout=60)
            results[name] = {"status": "PASS", "seconds": round(time.monotonic() - start, 2), **value}
        except httpx.HTTPStatusError as exc:
            results[name] = {"status": "FAIL", "http_status": exc.response.status_code}
        except Exception as exc:
            # Never print HTTP bodies, headers or full exception messages.
            results[name] = {"status": "FAIL", "error_type": type(exc).__name__}
        print(json.dumps({name: results[name]}, ensure_ascii=False), flush=True)

    async def chat_probe(provider):
        answer = await chat(ChatProvider(configured_choice(provider)), [{"role": "user", "content": "Reply with OK only."}])
        return {"model": configured_choice(provider).model, "text_chars": len(answer)}

    async def embedding_probe():
        if not settings.siliconflow_api_key:
            raise ValueError("Embedding key missing")
        vectors = await EmbeddingProvider().embed(["The verification code is ORCHID-482.", "A recipe for vegetable soup."])
        if len(vectors) != 2 or any(len(v) != settings.embedding_dimension or not all(math.isfinite(x) for x in v) for v in vectors):
            raise ValueError("Embedding result count, dimension or values invalid")
        return {"model": settings.embedding_model, "dimension": len(vectors[0])}

    async def rerank_probe():
        if not settings.rerank_enabled or not (settings.rerank_api_key or settings.siliconflow_api_key):
            raise ValueError("Rerank disabled or credential missing")
        scores = await RerankProvider().rerank("What is the verification code?", ["The verification code is ORCHID-482.", "A recipe for vegetable soup."], 2)
        if not scores or any(index not in (0, 1) or not math.isfinite(score) for index, score in scores):
            raise ValueError("Rerank returned no valid scores")
        return {"model": settings.rerank_model, "scored_documents": len(scores)}

    await asyncio.gather(check("chat", lambda: chat_probe("openai")), check("deepseek_chat", lambda: chat_probe("deepseek")), check("embedding", embedding_probe), check("rerank", rerank_probe))

    async def chain_probe():
        # Use isolated in-memory storage; no changes to existing documents,
        # collections, users, sessions, or databases.
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        store = object.__new__(VectorStore)
        store.settings = settings
        store.client = None
        store._vectors = {}
        texts = ["The verification code is ORCHID-482.", "A recipe for vegetable soup."]
        vectors = await EmbeddingProvider().embed(texts)
        with Session(engine) as db:
            for i, (content, vector) in enumerate(zip(texts, vectors)):
                chunk = DocumentChunk(id=f"probe-{i}", workspace_id="probe", knowledge_base_id="probe", document_id="probe", sequence=i, content=content, content_hash=hashlib.sha256(content.encode()).hexdigest())
                db.add(chunk)
                store.upsert([{"id": chunk.id, "vector": vector, "workspace_id": "probe", "knowledge_base_id": "probe"}])
            db.commit()
            hits = await hybrid_search(db, store, "probe", "probe", "What is the verification code?", 1)
            if not hits or "rerank_score" not in hits[0]:
                raise ValueError("Hybrid search fell back instead of performing rerank")
            answer = await chat(ChatProvider(configured_choice("openai")), [{"role": "system", "content": "Answer using only the provided evidence: " + hits[0]["chunk"].content}, {"role": "user", "content": "What is the verification code? Reply with the code only."}])
            if "ORCHID-482" not in answer:
                raise ValueError("Answer did not use retrieved evidence")
        engine.dispose()
        return {"storage": "isolated SQLite and in-memory vectors", "actual_rerank": True, "evidence_answer_verified": True}

    if all(results[name]["status"] == "PASS" for name in ("chat", "embedding", "rerank")):
        await check("rag_chain", chain_probe)
    else:
        results["rag_chain"] = {"status": "BLOCKED", "reason": "A required model probe failed"}
        print(json.dumps({"rag_chain": results["rag_chain"]}), flush=True)
    return 0 if results.get("rag_chain", {}).get("status") == "PASS" else 1


if __name__ == "__main__":
    import os
    os.chdir(ROOT)
    raise SystemExit(asyncio.run(main()))

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db
from app.main import app
from app.models.models import ChatMessage, Citation, Document, DocumentChunk
from app.api import routes


@pytest.fixture(scope="module")
def test_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="module")
def client(test_session_factory):
    def override_get_db():
        db = test_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # Do not enter the TestClient context here. The application's startup hook
    # intentionally connects to the configured production database, while this
    # test supplies its own dependency-overridden SQLite session.
    test_client = TestClient(app)
    yield test_client
    test_client.close()
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def account(client, test_session_factory):
    assert client.get("/api/v1/auth/setup-status").json() == {"initialized": False}
    response = client.post("/api/v1/auth/setup", json={"username": "reader", "password": "safe-password"})
    assert response.status_code == 200
    payload = response.json()
    token = payload["token"]
    headers = {"Authorization": f"Bearer {token}"}
    workspace_id = payload["workspace"]["id"]
    kb_response = client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"workspace_id": workspace_id, "name": "Research"},
    )
    assert kb_response.status_code == 200
    kb_id = kb_response.json()["id"]

    db: Session = test_session_factory()
    try:
        document = Document(
            workspace_id=workspace_id,
            knowledge_base_id=kb_id,
            filename="handbook.md",
            file_type=".md",
            storage_path="/tmp/handbook.md",
            file_size=128,
            content_hash="document-hash",
        )
        db.add(document)
        db.flush()
        chunk = DocumentChunk(
            workspace_id=workspace_id,
            knowledge_base_id=kb_id,
            document_id=document.id,
            sequence=0,
            content="The retention policy is seven years.",
            content_hash="chunk-hash",
            page_number=3,
            paragraph_index=2,
            char_start=10,
            char_end=48,
            heading_path=["Policies", "Retention"],
            index_status="indexed",
        )
        db.add(chunk)
        db.commit()
        chunk_id = chunk.id
    finally:
        db.close()
    return {"token": token, "headers": headers, "workspace_id": workspace_id, "kb_id": kb_id, "chunk_id": chunk_id}


def test_setup_status_and_citation_authorization(client, account):
    assert client.get("/api/v1/auth/setup-status").json() == {"initialized": True}

    unauthorized = client.get(f"/api/v1/chunks/{account['chunk_id']}/citation")
    assert unauthorized.status_code == 401

    response = client.get(
        f"/api/v1/chunks/{account['chunk_id']}/citation",
        headers=account["headers"],
    )
    assert response.status_code == 200
    citation = response.json()
    assert citation["document_id"]
    assert citation == {
        "chunk_id": account["chunk_id"],
        "document_id": citation["document_id"],
        "filename": "handbook.md",
        "content": "The retention policy is seven years.",
        "page_number": 3,
        "paragraph_index": 2,
        "heading_path": ["Policies", "Retention"],
        "char_start": 10,
        "char_end": 48,
    }


def test_chunking_config_can_be_read_and_updated(client, account):
    response = client.get(f"/api/v1/knowledge-bases/{account['kb_id']}/chunking-config", headers=account["headers"])
    assert response.status_code == 200
    assert response.json()["chunking_config"]["chunk_size"] == 512
    response = client.put(
        f"/api/v1/knowledge-bases/{account['kb_id']}/chunking-config",
        headers=account["headers"],
        json={"strategy": "recursive", "chunk_size": 300, "chunk_overlap": 30, "enable_parent_child": False},
    )
    assert response.status_code == 200
    assert response.json()["needs_reindex"] is True


def test_chunker_preview_uses_same_splitter(client, account):
    response = client.post(
        "/api/v1/chunker/preview",
        headers=account["headers"],
        json={"text": "# Title\n\n" + ("content " * 100), "chunking_config": {"chunk_size": 120, "chunk_overlap": 20, "enable_parent_child": False}},
    )
    assert response.status_code == 200
    assert response.json()["selected_strategy"] == "heading"
    assert response.json()["chunks"]


def test_rag_stream_emits_rich_citations_and_persists_them(client, account, test_session_factory, monkeypatch):
    db: Session = test_session_factory()
    try:
        chunk = db.get(DocumentChunk, account["chunk_id"])
        assert chunk is not None

        async def fake_search(*_args, **_kwargs):
            return [{"chunk": chunk, "score": 0.87}]

        class FakeProvider:
            choice = SimpleNamespace(provider="test-provider")

            async def stream(self, _messages):
                yield {"type": "token", "content": "Seven years."}
                yield {"type": "complete", "content": "Seven years."}

        monkeypatch.setattr(routes, "hybrid_search", fake_search)
        monkeypatch.setattr(routes, "ChatProvider", lambda _choice: FakeProvider())
    finally:
        db.close()

    session_response = client.post(
        "/api/v1/rag/sessions",
        headers=account["headers"],
        json={"workspace_id": account["workspace_id"], "knowledge_base_id": account["kb_id"]},
    )
    assert session_response.status_code == 200
    session_id = session_response.json()["id"]

    response = client.post(
        f"/api/v1/rag/sessions/{session_id}/messages",
        headers=account["headers"],
        json={"content": "How long is the retention policy?"},
    )
    assert response.status_code == 200
    events = []
    for frame in response.text.strip().split("\n\n"):
        data_line = next(line for line in frame.splitlines() if line.startswith("data:"))
        events.append(json.loads(data_line.removeprefix("data:").strip()))

    retrieval = next(event for event in events if event["type"] == "retrieval_result")
    assert retrieval["results"][0]["filename"] == "handbook.md"
    assert retrieval["results"][0]["heading_path"] == ["Policies", "Retention"]
    citation = next(event for event in events if event["type"] == "citation")
    assert citation["chunk_id"] == account["chunk_id"]
    assert citation["quoted_text"] == "The retention policy is seven years."
    assert events[-1]["type"] == "message_complete"

    db = test_session_factory()
    try:
        assistant = db.scalar(
            select(ChatMessage).where(ChatMessage.session_id == session_id, ChatMessage.role == "assistant")
        )
        assert assistant is not None
        stored = db.scalar(select(Citation).where(Citation.message_id == assistant.id))
        assert stored is not None
        assert stored.chunk_id == account["chunk_id"]
        assert stored.retrieval_rank == 1
        assert stored.quoted_text == "The retention policy is seven years."
    finally:
        db.close()


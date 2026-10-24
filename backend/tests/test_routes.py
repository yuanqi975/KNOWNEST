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
from app.models.models import ChatMessage, ChatSession, Citation, Document, DocumentChunk, MessageExecution, User
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


@pytest.mark.parametrize("mode", ["conversation", "rag", "agent"])
def test_conversation_rename_and_delete(client, account, test_session_factory, mode):
    path = "/conversations" if mode == "conversation" else f"/{mode}/sessions"
    created = client.post(f"/api/v1{path}", headers=account["headers"], json={
        "workspace_id": account["workspace_id"], "knowledge_base_id": account["kb_id"],
    })
    assert created.status_code == 200
    conversation_id = created.json()["id"]
    endpoint = f"/api/v1/conversations/{conversation_id}"
    for invalid in ["", "   ", "a" * 256]:
        assert client.patch(endpoint, headers=account["headers"], json={"title": invalid}).status_code == 422
    renamed = client.patch(endpoint, headers=account["headers"], json={"title": "  项目研究记录  "})
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "项目研究记录"
    assert client.get(endpoint, headers=account["headers"]).json()["title"] == "项目研究记录"
    listed = client.get(f"/api/v1/conversations?workspace_id={account['workspace_id']}", headers=account["headers"]).json()
    assert next(item for item in listed if item["id"] == conversation_id)["title"] == "项目研究记录"

    with test_session_factory() as db:
        message = ChatMessage(session_id=conversation_id, role="assistant", content="An answer.")
        db.add(message)
        db.flush()
        message_id = message.id
        document_id = db.get(DocumentChunk, account["chunk_id"]).document_id
        citation = Citation(message_id=message_id, citation_index=1, document_id=document_id, chunk_id=account["chunk_id"], quoted_text="A source.")
        db.add_all([citation, MessageExecution(message_id=message_id, mode="rag")])
        db.commit()
        citation_id = citation.id

    assert client.delete(endpoint, headers=account["headers"]).status_code == 204
    assert client.get(endpoint, headers=account["headers"]).status_code == 404
    assert client.delete(endpoint, headers=account["headers"]).status_code == 404
    listed = client.get(f"/api/v1/conversations?workspace_id={account['workspace_id']}", headers=account["headers"]).json()
    assert all(item["id"] != conversation_id for item in listed)
    with test_session_factory() as db:
        assert db.get(ChatSession, conversation_id) is None
        assert db.get(ChatMessage, message_id) is None
        assert db.get(Citation, citation_id) is None
        assert db.get(MessageExecution, message_id) is None
        assert db.get(Document, document_id) is not None
        assert db.get(DocumentChunk, account["chunk_id"]) is not None


def test_conversation_mutations_require_ownership(client, account, test_session_factory):
    with test_session_factory() as db:
        other = User(username="other-conversation-owner", password_hash="unused")
        db.add(other)
        db.flush()
        conversation = ChatSession(user_id=other.id, workspace_id=account["workspace_id"], mode="conversation", title="Private conversation")
        db.add(conversation)
        db.commit()
        endpoint = f"/api/v1/conversations/{conversation.id}"
    assert client.patch(endpoint, json={"title": "Changed"}).status_code == 401
    assert client.delete(endpoint).status_code == 401
    assert client.patch(endpoint, headers=account["headers"], json={"title": "Changed"}).status_code == 404
    assert client.delete(endpoint, headers=account["headers"]).status_code == 404
    with test_session_factory() as db:
        assert db.get(ChatSession, conversation.id).title == "Private conversation"


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




def test_memory_api_scope_versions_and_context(client, account, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "context_cache_enabled", False)
    base = f"/api/v1/workspaces/{account['workspace_id']}/memories"
    payload = {"workspace_id": account["workspace_id"], "type": "preference", "content": "回答请简洁", "knowledge_base_id": account["kb_id"]}
    created = client.post(base, headers=account["headers"], json=payload)
    assert created.status_code == 200
    item = created.json()
    assert item["status"] == "active" and item["version"] == 1
    updated = client.patch(f"/api/v1/memories/{item['id']}", headers=account["headers"], json={"content": "回答请使用中文", "version": 1})
    assert updated.status_code == 200 and updated.json()["version"] == 2
    stale = client.patch(f"/api/v1/memories/{item['id']}", headers=account["headers"], json={"content": "stale", "version": 1})
    assert stale.status_code == 409
    invalid = client.post(base, headers=account["headers"], json={**payload, "workspace_id": "wrong"})
    assert invalid.status_code == 400
    assert client.delete(f"/api/v1/memories/{item['id']}", headers=account["headers"]).status_code == 204


def test_stream_latest_question_idempotent_replay_and_explicit_memory(client, account, test_session_factory, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "context_cache_enabled", False)
    called = []
    class Provider:
        choice = SimpleNamespace(provider="fake")
        async def stream(self, messages):
            called.append(messages)
            yield {"type": "token", "content": "answer"}
            yield {"type": "complete"}
    monkeypatch.setattr(routes, "ChatProvider", lambda _: Provider())
    session = client.post("/api/v1/conversations", headers=account["headers"], json={"workspace_id": account["workspace_id"]}).json()
    with test_session_factory() as db:
        for i in range(15):
            db.add(ChatMessage(session_id=session["id"], role="user", content=f"u{i}", sequence=i*2+1))
            db.add(ChatMessage(session_id=session["id"], role="assistant", content=f"a{i}", sequence=i*2+2))
        db.get(ChatSession, session["id"]).next_sequence = 31
        db.commit()
    payload = {"content": "请记住：回答请用中文", "mode": "rag", "client_request_id": "replay-test"}
    first = client.post(f"/api/v1/conversations/{session['id']}/messages", headers=account["headers"], json=payload)
    assert first.status_code == 200 and '"type": "memory_saved"' in first.text
    assert '"type": "message_complete"' in first.text
    assert called[0][-1]["content"] == payload["content"]
    assert any(m["content"] == "a14" for m in called[0])
    replay = client.post(f"/api/v1/conversations/{session['id']}/messages", headers=account["headers"], json=payload)
    assert '"replayed": true' in replay.text and len(called) == 1
    context = client.get(f"/api/v1/conversations/{session['id']}/context", headers=account["headers"])
    assert context.status_code == 200 and context.json()["status"] == "completed"
    assert context.json()["memories"]


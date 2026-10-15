from __future__ import annotations

import json
import os
import sys
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
import httpx

from app.evaluation import (
    EVALUATION_DIR,
    EvaluationDataError,
    binary_metrics,
    citation_metrics,
    load_cases,
    load_manifest,
    percentile95,
    retrieval_metrics,
    validate_dataset,
)
from app import evaluation_cli
from app.evaluation_cli import EvaluationRunError, _delete_workspace, _diagnose_retrieval, _diagnostic_report, _ensure_isolated_local, _markdown_report, _redact_model_text, _send_question


def test_checked_in_dataset_has_fixed_distribution_and_valid_evidence():
    result = validate_dataset()
    assert result["valid"] is True
    assert result["case_count"] == 120
    assert result["category_counts"] == {
        "simple": 28,
        "composite": 20,
        "no_answer": 18,
        "conflict": 12,
        "table_calculation": 12,
        "multi_turn": 10,
        "tools_mcp": 10,
        "degradation": 10,
    }
    assert result["language_counts"] == {"zh": 90, "en": 30}
    assert result["scenario_count"] >= 16


def test_retrieval_metrics_reflect_removed_or_decoy_evidence():
    case = {
        "gold_claims": [{"text": "The answer is 14 days.", "evidence": [{"source_id": "handbook", "quote": "Equipment loans last 14 calendar days."}]}]
    }
    source_map = {"right": "handbook", "decoy": "decoy"}
    found = retrieval_metrics(case, [{"document_id": "right", "content": "Equipment loans last 14 calendar days."}], source_map)
    absent = retrieval_metrics(case, [], source_map)
    distractor = retrieval_metrics(case, [{"document_id": "decoy", "content": "Equipment loans last 14 calendar days."}], source_map)
    assert found["recall@5"] == 1
    assert found["mrr"] == 1
    assert found["evidence_coverage"] == 1
    assert absent["recall@5"] == 0
    assert distractor["recall@5"] == 0


def test_retrieval_diagnosis_separates_candidate_miss_rerank_drop_and_chunk_mismatch():
    case = {"gold_claims": [{"evidence": [
        {"source_id": "candidate_miss", "quote": "missing exact passage"},
        {"source_id": "rerank", "quote": "exact passage in candidate"},
        {"source_id": "chunk", "quote": "gold passage split across chunks"},
    ]}]}
    diagnostics = {"final_count": 2, "candidate_trace": [
        {"chunk_id": "c1", "document_id": "d2", "content": "exact passage in candidate", "fusion_rank": 7, "rerank_rank": 18},
        {"chunk_id": "c2", "document_id": "d3", "content": "nearby different text", "fusion_rank": 4, "rerank_rank": 1},
    ]}
    diagnosis = _diagnose_retrieval(case, diagnostics, [{"chunk_id": "c2"}], {"d1": "candidate_miss", "d2": "rerank", "d3": "chunk"})
    assert [item["diagnosis"] for item in diagnosis["evidence"]] == ["candidate_miss", "rerank_below_final", "chunk_mismatch"]


def test_metrics_handle_empty_inputs_and_validate_citations():
    assert binary_metrics([], [])["accuracy"] == 0
    assert percentile95([]) is None
    assert percentile95([1, 2, 3, 4]) == 4
    case = {"gold_claims": [{"evidence": [{"source_id": "s", "quote": "Evidence passage."}]}]}
    scores = citation_metrics(
        [{"document_id": "doc", "chunk_id": "chunk", "source_id": "s", "quoted_text": "Evidence passage."}],
        evaluation_document_ids={"doc"},
        case=case,
    )
    assert scores == {"citation_count": 1, "valid_id_rate": 1, "support_rate": 1}
    assert citation_metrics(
        [{"document_id": "doc", "chunk_id": "unretrieved", "source_id": "s", "quoted_text": "Evidence passage."}],
        evaluation_document_ids={"doc"},
        case=case,
        retrieved_chunk_ids={"some-other-chunk"},
    )["valid_id_rate"] == 0


def test_missing_evidence_excerpt_invalidates_manifest_copy(tmp_path: Path):
    manifest = load_manifest()
    cases = load_cases()
    case = next(item for item in cases if item["gold_claims"])
    case["gold_claims"][0]["evidence"][0]["quote"] = "quote not in fixed corpus"
    with pytest.raises(EvaluationDataError, match="evidence quote not found"):
        validate_dataset(manifest, cases, evaluation_dir=EVALUATION_DIR, repo_root=Path(__file__).resolve().parents[2])


def test_diagnostic_run_is_explicitly_not_acceptance():
    report = _diagnostic_report("unit-diagnostic")
    assert report["result_type"] == "offline_diagnostic_not_for_acceptance"
    assert report["acceptance_status"] == "not_scored"
    assert report["scenario_suite"]["status"] == "contract_only_not_executed"
    markdown = _markdown_report(report)
    assert "Deterministic metric plumbing smoke" in markdown
    assert "retrieval_empty_results" in markdown
    assert "not Runtime or model-quality scores" in markdown
    assert "Answer correctness: None" not in markdown


def test_real_run_requires_explicit_isolated_marker_and_loopback(monkeypatch):
    settings = SimpleNamespace(
        environment="development",
        database_url="postgresql+psycopg://local:local@localhost:5432/weknora_eval",
        milvus_collection="vectors_eval",
        storage_path="./data/eval-uploads",
        milvus_uri="http://localhost:19530",
        redis_url="redis://localhost:6379/15",
    )
    monkeypatch.delenv("WEKNORA_EVAL_ENV", raising=False)
    monkeypatch.setenv("WEKNORA_EVAL_TOKEN", "dedicated-test-token")
    with pytest.raises(EvaluationRunError, match="WEKNORA_EVAL_ENV"):
        _ensure_isolated_local(settings, "http://127.0.0.1:8000")
    monkeypatch.setenv("WEKNORA_EVAL_ENV", "isolated")
    assert _ensure_isolated_local(settings, "http://127.0.0.1:8000") == ""
    with pytest.raises(EvaluationRunError, match="loopback"):
        _ensure_isolated_local(settings, "https://example.com")


def test_real_run_refuses_production_or_non_eval_database(monkeypatch):
    monkeypatch.setenv("WEKNORA_EVAL_ENV", "isolated")
    monkeypatch.setenv("WEKNORA_EVAL_TOKEN", "dedicated-test-token")
    production = SimpleNamespace(
        environment="production",
        database_url="postgresql+psycopg://local:local@localhost:5432/weknora_eval",
        milvus_collection="vectors_eval",
        storage_path="./data/eval-uploads",
        milvus_uri="http://localhost:19530",
        redis_url="redis://localhost:6379/15",
    )
    with pytest.raises(EvaluationRunError, match="production"):
        _ensure_isolated_local(production, "http://127.0.0.1:8000")
    non_eval_db = SimpleNamespace(**(vars(production) | {"environment": "development", "database_url": "sqlite:///./weknora.db"}))
    with pytest.raises(EvaluationRunError, match="database"):
        _ensure_isolated_local(non_eval_db, "http://127.0.0.1:8000")


def test_report_redaction_removes_common_key_shapes():
    assert _redact_model_text("Bearer abc123 and sk-12345678901234567890") == "Bearer [REDACTED] and [REDACTED_KEY]"


def test_multiturn_replay_uses_user_turns_and_regenerates_assistant_turns(monkeypatch):
    replayed = []
    durations = iter([0.1, 0.2, 0.3])

    class SessionResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "evaluation-session"}

    class Client:
        async def post(self, url, json):
            return SessionResponse()

    async def fake_sse_post(client, url, body):
        replayed.append(body["content"])
        return [], next(durations)

    monkeypatch.setattr(evaluation_cli, "_sse_post", fake_sse_post)
    case = {
        "history": [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "Fixture answer that must not be sent"},
            {"role": "user", "content": "Follow-up question"},
            {"role": "assistant", "content": "Another fixture answer that must not be sent"},
        ],
        "question": "Current question",
    }

    result = asyncio.run(_send_question(Client(), "http://127.0.0.1/api/v1", "workspace", "kb", "rag", case))

    assert replayed == ["First question", "Follow-up question", "Current question"]
    assert result[3] == 0.3
    assert result[4]["history_replay_latency_seconds"] == 0.3


def test_workspace_cleanup_checks_http_status():
    class Client:
        async def delete(self, url):
            request = httpx.Request("DELETE", url)
            return httpx.Response(500, request=request)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(_delete_workspace(Client(), "http://127.0.0.1/api/v1", "evaluation-workspace"))

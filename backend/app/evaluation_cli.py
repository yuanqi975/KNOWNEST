"""Safe local runner for the checked-in WeKnora Runtime evaluation set."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.evaluation import (
    EVALUATION_DIR,
    REPO_ROOT,
    binary_metrics,
    citation_metrics,
    load_cases,
    load_manifest,
    percentile95,
    retrieval_metrics,
    sha256_file,
    validate_dataset,
)
from app.services.providers import ChatProvider, EmbeddingProvider, RerankProvider, configured_choice

RUN_OUTPUT = REPO_ROOT / "output" / "evaluation"
RUBRIC_PATH = EVALUATION_DIR / "rubric.md"
GIT_REVISION = "unknown"


class EvaluationRunError(RuntimeError):
    """Expected, user-actionable failure before or during a local eval run."""


def _git_revision() -> str:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _git_working_tree_provenance() -> dict[str, Any]:
    """Fingerprint tracked local edits without putting source or secrets in reports."""
    import subprocess

    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO_ROOT,
            check=True, capture_output=True, timeout=5,
        ).stdout
        diff = subprocess.run(
            ["git", "diff", "HEAD", "--binary"], cwd=REPO_ROOT,
            check=True, capture_output=True, timeout=10,
        ).stdout
        return {
            "tracked_changes_present": bool(status.strip()),
            "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
        }
    except Exception:
        return {"status": "unknown"}


def _code_artifact_hashes() -> dict[str, str]:
    paths = (
        "backend/app/api/routes.py",
        "backend/app/core/config.py",
        "backend/app/core/db.py",
        "backend/app/main.py",
        "backend/app/models/models.py",
        "backend/app/services/agent.py",
        "backend/app/services/ingestion.py",
        "backend/app/services/parser.py",
        "backend/app/services/providers.py",
        "backend/app/services/retrieval.py",
        "backend/app/services/vector_store.py",
        "backend/app/evaluation.py",
        "backend/app/evaluation_cli.py",
        "dataset/evaluation/build_assets.py",
        "dataset/evaluation/rubric.md",
    )
    return {path: sha256_file(REPO_ROOT / path) for path in paths if (REPO_ROOT / path).is_file()}


def _ensure_isolated_local(settings: Any, base_url: str) -> str:
    if os.environ.get("WEKNORA_EVAL_ENV", "").strip().lower() != "isolated":
        raise EvaluationRunError("Set WEKNORA_EVAL_ENV=isolated only for a dedicated evaluation deployment.")
    if not os.environ.get("WEKNORA_EVAL_TOKEN", "").strip():
        raise EvaluationRunError("WEKNORA_EVAL_TOKEN must contain a dedicated user token for the isolated evaluation deployment.")
    if settings.environment.lower() not in {"development", "test", "local"}:
        raise EvaluationRunError("Evaluation refuses production or staging configuration.")

    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise EvaluationRunError("The API URL must be an HTTP(S) URL without embedded credentials.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))}
    except OSError as exc:
        raise EvaluationRunError("The API host could not be resolved; only loopback hosts are allowed.") from exc
    if not addresses or any(not address.startswith("127.") and address != "::1" for address in addresses):
        raise EvaluationRunError("Evaluation is restricted to a loopback API host; remote and production hosts are refused.")

    try:
        database = make_url(settings.database_url)
    except Exception as exc:
        raise EvaluationRunError("The configured database URL is invalid.") from exc
    db_marker = (database.database or "").lower()
    if "eval" not in db_marker:
        raise EvaluationRunError("DATABASE_URL must point to a dedicated database whose name contains 'eval'.")
    if database.host and database.host.lower() not in {"localhost", "127.0.0.1", "::1", "postgres"}:
        raise EvaluationRunError("The evaluation database must be local to the isolated evaluation deployment.")
    if "eval" not in settings.milvus_collection.lower():
        raise EvaluationRunError("MILVUS_COLLECTION must be a dedicated collection whose name contains 'eval'.")
    milvus_host = urlsplit(settings.milvus_uri).hostname
    if milvus_host not in {"localhost", "127.0.0.1", "::1", "milvus"}:
        raise EvaluationRunError("MILVUS_URI must point to the isolated local Milvus service.")
    if "eval" not in settings.storage_path.lower().replace("\\", "/"):
        raise EvaluationRunError("STORAGE_PATH must be a dedicated evaluation path containing 'eval'.")
    redis = make_url(settings.redis_url)
    if redis.host and redis.host.lower() not in {"localhost", "127.0.0.1", "::1", "redis"}:
        raise EvaluationRunError("REDIS_URL must point to the isolated local Redis service.")
    if (redis.database or "0") == "0":
        raise EvaluationRunError("REDIS_URL must use a non-default dedicated database index for evaluation (for example /15).")
    return parsed.path.rstrip("/")


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP request failed with status {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "request timed out"
    return type(exc).__name__


def _redact_model_text(text: str) -> str:
    text = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [REDACTED]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED_KEY]", text)
    return re.sub(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", text)


async def _preflight(settings: Any) -> dict[str, Any]:
    missing = []
    if not settings.siliconflow_api_key:
        missing.append("real Embedding credential (SILICONFLOW_API_KEY)")
    if not settings.rerank_enabled:
        missing.append("Rerank is disabled (RERANK_ENABLED must be true)")
    if not (settings.rerank_api_key or settings.siliconflow_api_key):
        missing.append("real Rerank credential (RERANK_API_KEY or SILICONFLOW_API_KEY)")
    if not settings.openai_api_key:
        missing.append("real LLM credential for the current runtime default provider (OPENAI_API_KEY)")
    if missing:
        raise EvaluationRunError("Preflight failed: " + "; ".join(missing))

    started = time.perf_counter()
    try:
        vectors = await EmbeddingProvider().embed(["WeKnora evaluation readiness probe"])
        if len(vectors) != 1 or len(vectors[0]) != settings.embedding_dimension:
            raise EvaluationRunError("Embedding readiness probe returned an invalid vector dimension.")
        ranked = await RerankProvider().rerank("readiness probe", ["evaluation probe document"], top_n=1)
        if not ranked:
            raise EvaluationRunError("Rerank readiness probe returned no ranking result.")
        response = ""
        async for event in ChatProvider(configured_choice("openai")).stream([{"role": "user", "content": "Reply with OK."}]):
            if event.get("type") == "token":
                response += str(event.get("content", ""))
        if not response.strip() or "未配置模型 API Key" in response:
            raise EvaluationRunError("LLM readiness probe did not return a real model response.")
    except EvaluationRunError:
        raise
    except Exception as exc:
        raise EvaluationRunError(f"Real-model preflight failed ({_safe_error(exc)}); no evaluation cases were run.") from exc
    return {
        "status": "passed",
        "duration_seconds": round(time.perf_counter() - started, 3),
        "embedding": {"model": settings.embedding_model, "dimension": settings.embedding_dimension, "real_provider": True},
        "rerank": {"model": settings.rerank_model, "enabled": True, "real_provider": True},
        "llm": {"provider": "openai-compatible", "model": settings.openai_model, "real_provider": True},
    }


def _parse_sse_line_state(events: list[dict[str, Any]], event_name: str | None, data_lines: list[str]) -> tuple[str | None, list[str]]:
    if not data_lines:
        return None, []
    try:
        payload = json.loads("\n".join(data_lines))
    except json.JSONDecodeError:
        return None, []
    if isinstance(payload, dict):
        payload.setdefault("type", event_name or "message")
        events.append(payload)
    return None, []


async def _sse_post(client: httpx.AsyncClient, url: str, body: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    events: list[dict[str, Any]] = []
    started = time.perf_counter()
    async with client.stream("POST", url, json=body, timeout=240) as response:
        response.raise_for_status()
        event_name: str | None = None
        data_lines: list[str] = []
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
            elif not line:
                event_name, data_lines = _parse_sse_line_state(events, event_name, data_lines)
        _parse_sse_line_state(events, event_name, data_lines)
    return events, time.perf_counter() - started


async def _delete_workspace(client: httpx.AsyncClient, api_root: str, workspace_id: str) -> None:
    """Delete the ephemeral evaluation workspace and verify the API accepted it."""
    response = await client.delete(f"{api_root}/workspaces/{workspace_id}")
    response.raise_for_status()


async def _judge_answer(
    answer: str,
    case: dict[str, Any],
    settings: Any,
    rubric: str,
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt = {
        "question": case["question"],
        "answerability": case["answerability"],
        "gold_claims": case.get("gold_claims", []),
        "must_not_claim": case.get("must_not_claim", []),
        "answer": _redact_model_text(answer),
        "runtime_citations": citations,
    }
    messages = [
        {"role": "system", "content": rubric},
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ]
    output = ""
    try:
        async for event in ChatProvider(configured_choice("openai")).stream(messages):
            if event.get("type") == "token":
                output += str(event.get("content", ""))
    except Exception as exc:
        return {"status": "error", "error": _safe_error(exc)}
    try:
        match = re.search(r"\{.*\}", output, re.S)
        payload = json.loads(match.group(0)) if match else None
        if not isinstance(payload, dict):
            raise ValueError("no JSON object")
        normalized = {
            key: payload.get(key)
            for key in ("answer_correct", "evidence_supported", "appropriate_abstention", "forbidden_assertion", "citation_support_rate")
        }
        if not all(isinstance(normalized[key], bool) for key in ("answer_correct", "evidence_supported", "appropriate_abstention", "forbidden_assertion")):
            raise ValueError("invalid rubric fields")
        citation_support = normalized["citation_support_rate"]
        if isinstance(citation_support, bool) or not isinstance(citation_support, (int, float)) or not 0 <= citation_support <= 1:
            raise ValueError("invalid citation support rate")
        normalized["citation_support_rate"] = float(citation_support)
        return {"status": "scored", **normalized}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {"status": "error", "error": "judge_output_invalid"}


def _case_rubric_result(case: dict[str, Any], judge: dict[str, Any]) -> dict[str, Any]:
    is_no_answer = case.get("answerability") == "insufficient"
    expected_decision = (
        bool(judge.get("appropriate_abstention")) and not bool(judge.get("forbidden_assertion"))
        if is_no_answer else bool(judge.get("answer_correct"))
    )
    return {
        "answer_correct": judge.get("answer_correct"),
        "evidence_supported": judge.get("evidence_supported"),
        "refused": judge.get("appropriate_abstention"),
        "forbidden_assertion": judge.get("forbidden_assertion"),
        "citation_support_rate": judge.get("citation_support_rate"),
        "decision_correct": expected_decision,
    }


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    qa_results = [item for item in results if item.get("case_type") == "qa"]
    category_summary: dict[str, Any] = {}
    for category in sorted({item["category"] for item in qa_results}):
        selected = [item for item in qa_results if item["category"] == category]
        category_summary[category] = {
            "count": len(selected),
            "answer_correct_rate": _mean([float(item["quality"]["answer_correct"]) for item in selected if isinstance(item.get("quality", {}).get("answer_correct"), bool)]),
            "evidence_supported_rate": _mean([float(item["quality"]["evidence_supported"]) for item in selected if isinstance(item.get("quality", {}).get("evidence_supported"), bool)]),
            "recall@5": _mean([item["retrieval"]["recall@5"] for item in selected if item.get("retrieval", {}).get("recall@5") is not None]),
            "mrr": _mean([item["retrieval"]["mrr"] for item in selected if item.get("retrieval", {}).get("mrr") is not None]),
        }
    all_cited = [citation for item in qa_results for citation in item.get("cited_references", [])]
    citation_validity = sum(item["valid"] for item in all_cited) / len(all_cited) if all_cited else 0.0
    cited_support = _mean([float(item["quality"]["citation_support_rate"]) for item in qa_results if item["answerability"] != "insufficient" and isinstance(item.get("quality", {}).get("citation_support_rate"), (int, float))])
    no_answer = [item for item in qa_results if item["answerability"] == "insufficient"]
    no_answer_correct = [bool(item.get("quality", {}).get("decision_correct")) for item in no_answer]
    refusal_expected = [item["answerability"] == "insufficient" for item in qa_results]
    refusal_predicted = [bool(item.get("quality", {}).get("refused")) for item in qa_results]
    refusal = binary_metrics(refusal_expected, refusal_predicted)
    no_answer_rate = _mean([float(item.get("quality", {}).get("decision_correct")) for item in no_answer if isinstance(item.get("quality", {}).get("decision_correct"), bool)])
    duration_values = [float(item["latency_seconds"]) for item in qa_results]
    history_replay_durations = [float(item.get("history_replay_latency_seconds", 0)) for item in qa_results if item.get("history_replay_latency_seconds", 0) > 0]
    ordinary_durations = [float(item["latency_seconds"]) for item in qa_results if item.get("expected", {}).get("target_complexity") in {"simple", "composite"}]
    research_durations = [float(item["latency_seconds"]) for item in qa_results if item.get("expected", {}).get("target_complexity") == "research"]
    tool_cases = [item for item in qa_results if item.get("category") == "tools_mcp"]
    tool_scored = [item for item in tool_cases if item.get("tool_expected") is not None]
    tool_accuracy = _mean([float(item["tool_expected"]) for item in tool_scored])
    target_tool_scored = [item for item in tool_cases if item.get("target_tool_expected") is not None]
    target_tool_accuracy = _mean([float(item["target_tool_expected"]) for item in target_tool_scored])
    answer_correct = _mean([float(item["quality"]["answer_correct"]) for item in qa_results if isinstance(item.get("quality", {}).get("answer_correct"), bool)])
    evidence_supported = _mean([float(item["quality"]["evidence_supported"]) for item in qa_results if isinstance(item.get("quality", {}).get("evidence_supported"), bool)])
    route_scored = [item for item in qa_results if isinstance(item.get("route_expected"), bool)]
    route_planner_accuracy = _mean([float(item["route_expected"]) for item in route_scored])
    return {
        "per_category": category_summary,
        "retrieval": {
            "recall@5": _mean([item["retrieval"]["recall@5"] for item in qa_results if item.get("retrieval", {}).get("recall@5") is not None]),
            "recall@8": _mean([item["retrieval"]["recall@8"] for item in qa_results if item.get("retrieval", {}).get("recall@8") is not None]),
            "recall@10": _mean([item["retrieval"]["recall@10"] for item in qa_results if item.get("retrieval", {}).get("recall@10") is not None]),
            "mrr": _mean([item["retrieval"]["mrr"] for item in qa_results if item.get("retrieval", {}).get("mrr") is not None]),
            "ndcg": _mean([item["retrieval"]["ndcg"] for item in qa_results if item.get("retrieval", {}).get("ndcg") is not None]),
            "evidence_coverage": _mean([item["retrieval"]["evidence_coverage"] for item in qa_results if item.get("retrieval", {}).get("evidence_coverage") is not None]),
        },
        "routing": {"query_plan_complexity_accuracy": route_planner_accuracy, "scored_case_count": len(route_scored), "automatic_mode_route_accuracy": {"status": "not_implemented", "reason": "The current Runtime has explicit RAG/Agent endpoints, not an automatic mode dispatcher."}},
        "tools": {"baseline_expected_tool_accuracy": tool_accuracy, "target_tool_accuracy_on_observed_route": target_tool_accuracy, "scored_case_count": len(tool_scored), "target_scored_case_count": len(target_tool_scored), "tool_case_count": len(tool_cases)},
        "answer": {"conclusion_correct_rate": answer_correct, "evidence_supported_rate": evidence_supported},
        "citations": {"answer_cited_id_valid_rate": citation_validity, "answer_cited_quote_support_rate": cited_support, "cited_id_count": len(all_cited)},
        "no_answer": {"precision_recall": refusal, "classification_accuracy": refusal["accuracy"], "accuracy": no_answer_rate, "correct_count": sum(no_answer_correct), "total": len(no_answer)},
        "latency_seconds": {
            "ordinary_p95": percentile95(ordinary_durations),
            "research_p95": percentile95(research_durations),
            "all_p95": percentile95(duration_values),
            "history_replay_p95": percentile95(history_replay_durations),
        },
    }


def _acceptance_targets(metrics: dict[str, Any]) -> dict[str, Any]:
    citations = metrics["citations"]
    no_answer = metrics["no_answer"]
    latency = metrics["latency_seconds"]
    def threshold(value: float | None, target: float, comparator: str = "gte") -> dict[str, Any]:
        if value is None:
            return {"status": "not_measured", "target": target, "value": None}
        passed = value >= target if comparator == "gte" else value <= target
        return {"status": "pass" if passed else "fail", "target": target, "value": value}
    return {
        "citation_id_validity_100_percent": threshold(citations["answer_cited_id_valid_rate"], 1.0),
        "citation_support_at_least_90_percent": threshold(citations["answer_cited_quote_support_rate"], 0.90),
        "no_answer_refusal_at_least_85_percent": threshold(no_answer["accuracy"], 0.85) | {"minimum_correct_count": 16, "sample_count": no_answer.get("total", 18)},
        "ordinary_p95_at_most_20s": threshold(latency["ordinary_p95"], 20.0, "lte"),
        "research_p95_at_most_45s": threshold(latency["research_p95"], 45.0, "lte"),
        "cross_workspace_unauthorized_access_zero": {"status": "not_implemented", "reason": "Independent chain/security scenarios were defined but were not executed by the QA runner."},
        "automatic_route_classifier": {"status": "not_implemented"},
        "vector_reconciliation": {"status": "not_implemented"},
        "manual_review": {"status": "pending", "reason": "Review all high-risk failures and at least 20% deterministic random sample before acceptance."},
    }


def _markdown_report(report: dict[str, Any]) -> str:
    metrics = report.get("metrics", {})
    if report.get("result_type") == "offline_diagnostic_not_for_acceptance":
        smoke = metrics.get("metric_smoke", {})
        dataset = report.get("dataset", {})
        lines = [
            f"# WeKnora diagnostic run {report['run_id']}",
            "",
            "- Result type: `offline_diagnostic_not_for_acceptance`",
            "- Acceptance status: `not_scored`",
            f"- Code revision: `{report.get('code_revision', 'unknown')}`",
            f"- Tracked working-tree changes: `{report.get('working_tree', {}).get('tracked_changes_present', 'unknown')}`",
            f"- Dataset: {dataset.get('case_count')} QA cases, {dataset.get('scenario_count')} separate chain scenarios",
            "",
            "## Deterministic metric plumbing smoke",
            "",
            "These values only exercise metric calculations; they are not Runtime or model-quality scores.",
            "",
            "| Check | Result |",
            "|---|---:|",
        ]
        lines.extend(f"| {name} | {value} |" for name, value in smoke.items())
        lines += ["", "## Notes", ""]
        lines.extend(f"- {note}" for note in report.get("notes", []))
        lines.append("")
        return "\n".join(lines)

    targets = report.get("acceptance_targets", {})
    lines = [
        f"# WeKnora evaluation run {report['run_id']}",
        "",
        f"- Result type: `{report['result_type']}`",
        f"- Scope: `{'partial run, ' + str(report.get('evaluation_scope', {}).get('cases_run')) + '/' + str(report.get('evaluation_scope', {}).get('full_dataset_case_count')) + ' QA cases' if report.get('evaluation_scope', {}).get('partial') else 'full dataset'}`",
        "- This partial run is not eligible for full acceptance." if report.get('evaluation_scope', {}).get('partial') else "",
        f"- Started: {report['started_at']}",
        f"- Code revision: `{report.get('code_revision', 'unknown')}`",
        f"- Tracked working-tree changes: `{report.get('working_tree', {}).get('tracked_changes_present', 'unknown')}`",
        f"- Corpus cases: {report['dataset']['case_count']} QA + {report['dataset']['scenario_count']} separate chain scenarios",
        f"- Manual review: `{report.get('manual_review', {}).get('status', 'not_applicable')}`",
        "",
        "## Quality baseline (current Runtime)",
        "",
        f"- Answer correctness: {metrics.get('answer', {}).get('conclusion_correct_rate')}",
        f"- Evidence support: {metrics.get('answer', {}).get('evidence_supported_rate')}",
        f"- Retrieval Recall@5: {metrics.get('retrieval', {}).get('recall@5')}; MRR: {metrics.get('retrieval', {}).get('mrr')}; nDCG: {metrics.get('retrieval', {}).get('ndcg')}",
        f"- Valid cited IDs: {metrics.get('citations', {}).get('answer_cited_id_valid_rate')}; cited-quote support: {metrics.get('citations', {}).get('answer_cited_quote_support_rate')}",
        f"- No-answer refusal: {metrics.get('no_answer', {}).get('correct_count')}/{metrics.get('no_answer', {}).get('total')}; precision {metrics.get('no_answer', {}).get('precision_recall', {}).get('precision')}; recall {metrics.get('no_answer', {}).get('precision_recall', {}).get('recall')}",
        f"- P95 latency: ordinary {metrics.get('latency_seconds', {}).get('ordinary_p95')}s; research {metrics.get('latency_seconds', {}).get('research_p95')}s",
        f"- Multi-turn history replay setup P95 (excluded from answer latency): {metrics.get('latency_seconds', {}).get('history_replay_p95')}s",
        "",
        "## P0/P1 acceptance targets (kept separate from baseline)",
        "",
        "| Target | Status | Value | Threshold |",
        "|---|---:|---:|---:|",
    ]
    for name, item in targets.items():
        if isinstance(item, dict):
            lines.append(f"| {name} | {item.get('status')} | {item.get('value', '—')} | {item.get('target', '—')} |")
        else:
            lines.append(f"| {name} | {item} | — | — |")
    lines += ["", "## Scenario slices", "", "| Category | N | Answer correct | Evidence supported | Recall@5 | MRR |", "|---|---:|---:|---:|---:|---:|"]
    for category, row in metrics.get("per_category", {}).items():
        lines.append(f"| {category} | {row['count']} | {row['answer_correct_rate']} | {row['evidence_supported_rate']} | {row['recall@5']} | {row['mrr']} |")
    lines += ["", "## Runtime and failure notes", ""]
    for note in report.get("notes", []):
        lines.append(f"- {note}")
    lines += ["", "This report is not an acceptance sign-off until required human review is complete.", ""]
    return "\n".join(lines)


def _write_report(report: dict[str, Any]) -> Path:
    run_dir = RUN_OUTPUT / report["run_id"]
    markdown = _markdown_report(report)
    json_report = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "report.json").write_text(json_report, encoding="utf-8")
    (run_dir / "report.md").write_text(markdown, encoding="utf-8")
    return run_dir


async def _index_corpus(client: httpx.AsyncClient, api_root: str, workspace_id: str, kb_id: str, manifest: dict[str, Any]) -> dict[str, str]:
    source_to_document: dict[str, str] = {}
    source_to_upload_name = {item["id"]: item["upload_name"] for item in manifest["sources"]}
    for source in manifest["sources"]:
        path = REPO_ROOT / source["path"]
        response = await client.post(
            f"{api_root}/knowledge-bases/{kb_id}/documents",
            content=path.read_bytes(),
            headers={"X-Filename": source["upload_name"], "Content-Type": "application/octet-stream"},
            timeout=240,
        )
        response.raise_for_status()
        uploaded = response.json()
        document_id = uploaded["document_id"]
        job_id = uploaded["job_id"]
        source_to_document[source["id"]] = document_id
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            job_response = await client.get(f"{api_root}/jobs/{job_id}")
            job_response.raise_for_status()
            job = job_response.json()
            if job.get("status") == "indexed":
                break
            if job.get("status") == "failed":
                raise EvaluationRunError(f"Corpus ingestion failed for {source['id']}.")
            await asyncio.sleep(1)
        else:
            raise EvaluationRunError(f"Corpus ingestion timed out for {source['id']}; confirm the isolated Celery worker is running.")
    if len(source_to_document) != len(source_to_upload_name):
        raise EvaluationRunError("Not all manifest documents were indexed.")
    return source_to_document


async def _send_question(
    client: httpx.AsyncClient,
    api_root: str,
    workspace_id: str,
    kb_id: str,
    mode: str,
    case: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], float, dict[str, Any]]:
    created = await client.post(f"{api_root}/chat/{mode}/sessions", json={"workspace_id": workspace_id, "knowledge_base_id": kb_id})
    created.raise_for_status()
    session_id = created.json()["id"]
    message_url = f"{api_root}/{mode}/sessions/{session_id}/messages"
    history_replay_latency = 0.0
    prior_events: list[dict[str, Any]] = []
    prior_retrieved_ids: set[str] = set()
    # Re-submit prior user turns only. The Runtime persists fresh assistant
    # replies in this session; replaying fixture assistant text would leak
    # answer-side information into the evaluated conversation.
    for message in case.get("history", []):
        if message.get("role") != "user":
            continue
        events, duration = await _sse_post(client, message_url, {"content": message["content"]})
        history_replay_latency += duration
        prior_events.extend(events)
        prior_retrieved_ids.update(str(result.get("chunk_id")) for event in events if event.get("type") == "retrieval_result" for result in event.get("results", []) if result.get("chunk_id"))
    events, duration = await _sse_post(client, message_url, {"content": case["question"]})
    latency = duration
    ranked_results: list[dict[str, Any]] = []
    retrieved_ids = set(prior_retrieved_ids)
    citations: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") == "retrieval_result":
            results = list(event.get("results") or [])
            if not ranked_results:
                ranked_results = results
            retrieved_ids.update(str(result.get("chunk_id")) for result in results if result.get("chunk_id"))
        elif event.get("type") == "citation":
            citations.append(dict(event))
    for event in prior_events:
        if event.get("type") in {"tool_call_start", "mcp_tool_call"}:
            citations.append({"_prior_tool_event": event})
    answer = ""
    for event in reversed(events):
        if event.get("type") in {"message_complete", "agent_complete"}:
            answer = str(event.get("content", ""))
            break
    observed_tools = [
        str(event.get("name"))
        for event in prior_events + events
        if event.get("type") in {"tool_call_start", "mcp_tool_call"} and event.get("name")
    ]
    query_plan = next((item for item in events if item.get("type") == "query_plan"), {})
    return answer, ranked_results, citations, latency, {
        "events": events,
        "observed_tools": observed_tools,
        "query_plan": query_plan,
        "retrieved_ids": sorted(retrieved_ids),
        "history_replay_latency_seconds": round(history_replay_latency, 3),
    }


async def _run_case(
    client: httpx.AsyncClient,
    api_root: str,
    workspace_id: str,
    kb_id: str,
    case: dict[str, Any],
    document_ids: dict[str, str],
    document_sources: dict[str, str],
    settings: Any,
    rubric: str,
) -> dict[str, Any]:
    mode = case.get("expected", {}).get("baseline_route", "rag")
    if mode not in {"rag", "agent"}:
        mode = "rag"
    answer, retrieved, citation_events, latency, trace = await _send_question(client, api_root, workspace_id, kb_id, mode, case)
    for result in retrieved:
        result["source_id"] = document_sources.get(str(result.get("document_id", "")))
    retrieval = retrieval_metrics(case, retrieved, document_sources)

    citation_ids_in_answer = list(dict.fromkeys(re.findall(r"\[source:([^\]\s]+)\]", answer)))
    evidence_by_source = {
        source_id: [item for claim in case.get("gold_claims", []) for item in claim.get("evidence", []) if item["source_id"] == source_id]
        for source_id in document_sources.values()
    }
    cited_references: list[dict[str, Any]] = []
    for chunk_id in citation_ids_in_answer:
        response = await client.get(f"{api_root}/chunks/{chunk_id}/citation")
        if response.status_code != 200:
            cited_references.append({"chunk_id": chunk_id, "valid": False, "supported": False})
            continue
        payload = response.json()
        document_id = str(payload.get("document_id", ""))
        source_id = document_sources.get(document_id)
        chunk_content = str(payload.get("content", ""))
        support = any(
            _normalize_ref(item["quote"]) in _normalize_ref(chunk_content)
            for item in evidence_by_source.get(source_id, [])
        )
        cited_references.append({
            "chunk_id": chunk_id,
            "document_id": document_id,
            "source_id": source_id,
            "content": chunk_content,
            "valid": document_id in set(document_ids.values()) and chunk_id in set(trace.get("retrieved_ids", [])),
            "supported": support,
        })
    judge_citations = [
        {"chunk_id": item.get("chunk_id"), "valid_id": bool(item.get("valid")), "source_id": item.get("source_id"), "content": item.get("content", "")}
        for item in cited_references
    ]
    citation_summary = citation_metrics(
        [{"chunk_id": item.get("chunk_id"), "document_id": item.get("document_id"), "source_id": item.get("source_id"), "quoted_text": item.get("content", "")} for item in cited_references],
        evaluation_document_ids=set(document_ids.values()),
        case=case,
        retrieved_chunk_ids=set(trace.get("retrieved_ids", [])),
    ) if cited_references else {"citation_count": 0, "valid_id_rate": 0.0, "support_rate": 0.0}
    judge = await _judge_answer(answer, case, settings, rubric, judge_citations)
    quality = _case_rubric_result(case, judge) if judge.get("status") == "scored" else {
        "answer_correct": None, "evidence_supported": None, "refused": None, "forbidden_assertion": None, "decision_correct": None,
    }
    expected_tools = case.get("expected", {}).get("baseline_tools", [])
    target_tools = case.get("expected", {}).get("target_tools", [])
    observed_complexity = trace.get("query_plan", {}).get("complexity")
    route_expected = observed_complexity == case.get("expected", {}).get("target_route") if observed_complexity else None
    observed_tools = sorted(set(trace["observed_tools"]))
    retrieval_diagnostics = next((event.get("diagnostics") for event in trace["events"] if event.get("type") == "retrieval_result"), {})
    retrieval_diagnosis = _diagnose_retrieval(case, retrieval_diagnostics, retrieved, document_sources)
    tool_expected = None
    target_tool_expected = None
    if case.get("category") == "tools_mcp":
        tool_expected = set(observed_tools) == set(expected_tools)
        target_tool_expected = set(observed_tools) == set(target_tools)
    return {
        "id": case["id"],
        "case_type": "qa",
        "category": case["category"],
        "language": case["language"],
        "answerability": case["answerability"],
        "expected": case.get("expected", {}),
        "answer": _redact_model_text(answer),
        "latency_seconds": round(latency, 3),
        "history_replay_latency_seconds": trace["history_replay_latency_seconds"],
        "retrieval": retrieval,
        "retrieval_diagnostics": retrieval_diagnostics,
        "retrieval_diagnosis": retrieval_diagnosis,
        "citations": citation_summary,
        "cited_references": cited_references,
        "quality": quality,
        "judge": judge,
        "observed_tools": observed_tools,
        "tool_expected": tool_expected,
        "target_tool_expected": target_tool_expected,
        "route_expected": route_expected,
        "route_observed": {"mode_requested": mode, "query_plan_complexity": observed_complexity, "automatic_mode_dispatch": "not_implemented"},
        "trace_summary": {"event_types": [str(item.get("type")) for item in trace["events"]]},
    }


def _normalize_ref(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _diagnose_retrieval(case: dict[str, Any], diagnostics: dict[str, Any], final_results: list[dict[str, Any]], document_sources: dict[str, str]) -> dict[str, Any]:
    """Classify why each gold evidence passage was not retrieved."""
    candidates = diagnostics.get("candidate_trace") if isinstance(diagnostics, dict) else []
    candidates = candidates if isinstance(candidates, list) else []
    final_count = int(diagnostics.get("final_count") or len(final_results)) if isinstance(diagnostics, dict) else len(final_results)
    final_chunk_ids = {str(item.get("chunk_id")) for item in final_results}
    evidence_items = [evidence for claim in case.get("gold_claims", []) for evidence in claim.get("evidence", [])]
    analyses = []
    for evidence in evidence_items:
        source_id = evidence.get("source_id")
        quote = _normalize_ref(str(evidence.get("quote", "")))
        source_candidates = [item for item in candidates if document_sources.get(str(item.get("document_id"))) == source_id]
        exact_candidates = [item for item in source_candidates if quote and quote in _normalize_ref(str(item.get("content", "")))]
        exact_final = [item for item in exact_candidates if str(item.get("chunk_id")) in final_chunk_ids]
        if exact_final:
            diagnosis = "retrieved_final"
        elif exact_candidates:
            rerank_ranks = [item.get("rerank_rank") for item in exact_candidates if item.get("rerank_rank") is not None]
            if not rerank_ranks:
                diagnosis = "rerank_dropped"
            elif min(rerank_ranks) > final_count:
                diagnosis = "rerank_below_final"
            else:
                diagnosis = "final_result_mismatch"
        elif source_candidates:
            diagnosis = "chunk_mismatch"
        else:
            diagnosis = "candidate_miss"
        analyses.append({
            "source_id": source_id,
            "quote": evidence.get("quote"),
            "diagnosis": diagnosis,
            "source_candidate_count": len(source_candidates),
            "exact_candidate_count": len(exact_candidates),
            "exact_candidate_ranks": [item.get("fusion_rank") for item in exact_candidates],
            "exact_rerank_ranks": [item.get("rerank_rank") for item in exact_candidates],
        })
    return {"final_count": final_count, "evidence": analyses}


async def _run_real(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    api_base_path = _ensure_isolated_local(settings, args.base_url)
    manifest = load_manifest()
    all_cases = load_cases()
    if args.limit is not None:
        if args.limit <= 0:
            raise EvaluationRunError("--limit must be a positive integer.")
        if args.limit > len(all_cases):
            raise EvaluationRunError(f"--limit cannot exceed the dataset size ({len(all_cases)} cases).")
    selected_case_ids = None
    if args.case_ids:
        selected_case_ids = list(dict.fromkeys(item.strip() for item in args.case_ids.split(",") if item.strip()))
        known_ids = {case["id"] for case in all_cases}
        unknown_ids = sorted(set(selected_case_ids) - known_ids)
        if unknown_ids:
            raise EvaluationRunError("--case-ids contains unknown IDs: " + ", ".join(unknown_ids))
        cases = [case for case in all_cases if case["id"] in set(selected_case_ids)]
        if not cases:
            raise EvaluationRunError("--case-ids must select at least one case.")
    else:
        cases = all_cases[: args.limit] if args.limit is not None else all_cases
    partial_run = len(cases) < len(all_cases)
    # Always validate and index the complete fixed corpus. --limit only limits
    # the QA questions executed against that corpus.
    dataset_report = validate_dataset(manifest, all_cases)
    rubric = RUBRIC_PATH.read_text(encoding="utf-8")
    parsed_base_url = urlsplit(args.base_url)
    base_url = f"{parsed_base_url.scheme}://{parsed_base_url.netloc}"
    if api_base_path and api_base_path != settings.api_prefix:
        raise EvaluationRunError("API URL path must be empty or match API_PREFIX for the isolated local configuration.")
    api_root = f"{base_url}{api_base_path or settings.api_prefix}"
    preflight = await _preflight(settings)
    token = os.environ["WEKNORA_EVAL_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8]
    started_at = datetime.now(timezone.utc).isoformat()
    client = httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(30, connect=8), follow_redirects=False)
    workspace_id: str | None = None
    results: list[dict[str, Any]] = []
    cleanup_status = "not_needed"
    notes: list[str] = ["Concurrency is fixed at 1.", "Credentials are not written to the report.", "Chain scenarios are independent and were not run by this QA runner."]
    try:
        health = await client.get(f"{api_root}/health")
        health.raise_for_status()
        if health.json().get("status") != "ok":
            raise EvaluationRunError("The isolated Runtime health check did not pass.")
        workspace_response = await client.post(f"{api_root}/workspaces", json={"name": f"P0P1 Evaluation {run_id}", "description": "Ephemeral evaluation workspace; cleaned after this run."})
        workspace_response.raise_for_status()
        workspace_id = workspace_response.json()["id"]
        kb_response = await client.post(f"{api_root}/knowledge-bases", json={"workspace_id": workspace_id, "name": f"Evaluation {run_id}", "description": "Fixed P0/P1 corpus snapshot."})
        kb_response.raise_for_status()
        kb_id = kb_response.json()["id"]
        document_ids = await _index_corpus(client, api_root, workspace_id, kb_id, manifest)
        document_sources = {document_id: source_id for source_id, document_id in document_ids.items()}

        # QA execution is serial by design. Previous user turns are replayed in
        # a fresh session and the Runtime regenerates the assistant turns.
        for case in cases:
            results.append(await _run_case(client, api_root, workspace_id, kb_id, case, document_ids, document_sources, settings, rubric))
        try:
            await _delete_workspace(client, api_root, workspace_id)
            cleanup_status = "deleted"
            workspace_id = None
        except Exception as exc:
            cleanup_status = f"failed:{_safe_error(exc)}"
            notes.append("Evaluation workspace cleanup failed; inspect the isolated environment before reuse.")
    finally:
        if workspace_id:
            try:
                await _delete_workspace(client, api_root, workspace_id)
                cleanup_status = "deleted_after_error"
            except Exception as exc:
                cleanup_status = f"failed:{_safe_error(exc)}"
        await client.aclose()

    metrics = _aggregate(results)
    sample_count = min(24, len(results))
    sample_ids = sorted(item["id"] for item in random.Random(20261015).sample(results, sample_count))
    high_risk_failures = [
        item["id"] for item in results
        if (item["category"] in {"no_answer", "conflict", "tools_mcp"} or "security" in item.get("expected", {}).get("target_tools", []))
        and (item.get("quality", {}).get("decision_correct") is False or item.get("quality", {}).get("forbidden_assertion") is True)
    ]
    judged_errors = sum(item.get("judge", {}).get("status") != "scored" for item in results)
    manual_review = {"status": "pending", "minimum_random_sample_count": sample_count, "random_sample_case_ids": sample_ids, "high_risk_failure_case_ids": high_risk_failures}
    acceptance_targets = _acceptance_targets(metrics)
    if partial_run:
        for item in acceptance_targets.values():
            if isinstance(item, dict) and item.get("status") not in {"not_implemented", "not_measured"}:
                item["status"] = "not_applicable_partial_run"
                item["reason"] = f"Partial run ({len(results)}/{len(all_cases)} cases); full-dataset acceptance is not evaluated."
    report = {
        "schema_version": 1,
        "run_id": run_id,
        "result_type": "real_model_evaluation",
        "acceptance_status": "partial_run_pending_manual_review" if partial_run and not judged_errors and cleanup_status in {"deleted", "deleted_after_error"} else "partial_run_invalid_judge_results" if partial_run and judged_errors else "pending_manual_review" if not judged_errors and cleanup_status in {"deleted", "deleted_after_error"} else "invalid_judge_results" if judged_errors else "cleanup_failed",
        "evaluation_scope": {"case_limit": args.limit, "case_ids": selected_case_ids, "cases_run": len(results), "full_dataset_case_count": len(all_cases), "partial": partial_run},
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "code_revision": _git_revision(),
        "working_tree": _git_working_tree_provenance(),
        "dataset": dataset_report | {"dataset_id": manifest["dataset_id"], "manifest_sha256": sha256_file(EVALUATION_DIR / "manifest.json"), "cases_sha256": manifest["cases_sha256"], "source_snapshot_hashes": {source["id"]: source["sha256"] for source in manifest["sources"]}},
        "models": preflight,
        "configuration": {
            "parallelism": 1,
            "embedding_model": settings.embedding_model,
            "embedding_dimension": settings.embedding_dimension,
            "rerank_model": settings.rerank_model,
            "rerank_enabled": settings.rerank_enabled,
            "llm_model": settings.openai_model,
            "milvus_collection": settings.milvus_collection,
            "runtime_environment": settings.environment,
            "secrets_included": False,
        },
        "code_artifacts_sha256": _code_artifact_hashes(),
        "parallelism": 1,
        "workspace_cleanup": cleanup_status,
        "metrics": metrics,
        "acceptance_targets": acceptance_targets,
        "scenario_suite": {"count": manifest["scenario_count"], "status": "not_run_separate_from_qa"},
        "manual_review": manual_review,
        "results": results,
        "notes": notes,
    }
    return report


def _diagnostic_report(run_id: str | None = None) -> dict[str, Any]:
    """Offline deterministic smoke of scoring only; never an acceptance result."""
    manifest = load_manifest()
    cases = load_cases()
    dataset = validate_dataset(manifest, cases)
    sample_case = next(case for case in cases if case["gold_claims"])
    fake_results = [{"document_id": "synthetic-doc", "content": "synthetic evidence"}]
    metrics = {
        "metric_smoke": {
            "retrieval_empty_results": retrieval_metrics(sample_case, [], {})["recall@5"],
            "binary_accuracy": binary_metrics([True, False], [True, True])["accuracy"],
            "p95": percentile95([1.0, 2.0, 3.0]),
            "citation_id_validity": citation_metrics([{"document_id": "synthetic-doc", "chunk_id": "synthetic-chunk"}], evaluation_document_ids={"synthetic-doc"}, case=sample_case)["valid_id_rate"],
            "decoy_unmatched": retrieval_metrics(sample_case, fake_results, {"synthetic-doc": "decoy"})["recall@5"],
        },
        "acceptance_targets": {"status": "not_scored_diagnostic_only"},
    }
    return {
        "schema_version": 1,
        "run_id": run_id or "diagnostic-" + uuid4().hex[:8],
        "result_type": "offline_diagnostic_not_for_acceptance",
        "acceptance_status": "not_scored",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "code_revision": _git_revision(),
        "dataset": dataset | {
            "dataset_id": manifest["dataset_id"],
            "manifest_sha256": sha256_file(EVALUATION_DIR / "manifest.json"),
            "cases_sha256": manifest["cases_sha256"],
            "source_snapshot_hashes": {source["id"]: source["sha256"] for source in manifest["sources"]},
        },
        "working_tree": _git_working_tree_provenance(),
        "code_artifacts_sha256": _code_artifact_hashes(),
        "metrics": metrics,
        "acceptance_targets": {"status": "not_scored_diagnostic_only"},
        "scenario_suite": {"count": manifest["scenario_count"], "status": "contract_only_not_executed"},
        "manual_review": {"status": "not_applicable_to_metric_smoke"},
        "notes": ["No network, model, or runtime calls were made.", "This deterministic smoke verifies score plumbing only; never use it for model-quality acceptance."],
        "results": [],
    }


def _compare_with_previous(report: dict[str, Any], baseline_path: Path) -> dict[str, Any]:
    allowed_root = RUN_OUTPUT.resolve()
    candidate = baseline_path.resolve()
    try:
        candidate.relative_to(allowed_root)
    except ValueError as exc:
        raise EvaluationRunError("--compare-to must point to a report under output/evaluation/.") from exc
    if not candidate.is_file():
        raise EvaluationRunError("The comparison report does not exist.")
    try:
        previous = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationRunError("The comparison report is not valid JSON.") from exc
    current_dataset = report.get("dataset", {})
    previous_dataset = previous.get("dataset", {})
    if current_dataset.get("cases_sha256") != previous_dataset.get("cases_sha256") or current_dataset.get("dataset_id") != previous_dataset.get("dataset_id"):
        return {"status": "incomparable_dataset_changed", "baseline_run_id": previous.get("run_id"), "baseline_report": str(candidate)}

    paths = {
        "answer.conclusion_correct_rate": ("answer", "conclusion_correct_rate"),
        "answer.evidence_supported_rate": ("answer", "evidence_supported_rate"),
        "retrieval.recall@5": ("retrieval", "recall@5"),
        "retrieval.mrr": ("retrieval", "mrr"),
        "citations.id_valid_rate": ("citations", "answer_cited_id_valid_rate"),
        "citations.quote_support_rate": ("citations", "answer_cited_quote_support_rate"),
        "no_answer.refusal_accuracy": ("no_answer", "accuracy"),
        "latency.ordinary_p95_seconds": ("latency_seconds", "ordinary_p95"),
        "latency.research_p95_seconds": ("latency_seconds", "research_p95"),
    }
    deltas: dict[str, Any] = {}
    for name, (section, key) in paths.items():
        current_value = report.get("metrics", {}).get(section, {}).get(key)
        previous_value = previous.get("metrics", {}).get(section, {}).get(key)
        deltas[name] = {
            "current": current_value,
            "baseline": previous_value,
            "delta": (current_value - previous_value) if isinstance(current_value, (int, float)) and isinstance(previous_value, (int, float)) else None,
        }
    category_delta: dict[str, Any] = {}
    current_categories = report.get("metrics", {}).get("per_category", {})
    previous_categories = previous.get("metrics", {}).get("per_category", {})
    for category in sorted(set(current_categories) | set(previous_categories)):
        category_delta[category] = {}
        for key in ("answer_correct_rate", "evidence_supported_rate", "recall@5", "mrr"):
            current_value = current_categories.get(category, {}).get(key)
            previous_value = previous_categories.get(category, {}).get(key)
            category_delta[category][key] = {
                "current": current_value,
                "baseline": previous_value,
                "delta": (current_value - previous_value) if isinstance(current_value, (int, float)) and isinstance(previous_value, (int, float)) else None,
            }
    return {"status": "compared", "baseline_run_id": previous.get("run_id"), "baseline_report": str(candidate), "metrics": deltas, "per_category": category_delta}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the WeKnora P0/P1 golden evaluation against a dedicated local Runtime.")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--validate-only", action="store_true", help="Validate corpus, manifest, hashes, evidence and scenario definitions without network calls.")
    modes.add_argument("--diagnostic-mocks", action="store_true", help="Run deterministic metric smoke only; output is never an acceptance result.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Loopback URL for the isolated local Runtime.")
    parser.add_argument("--run-id", help="Optional output folder name; must be a simple path component.")
    parser.add_argument("--limit", type=int, help="Run only the first N QA cases; partial runs are never full acceptance results.")
    parser.add_argument("--case-ids", help="Run a comma-separated subset of QA case IDs; partial runs are never full acceptance results.")
    parser.add_argument("--compare-to", type=Path, help="Compare this real run with an earlier report under output/evaluation/.")
    args = parser.parse_args(argv)
    if args.run_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", args.run_id):
        parser.error("--run-id must be a simple alphanumeric path component")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be a positive integer")
    if args.limit is not None and args.case_ids:
        parser.error("--limit and --case-ids cannot be used together")

    try:
        if args.validate_only:
            if args.compare_to:
                parser.error("--compare-to is only available for real-model runs")
            result = validate_dataset()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.diagnostic_mocks:
            if args.compare_to:
                parser.error("--compare-to is only available for real-model runs")
            report = _diagnostic_report(args.run_id)
        else:
            if args.compare_to:
                expected_manifest = load_manifest()
                _compare_with_previous({"dataset": {"dataset_id": expected_manifest["dataset_id"], "cases_sha256": expected_manifest["cases_sha256"]}, "metrics": {}}, args.compare_to)
            report = asyncio.run(_run_real(args))
            if args.compare_to:
                report["baseline_comparison"] = _compare_with_previous(report, args.compare_to)
        output_path = _write_report(report)
        print(json.dumps({"run_id": report["run_id"], "result_type": report["result_type"], "acceptance_status": report["acceptance_status"], "report_directory": str(output_path)}, ensure_ascii=False, indent=2))
        return 0
    except EvaluationRunError as exc:
        print(f"Evaluation aborted: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Evaluation aborted ({_safe_error(exc)}). No credentials or provider response bodies were written.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

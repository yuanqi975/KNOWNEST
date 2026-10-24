"""Isolated retrieval-only diagnostic for ranking failures."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.evaluation import EVALUATION_DIR, REPO_ROOT, load_cases, load_manifest, validate_dataset
from app.evaluation_cli import EvaluationRunError, _diagnose_retrieval, _ensure_isolated_local, _index_corpus


async def run(args: argparse.Namespace) -> dict:
    settings = get_settings()
    api_path = _ensure_isolated_local(settings, args.base_url)
    manifest = load_manifest()
    all_cases = load_cases()
    wanted = [item.strip() for item in args.case_ids.split(",") if item.strip()]
    known = {case["id"] for case in all_cases}
    unknown = sorted(set(wanted) - known)
    if unknown:
        raise EvaluationRunError("Unknown case IDs: " + ", ".join(unknown))
    cases = [case for case in all_cases if case["id"] in set(wanted)]
    if not cases:
        raise EvaluationRunError("No cases selected.")
    token = os.environ.get("KNOWNEST_EVAL_TOKEN")
    if not token:
        raise EvaluationRunError("KNOWNEST_EVAL_TOKEN is required.")
    base = args.base_url.rstrip("/")
    api_root = base + (api_path or settings.api_prefix)
    headers = {"Authorization": f"Bearer {token}"}
    run_id = args.run_id
    client = httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(240, connect=10))
    workspace_id = None
    results = []
    try:
        health = await client.get(f"{api_root}/health")
        health.raise_for_status()
        workspace = await client.post(f"{api_root}/workspaces", json={"name": f"Retrieval diagnostic {run_id}", "description": "Ephemeral retrieval-only diagnostic."})
        workspace.raise_for_status()
        workspace_id = workspace.json()["id"]
        kb = await client.post(f"{api_root}/knowledge-bases", json={"workspace_id": workspace_id, "name": f"Retrieval diagnostic {run_id}", "description": "Fixed P0/P1 corpus snapshot."})
        kb.raise_for_status()
        kb_id = kb.json()["id"]
        document_ids = await _index_corpus(client, api_root, workspace_id, kb_id, manifest)
        document_sources = {document_id: source_id for source_id, document_id in document_ids.items()}
        for case in cases:
            response = await client.post(
                f"{api_root}/knowledge-bases/{kb_id}/search",
                json={"workspace_id": workspace_id, "knowledge_base_id": kb_id, "query": case["question"], "top_k": args.top_k},
            )
            response.raise_for_status()
            payload = response.json()
            final_results = payload.get("results", [])
            diagnostics = payload.get("diagnostics", {})
            results.append({
                "id": case["id"],
                "question": case["question"],
                "category": case["category"],
                "language": case["language"],
                "top_k": args.top_k,
                "diagnostics": diagnostics,
                "diagnosis": _diagnose_retrieval(case, diagnostics, final_results, document_sources),
                "final_results": [
                    {"rank": item.get("rank"), "chunk_id": item.get("chunk_id"), "document_id": item.get("document_id"), "source_id": document_sources.get(str(item.get("document_id"))), "content": item.get("content", "")}
                    for item in final_results
                ],
            })
        await client.delete(f"{api_root}/workspaces/{workspace_id}")
        workspace_id = None
    finally:
        if workspace_id:
            try:
                await client.delete(f"{api_root}/workspaces/{workspace_id}")
            except Exception:
                pass
        await client.aclose()

    diagnosis_counts = {}
    for result in results:
        for evidence in result["diagnosis"]["evidence"]:
            diagnosis_counts[evidence["diagnosis"]] = diagnosis_counts.get(evidence["diagnosis"], 0) + 1
    return {
        "schema_version": 1,
        "run_id": run_id,
        "result_type": "retrieval_only_diagnostic_not_for_acceptance",
        "acceptance_status": "not_scored",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "dataset": validate_dataset(manifest),
        "scope": {"case_ids": wanted, "case_count": len(results), "top_k": args.top_k, "candidate_count": 24, "rerank_trace_enabled": True},
        "diagnosis_counts": diagnosis_counts,
        "results": results,
        "notes": ["No LLM answer generation or answer judge was run.", "This report diagnoses retrieval ranking only and is not an acceptance result."],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run retrieval-only ranking diagnostics in an isolated local Runtime.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--run-id", default="retrieval-diagnostic")
    parser.add_argument("--case-ids", required=True)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args(argv)
    report = asyncio.run(run(args))
    out = REPO_ROOT / "output" / "evaluation" / report["run_id"]
    out.mkdir(parents=True, exist_ok=False)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"# Retrieval diagnostic {report['run_id']}", "", "- Result type: `retrieval_only_diagnostic_not_for_acceptance`", f"- Cases: {report['scope']['case_count']}", f"- Top-K: {report['scope']['top_k']}; candidate pool: {report['scope']['candidate_count']}", "", "## Diagnosis counts", ""]
    lines.extend(f"- `{name}`: {count}" for name, count in sorted(report["diagnosis_counts"].items()))
    lines += ["", "## Per-case evidence diagnosis", "", "| Case | Evidence source | Diagnosis | Fusion rank | Rerank rank |", "|---|---|---|---:|---:|"]
    for result in report["results"]:
        for evidence in result["diagnosis"]["evidence"]:
            fusion = ", ".join(str(item) for item in evidence["exact_candidate_ranks"]) or "-"
            rerank = ", ".join(str(item) for item in evidence["exact_rerank_ranks"]) or "-"
            lines.append(f"| {result['id']} | {evidence['source_id']} | {evidence['diagnosis']} | {fusion} | {rerank} |")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"run_id": report["run_id"], "report_directory": str(out), "diagnosis_counts": report["diagnosis_counts"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Dataset validation and deterministic metrics for the local WeKnora eval set."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
EVALUATION_DIR = REPO_ROOT / "dataset" / "evaluation"
EXPECTED_CATEGORY_COUNTS = {
    "simple": 28,
    "composite": 20,
    "no_answer": 18,
    "conflict": 12,
    "table_calculation": 12,
    "multi_turn": 10,
    "tools_mcp": 10,
    "degradation": 10,
}


class EvaluationDataError(ValueError):
    """Raised when the checked-in evaluation corpus is incomplete or stale."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    manifest_path = path or EVALUATION_DIR / "manifest.json"
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationDataError(f"Cannot read evaluation manifest: {manifest_path}") from exc


def load_cases(path: Path | None = None) -> list[dict[str, Any]]:
    cases_path = path or EVALUATION_DIR / "cases.jsonl"
    cases: list[dict[str, Any]] = []
    try:
        with cases_path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise EvaluationDataError(f"Invalid JSON on {cases_path}:{line_number}") from exc
                if not isinstance(value, dict):
                    raise EvaluationDataError(f"Case on {cases_path}:{line_number} must be an object")
                cases.append(value)
    except OSError as exc:
        raise EvaluationDataError(f"Cannot read evaluation cases: {cases_path}") from exc
    return cases


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def corpus_text(source: dict[str, Any], repo_root: Path = REPO_ROOT) -> str:
    path = repo_root / source["path"]
    suffix = path.suffix.lower()
    if suffix == ".docx":
        from app.services.parser import extract_text

        return extract_text(path, suffix)
    return path.read_text(encoding="utf-8")


def validate_dataset(
    manifest: dict[str, Any] | None = None,
    cases: list[dict[str, Any]] | None = None,
    *,
    evaluation_dir: Path = EVALUATION_DIR,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Validate fixed snapshots, sample contracts, counts and evidence excerpts."""
    manifest = manifest or load_manifest(evaluation_dir / "manifest.json")
    cases = cases if cases is not None else load_cases(evaluation_dir / "cases.jsonl")
    errors: list[str] = []

    if manifest.get("schema_version") != 1:
        errors.append("manifest schema_version must be 1")
    if not manifest.get("sources"):
        errors.append("manifest must declare fixed corpus sources")
    source_by_id: dict[str, dict[str, Any]] = {}
    for source in manifest.get("sources", []):
        source_id = source.get("id")
        if not source_id or source_id in source_by_id:
            errors.append(f"duplicate or missing source id: {source_id!r}")
            continue
        source_by_id[source_id] = source
        path = repo_root / str(source.get("path", ""))
        if not str(source.get("path", "")).replace("\\", "/").startswith("dataset/evaluation/corpus/"):
            errors.append(f"source is not a fixed evaluation snapshot: {source.get('path')}")
        if not path.is_file():
            errors.append(f"missing source file: {source.get('path')}")
            continue
        expected_hash = source.get("sha256")
        if not expected_hash or sha256_file(path) != expected_hash:
            errors.append(f"source hash mismatch: {source.get('path')}")
        if path.suffix.lower() not in {".pdf", ".md", ".markdown", ".txt", ".docx"}:
            errors.append(f"unsupported corpus source format: {source.get('path')}")

    if manifest.get("scenario_count", 0) < 16:
        errors.append("at least 16 independent lifecycle/security scenarios are required")
    if not manifest.get("scenarios_sha256"):
        errors.append("manifest scenarios_sha256 is required")
    scenario_path = evaluation_dir / "scenarios.json"
    if not scenario_path.is_file():
        errors.append("scenarios.json is missing")
    elif manifest.get("scenarios_sha256") and sha256_file(scenario_path) != manifest["scenarios_sha256"]:
        errors.append("scenarios.json hash mismatch")
    else:
        try:
            scenario_data = json.loads(scenario_path.read_text(encoding="utf-8"))
            scenarios = scenario_data.get("scenarios", [])
            if len(scenarios) < 16 or len({row.get("id") for row in scenarios}) != len(scenarios):
                errors.append("scenario IDs must be unique and scenario count must be at least 16")
            required_scenarios = {
                "upload_to_index", "embedding_timeout_then_retry", "rerank_timeout", "milvus_unavailable",
                "index_retry", "document_delete", "vector_reconciliation", "sse_cancel",
                "cross_workspace_access", "mcp_tool_failure", "mcp_tool_timeout", "sse_event_contract",
            }
            scenario_categories = {row.get("fault_injection") for row in scenarios}
            missing_scenarios = required_scenarios - scenario_categories
            if missing_scenarios:
                errors.append(f"required lifecycle/security scenario categories missing: {sorted(missing_scenarios)}")
            for scenario in scenarios:
                if scenario.get("environment") != "isolated_local_only" or not scenario.get("contract", {}).get("manual_review_required"):
                    errors.append(f"{scenario.get('id')}: scenario must be isolated and require manual review")
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            errors.append(f"invalid scenarios.json: {type(exc).__name__}")

    cases_path = evaluation_dir / "cases.jsonl"
    if not manifest.get("cases_sha256"):
        errors.append("manifest cases_sha256 is required")
    if not cases_path.is_file():
        errors.append("cases.jsonl is missing")
    elif manifest.get("cases_sha256") and sha256_file(cases_path) != manifest["cases_sha256"]:
        errors.append("cases.jsonl hash mismatch")

    ids: set[str] = set()
    actual_counts: dict[str, int] = {}
    source_text: dict[str, str] = {}
    for case in cases:
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id:
            errors.append("a case has no id")
        elif case_id in ids:
            errors.append(f"duplicate case id: {case_id}")
        else:
            ids.add(case_id)
        category = case.get("category")
        actual_counts[category] = actual_counts.get(category, 0) + 1
        if case.get("case_type") != "qa":
            errors.append(f"{case_id}: only QA rows belong in cases.jsonl; chain scenarios live separately")
        if case.get("language") not in {"zh", "en"}:
            errors.append(f"{case_id}: invalid language")
        if not isinstance(case.get("question"), str) or not case["question"].strip():
            errors.append(f"{case_id}: question is empty")
        if not isinstance(case.get("history", []), list):
            errors.append(f"{case_id}: history must be a list")
        elif any(not isinstance(turn, dict) or turn.get("role") not in {"user", "assistant"} or not isinstance(turn.get("content"), str) for turn in case.get("history", [])):
            errors.append(f"{case_id}: history turns must have user/assistant role and string content")

        answerability = case.get("answerability")
        evidence_count = 0
        for claim in case.get("gold_claims", []):
            for evidence in claim.get("evidence", []):
                evidence_count += 1
                source_id = evidence.get("source_id")
                source = source_by_id.get(source_id)
                if not source:
                    errors.append(f"{case_id}: unknown evidence source {source_id!r}")
                    continue
                if evidence.get("path") != source.get("path"):
                    errors.append(f"{case_id}: evidence path does not match manifest source {source_id}")
                if source_id not in source_text:
                    try:
                        source_text[source_id] = corpus_text(source, repo_root)
                    except Exception as exc:  # report validation failure without leaking file contents
                        errors.append(f"{case_id}: cannot parse source {source_id}: {type(exc).__name__}")
                        continue
                quote = evidence.get("quote")
                if not isinstance(quote, str) or not quote.strip():
                    errors.append(f"{case_id}: empty evidence quote")
                elif _normalized(quote) not in _normalized(source_text[source_id]):
                    errors.append(f"{case_id}: evidence quote not found in {source_id}")
        if case.get("case_type") == "qa":
            if answerability in {"answerable", "conflicting"} and evidence_count == 0:
                errors.append(f"{case_id}: answerable case has no evidence")
            if answerability == "insufficient" and evidence_count:
                errors.append(f"{case_id}: insufficient case must not have gold evidence")
            if answerability not in {"answerable", "insufficient", "conflicting"}:
                errors.append(f"{case_id}: invalid answerability")
            if not isinstance(case.get("expected"), dict) or not case["expected"].get("baseline_route") or not case["expected"].get("target_route"):
                errors.append(f"{case_id}: baseline and target route expectations are required")
            if answerability == "insufficient":
                absence_checks = case.get("absence_checks", [])
                if not absence_checks:
                    errors.append(f"{case_id}: insufficient case must state checked absences")
                for check in absence_checks:
                    source_id = check.get("source_id")
                    source = source_by_id.get(source_id)
                    if not source:
                        errors.append(f"{case_id}: unknown absence-check source {source_id!r}")
                        continue
                    if source_id not in source_text:
                        try:
                            source_text[source_id] = corpus_text(source, repo_root)
                        except Exception as exc:
                            errors.append(f"{case_id}: cannot parse absence-check source {source_id}: {type(exc).__name__}")
                            continue
                    quote = check.get("quote", "")
                    if not quote or _normalized(quote) not in _normalized(source_text[source_id]):
                        errors.append(f"{case_id}: absence-check quote not found in {source_id}")
                    must_not_appear = check.get("must_not_appear")
                    if must_not_appear:
                        for source_key, corpus_source in source_by_id.items():
                            if source_key not in source_text:
                                try:
                                    source_text[source_key] = corpus_text(corpus_source, repo_root)
                                except Exception as exc:
                                    errors.append(f"{case_id}: cannot parse absence-scope source {source_key}: {type(exc).__name__}")
                                    continue
                            if _normalized(must_not_appear) in _normalized(source_text[source_key]):
                                errors.append(f"{case_id}: alleged missing fact occurs in the fixed corpus ({source_key})")
                absence_review = case.get("absence_review", {})
                if absence_review.get("status") != "programmatically_checked_against_fixed_snapshot" or absence_review.get("human_review") != "pending":
                    errors.append(f"{case_id}: insufficient case must distinguish mechanical check from pending human review")
        else:
            errors.append(f"{case_id}: malformed case type")
        for claim in case.get("gold_claims", []):
            if not str(claim.get("text", "")).strip():
                errors.append(f"{case_id}: gold claim text is empty")
            if claim.get("atomic") is not True:
                errors.append(f"{case_id}: gold conclusion must be explicitly atomized")
            if not claim.get("evidence"):
                errors.append(f"{case_id}: atomic gold claim has no evidence")
    expected_counts = manifest.get("category_counts", EXPECTED_CATEGORY_COUNTS)
    if actual_counts != expected_counts:
        errors.append(f"category counts differ: expected {expected_counts}, got {actual_counts}")
    if len(cases) != manifest.get("case_count", 120):
        errors.append(f"expected {manifest.get('case_count', 120)} cases, got {len(cases)}")
    if manifest.get("qa_case_count", 120) != len(cases):
        errors.append(f"manifest qa_case_count differs from case rows: {manifest.get('qa_case_count')}")
    language_counts = {language: sum(case.get("language") == language for case in cases) for language in ("zh", "en")}
    expected_languages = manifest.get("language_counts", {"zh": 90, "en": 30})
    if language_counts != expected_languages:
        errors.append(f"language counts differ: expected {expected_languages}, got {language_counts}")

    if errors:
        raise EvaluationDataError("Evaluation dataset validation failed:\n- " + "\n- ".join(errors))
    return {
        "valid": True,
        "case_count": len(cases),
        "category_counts": actual_counts,
        "language_counts": language_counts,
        "source_count": len(source_by_id),
        "scenario_count": manifest.get("scenario_count", 0),
        "annotation_review_status": manifest.get("annotation_review_status", "unknown"),
    }


def retrieval_metrics(
    case: dict[str, Any],
    ranked_results: list[dict[str, Any]],
    document_sources: dict[str, str],
    *,
    cutoffs: tuple[int, ...] = (5, 8, 10),
) -> dict[str, float | int | None]:
    """Score retrieved citations against evidence source IDs and anchored quotes."""
    evidence = [
        item
        for claim in case.get("gold_claims", [])
        for item in claim.get("evidence", [])
    ]
    if not evidence:
        return {f"recall@{cutoff}": None for cutoff in cutoffs} | {"mrr": None, "ndcg": None, "evidence_coverage": None}

    relevant_sources = {item["source_id"] for item in evidence}
    relevant_ranks: list[int] = []
    found_sources: set[str] = set()
    for rank, result in enumerate(ranked_results, start=1):
        source_id = document_sources.get(str(result.get("document_id", "")))
        if source_id not in relevant_sources:
            continue
        contents = " ".join(str(result.get(key, "")) for key in ("content", "quoted_text", "context_content"))
        normalized_contents = _normalized(contents)
        if any(item["source_id"] == source_id and _normalized(item["quote"]) in normalized_contents for item in evidence):
            if source_id not in found_sources:
                relevant_ranks.append(rank)
                found_sources.add(source_id)

    scores: dict[str, float | int | None] = {}
    for cutoff in cutoffs:
        retrieved_relevant_sources = sum(rank <= cutoff for rank in relevant_ranks)
        scores[f"recall@{cutoff}"] = retrieved_relevant_sources / len(relevant_sources)
    scores["mrr"] = 1.0 / min(relevant_ranks) if relevant_ranks else 0.0
    dcg = sum(1.0 / math.log2(rank + 1) for rank in relevant_ranks)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(relevant_sources), len(ranked_results)) + 1))
    scores["ndcg"] = dcg / ideal if ideal else 0.0
    covered_claims = 0
    claims = case.get("gold_claims", [])
    for claim in claims:
        refs = claim.get("evidence", [])
        if any(
            document_sources.get(str(result.get("document_id", ""))) == ref["source_id"]
            and _normalized(ref["quote"]) in _normalized(" ".join(str(result.get(key, "")) for key in ("content", "quoted_text", "context_content")))
            for ref in refs
            for result in ranked_results
        ):
            covered_claims += 1
    scores["evidence_coverage"] = covered_claims / len(claims) if claims else 0.0
    return scores


def citation_metrics(
    citations: list[dict[str, Any]],
    *,
    evaluation_document_ids: set[str],
    case: dict[str, Any],
    retrieved_chunk_ids: set[str] | None = None,
) -> dict[str, float | int | None]:
    """Measure citation-ID validity and quote support separately."""
    if not citations:
        return {"citation_count": 0, "valid_id_rate": 0.0, "support_rate": 0.0}
    valid = [
        citation.get("document_id") in evaluation_document_ids
        and bool(citation.get("chunk_id"))
        and (retrieved_chunk_ids is None or str(citation.get("chunk_id")) in retrieved_chunk_ids)
        for citation in citations
    ]
    evidence = [item for claim in case.get("gold_claims", []) for item in claim.get("evidence", [])]
    supported = []
    for citation in citations:
        quote = _normalized(str(citation.get("content") or citation.get("quoted_text") or ""))
        source_id = citation.get("source_id")
        supported.append(any(
            (source_id is None or source_id == ref["source_id"])
            and _normalized(ref["quote"]) in quote
            for ref in evidence
        ))
    return {
        "citation_count": len(citations),
        "valid_id_rate": sum(valid) / len(valid),
        "support_rate": sum(supported) / len(supported),
    }


def binary_metrics(expected: Iterable[bool], predicted: Iterable[bool]) -> dict[str, float | int]:
    pairs = list(zip(expected, predicted))
    tp = sum(want and got for want, got in pairs)
    fp = sum(not want and got for want, got in pairs)
    fn = sum(want and not got for want, got in pairs)
    tn = sum(not want and not got for want, got in pairs)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "accuracy": (tp + tn) / len(pairs) if pairs else 0.0,
    }


def percentile95(values: Iterable[float]) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]

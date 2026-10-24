"""Build the checked-in synthetic DOCX, golden JSONL and corpus manifest."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "dataset" / "evaluation"
CORPUS = EVAL / "corpus"
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


SOURCES = [
    ("readme", "README.md", "dataset/evaluation/corpus/snapshot_readme.md", "runtime-readme.md"),
    ("product", "PRODUCT.md", "dataset/evaluation/corpus/snapshot_product.md", "product.md"),
    ("api", "backend/API.md", "dataset/evaluation/corpus/snapshot_api.md", "runtime-api.md"),
    ("review", "dataset/evaluation/corpus/snapshot_production_review.md", "dataset/evaluation/corpus/snapshot_production_review.md", "production-review.md"),
    ("chunking", "docs/CHUNKING.md", "dataset/evaluation/corpus/snapshot_chunking.md", "chunking-guide.md"),
    ("p0p1", "dataset/evaluation/corpus/p0p1_targets.md", "dataset/evaluation/corpus/p0p1_targets.md", "p0p1-targets.md"),
    ("handbook", "dataset/evaluation/corpus/synthetic_handbook_zh.md", "dataset/evaluation/corpus/synthetic_handbook_zh.md", "synthetic-handbook.md"),
    ("policy_v1", "dataset/evaluation/corpus/synthetic_policy_v1.md", "dataset/evaluation/corpus/synthetic_policy_v1.md", "synthetic-policy-v1.md"),
    ("policy_v2", "dataset/evaluation/corpus/synthetic_policy_v2.md", "dataset/evaluation/corpus/synthetic_policy_v2.md", "synthetic-policy-v2.md"),
    ("decoy", "dataset/evaluation/corpus/synthetic_decoy.md", "dataset/evaluation/corpus/synthetic_decoy.md", "synthetic-decoy.md"),
    ("research_en", "dataset/evaluation/corpus/synthetic_research_en.md", "dataset/evaluation/corpus/synthetic_research_en.md", "synthetic-research.md"),
    ("table_notes", "dataset/evaluation/corpus/synthetic_table_notes.md", "dataset/evaluation/corpus/synthetic_table_notes.md", "synthetic-table-notes.md"),
    ("absence_register", "dataset/evaluation/corpus/absence_register.md", "dataset/evaluation/corpus/absence_register.md", "absence-register.md"),
    ("table_docx", "dataset/evaluation/corpus/synthetic_department_report.docx", "dataset/evaluation/corpus/synthetic_department_report.docx", "synthetic-department-report.docx"),
]

SCENARIOS: list[dict] = []


def build_snapshots(*, refresh: bool = False) -> None:
    """Copy project reference docs into the immutable evaluation corpus snapshot."""
    for _source_id, origin, snapshot, _upload_name in SOURCES:
        if origin != snapshot and (refresh or not (ROOT / snapshot).exists()):
            target = ROOT / snapshot
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text((ROOT / origin).read_text(encoding="utf-8"), encoding="utf-8", newline="\n")


def build_table_docx() -> None:
    from datetime import datetime
    from docx import Document

    document = Document()
    document.core_properties.author = "KNOWNEST evaluation fixture"
    document.core_properties.created = datetime(2020, 1, 1)
    document.core_properties.modified = datetime(2020, 1, 1)
    document.add_heading("Synthetic evaluation fixture: 2025 Northstar quarterly report", 0)
    document.add_paragraph(
        "Fictional data for KNOWNEST evaluation only. Amounts are in million CNY; headcount is people."
    )
    table = document.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    for cell, value in zip(table.rows[0].cells, ("Department", "Q1 revenue (million CNY)", "Q2 revenue (million CNY)", "Headcount")):
        cell.text = value
    for values in (
        ("Analytics", "1.2", "1.5", "12"),
        ("Platform", "2.4", "2.1", "18"),
        ("Support", "0.9", "1.1", "10"),
    ):
        for cell, value in zip(table.add_row().cells, values):
            cell.text = value
    document.add_paragraph("No budget, profit margin, or employee names are included in this report.")
    path = CORPUS / "synthetic_department_report.docx"
    normalized_path = path.with_name(path.stem + ".normalized.docx")
    document.save(path)
    with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(normalized_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as normalized:
        for name in sorted(source.namelist()):
            original = source.getinfo(name)
            item = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = original.external_attr
            item.create_system = original.create_system
            item.flag_bits = original.flag_bits
            normalized.writestr(item, source.read(name), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    normalized_path.replace(path)


def ev(source_id: str, quote: str) -> dict[str, str]:
    paths = {item[0]: item[2].replace("\\", "/") for item in SOURCES}
    return {"source_id": source_id, "path": paths[source_id], "quote": quote}


cases: list[dict] = []


def add_qa(
    category: str,
    language: str,
    question: str,
    answer: str | None,
    evidence: Iterable[dict[str, str]] = (),
    *,
    answerability: str = "answerable",
    baseline_route: str = "rag",
    target_complexity: str = "simple",
    target_tools: Iterable[str] = (),
    baseline_tools: Iterable[str] | None = None,
    history: list[str] | None = None,
    tags: Iterable[str] = (),
    must_not_claim: Iterable[str] = (),
    extra_claims: list[dict] | None = None,
    absence_checks: Iterable[dict[str, str]] = (),
) -> None:
    evidence = list(evidence)
    claims = extra_claims or ([{"text": answer, "required": True, "atomic": True, "evidence": evidence}] if answer else [])
    behavior = {
        "answerable": "answer_with_supported_claims",
        "insufficient": "refuse_without_inventing",
        "conflicting": "surface_both_sources_and_conflict",
    }[answerability]
    cases.append({
        "id": f"EVAL-{len(cases) + 1:03d}",
        "case_type": "qa",
        "category": category,
        "language": language,
        "tags": list(tags),
        "question": question,
        "history": history or [],
        "answerability": answerability,
        "expected": {
            "baseline_route": baseline_route,
            "baseline_tools": list(baseline_tools or []),
            "target_route": target_complexity,
            "target_complexity": target_complexity,
            "target_tools": list(target_tools),
            "refusal": answerability == "insufficient",
            "must_surface_conflict": answerability == "conflicting",
            "behavior": behavior,
        },
        "gold_claims": claims,
        "must_not_claim": list(must_not_claim),
        "absence_checks": list(absence_checks),
        "absence_review": ({"status": "programmatically_checked_against_fixed_snapshot", "human_review": "pending", "scope": "manifest_sources"} if answerability == "insufficient" else None),
    })


def add_scenario(language: str, question: str, scenario_id: str, fault: str, steps: list[str], expectations: list[str]) -> None:
    SCENARIOS.append({
        "id": scenario_id,
        "category": fault,
        "language": language,
        "question": question,
        "fault_injection": fault,
        "steps": steps,
        "environment": "isolated_local_only",
        "contract": {
            "setup": "Use the isolated local evaluation database, workspace, knowledge base, storage path and vector collection; inject only the named fault.",
            "assertions": [
                "Observe the expected API, SSE, job, database and vector-store state",
                "Never report success when the dependency or operation failed",
                "No cross-workspace data exposure",
                "Cleanup leaves no evaluation documents, chunks, vectors, files, or sessions",
            ] + expectations,
            "manual_review_required": True,
        },
        "baseline": {"status": "measure_current_behavior"},
        "target": {"status": "required", "pass_condition": "All listed assertions hold; retain redacted trace and cleanup evidence."},
    })


def build_scenarios() -> None:
    """Write independent lifecycle/security tests; these are not QA rows."""
    SCENARIOS.clear()
    definitions = [
        ("zh", "上传后从任务完成到向量可检索的端到端链路是否一致？", "SCN-UPLOAD-TO-INDEX", "upload_to_index", ["上传固定 Markdown 样本", "轮询任务及文档状态至终态", "搜索专属标记并检查 chunk/vector 对应关系"], ["Job 与 Document 均为 indexed", "搜索结果只属于评测 Workspace"]),
        ("zh", "Embedding 超时后重试能否恢复，且不遗留半成品索引？", "SCN-EMBED-RETRY", "embedding_timeout_then_retry", ["对隔离评测请求注入一次 Embedding 超时", "确认任务失败或显式降级", "移除注入并触发重试/重建", "再次查询并比较 SQL 与向量状态"], ["故障轮次不得标记 indexed", "成功重试后每个可检索 chunk 只有一个有效向量"]),
        ("zh", "Rerank 超时是否出现在检索降级状态和 SSE 诊断中？", "SCN-RERANK-TIMEOUT", "rerank_timeout", ["让 Rerank endpoint 延迟至超时", "运行检索和 RAG SSE", "检查诊断字段与最终回答声明"], ["标明 rerank_used=false 及原因", "不能将降级结果称为完整重排结果"]),
        ("zh", "Milvus 不可用时是否会静默切换到进程内内存向量索引？", "SCN-MILVUS-FAILURE", "milvus_unavailable", ["使用独立 Milvus collection 并注入连接失败", "执行上传或搜索", "检查 API/job 状态和日志"], ["不发生无提示的内存索引回退", "错误可诊断且不伪称向量检索成功"]),
        ("zh", "超出大小上限或使用不支持扩展名时，会不会留下孤儿记录/文件？", "SCN-UPLOAD-GUARDS", "oversized_and_unsupported_upload", ["上传超过隔离环境配置上限的文件", "上传不支持的扩展名", "检查数据库、任务和 storage path"], ["分别返回 413 和 400", "失败请求无 document/job/文件残留"]),
        ("zh", "Worker 重启后进行中的索引任务能否安全恢复？", "SCN-WORKER-RESTART", "worker_restart", ["在隔离任务进入 embedding 阶段暂停 Worker", "重启 Worker", "轮询原始 job 并搜索样本"], ["job 达到明确终态", "恢复不重复创建孤儿 chunk/vector"]),
        ("zh", "同一文档重复重试和重建是否幂等？", "SCN-INDEX-IDEMPOTENCY", "index_retry", ["保存初次 chunk/vector 清单", "对同一文档连续执行两次 reindex", "比较内容、数量和向量归属"], ["不产生重复活动 chunk/vector", "失败版本不会覆盖最近一次有效内容"]),
        ("zh", "删除文档后 SQL、Milvus 和文件存储是否都清理完成？", "SCN-DELETE-CLEANUP", "document_delete", ["索引专属 DOCX/Markdown 文件", "通过删除 API 删除", "复查 document/chunk/job、Milvus IDs 和存储路径"], ["所有文档向量被删除", "文件和记录清理结果一致"]),
        ("zh", "向量对账发现缺失向量或孤儿向量后能否修复且可重复执行？", "SCN-VECTOR-RECONCILE", "vector_reconciliation", ["在隔离 collection 中分别制造 SQL-only chunk 和 vector-only ID", "运行 reconciliation", "再运行一次并核对差异集"], ["修复缺失向量并删除孤儿向量", "二次运行无新增变更；若功能缺失标记 not_implemented"]),
        ("zh", "Agent 取消时 SSE 是否有唯一终态且不会随后补发 complete？", "SCN-SSE-CANCEL", "sse_cancel", ["启动可控延迟 Agent 请求", "发送取消请求", "收集直到 SSE 流关闭"], ["出现 cancelled/error 终态", "取消后不再出现 agent_complete"]),
        ("zh", "模型返回不存在或跨 Workspace 引用 ID 时如何处置？", "SCN-CITATION-VALIDATION", "invalid_citation", ["在隔离用例中让模型输出伪造 chunk ID", "读取 SSE citation 和已存 Citation", "用另一个 Workspace 的真实 chunk 重复"], ["无效/越权 ID 不进入最终引用", "修正失败时明确降级而不伪造来源；若缺少校验标记 not_implemented"]),
        ("zh", "跨 Workspace 搜索、读取文档和 citation endpoint 是否严格隔离？", "SCN-CROSS-WORKSPACE", "cross_workspace_access", ["在两个测试 Workspace 各上传含唯一 canary 的文档", "使用 A 的 token 查询/读取 B 的文档和 chunk", "检查 body、citation、SSE 与日志"], ["越权请求统一拒绝/隐藏为 404", "B 的 canary 零次出现在 A 的响应或引用中"]),
        ("en", "Does an MCP tool failure or timeout become an explicit failure rather than fabricated success?", "SCN-MCP-FAILURE", "mcp_tool_failure", ["Register an enabled test MCP tool that returns a controlled error", "Run an Agent query that requires it", "Inspect tool result, SSE terminal event, and final answer"], ["Tool error is visible and bounded", "The final answer never claims a successful lookup"]),
        ("en", "Does an MCP tool exceeding its configured timeout terminate within the allowed bound?", "SCN-MCP-TIMEOUT", "mcp_tool_timeout", ["Register a test MCP tool that delays beyond the configured limit", "Invoke it in Agent mode", "Measure latency and inspect terminal events"], ["Timeout is surfaced within the configured bound", "No fabricated tool output or hanging SSE stream"]),
        ("zh", "RAG 和 Agent SSE 是否按约定输出检索、引用、工具和终态事件？", "SCN-SSE-EVENTS", "sse_event_contract", ["分别执行 RAG 与 Agent 的受控请求", "记录完整 event/data 帧", "检查 event 顺序、JSON schema 和连接关闭"], ["RAG 包含 retrieval_result/citation/message_complete", "Agent 的工具调用有结果及最终终态；不输出 hidden chain of thought"]),
        ("en", "After a failed parse or interrupted index, does rebuild clean stale state and converge?", "SCN-REBUILD-CLEANUP", "rebuild_after_partial_failure", ["Inject a failure after parse or vector upsert in an isolated fixture", "Rebuild the document", "Compare latest SQL chunks, active vectors, status, and stored file"], ["Stale vectors are removed or reconciled", "A rebuild converges to one indexed version or a clear failed state"]),
    ]
    for definition in definitions:
        add_scenario(*definition)
    assert len(SCENARIOS) >= 16
    (EVAL / "scenarios.json").write_text(json.dumps({"schema_version": 1, "scenario_count": len(SCENARIOS), "scenarios": SCENARIOS}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def Q(cat: str, lang: str, query: str, answer: str, refs: list[tuple[str, str]], **kw) -> None:
    add_qa(cat, lang, query, answer, [ev(*ref) for ref in refs], **kw)


def build_cases() -> None:
    # 28 direct facts (18 Chinese, 10 English).
    simple = [
        ("zh", "KNOWNEST 是什么类型的应用？", "它是面向所选知识库提问的 Web 知识应用。", "product", "KNOWNEST is a web knowledge application for asking questions of a selected knowledge base."),
        ("zh", "目标用户是谁？", "需要查找、理解和使用组织文档的企业知识工作者。", "product", "Enterprise knowledge workers who need to find, understand, and use information held across their organization's documents."),
        ("zh", "KNOWNEST 提供哪两种主要问答模式？", "直接检索增强问答和 Agent 研究模式。", "product", "It supports direct retrieval-assisted answers and an agentic research mode"),
        ("zh", "回答依据可以怎样供用户检查？", "产品提供来源引用和证据轨迹供审阅。", "product", "with source citations and evidence traces available for review."),
        ("zh", "用户在什么范围里选择知识库并提问？", "用户在一个 Workspace 和选定知识库中工作。", "product", "Users work within a workspace and selected knowledge base."),
        ("zh", "当前前端框架是什么？", "Vue 3。", "product", "The current frontend is a Vue 3 application"),
        ("zh", "项目后端使用什么 Web 框架？", "FastAPI。", "readme", "FastAPI, SQLAlchemy and PostgreSQL"),
        ("zh", "Milvus 向量维度是多少？", "4096 维。", "readme", "Milvus for 4096-dimensional Qwen/Qwen3-VL-Embedding-8B vectors"),
        ("zh", "文档索引任务使用哪些队列组件？", "Redis 和 Celery。", "readme", "Redis and Celery for document indexing jobs"),
        ("zh", "支持哪些兼容聊天服务商？", "OpenAI 和 DeepSeek 兼容服务商。", "readme", "OpenAI and DeepSeek compatible chat providers"),
        ("zh", "调用受保护 API 时需要发送什么认证头？", "Authorization: Bearer <access_token>。", "api", "Authorization: Bearer <access_token>"),
        ("zh", "首次 setup 在什么条件下可以执行？", "仅当系统还没有用户时可以调用。", "api", "仅允许在系统还没有用户时调用"),
        ("zh", "当前上传接口接受哪些文件格式？", "PDF、Markdown、TXT 或 DOCX。", "api", "上传 PDF、Markdown、TXT 或 DOCX。"),
        ("zh", "上传接口如何传递原始文件？", "以原始二进制请求体上传，并通过 X-Filename 或 filename 参数提供文件名。", "api", "接口接收**原始二进制请求体**"),
        ("zh", "索引任务有哪些状态？", "pending、processing、parsed、embedding、indexed、failed、deleting、deleted。", "api", "状态包括 `pending`、`processing`、`parsed`、`embedding`、`indexed`、`failed`、`deleting`、`deleted`。"),
        ("zh", "RAG 消息链路会调用 Agent 工具或 MCP 吗？", "不会；RAG 只做检索和模型生成。", "api", "RAG 只执行检索和模型生成，不调用 Agent 工具或 MCP。"),
        ("zh", "用户没有 bearer token 时读取引用片段会怎样？", "引用接口返回 401。", "api", "The endpoint returns `401` without a bearer token"),
        ("zh", "当前系统是否已经具备完整企业 RBAC？", "没有；当前权限更接近个人 Workspace 模型，完整企业协作权限仍有差距。", "review", "当前主要是“用户拥有 Workspace，Workspace 拥有知识库”的个人工作区模型，不足以支撑完整的企业协作"),
        ("en", "What is KNOWNEST's product platform?", "It is a web knowledge application.", "product", "KNOWNEST is a web knowledge application"),
        ("en", "Who is the intended audience?", "Enterprise knowledge workers using organizational documents.", "product", "Enterprise knowledge workers who need to find, understand, and use information held across their organization's documents."),
        ("en", "Which answer modes are described?", "Direct retrieval-assisted answers and an agentic research mode.", "product", "It supports direct retrieval-assisted answers and an agentic research mode"),
        ("en", "What can users inspect behind an answer?", "Source citations and evidence traces.", "product", "with source citations and evidence traces available for review."),
        ("en", "Which database stores application records?", "PostgreSQL.", "readme", "FastAPI, SQLAlchemy and PostgreSQL"),
        ("en", "Which system stores dense vectors?", "Milvus, using 4096-dimensional vectors.", "readme", "Milvus for 4096-dimensional Qwen/Qwen3-VL-Embedding-8B vectors"),
        ("en", "Which providers are supported for chat completion?", "OpenAI- and DeepSeek-compatible providers.", "readme", "OpenAI and DeepSeek compatible chat providers"),
        ("en", "Which document formats can the current upload API accept?", "PDF, Markdown, TXT, and DOCX.", "api", "上传 PDF、Markdown、TXT 或 DOCX。"),
        ("en", "Does the RAG endpoint invoke MCP tools?", "No. RAG performs retrieval and model generation only.", "api", "RAG 只执行检索和模型生成，不调用 Agent 工具或 MCP。"),
        ("en", "What is the default chunk overlap shown in the chunking guide?", "80 characters.", "chunking", "| **Chunk overlap** | 0–500 chars | 80 (~15%) |"),
    ]
    for lang, query, answer, source, quote in simple:
        Q("simple", lang, query, answer, [(source, quote)])

    # 20 synthesis questions (15 Chinese, 5 English); each requires multiple passages.
    composite = [
        ("zh", "为什么不能只凭答案带了引用就认为它可信？", "引用存在并不证明引用 ID 有效、片段相关或每个结论都受证据支持；需要校验引用与断言的一致性。", [("review", "答案中的引用 ID 是否真实存在"), ("review", "每个关键结论是否被引用支持")]),
        ("zh", "当前 RAG 和 Agent 的初始检索链路有什么共同点，方案指出什么问题？", "两者目前都先取 5 条结果；Agent 常直接复用初始证据，可能与 RAG 只在提示词上不同，缺少多步研究能力。", [("review", "普通 RAG 和智能回答都先调用同一个 `hybrid_search` 获取 5 条结果"), ("review", "因此，如果模型第一轮直接生成答案，两个模式实际上只是系统提示词不同，最终答案和引用很容易完全相同。"), ("review", "多轮检索和多跳推理")]),
        ("zh", "总结当前上传能力及仍存在的文档解析风险。", "当前支持 PDF、Markdown、TXT、DOCX；扫描 PDF 无 OCR、复杂 DOCX 和表格结构保真等仍有限。", [("review", "目前支持 PDF、Markdown、TXT、DOCX"), ("review", "扫描 PDF 没有 OCR")]),
        ("zh", "项目的主要运行组件分别承担什么角色？", "FastAPI/SQLAlchemy/PostgreSQL 组成应用后端，Milvus 存向量，Redis/Celery 承担索引任务，Vue 3 是前端。", [("readme", "FastAPI, SQLAlchemy and PostgreSQL"), ("readme", "Milvus for 4096-dimensional"), ("readme", "Redis and Celery for document indexing jobs"), ("readme", "Vue 3 frontend")]),
        ("zh", "按照 P0/P1 方案，哪些问题应走 simple、composite 和 research？", "单事实、定义、简单定位走 simple；比较、总结、列举、流程或跨文档走 composite；工具、计算、全文或多跳验证走 research。", [("p0p1", "单事实、定义和简单定位走 simple 快速 RAG。"), ("p0p1", "比较、总结、列举、流程和跨文档问题走 composite。"), ("p0p1", "需要工具、计算、完整文档或多跳验证的问题走 research。")]),
        ("zh", "P0/P1 方案给普通和复杂问题分别设置什么召回规模？", "普通问题 5–8 条，复杂问题 12–20 条，候选集最多 30 条。", [("p0p1", "普通问题召回 5–8 条，复杂问题召回 12–20 条，候选集上限 30 条。")]),
        ("zh", "Rerank 失败时，目标链路应怎样呈现，而不是怎样做？", "应报告是否使用 Rerank 和降级原因；不能静默降级后仍让用户以为检索正常。", [("p0p1", "检索应明确报告 Embedding、Rerank 是否使用及降级原因。"), ("review", "用户不一定意识到检索质量已下降")]),
        ("zh", "什么情况下目标链路不应强行给确定答案？", "无候选、最高分低于阈值、证据冲突或只有低质量降级结果时。", [("p0p1", "无候选、最高分低于阈值、证据冲突或只有低质量降级结果时，不得强行生成确定答案。")]),
        ("zh", "研究模式的子问题、检索、验证和工具调用上限分别是多少？", "最多 3 个子问题、每题最多检索 2 次、最多验证 2 次，工具调用总数最多 6 次。", [("p0p1", "最多 3 个子问题；每个子问题最多检索 2 次；最多验证 2 次。"), ("p0p1", "工具调用总数最多 6 次")]),
        ("zh", "研究流程有哪些状态，何时允许最终回答？", "plan、retrieve、inspect、verify、synthesize、validate、complete；只有证据满足完成条件后才允许完成。", [("p0p1", "研究状态依次为 plan、retrieve、inspect、verify、synthesize、validate、complete。"), ("p0p1", "只有证据满足该任务完成条件后，研究流程才进入 complete。")]),
        ("zh", "P0/P1 对工具选择和失败有什么要求？", "明确计算调用安全 calculator；MCP 必须显式启用；工具失败要进入可解释降级路径。", [("p0p1", "明确计算必须调用安全 calculator；不得把模型心算伪装成工具结果。"), ("p0p1", "MCP 工具必须显式启用；工具失败必须进入可解释的降级路径。")]),
        ("zh", "上下文超预算时，方案要求优先保留哪些信息？", "保留用户问题、直接证据、工具结果和未解决冲突；并标明截断。", [("p0p1", "接近预算时优先保留用户问题、直接证据、工具结果和未解决冲突，并在报告中标明截断。")]),
        ("zh", "引用校验要检查什么？", "校验引用 ID 属于本次工作区和本次检索结果，且引用片段支持对应结论。", [("p0p1", "回答前校验引用 ID 属于本次工作区、本次检索结果，且引用片段支持对应结论。")]),
        ("zh", "内部试用的引用和拒答门槛分别是多少？", "引用 ID 有效率 100%，知识库内问题引用支持率至少 90%，无答案拒答准确率至少 85%。", [("p0p1", "引用 ID 有效率为 100%。"), ("p0p1", "知识库内问题的引用支持率至少 90%。"), ("p0p1", "无答案问题的拒答准确率至少 85%。")]),
        ("zh", "PostgreSQL 与 Milvus 如何避免长期不一致？", "通过 reconciliation 比较 chunks、vectors、索引代次和模型版本，并补缺失向量、删孤儿或重建索引。", [("p0p1", "reconciliation 对比 PostgreSQL chunks、Milvus vectors、索引代次和模型版本"), ("p0p1", "支持补写缺失向量、删除孤儿向量和重新索引。")]),
        ("en", "Summarize the migration board's final decision and the record-retention window.", "The board approved cutover on 2026-04-17 for 8,420 records; the legacy catalog stayed read-only for 90 days.", [("research_en", "The migration board approved the final cutover on 2026-04-17"), ("research_en", "The approved collection contained 8,420 records."), ("research_en", "The team retained the legacy catalog in read-only mode for 90 days after cutover.")]),
        ("en", "How do the product principles connect to answer citations and tool traces?", "The product is designed to ground answers in inspectable sources and make research activity legible, with citations/evidence traces available for review.", [("product", "Ground answers in inspectable source material."), ("product", "Make research progress and system activity legible"), ("product", "source citations and evidence traces available for review")]),
        ("en", "What does the P0/P1 plan require when retrieval evidence is missing or conflicting?", "It requires an insufficient-evidence response rather than a forced definitive answer.", [("p0p1", "无候选、最高分低于阈值、证据冲突或只有低质量降级结果时，不得强行生成确定答案。")]),
        ("en", "Compare the P0/P1 latency budgets for ordinary and research questions.", "Ordinary questions target P95 at or below 20 seconds; research questions target P95 at or below 45 seconds.", [("p0p1", "普通问题 P95 不超过 20 秒；研究问题 P95 不超过 45 秒。")]),
        ("en", "What safeguards are expected around a failed MCP tool call?", "MCP must be explicitly enabled, and a failure must produce an explainable degradation path rather than a fabricated success.", [("p0p1", "MCP 工具必须显式启用；工具失败必须进入可解释的降级路径。")]),
    ]
    composite_claims = [
        [("存在引用不证明引用 ID 真实有效。", [0]), ("每个关键结论仍必须由其引用支持。", [1])],
        [("RAG 和 Agent 初始都检索 5 条结果。", [0]), ("Agent 可能只与 RAG 在提示词上不同，且缺少多步检索/验证能力。", [1, 2])],
        [("当前上传格式包括 PDF、Markdown、TXT 和 DOCX。", [0]), ("扫描 PDF 无 OCR，复杂 DOCX/表格保真仍有限。", [1])],
        [("FastAPI、SQLAlchemy、PostgreSQL 是后端组件。", [0]), ("Milvus 存储向量。", [1]), ("Redis 与 Celery 承担索引任务。", [2]), ("Vue 3 是前端。", [3])],
        [("单事实、定义和简单定位走 simple。", [0]), ("比较、总结、列表、流程、跨文档走 composite。", [1]), ("工具、计算、完整文档、多跳验证走 research。", [2])],
        [("普通问题召回 5–8 条，复杂问题召回 12–20 条。", [0]), ("候选集上限为 30 条。", [0])],
        [("检索要报告 Embedding/Rerank 是否使用及降级原因。", [0]), ("Rerank 失败可能静默退回 RRF，使用户误以为质量正常。", [1])],
        [("无候选、低于阈值、证据冲突或低质量降级时不应强行给确定答案。", [0])],
        [("最多拆 3 个子问题，每个最多检索 2 次，并最多验证 2 次。", [0]), ("工具总调用最多 6 次。", [1])],
        [("研究状态依次为 plan、retrieve、inspect、verify、synthesize、validate、complete。", [0]), ("只有证据满足完成条件后才能进入 complete。", [1])],
        [("明确计算使用安全 calculator。", [0]), ("MCP 工具必须显式启用。", [1]), ("工具失败必须进入可解释降级路径。", [1])],
        [("上下文接近预算时保留用户问题、直接证据、工具结果、未解决冲突，并标明截断。", [0])],
        [("引用 ID 必须属于本次工作区和检索结果，且片段要支持结论。", [0])],
        [("引用 ID 有效率目标是 100%。", [0]), ("知识库问题引用支持率目标至少 90%。", [1]), ("无答案拒答准确率目标至少 85%。", [2])],
        [("对账要比较 PostgreSQL chunks、Milvus vectors、索引代次和模型版本。", [0]), ("对账支持补缺向量、删孤儿向量和重新索引。", [1])],
        [("最终切换于 2026-04-17 获批。", [0]), ("获批集合有 8,420 条记录。", [1]), ("旧目录切换后只读保留 90 天。", [2])],
        [("产品原则是用可检查来源为答案提供依据。", [0]), ("研究进度和系统活动应清晰可见。", [1]), ("用户可以审阅来源引用和证据轨迹。", [2])],
        [("证据缺失或冲突时应说明不足，不能强行给确定结论。", [0])],
        [("普通问题 P95 目标不超过 20 秒。", [0]), ("研究问题 P95 目标不超过 45 秒。", [0])],
        [("MCP 工具调用前必须显式启用。", [0]), ("MCP 失败必须走可解释降级而非伪造成功。", [0])],
    ]
    for (lang, query, answer, refs), claims in zip(composite, composite_claims, strict=True):
        atomic = [{"text": text, "required": True, "atomic": True, "evidence": [ev(*refs[index]) for index in evidence_indexes]} for text, evidence_indexes in claims]
        Q("composite", lang, query, answer, refs, target_complexity="composite", extra_claims=atomic)

    # 18 deliberate no-answer questions (14 Chinese, 4 English).
    no_answer = [
        ("zh", "KNOWNEST 对外承诺的月度可用性百分比是多少？", "月度 SLA 百分比", "99.99%"),
        ("zh", "系统每天几点自动备份，备份保留多少天？", "备份时间和保留期限", "02:00 UTC"),
        ("zh", "每个用户每秒最多可以请求多少次 API？", "每用户 API 限流数", "100 req/s"),
        ("zh", "生产环境的数据库部署在哪个云区域？", "云区域", "ap-southeast-1"),
        ("zh", "普通用户最多可以创建多少个知识库？", "知识库数量上限", "50 knowledge bases"),
        ("zh", "客服团队的电话号码是什么？", "客服电话号码", "400-123-4567"),
        ("zh", "产品保证的最大同时在线用户数是多少？", "最大在线人数", "100 concurrent users"),
        ("zh", "OpenAI API 的月度费用预算是多少？", "月度模型预算", "$500/month"),
        ("zh", "生产环境中 PostgreSQL 的自动备份恢复时间目标是多少？", "数据库 RTO", "RTO 30 minutes"),
        ("zh", "是否承诺 99.99% 的服务可用性？", "99.99% SLA 承诺", "99.99%"),
        ("zh", "员工离职后其 Workspace 数据几天内清除？", "离职数据清理期限", "retained for 30 days"),
        ("zh", "项目目前部署在哪个 Kubernetes 集群？", "生产 Kubernetes 集群名称", "prod-shanghai-01"),
        ("zh", "每个 DOCX 文件最多允许包含多少张表？", "DOCX 表格数量上限", "20 tables"),
        ("zh", "系统支持的最大单知识库文档数量是多少？", "知识库文档数量上限", "10,000 documents"),
        ("en", "What monthly uptime SLA does KNOWNEST guarantee?", "monthly uptime SLA", "99.99%"),
        ("en", "How many days are production database backups retained?", "backup retention period", "retained for 30 days"),
        ("en", "What is the maximum number of documents allowed in one knowledge base?", "per-knowledge-base document limit", "10,000 documents"),
        ("en", "Which cloud region hosts the production database?", "production cloud region", "ap-southeast-1"),
    ]
    for lang, query, missing, absence_check in no_answer:
        absence_quote = "KNOWNEST 项目文档和本评测快照未给出对外月度 SLA、生产数据库备份时刻/保留期/RTO、每用户 API 限流数、生产云区域或 Kubernetes 集群名、知识库/文档容量配额、客服电话号码、最大并发用户数、模型月度费用预算、离职数据清理期限或 DOCX 表格数量上限。"
        absence_check = ev("absence_register", absence_quote) | {"must_not_appear": absence_check}
        add_qa("no_answer", lang, query, None, answerability="insufficient", target_complexity="simple", must_not_claim=[f"a specific value for {missing}"], absence_checks=[absence_check], tags=["absence_scope", missing])

    # 12 policy-version examples: six source-scoped questions and six true conflicts.
    for index, (lang, query) in enumerate([
        ("zh", "政策 v1 写明的现行餐费标准是多少？"),
        ("zh", "只看 2025-01-10 发布的 v1，餐费上限是多少？"),
        ("zh", "v1 文档中的餐费额度是多少元/人/天？"),
        ("zh", "餐费政策第一版给出的每日额度是多少？"),
        ("zh", "v1 要求差旅票据在什么时候提交？"),
        ("en", "According to policy v2, what is the meal allowance per person per day?"),
    ]):
        source, quote, answer = ("policy_v1", "本文件声明当前现行差旅餐费标准为每人每天 120 元。", "v1 声明每人每天 120 元。") if index < 5 else ("policy_v2", "本文件同样声明当前现行差旅餐费标准为每人每天 150 元。", "v2 声明每人每天 150 元。")
        if index == 4:
            quote, answer = "差旅人员需保留发票并在行程结束后 10 个工作日内提交报销。", "行程结束后 10 个工作日内。"
        Q("conflict", lang, query, answer, [(source, quote)], target_complexity="composite", tags=["version_specific"])
    for lang, query in [
        ("zh", "这两份政策对当前每日餐费上限说法一致吗？"),
        ("zh", "根据知识库中的两份文件，现行餐费额度到底是多少？"),
        ("zh", "v1 和 v2 对餐费金额的现行规定有什么冲突？"),
        ("zh", "是否能从这两份政策确定唯一的餐费报销额度？"),
        ("zh", "请指出餐费政策中彼此不一致的数字。"),
        ("en", "Do the two policy documents agree on the current daily meal allowance?"),
    ]:
        claims = [
            {"text": "v1 声明每人每天 120 元。", "required": True, "atomic": True, "evidence": [ev("policy_v1", "本文件声明当前现行差旅餐费标准为每人每天 120 元。")]},
            {"text": "v2 声明每人每天 150 元。", "required": True, "atomic": True, "evidence": [ev("policy_v2", "本文件同样声明当前现行差旅餐费标准为每人每天 150 元。") ]},
        ]
        add_qa("conflict", lang, query, "两份文件互相冲突：v1 说 120 元，v2 说 150 元，不能据此给出唯一现行额度。", answerability="conflicting", baseline_route="rag", target_complexity="composite", tags=["conflicting_evidence"], must_not_claim=["a single agreed current allowance"], extra_claims=claims)

    # 12 table and arithmetic questions (10 Chinese, 2 English).
    table_rows = [
        "Analytics | 1.2 | 1.5 | 12",
        "Platform | 2.4 | 2.1 | 18",
        "Support | 0.9 | 1.1 | 10",
    ]
    table_questions = [
        ("zh", "Analytics 部门 Q1 收入是多少？", "1.2 百万元人民币。", [table_rows[0]], False),
        ("zh", "哪个部门 Q1 收入最高？", "Platform，Q1 收入为 2.4 百万元人民币。", [table_rows[1]], False),
        ("zh", "哪个部门员工人数最多？", "Platform，有 18 人。", [table_rows[1]], False),
        ("zh", "Support 部门两个季度的收入分别是多少？", "Q1 为 0.9，Q2 为 1.1 百万元人民币。", [table_rows[2]], False),
        ("zh", "Q1 三个部门的总收入是多少？", "4.5 百万元人民币。", table_rows, True),
        ("zh", "Q2 三个部门的总收入是多少？", "4.7 百万元人民币。", table_rows, True),
        ("zh", "Platform 的 Q1 到 Q2 收入变化是多少？", "下降 0.3 百万元人民币。", [table_rows[1]], True),
        ("zh", "Analytics 的 Q1 到 Q2 收入增长了百分之多少？", "增长 25%。", [table_rows[0]], True),
        ("zh", "三个部门合计有多少员工？", "40 人。", table_rows, True),
        ("zh", "Q2 收入最高的部门是哪一个，收入是多少？", "Platform，2.1 百万元人民币。", [table_rows[1]], False),
        ("en", "What was Support's Q2 revenue?", "1.1 million CNY.", [table_rows[2]], False),
        ("en", "What is the combined Q1 revenue across all three departments?", "4.5 million CNY.", table_rows, True),
    ]
    for lang, query, answer, rows, calculate in table_questions:
        Q("table_calculation", lang, query, answer, [("table_docx", row) for row in rows] + [("table_notes", "金额单位为百万元人民币，人数为整数。")], baseline_route="agent" if calculate else "rag", target_complexity="research" if calculate else "simple", target_tools=["calculator"] if calculate else [], tags=["table", "calculation" if calculate else "lookup"])

    # 10 conversational follow-ups (8 Chinese, 2 English); history is replayed by the runner.
    multi_turn = [
        ("zh", "北辰实验室设备可以借多久？", "研发设备可借用多少天？", "14 个自然日。", "设备借用 14 个自然日。", "handbook", "研发设备可借用 14 个自然日。"),
        ("zh", "新员工安全课程的期限是多少？", "如果没通过，多久能重考？", "2 个工作日后可以重考。", "新员工可以在 2 个工作日后重考。", "handbook", "未通过课程测验时，可以在 2 个工作日后重考。"),
        ("zh", "办公用品报销需要什么条件？", "那金额超过多少要附审批？", "单笔金额超过 500 元须附主管审批记录。", "超过 500 元。", "handbook", "单笔金额超过 500 元时须附主管审批记录。"),
        ("zh", "网络故障怎么提交？", "首次响应目标是多少？", "服务台表单；目标为 4 个工作小时内首次响应。", "4 个工作小时内。", "handbook", "服务台目标为 4 个工作小时内首次响应。"),
        ("zh", "KNOWNEST 有什么回答模式？", "其中哪一种会使用 MCP？", "Agent 研究模式可以调用显式启用的 MCP 工具；RAG 不调用 MCP。", "KNOWNEST 提供直接 RAG 和 Agent 研究模式。", "api", "RAG 只执行检索和模型生成，不调用 Agent 工具或 MCP。"),
        ("zh", "P0/P1 研究最多能拆几个子问题？", "每个子问题最多检索几次？", "每个子问题最多检索 2 次。", "2 次。", "p0p1", "每个子问题最多检索 2 次"),
        ("zh", "文件索引任务有哪些状态？", "成功完成时的状态是什么？", "indexed。", "indexed。", "api", "`indexed`"),
        ("zh", "餐费政策的 v2 写了多少？", "与 v1 相比增加多少元？", "增加 30 元/人/天；注意两份文件都声称自己是现行规定。", "30 元/人/天。", "policies", "v1 声明当前现行差旅餐费标准为每人每天 120 元。"),
        ("en", "How long does the synthetic archive keep the legacy catalog read-only?", "What was the approved record count?", "8,420 records.", "8,420 records.", "research", "The approved collection contained 8,420 records."),
        ("en", "What does the product expose so users can review answer evidence?", "Which principle does that support?", "Grounding answers in inspectable source material.", "Ground answers in inspectable source material.", "product", "Ground answers in inspectable source material."),
    ]
    for lang, first, follow, answer, prior, key, quote in multi_turn:
        doc = {"handbook": "handbook", "API": "api", "p0p1": "p0p1", "api": "api", "policies": "policy_v1", "research": "research_en", "product": "product"}[key]
        refs = [(doc, quote)]
        if key == "policies":
            refs = [("policy_v1", "本文件声明当前现行差旅餐费标准为每人每天 120 元。"), ("policy_v2", "本文件同样声明当前现行差旅餐费标准为每人每天 150 元。")]
        Q("multi_turn", lang, follow, answer, refs, target_complexity="composite", history=[{"role": "user", "content": first}, {"role": "assistant", "content": prior}], tags=["follow_up", "reference_resolution"])

    # 10 tool-oriented questions (7 Chinese, 3 English). MCP prerequisites are explicit.
    tool_questions = [
        ("zh", "用安全计算器算 15 × 4 + 2。", "62。", "15 * 4 + 2", "calculator", "确定的算术请求应调用 calculator。", "readme", "tools"),
        ("zh", "请计算 180 / 12。", "15。", "180 / 12", "calculator", "明确计算请求只由 calculator 处理。", "p0p1", "tools"),
        ("zh", "表格中三个部门的 Q2 总收入是多少？请用计算器核算。", "4.7 百万元人民币。", "1.5 + 2.1 + 1.1", "calculator", "工具调用应计算表格中的已知数字。", "table_notes", "table"),
        ("zh", "将 14 天借期延长 7 天，总共是几天？", "21 天。", "14 + 7", "calculator", "只计算明确给出的数值。", "handbook", "loan"),
        ("zh", "帮我计算 120 元每天、5 天的总餐费额度。", "600 元。", "120 * 5", "calculator", "这是明确的乘法计算。", "policy_v1", "policy"),
        ("zh", "需要读取 Meridian Archive 迁移的最终完整记录时，哪个内置工具适合？", "read_document 可读取所选知识库中某份文档的索引片段。", "read_document", "read_document", "需读取完整文档上下文时可使用 read_document。", "readme", "document"),
        ("zh", "要检查北辰手册完整的设备规则，Agent 应使用哪个文档读取工具？", "read_document。", "read_document", "read_document", "完整文档上下文应使用 read_document。", "readme", "document"),
        ("en", "Calculate the total Q2 revenue for Analytics, Platform, and Support.", "4.7 million CNY.", "1.5 + 2.1 + 1.1", "calculator", "An explicit arithmetic request should use the calculator.", "table_notes", "calculation"),
        ("en", "Which built-in tool can read indexed passages from a selected document?", "read_document.", "read_document", "read_document", "The tool reads indexed passages from a document in the selected knowledge base.", "readme", "document"),
        ("en", "When may an Agent call an MCP tool, and what should it do if that tool is unavailable?", "Only explicitly enabled MCP tools may be called; an unavailable tool must be reported as unavailable, not treated as a successful lookup.", "none", "none", "MCP tools must be explicitly enabled and an unavailable tool is not a successful lookup.", "p0p1", "mcp_policy"),
    ]
    for lang, query, answer, expression, tool, behavior, source, tag in tool_questions:
        readme_quote = "calculate arithmetic expressions" if tool == "calculator" else "read indexed documents"
        p0p1_quote = "明确计算必须调用安全 calculator；不得把模型心算伪装成工具结果。" if tool == "calculator" else "MCP 工具必须显式启用；工具失败必须进入可解释的降级路径。"
        refs = [(source, readme_quote if source == "readme" else p0p1_quote if source == "p0p1" else "RAG 只执行检索和模型生成，不调用 Agent 工具或 MCP。" if source == "api" else "金额单位为百万元人民币，人数为整数。" if source == "table_notes" else "研发设备可借用 14 个自然日。" if source == "handbook" else "本文件声明当前现行差旅餐费标准为每人每天 120 元。")]
        if source == "table_notes":
            refs.extend(("table_docx", row) for row in table_rows)
        mcp_policy = tool == "none"
        policy_or_tool_definition = tool in {"none", "read_document"}
        target_tools = [] if policy_or_tool_definition else [tool]
        Q("tools_mcp", lang, query, answer, refs, baseline_route="rag" if policy_or_tool_definition else "agent", target_complexity="simple" if policy_or_tool_definition else "research", target_tools=target_tools, baseline_tools=target_tools, tags=[tag, "tool_policy" if policy_or_tool_definition else "tool_expected"], must_not_claim=["a fabricated tool result"] if mcp_policy else [])

    # 10 degradation-behavior QA rows remain part of the golden 120.
    degradation = [
        ("zh", "Embedding 超时导致未获得向量时，目标检索链路必须怎样处理？", "明确标记 Embedding 未使用及其降级原因，不能把结果说成正常完整检索。", "Embedding 服务超时", "Embedding、Rerank 等依赖不可用时，必须报告实际未使用的组件和降级原因。"),
        ("zh", "Rerank 超时后，用户应该看到什么信息？", "应明确说明 Rerank 未使用并解释降级原因。", "Rerank 服务不可用", "Embedding、Rerank 等依赖不可用时，必须报告实际未使用的组件和降级原因。"),
        ("zh", "Milvus 不可用时能否静默切到进程内内存索引？", "不能；必须明确报告 Milvus 不可用，不能静默切换。", "Milvus 不可用", "Milvus 不可用时不能静默切换到进程内内存索引。"),
        ("zh", "检索没有候选或最高分低于阈值时，应如何回答？", "说明当前没有足够证据，不强行生成确定结论。", "没有足够证据", "无候选、最高分低于阈值、证据冲突或只有低质量降级结果时"),
        ("zh", "工具调用失败或超时后，答案可以怎样描述执行结果？", "要返回可解释的失败/降级状态，不能声称工具成功。", "工具失败", "依赖超时、取消或失败时返回可解释状态，不得报告为成功。"),
        ("zh", "索引失败时应把文档标记为 indexed 还是 failed？", "应标记为 failed 并保留可诊断的失败信息，不能报告索引成功。", "failed", "索引流程为解析、分块、Embedding、向量 upsert、数据库提交、标记 indexed"),
        ("zh", "引用片段不支持结论时，目标行为是什么？", "引用校验应识别不支持的引用并修正或降低置信度，不能保留伪造引用。", "引用校验", "引用片段支持对应结论"),
        ("en", "What should the system report when embedding or reranking is unavailable?", "It should identify which dependency was not used and explain the degradation; it must not present the result as a normal full-quality retrieval.", "degradation reason", "Embedding、Rerank 等依赖不可用时，必须报告实际未使用的组件和降级原因。"),
        ("en", "What should happen when evidence conflicts or only low-quality degraded results remain?", "Do not force a definitive answer; surface the conflict or say the evidence is insufficient.", "conflicting evidence", "发生证据冲突或仅剩低质量降级结果时，不得强行生成确定答案。"),
        ("zh", "普通问题和 research 问题的 P95 延迟目标分别是多少？", "普通问题 P95 不超过 20 秒，research 问题不超过 45 秒。", "latency", "普通问题 P95 不超过 20 秒；研究问题 P95 不超过 45 秒。"),
    ]
    for lang, query, answer, tag, quote in degradation:
        source = "p0p1" if quote in (ROOT / "dataset/evaluation/corpus/p0p1_targets.md").read_text(encoding="utf-8") else "review"
        Q("degradation", lang, query, answer, [(source, quote)], baseline_route="rag", target_complexity="simple", tags=["degradation", tag])

    assert len(cases) == 120, f"expected 120 rows, generated {len(cases)}"
    counts = {key: sum(item["category"] == key for item in cases) for key in ("simple", "composite", "no_answer", "conflict", "table_calculation", "multi_turn", "tools_mcp", "degradation")}
    languages = {key: sum(item["language"] == key for item in cases) for key in ("zh", "en")}
    assert counts == {"simple": 28, "composite": 20, "no_answer": 18, "conflict": 12, "table_calculation": 12, "multi_turn": 10, "tools_mcp": 10, "degradation": 10}, counts
    assert languages == {"zh": 90, "en": 30}, languages
    path = EVAL / "cases.jsonl"
    path.write_text("".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in cases), encoding="utf-8", newline="\n")


def build_manifest() -> None:
    sources = []
    for source_id, origin, snapshot, upload_name in SOURCES:
        source_path = ROOT / snapshot
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        sources.append({"id": source_id, "path": snapshot.replace("\\", "/"), "origin_path": origin.replace("\\", "/"), "snapshot_version": "knownest-python-runtime-p0p1-v1", "upload_name": upload_name, "sha256": sha256(source_path)})
    case_path = EVAL / "cases.jsonl"
    scenario_path = EVAL / "scenarios.json"
    cases = [json.loads(line) for line in case_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    manifest = {
        "schema_version": 1,
        "dataset_id": "knownest-python-runtime-p0p1-v1",
        "description": "Golden QA and failure-scenario fixture for the Python Runtime; synthetic organization documents are fictional.",
        "case_count": 120,
        "qa_case_count": len(cases),
        "scenario_case_count": len(SCENARIOS),
        "scenario_count": len(SCENARIOS),
        "category_counts": {key: sum(item["category"] == key for item in cases) for key in ("simple", "composite", "no_answer", "conflict", "table_calculation", "multi_turn", "tools_mcp", "degradation")},
        "language_counts": {key: sum(item["language"] == key for item in cases) for key in ("zh", "en")},
        "sources": sources,
        "cases_sha256": sha256(case_path),
        "scenarios_sha256": sha256(scenario_path),
        "rubric_path": "dataset/evaluation/rubric.md",
        "annotation_review_status": "human_review_pending_before_acceptance",
        "baseline_and_target": "Runtime baseline observations are reported separately from the P0/P1 target contract; unsupported target capabilities are not scored as baseline passes.",
    }
    (EVAL / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    build_table_docx()
    build_snapshots(refresh="--refresh-snapshots" in sys.argv[1:])
    build_scenarios()
    build_cases()
    build_manifest()

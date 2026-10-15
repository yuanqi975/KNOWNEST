from __future__ import annotations

import ast
import asyncio
import json
import math
import time
import operator
from typing import Any, AsyncIterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import ChatMessage, Citation, Document, DocumentChunk, McpCallAudit, MessageExecution
from app.services.retrieval import hybrid_search
from app.services.vector_store import VectorStore

MAX_AGENT_STEPS = 4
MAX_TOOL_CALLS_PER_STEP = 3
TOOL_TIMEOUT_SECONDS = 12
AGENT_RUN_TIMEOUT_SECONDS = 80
AGENT_PROVIDER_TIMEOUT_SECONDS = 60
MAX_TOOL_RESULT_CHARS = 20_000
CANCELLED_SESSIONS: set[str] = set()


async def _provider_stream(provider, messages, tools, timeout_seconds: float):
    """Stream one model round with a hard upper bound."""
    try:
        async with asyncio.timeout(max(0.1, timeout_seconds)):
            async for event in provider.stream(messages, tools):
                yield event
    except asyncio.TimeoutError:
        yield {"type": "provider_timeout"}


def request_cancel(session_id: str) -> None:
    CANCELLED_SESSIONS.add(session_id)


def safe_calculate(expression: str) -> float:
    if not isinstance(expression, str) or len(expression) > 256:
        raise ValueError("expression must be a string of at most 256 characters")

    allowed = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    def visit(node: ast.AST, depth: int = 0) -> float:
        if depth > 24:
            raise ValueError("expression is too complex")
        if isinstance(node, ast.Expression):
            return visit(node.body, depth + 1)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed:
            return float(allowed[type(node.op)](visit(node.operand, depth + 1)))
        if isinstance(node, ast.BinOp) and type(node.op) in allowed:
            left = visit(node.left, depth + 1)
            right = visit(node.right, depth + 1)
            if abs(left) > 1e12 or abs(right) > 1e8:
                raise ValueError("number out of range")
            if isinstance(node.op, ast.Pow) and abs(right) > 8:
                raise ValueError("exponent out of range")
            result = float(allowed[type(node.op)](left, right))
            if not math.isfinite(result) or abs(result) > 1e100:
                raise ValueError("result out of range")
            return result
        raise ValueError("unsupported expression")

    try:
        return visit(ast.parse(expression, mode="eval"))
    except (SyntaxError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError("invalid arithmetic expression") from exc


def built_in_schemas() -> list[dict[str, Any]]:
    return [
        {"type": "function", "function": {"name": "search_knowledge_base", "description": "Search the selected knowledge base and return source passages.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer", "minimum": 1, "maximum": 12}}, "required": ["query"], "additionalProperties": False}}},
        {"type": "function", "function": {"name": "read_document", "description": "Read indexed passages from a document in the selected knowledge base.", "parameters": {"type": "object", "properties": {"document_id": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, "required": ["document_id"], "additionalProperties": False}}},
        {"type": "function", "function": {"name": "calculator", "description": "Calculate a safe arithmetic expression.", "parameters": {"type": "object", "properties": {"expression": {"type": "string", "maxLength": 256}}, "required": ["expression"], "additionalProperties": False}}},
    ]


async def run_builtin(
    db: Session,
    vector_store: VectorStore,
    name: str,
    args: dict[str, Any],
    workspace_id: str,
    kb_id: str | None,
    mcp_servers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if name == "calculator":
        expression = args.get("expression")
        if not isinstance(expression, str):
            return {"error": "expression must be a string"}
        return {"result": safe_calculate(expression)}

    if name == "search_knowledge_base":
        if not kb_id:
            return {"error": "No knowledge base selected"}
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return {"error": "query must be a non-empty string"}
        top_k = max(1, min(int(args.get("top_k", 10)), 12))
        hits = await hybrid_search(db, vector_store, workspace_id, kb_id, query, top_k)
        return {"results": [{"chunk_id": item["chunk"].id, "document_id": item["chunk"].document_id, "filename": (db.get(Document, item["chunk"].document_id).filename if db.get(Document, item["chunk"].document_id) else "Unknown document"), "content": item["chunk"].content, "context_content": (item.get("context_chunk") or item["chunk"]).content, "rerank_score": item.get("rerank_score"), "rank": item["rank"], "retrieval_degraded": item.get("retrieval_degraded", False), "page_number": item["chunk"].page_number, "char_start": item["chunk"].char_start, "char_end": item["chunk"].char_end} for item in hits]}

    if name == "read_document":
        document_id = args.get("document_id")
        document = db.scalar(select(Document).where(Document.id == document_id, Document.workspace_id == workspace_id, Document.knowledge_base_id == kb_id))
        if not document:
            return {"error": "Document not found in the selected knowledge base"}
        limit = max(1, min(int(args.get("limit", 5)), 10))
        chunks = list(db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id).order_by(DocumentChunk.sequence).limit(limit)))
        return {"document_id": document.id, "filename": document.filename, "chunks": [{"chunk_id": chunk.id, "sequence": chunk.sequence, "content": chunk.content, "page_number": chunk.page_number, "char_start": chunk.char_start, "char_end": chunk.char_end} for chunk in chunks]}

    if mcp_servers and name in mcp_servers:
        from app.services.mcp import get_mcp_manager
        entry = mcp_servers[name]
        server, remote_name = entry[:2]
        tool = entry[2] if len(entry) > 2 else None
        schema = getattr(tool, "input_schema", None) if tool else None
        return await asyncio.wait_for(get_mcp_manager().call(server, remote_name, args, schema), timeout=min(server.timeout_seconds, TOOL_TIMEOUT_SECONDS))

    return {"error": f"Unknown tool: {name}"}


def _tool_result_content(result: dict[str, Any]) -> str:
    content = json.dumps(result, ensure_ascii=False, default=str)
    if len(content) > MAX_TOOL_RESULT_CHARS:
        return content[:MAX_TOOL_RESULT_CHARS] + "… [truncated]"
    return content


async def agent_events(
    db: Session,
    vector_store: VectorStore,
    provider,
    messages: list[dict[str, Any]],
    workspace_id: str,
    kb_id: str | None,
    mcp_tools: list[dict[str, Any]] | None = None,
    mcp_servers: dict[str, Any] | None = None,
    session_id: str | None = None,
    initial_hits: list[dict[str, Any]] | None = None,
    message_mode: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run a bounded ReAct tool loop and emit only observable actions/results.

    Raw model reasoning is never streamed. Each provider round either returns
    an answer or typed tool calls; tool outputs are added to the next request.
    """
    builtins = built_in_schemas()
    if initial_hits:
        # The route has already retrieved the relevant document passages.
        # Do not encourage an avoidable search -> second model-round loop.
        builtins = [tool for tool in builtins if tool["function"]["name"] not in {"search_knowledge_base", "read_document"}]
    tools = (builtins + (mcp_tools or [])) if getattr(provider.choice, "supports_tools", True) else []
    working = list(messages)
    last_answer = ""
    collected_citations: list[dict[str, Any]] = []
    cited_chunk_ids: set[str] = set()
    deadline = asyncio.get_running_loop().time() + AGENT_RUN_TIMEOUT_SECONDS

    try:
        yield {"type": "agent_start", "max_steps": MAX_AGENT_STEPS, "max_tool_calls_per_step": MAX_TOOL_CALLS_PER_STEP}
        # Always expose the current document scope before asking the model to
        # plan. This keeps Agent mode grounded even when the provider does not
        # emit a search tool call (or has tools disabled).
        if initial_hits:
            initial_results = []
            for item in initial_hits:
                chunk = item["chunk"]
                document = db.get(Document, chunk.document_id)
                initial_results.append({
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "filename": document.filename if document else "Unknown document",
                    "content": chunk.content,
                    "context_content": (item.get("context_chunk") or chunk).content,
                    "rerank_score": item.get("rerank_score"),
                    "rank": item.get("rank"),
                    "retrieval_degraded": item.get("retrieval_degraded", False),
                    "page_number": chunk.page_number,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                })
            yield {"type": "retrieval_result", "results": initial_results, "diagnostics": initial_hits[0].get("retrieval_meta", {}), "step": 0}
            for index, source in enumerate(initial_results, start=1):
                citation = {
                    "citation_index": index,
                    "document_id": source["document_id"],
                    "filename": source["filename"],
                    "chunk_id": source["chunk_id"],
                    "page_number": source["page_number"],
                    "char_start": source["char_start"],
                    "char_end": source["char_end"],
                    "quoted_text": source["content"][:500],
                    "quote_truncated": len(source["content"]) > 500,
                    "rerank_score": source.get("rerank_score"),
                    "rank": source.get("rank"),
                    "retrieval_degraded": source.get("retrieval_degraded", False),
                }
                collected_citations.append({key: citation[key] for key in ("citation_index", "document_id", "chunk_id", "page_number", "char_start", "char_end", "quoted_text")} | {"retrieval_rank": citation["rank"]})
                cited_chunk_ids.add(source["chunk_id"])
                yield {"type": "citation", **citation, "step": 0}
        for step in range(1, MAX_AGENT_STEPS + 1):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                yield {"type": "agent_error", "code": "timeout", "message": f"Agent run timed out after {AGENT_RUN_TIMEOUT_SECONDS} seconds", "steps": step - 1}
                return
            if session_id and session_id in CANCELLED_SESSIONS:
                CANCELLED_SESSIONS.discard(session_id)
                yield {"type": "agent_error", "code": "cancelled", "message": "Agent run cancelled", "steps": step - 1}
                return
            yield {"type": "planning_status", "step": step, "content": "Selecting the next verifiable action"}
            calls: list[dict[str, Any]] = []
            answer = ""
            provider_timed_out = False
            async for event in _provider_stream(provider, working, tools, min(AGENT_PROVIDER_TIMEOUT_SECONDS, remaining)):
                if event.get("type") == "provider_timeout":
                    provider_timed_out = True
                    break
                if event.get("type") == "token":
                    answer += event.get("content", "")
                    yield event
                elif event.get("type") == "tool_call":
                    calls.append(event.get("tool_call") or {})

            if provider_timed_out:
                yield {"type": "agent_error", "code": "timeout", "message": "Model response timed out", "steps": step}
                return

            last_answer = answer or last_answer
            if not calls:
                if session_id:
                    message = ChatMessage(session_id=session_id, role="assistant", content=answer, provider=provider.choice.provider)
                    db.add(message)
                    db.flush()
                    if message_mode:
                        db.add(MessageExecution(message_id=message.id, mode=message_mode))
                    for citation in collected_citations:
                        if citation.get("document_id") and citation.get("chunk_id"):
                            db.add(Citation(message_id=message.id, **citation))
                    db.commit()
                yield {"type": "agent_complete", "content": answer, "steps": step}
                return

            working.append({"role": "assistant", "content": answer or None, "tool_calls": calls})
            for call_index, call in enumerate(calls):
                if session_id and session_id in CANCELLED_SESSIONS:
                    CANCELLED_SESSIONS.discard(session_id)
                    yield {"type": "agent_error", "code": "cancelled", "message": "Agent run cancelled", "steps": step}
                    return
                call_id = call.get("id") or f"step-{step}-call-{call_index}"
                function = call.get("function") or {}
                name = function.get("name") or "unknown"
                try:
                    args = json.loads(function.get("arguments") or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("tool arguments must be a JSON object")
                except (json.JSONDecodeError, ValueError) as exc:
                    result = {"error": f"Invalid tool arguments: {exc}"}
                    args = {}
                    yield {"type": "tool_call_start", "name": name, "arguments": args, "step": step}
                else:
                    yield {"type": "tool_call_start", "name": name, "arguments": args, "step": step}
                    if call_index >= MAX_TOOL_CALLS_PER_STEP:
                        result = {"error": f"At most {MAX_TOOL_CALLS_PER_STEP} tool calls may run in one step"}
                    else:
                        started_at = time.perf_counter()
                        try:
                            remaining = deadline - asyncio.get_running_loop().time()
                            result = await asyncio.wait_for(
                                run_builtin(db, vector_store, name, args, workspace_id, kb_id, mcp_servers),
                                timeout=max(0.1, min(TOOL_TIMEOUT_SECONDS, remaining)),
                            )
                        except asyncio.TimeoutError:
                            result = {"error": f"Tool timed out after {TOOL_TIMEOUT_SECONDS} seconds"}
                        except Exception as exc:  # A tool error should not discard the agent turn.
                            result = {"error": str(exc)[:1000]}

                        if name.startswith("mcp_") and db is not None and mcp_servers and name in mcp_servers:
                            server = mcp_servers[name][0]
                            db.add(McpCallAudit(
                                workspace_id=workspace_id,
                                server_id=server.id,
                                tool_name=mcp_servers[name][1],
                                success=not (isinstance(result, dict) and result.get("error")),
                                duration_ms=int((time.perf_counter() - started_at) * 1000),
                                error=(result.get("error") if isinstance(result, dict) else None),
                            ))
                            db.commit()

                content = _tool_result_content(result)
                yield {"type": "tool_call_result", "name": name, "result": result, "step": step}
                if name == "search_knowledge_base":
                    results = result.get("results", []) if isinstance(result, dict) else []
                    yield {"type": "retrieval_result", "results": results, "step": step}
                    for source in results:
                        chunk_id = source.get("chunk_id")
                        if not chunk_id or chunk_id in cited_chunk_ids:
                            continue
                        citation = {
                            "citation_index": len(collected_citations) + 1,
                            "document_id": source.get("document_id"),
                            "filename": source.get("filename", "Unknown document"),
                            "chunk_id": chunk_id,
                            "page_number": source.get("page_number"),
                            "char_start": source.get("char_start"),
                            "char_end": source.get("char_end"),
                            "quoted_text": source.get("content", "")[:500],
                            "quote_truncated": len(source.get("content", "")) > 500,
                            "rank": source.get("rank"),
                        }
                        collected_citations.append({key: citation[key] for key in ("citation_index", "document_id", "chunk_id", "page_number", "char_start", "char_end", "quoted_text")} | {"retrieval_rank": citation["rank"]})
                        cited_chunk_ids.add(chunk_id)
                        yield {
                            "type": "citation",
                            **citation,
                            "rerank_score": source.get("rerank_score"),
                            "rank": source.get("rank"),
                            "retrieval_degraded": source.get("retrieval_degraded", False),
                            "step": step,
                        }
                elif name == "read_document":
                    yield {"type": "document_read_result", "document_id": result.get("document_id"), "chunks": result.get("chunks", []), "step": step}
                elif name.startswith("mcp_"):
                    yield {"type": "mcp_tool_call", "name": name, "arguments": args, "step": step}
                    yield {"type": "mcp_tool_result", "name": name, "result": result, "step": step}
                yield {"type": "evidence_trace", "kind": "tool", "name": name, "result": result, "step": step}
                working.append({"role": "tool", "tool_call_id": call_id, "content": content})

        final = "Agent reached the maximum number of reasoning steps."
        if last_answer:
            final = f"{last_answer}\n\n{final}"
        if session_id:
            message = ChatMessage(session_id=session_id, role="assistant", content=final, provider=provider.choice.provider)
            db.add(message)
            db.flush()
            if message_mode:
                db.add(MessageExecution(message_id=message.id, mode=message_mode))
            for citation in collected_citations:
                if citation.get("document_id") and citation.get("chunk_id"):
                    db.add(Citation(message_id=message.id, **citation))
            db.commit()
        yield {"type": "agent_complete", "content": final, "steps": MAX_AGENT_STEPS, "step_limit_reached": True}
    except Exception as exc:
        db.rollback()
        yield {"type": "agent_error", "message": str(exc)[:1000]}

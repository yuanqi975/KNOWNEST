from __future__ import annotations
import asyncio
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator
import httpx
from app.core.config import get_settings


@dataclass
class ModelChoice:
    provider: str
    base_url: str
    api_key: str
    model: str
    supports_tools: bool = True
    context_window_tokens: int = 32768
    max_output_tokens: int = 4096


def configured_choice(provider: str, model: str | None = None) -> ModelChoice:
    s = get_settings()
    if provider == "deepseek":
        return ModelChoice("deepseek", s.deepseek_base_url, s.deepseek_api_key, model or s.deepseek_model)
    return ModelChoice("openai", s.openai_base_url, s.openai_api_key, model or s.openai_model)


class ChatProvider:
    def __init__(self, choice: ModelChoice):
        self.choice = choice

    async def stream(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> AsyncIterator[dict[str, Any]]:
        # A development fallback keeps the full API runnable without credentials.
        if not self.choice.api_key:
            answer = "开发模式：未配置模型 API Key。请配置 OpenAI 或 DeepSeek 后重试。"
            # Keep the offline path visibly stream-like as well. The browser
            # still owns the typewriter pacing because real gateways may
            # coalesce several SSE frames into one network chunk.
            for start in range(0, len(answer), 4):
                await asyncio.sleep(0.015)
                yield {"type": "token", "content": answer[start:start + 4]}
            yield {"type": "complete", "content": answer}
            return
        headers = {"Authorization": f"Bearer {self.choice.api_key}", "Content-Type": "application/json"}
        body: dict[str, Any] = {"model": self.choice.model, "messages": messages, "stream": True,
                                "max_tokens": self.choice.max_output_tokens}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", self.choice.base_url.rstrip("/") + "/chat/completions", headers=headers, json=body) as response:
                response.raise_for_status()
                tool_calls: dict[int, dict[str, Any]] = {}
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    value = line[5:].strip()
                    if value == "[DONE]":
                        break
                    try:
                        event = json.loads(value)
                    except json.JSONDecodeError:
                        continue
                    choice = (event.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        yield {"type": "token", "content": delta["content"]}
                    for call in delta.get("tool_calls") or []:
                        index = call.get("index", 0)
                        item = tool_calls.setdefault(index, {"id": call.get("id", ""), "type": "function", "function": {"name": "", "arguments": ""}})
                        item["id"] = item["id"] or call.get("id", "")
                        function = call.get("function") or {}
                        item["function"]["name"] += function.get("name", "")
                        item["function"]["arguments"] += function.get("arguments", "")
                for call in tool_calls.values():
                    yield {"type": "tool_call", "tool_call": call}
                yield {"type": "complete"}


class EmbeddingProvider:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        s = get_settings()
        if not s.siliconflow_api_key:
            # Deterministic local fallback used only for tests/development.
            return [self._fallback(text, s.embedding_dimension) for text in texts]
        headers = {"Authorization": f"Bearer {s.siliconflow_api_key}", "Content-Type": "application/json"}
        body = {"model": s.embedding_model, "input": texts}
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(s.siliconflow_base_url.rstrip("/") + "/embeddings", headers=headers, json=body)
            response.raise_for_status()
            data = response.json().get("data", [])
        vectors = [item["embedding"] for item in sorted(data, key=lambda x: x.get("index", 0))]
        if any(len(vector) != s.embedding_dimension for vector in vectors):
            raise ValueError(f"embedding dimension must be {s.embedding_dimension}")
        return vectors

    @staticmethod
    def _fallback(text: str, dimension: int) -> list[float]:
        # Stable, dependency-free vector for offline smoke tests, not production quality.
        import hashlib, math
        vector = [0.0] * dimension
        for index in range(0, len(text), 4):
            digest = hashlib.sha256(text[index:index + 4].encode()).digest()
            slot = int.from_bytes(digest[:4], "big") % dimension
            vector[slot] += (digest[4] / 255.0) * 2 - 1
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class RerankProvider:
    """Score query/document pairs through an OpenAI-compatible rerank API.

    SiliconFlow, Jina and several self-hosted gateways expose the same basic
    ``POST /rerank`` contract.  The response parser accepts both the common
    ``results`` and ``data`` envelopes so switching providers does not require
    changing retrieval code.
    """

    async def rerank(self, query: str, documents: list[str], top_n: int | None = None) -> list[tuple[int, float]]:
        s = get_settings()
        if not documents:
            return []
        # Reuse the SiliconFlow credential by default, while allowing a
        # separate key for providers hosted at another rerank endpoint.
        api_key = s.rerank_api_key or s.siliconflow_api_key
        if not s.rerank_enabled or not api_key:
            return []

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body: dict[str, Any] = {"model": s.rerank_model, "query": query, "documents": documents}
        if top_n is not None:
            body["top_n"] = top_n
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(s.rerank_base_url.rstrip("/") + "/rerank", headers=headers, json=body)
            response.raise_for_status()
            payload = response.json()

        raw_results = payload.get("results") or payload.get("data") or []
        scored: list[tuple[int, float]] = []
        for position, item in enumerate(raw_results):
            if not isinstance(item, dict):
                continue
            index = item.get("index", position)
            score = item.get("relevance_score", item.get("score"))
            try:
                scored.append((int(index), float(score)))
            except (TypeError, ValueError):
                continue
        return scored

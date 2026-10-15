from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import re
import socket
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from jsonschema import ValidationError, validate

from app.core.config import get_settings
from app.core.secrets import decrypt


class McpProtocolError(RuntimeError):
    """A protocol/transport error safe to expose as a tool error."""


def model_tool_name(server_name: str, tool_name: str) -> str:
    clean = lambda value: re.sub(r"[^A-Za-z0-9_-]", "_", value).strip("_") or "server"
    return f"mcp_{clean(server_name)}_{clean(tool_name)}"[:96]


def validate_endpoint(endpoint: str, *, allow_private: bool | None = None, resolve_dns: bool = False) -> None:
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ValueError("MCP endpoint is required for HTTP transports")
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("MCP endpoint must be an http(s) URL")
    settings = get_settings()
    if allow_private is None:
        allow_private = settings.mcp_allow_private_hosts
    if allow_private:
        return
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"}:
        raise ValueError("MCP endpoint points to a local host")
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        if not resolve_dns:
            return
        try:
            addresses = {ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)}
        except OSError as exc:
            raise ValueError("MCP endpoint host could not be resolved") from exc
    if any(address.is_private or address.is_loopback or address.is_link_local or address.is_reserved for address in addresses):
        raise ValueError("MCP endpoint resolves to a private or local address")


@dataclass
class _Connection:
    key: str
    stack: AsyncExitStack
    session: Any
    lock: asyncio.Lock


class McpClientManager:
    """Persistent MCP sessions using the official SDK transports."""

    def __init__(self):
        self.connections: dict[str, _Connection] = {}
        self._manager_lock = asyncio.Lock()

    @staticmethod
    def _config_key(server) -> str:
        value = "|".join(str(item) for item in (server.id, server.transport, server.endpoint, server.command, server.args_json, server.auth_type, server.auth_secret_encrypted))
        return hashlib.sha256(value.encode()).hexdigest()

    async def connect(self, server) -> Any:
        if not server.enabled:
            raise McpProtocolError("MCP server is disabled")
        key = self._config_key(server)
        async with self._manager_lock:
            existing = self.connections.get(server.id)
            if existing and existing.key == key:
                return existing.session
            if existing:
                await self._close(server.id)
            connection = await self._open(server, key)
            self.connections[server.id] = connection
            return connection.session

    async def _open(self, server, key: str) -> _Connection:
        stack = AsyncExitStack()
        try:
            if server.transport == "streamable_http":
                try:
                    from mcp.client.streamable_http import streamablehttp_client
                except ImportError:  # mcp 1.2 used the underscored name
                    from mcp.client.streamable_http import streamable_http_client as streamablehttp_client
                validate_endpoint(server.endpoint, resolve_dns=True)
                streams = await stack.enter_async_context(streamablehttp_client(server.endpoint, headers=self._headers(server), timeout=server.timeout_seconds))
            elif server.transport == "sse":
                from mcp.client.sse import sse_client
                validate_endpoint(server.endpoint, resolve_dns=True)
                streams = await stack.enter_async_context(sse_client(server.endpoint, headers=self._headers(server), timeout=server.timeout_seconds, sse_read_timeout=server.timeout_seconds))
            elif server.transport == "stdio":
                if not get_settings().mcp_allow_stdio:
                    raise McpProtocolError("stdio MCP transport is disabled by server policy")
                if not server.command:
                    raise McpProtocolError("stdio MCP server command is missing")
                from mcp.client.stdio import StdioServerParameters, stdio_client
                streams = await stack.enter_async_context(stdio_client(StdioServerParameters(command=server.command, args=server.args_json or [])))
            else:
                raise McpProtocolError(f"Unsupported MCP transport: {server.transport}")
            from mcp import ClientSession
            session = await stack.enter_async_context(ClientSession(*streams[:2]))
            await session.initialize()
            return _Connection(key=key, stack=stack, session=session, lock=asyncio.Lock())
        except Exception:
            await stack.aclose()
            raise

    async def _close(self, server_id: str) -> None:
        connection = self.connections.pop(server_id, None)
        if connection:
            await connection.stack.aclose()

    async def disconnect(self, server_id: str) -> None:
        async with self._manager_lock:
            await self._close(server_id)

    async def close_all(self) -> None:
        async with self._manager_lock:
            for server_id in list(self.connections):
                await self._close(server_id)

    async def discover(self, server) -> list[dict[str, Any]]:
        session = await self.connect(server)
        connection = self.connections[server.id]
        tools: list[dict[str, Any]] = []
        cursor = None
        try:
            async with connection.lock:
                while True:
                    result = await asyncio.wait_for(session.list_tools(cursor=cursor), timeout=server.timeout_seconds)
                    for tool in result.tools:
                        tools.append(tool.model_dump(by_alias=True, mode="json") if hasattr(tool, "model_dump") else dict(tool))
                    cursor = getattr(result, "nextCursor", None)
                    if not cursor:
                        break
        except Exception:
            await self.disconnect(server.id)
            raise
        return tools

    async def call(self, server, tool_name: str, arguments: dict[str, Any], input_schema: dict[str, Any] | None = None) -> dict[str, Any]:
        if input_schema:
            try:
                validate(arguments, input_schema)
            except ValidationError as exc:
                return {"error": f"Invalid MCP tool arguments: {exc.message}"}
        session = await self.connect(server)
        connection = self.connections[server.id]
        try:
            async with connection.lock:
                result = await asyncio.wait_for(session.call_tool(tool_name, arguments), timeout=server.timeout_seconds)
        except Exception:
            # A broken stream must not poison all later calls; the next call
            # will create a fresh initialized session.
            await self.disconnect(server.id)
            raise
        payload = result.model_dump(by_alias=True, mode="json") if hasattr(result, "model_dump") else dict(result)
        if payload.get("isError"):
            return {"error": "MCP tool returned an error", "content": payload.get("content", []), "structuredContent": payload.get("structuredContent")}
        response = {"content": payload.get("content", [])}
        if payload.get("structuredContent") is not None:
            response["structuredContent"] = payload["structuredContent"]
        return response

    @staticmethod
    def _headers(server) -> dict[str, str]:
        # The encrypted secret is decrypted by the API boundary before a real
        # call in production; do not log this header.
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if server.auth_type == "bearer" and server.auth_secret_encrypted:
            headers["Authorization"] = f"Bearer {decrypt(server.auth_secret_encrypted)}"
        elif server.auth_type == "api_key" and server.auth_secret_encrypted:
            headers["X-API-Key"] = decrypt(server.auth_secret_encrypted)
        return headers


_default_manager = McpClientManager()


def get_mcp_manager() -> McpClientManager:
    return _default_manager

from types import SimpleNamespace
import asyncio

import pytest

from app.services.mcp import McpClientManager, model_tool_name, validate_endpoint


def test_mcp_endpoint_policy_and_tool_names():
    validate_endpoint("https://mcp.example.com/mcp")
    with pytest.raises(ValueError):
        validate_endpoint("http://127.0.0.1:8000/mcp")
    validate_endpoint("http://127.0.0.1:8000/mcp", allow_private=True)
    assert model_tool_name("GitHub MCP", "search/issues") == "mcp_GitHub_MCP_search_issues"


def test_mcp_manager_discovers_pages_and_validates_arguments(monkeypatch):
    async def run():
        manager = McpClientManager()

        class FakeSession:
            def __init__(self):
                self.calls = 0

            async def list_tools(self, cursor=None):
                self.calls += 1
                tool = SimpleNamespace(model_dump=lambda **_: {"name": f"tool-{self.calls}", "inputSchema": {"type": "object"}})
                return SimpleNamespace(tools=[tool], nextCursor="next" if self.calls == 1 else None)

            async def call_tool(self, _name, _arguments):
                return SimpleNamespace(model_dump=lambda **_: {"content": [{"type": "text", "text": "ok"}], "isError": False})

        session = FakeSession()
        async def fake_connect(_server):
            manager.connections[_server.id] = SimpleNamespace(session=session, lock=asyncio.Lock())
            return session

        monkeypatch.setattr(manager, "connect", fake_connect)
        server = SimpleNamespace(id="s1", enabled=True, timeout_seconds=2)
        assert len(await manager.discover(server)) == 2
        result = await manager.call(server, "tool-1", {"value": 1}, {"type": "object", "required": ["name"]})
        assert result["error"].startswith("Invalid MCP tool arguments")

    asyncio.run(run())

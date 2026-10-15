import asyncio
from types import SimpleNamespace

from app.services.agent import agent_events, safe_calculate
from app.services.vector_store import VectorStore


class FakeProvider:
    class Choice:
        provider = "fake"

    choice = Choice()

    def __init__(self):
        self.round = 0

    async def stream(self, messages, tools):
        self.round += 1
        if self.round == 1:
            yield {
                "type": "tool_call",
                "tool_call": {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "calculator", "arguments": '{"expression":"2 + 3 * 4"}'},
                },
            }
        else:
            yield {"type": "token", "content": "The result is 14."}
            yield {"type": "complete"}


def test_agent_runs_tool_then_final_answer():
    async def run():
        events = [
            event
            async for event in agent_events(
                db=None,
                vector_store=VectorStore(),
                provider=FakeProvider(),
                messages=[{"role": "user", "content": "Calculate 2 + 3 * 4"}],
                workspace_id="workspace",
                kb_id=None,
            )
        ]
        return events

    events = asyncio.run(run())
    types = [event["type"] for event in events]
    assert types[0] == "agent_start"
    assert "tool_call_start" in types
    assert "tool_call_result" in types
    assert types[-1] == "agent_complete"
    assert events[-1]["content"] == "The result is 14."


def test_calculator_rejects_calls_and_limits_exponents():
    assert safe_calculate("2 + 3 * 4") == 14
    for expression in ("__import__('os').system('whoami')", "2 ** 99"):
        try:
            safe_calculate(expression)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe expression accepted")


def test_agent_starts_with_retrieved_evidence_without_repeating_knowledge_search():
    chunk = SimpleNamespace(
        id="chunk-1",
        document_id="document-1",
        content="The retention policy is seven years.",
        page_number=2,
        char_start=0,
        char_end=37,
    )

    class FakeDb:
        def get(self, _model, _id):
            return SimpleNamespace(filename="handbook.md")

    class DirectAnswerProvider:
        choice = SimpleNamespace(provider="fake")

        async def stream(self, _messages, tools):
            names = {tool["function"]["name"] for tool in tools}
            assert "search_knowledge_base" not in names
            assert "read_document" not in names
            yield {"type": "token", "content": "The retention policy is seven years."}
            yield {"type": "complete"}

    async def run():
        return [
            event
            async for event in agent_events(
                db=FakeDb(),
                vector_store=VectorStore(),
                provider=DirectAnswerProvider(),
                messages=[{"role": "user", "content": "How long is the retention policy?"}],
                workspace_id="workspace",
                kb_id="kb",
                initial_hits=[{"chunk": chunk, "score": 0.91}],
            )
        ]

    events = asyncio.run(run())
    citation = next(event for event in events if event["type"] == "citation")
    assert citation["chunk_id"] == "chunk-1"
    assert citation["filename"] == "handbook.md"
    assert events[-1]["type"] == "agent_complete"

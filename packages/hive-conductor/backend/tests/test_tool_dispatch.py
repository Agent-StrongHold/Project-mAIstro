"""The ``(tool_name, tool_args)`` dispatcher handed to maistro's factory
(#840 Slice 5): real tools are routed, unknown names refuse with the same
string react.py's un-guarded branch produces, and unusable arguments come
back as an error result the strategy can read -- never a fabricated
execution.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import services.tool_executor as tool_executor  # noqa: E402


async def test_an_unknown_tool_refuses_with_the_react_contract() -> None:
    assert (
        await tool_executor.dispatch_tool("make_coffee", {}) == "Tool 'make_coffee' not available"
    )


async def test_known_tools_route_to_the_real_functions(monkeypatch) -> None:
    calls: list[tuple[str, Any]] = []

    async def fake_web_search(query: str, max_results: int = 5) -> dict[str, Any]:
        calls.append(("web_search", query, max_results))
        return {"query": query}

    async def fake_browse_url(url: str, task: str = "") -> dict[str, Any]:
        calls.append(("browse_url", url, task))
        return {"url": url}

    async def fake_clarify(questions: list[str], context: dict[str, Any]) -> dict[str, Any]:
        calls.append(("clarify", questions, context))
        return {"answers": {}}

    monkeypatch.setattr(tool_executor, "web_search", fake_web_search)
    monkeypatch.setattr(tool_executor, "browse_url", fake_browse_url)
    monkeypatch.setattr(tool_executor, "clarify", fake_clarify)

    assert await tool_executor.dispatch_tool(
        "web_search", {"query": "jira api", "max_results": 2}
    ) == {"query": "jira api"}
    assert await tool_executor.dispatch_tool(
        "browse_url", {"url": "https://example.com", "task": "summarize"}
    ) == {"url": "https://example.com"}
    assert await tool_executor.dispatch_tool(
        "clarify", {"questions": ["which scope?"], "context": {"ws": "ws-1"}}
    ) == {"answers": {}}

    assert calls == [
        ("web_search", "jira api", 2),
        ("browse_url", "https://example.com", "summarize"),
        ("clarify", ["which scope?"], {"ws": "ws-1"}),
    ]


async def test_unusable_arguments_return_an_error_result_not_an_exception() -> None:
    result = await tool_executor.dispatch_tool("web_search", {"max_results": "not-a-number"})
    assert isinstance(result, str)
    assert result.startswith("Error: bad arguments for tool 'web_search'")

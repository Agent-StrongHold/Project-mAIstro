"""The degraded Agent port must never manufacture a successful completion (#840)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from adapters.maistro_core import StubAgentPort
from models.schemas import ChatCompletionRequest


@pytest.mark.asyncio
async def test_stub_agent_port_reports_unavailable() -> None:
    port = StubAgentPort()
    with pytest.raises(RuntimeError, match="Agent runtime is unavailable"):
        await port.route([{"role": "user", "content": "hello"}])


@pytest.mark.asyncio
async def test_conversation_execution_does_not_bypass_stub_runtime(monkeypatch) -> None:
    """A configured product callback cannot masquerade as a canonical turn."""
    import services.chat_execution as chat_execution

    engine = SimpleNamespace(agent_port=SimpleNamespace(container=None))
    monkeypatch.setattr(chat_execution, "get_engine", lambda: engine)
    called = False

    async def dispatch() -> dict:
        nonlocal called
        called = True
        return {"choices": [{"message": {"content": "fake success"}}]}

    request = SimpleNamespace(headers={}, state=SimpleNamespace(user={}))
    req = ChatCompletionRequest(messages=[{"role": "user", "content": "hello"}])
    with pytest.raises(RuntimeError, match="canonical maistro-core chat runtime"):
        await chat_execution.execute_conversation_turn(
            req,
            request,
            list(req.messages),
            dispatch,
        )
    assert called is False

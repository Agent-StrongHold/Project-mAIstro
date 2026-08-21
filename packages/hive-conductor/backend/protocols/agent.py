from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AgentPort(Protocol):
    """Any backend that can route a chat request to an agent and return an OpenAI-compatible response."""

    async def route(
        self,
        messages: list[dict[str, Any]],
        *,
        session_id: str | None = None,
        intent_hint: str = "",
    ) -> dict[str, Any]: ...

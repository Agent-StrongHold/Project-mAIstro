"""Subprocess-free reference HarnessRunner provider (SPEC-208).

A fake in-memory harness for tests and for wiring verification: scripted
responses/events, togglable health, and full call recording. Real providers
(pi, openclaw, claude_code, codex) wrap a sandboxed subprocess instead —
follow-up work; the protocol and safety wrapper are identical.
"""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING, Any

from maistro.capabilities.types import ProviderHealth

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from maistro.types.agent import AgentIdentity


class StubHarnessRunner:
    """In-memory HarnessRunner: echoes messages or replays scripted envelopes."""

    def __init__(
        self,
        *,
        name: str = "stub",
        healthy: bool = True,
        responses: list[dict[str, Any]] | None = None,
        events: list[dict[str, Any]] | None = None,
        crash_on_send: bool = False,
    ) -> None:
        self._name = name
        self.healthy = healthy
        self._responses = list(responses or [])
        self._events = list(events or [])
        self._crash_on_send = crash_on_send
        self._counter = itertools.count(1)
        self.sessions: dict[str, dict[str, Any]] = {}
        self.sent: list[tuple[str, list[dict[str, Any]]]] = []

    # --- CapabilityProvider ---
    @property
    def name(self) -> str:
        return self._name

    @property
    def slot(self) -> str:
        return "harness_runner"

    @property
    def trust_tier(self) -> str:
        return "t0"

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self) -> ProviderHealth:
        if self.healthy:
            return ProviderHealth(healthy=True)
        return ProviderHealth(healthy=False, detail="stub harness marked unhealthy")

    # --- HarnessRunner ---
    async def start_session(self, agent_spec: AgentIdentity, *, workdir: str) -> str:
        session_id = f"{self._name}-session-{next(self._counter)}"
        self.sessions[session_id] = {"agent": agent_spec.name, "workdir": workdir}
        return session_id

    async def send(self, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        if self._crash_on_send:
            raise RuntimeError("stub harness crashed")
        self.sent.append((session_id, messages))
        if self._responses:
            return self._responses.pop(0)
        content = " ".join(str(m.get("content", "")) for m in messages)
        return {"content": f"stub:{content}", "actions": []}

    async def stream(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        for event in self._events:
            yield event
        yield {"type": "done", "session_id": session_id}

    async def stop(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

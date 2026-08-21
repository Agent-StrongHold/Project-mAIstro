"""harness_runner slot: protocol for driving a foreign agent harness (SPEC-208 §1).

A ``HarnessRunner`` adapts a foreign agent harness — Pi, OpenClaw, Claude Code,
Codex, an OpenAI/Claude Agent SDK session — to maistro's capability framework:
maistro drives the harness's own session/turn loop while keeping it inside the
sandbox + Warden + Sentinel safety envelope (see ``providers.harness_safety``).

It is layered on ``CapabilityProvider`` so a harness installs, toggles, and
degrades (``SAFE_NOOP``) exactly like any other slot: an absent, disabled, or
crashed harness resolves to a typed ``Unavailable`` and never breaks the host
run. ``send()`` returns the same response-envelope shape the ``Conduit`` already
normalizes, so a session-backed agent is dispatched identically to a native one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from maistro.agents.spec.agent_spec import AgentSpec
from maistro.capabilities.protocols import CapabilityProvider

SLOT_NAME = "harness_runner"


class HarnessInputBlocked(Exception):
    """Raised when Warden blocks a message before it reaches the foreign harness.

    This is a *security stop*, distinct from the slot's ``SAFE_NOOP`` degradation:
    an unavailable harness yields ``Unavailable``, but a malicious payload aimed at
    a present harness is refused outright rather than silently dropped.
    """

    def __init__(self, flags: tuple[str, ...]) -> None:
        joined = ", ".join(flags) or "unspecified"
        super().__init__(f"harness input blocked by warden: {joined}")
        self.flags = flags


@runtime_checkable
class HarnessRunner(CapabilityProvider, Protocol):
    """Adapter over a foreign agent harness's session/process API."""

    async def start_session(self, agent_spec: AgentSpec, *, workdir: str) -> str:
        """Start (or attach to) a harness session; returns a ``session_id``."""
        ...

    async def send(self, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """One turn: send messages, return the harness's response envelope."""
        ...

    def stream(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        """Stream incremental events (tokens, tool calls, status) for a session."""
        ...

    async def stop(self, session_id: str) -> None:
        """Terminate the underlying process/session."""
        ...

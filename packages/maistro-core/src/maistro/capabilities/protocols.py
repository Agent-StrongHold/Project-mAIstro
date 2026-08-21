"""Capability provider protocol — base metadata + health for any slot implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from maistro.capabilities.types import ProviderHealth

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from maistro.types.agent import AgentIdentity


@runtime_checkable
class CapabilityProvider(Protocol):
    """A swappable implementation that fills a capability slot.

    Concrete providers ALSO implement the slot-specific protocol
    (e.g. InfraMonitor), which adds the slot's domain methods.
    """

    @property
    def name(self) -> str: ...

    @property
    def slot(self) -> str: ...

    @property
    def trust_tier(self) -> str: ...

    def requires(self) -> tuple[str, ...]:
        """Env vars / service ids this provider needs to be usable."""
        ...

    async def healthcheck(self) -> ProviderHealth: ...


@runtime_checkable
class HarnessRunner(CapabilityProvider, Protocol):
    """Adapter over a foreign agent harness's session/process API (SPEC-208).

    Fills the ``harness_runner`` slot (FallbackPolicy.SAFE_NOOP). One provider
    is registered per foreign harness (pi, openclaw, claude_code, codex);
    ``CapabilityRegistry.activate("harness_runner", name)`` selects which one
    an agent binds to.

    Providers must never be called directly by orchestration code — always go
    through ``maistro.capabilities.slots.harness.resolve_harness_runner``,
    which wraps the provider so every inbound message is scanned (Warden) and
    every reported action is policy-checked (Sentinel) regardless of provider.

    ``stream()`` is declared as a plain method returning an ``AsyncIterator``
    so that async-generator implementations conform under mypy --strict.
    """

    async def start_session(self, agent_spec: AgentIdentity, *, workdir: str) -> str:
        """Start (or attach to) a harness session; returns a session_id."""
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

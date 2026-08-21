"""Hierarchical orchestration across foreign harnesses (SPEC-070226-c4f8 / ADR-101).

A parent maistro instance discovers foreign harnesses (Pi, OpenClaw, another
maistro exposing the ``HarnessRunner`` adapter server), exports an agent via
SPEC-208's :func:`maistro.agents.export.export_agent`, sends it to a chosen
harness through an injected :class:`HarnessTransport`, and aggregates results:

- :meth:`HierarchicalOrchestrator.spawn_on_harness` — export + run + collect.
- :meth:`HierarchicalOrchestrator.spawn_wave_across_harnesses` — parallel wave
  (the Repertoire pattern from ``orchestrator/waves/ensemble.py``): gather with
  ``return_exceptions``, pick the best via an injected comparator.
- :meth:`HierarchicalOrchestrator.spawn_with_fallback` — ordered preference
  list; ``HarnessUnavailableError`` moves to the next harness, anything else
  propagates; ``NoAvailableHarnessError`` when every harness is down.

Errors from a foreign harness are *propagated*, never swallowed: a result
envelope carrying an error raises :class:`ForeignHarnessError`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import httpx

from maistro.agents.export import export_agent
from maistro.http import shared_client

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from maistro.agents.export import ExportBundle
    from maistro.types.agent import AgentIdentity
    from maistro.types.skill import SkillDefinition


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class HierarchyError(Exception):
    """Base error for hierarchical orchestration."""


class HarnessUnavailableError(HierarchyError):
    """The harness is unknown, unreachable, or refusing sessions."""


class ForeignHarnessError(HierarchyError):
    """The foreign harness ran the task and reported an error (propagated)."""


class AllHarnessesFailedError(HierarchyError):
    """Every harness in a wave failed; carries the per-harness failures."""

    def __init__(self, failures: list[BaseException]) -> None:
        self.failures = failures
        detail = "; ".join(f"{type(f).__name__}: {f}" for f in failures)
        super().__init__(f"all {len(failures)} harness spawns failed: {detail}")


class NoAvailableHarnessError(HierarchyError):
    """Fallback exhausted: no harness in the preference list was available."""

    def __init__(self, harness_ids: list[str]) -> None:
        self.harness_ids = list(harness_ids)
        super().__init__(f"no available harness among {self.harness_ids}")


# --------------------------------------------------------------------------
# Types
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HarnessAdvertisement:
    """A foreign harness's capability advertisement."""

    harness_id: str  # "pi-0", "openclaw-1"
    endpoint: str  # "https://pi.local:8000"
    capabilities: tuple[str, ...] = ()  # ("agent:run", "skill:import")
    agent_roster: tuple[str, ...] = ()  # agent names already on this harness
    cost_multiplier: float = 1.0  # relative cost vs. local
    latency_multiplier: float = 1.0


@dataclass
class HarnessTask:
    """The task shipped to a foreign harness."""

    id: str
    description: str
    context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "context": dict(self.context),
            "metadata": dict(self.metadata),
        }


@dataclass
class HarnessTaskResult:
    """Result envelope returned by a foreign harness."""

    harness_id: str
    task_id: str
    output: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def quality_score(self) -> float:
        return float(self.metadata.get("quality_score", 0.0))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> HarnessTaskResult:
        return cls(
            harness_id=str(payload.get("harness_id", "")),
            task_id=str(payload.get("task_id", "")),
            output=payload.get("output"),
            metadata=dict(payload.get("metadata", {})),
            error=payload.get("error"),
        )


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


@runtime_checkable
class HarnessRegistry(Protocol):
    """Discovery surface for connected foreign harnesses."""

    async def list_harnesses(self) -> list[HarnessAdvertisement]:
        """Discover all connected foreign harnesses."""
        ...

    async def get_harness(self, harness_id: str) -> HarnessAdvertisement:
        """Look up one harness; raises HarnessUnavailableError if unknown."""
        ...


class InMemoryHarnessRegistry:
    """Reference HarnessRegistry (tests/dev; a live one would poll peers)."""

    def __init__(self, harnesses: list[HarnessAdvertisement] | None = None) -> None:
        self._harnesses: dict[str, HarnessAdvertisement] = {
            h.harness_id: h for h in harnesses or []
        }

    def register(self, advertisement: HarnessAdvertisement) -> None:
        self._harnesses[advertisement.harness_id] = advertisement

    def unregister(self, harness_id: str) -> None:
        self._harnesses.pop(harness_id, None)

    async def list_harnesses(self) -> list[HarnessAdvertisement]:
        return list(self._harnesses.values())

    async def get_harness(self, harness_id: str) -> HarnessAdvertisement:
        try:
            return self._harnesses[harness_id]
        except KeyError:
            raise HarnessUnavailableError(f"unknown harness: {harness_id!r}") from None


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------


@runtime_checkable
class HarnessTransport(Protocol):
    """Ships an exported agent + task to a harness and returns its result.

    Implementations raise :class:`HarnessUnavailableError` when the harness
    cannot be reached, and return the harness's result envelope otherwise
    (foreign errors travel in ``HarnessTaskResult.error``).
    """

    async def spawn(
        self,
        harness: HarnessAdvertisement,
        bundle: ExportBundle,
        task: HarnessTask,
    ) -> HarnessTaskResult: ...


class LoopbackHarnessTransport:
    """In-memory transport: per-harness async handlers (tests/dev).

    A harness with no handler is treated as unreachable
    (:class:`HarnessUnavailableError`), mirroring a connection failure.
    """

    def __init__(
        self,
        handlers: dict[str, Callable[[ExportBundle, HarnessTask], Awaitable[HarnessTaskResult]]]
        | None = None,
    ) -> None:
        self._handlers = dict(handlers or {})

    def connect(
        self,
        harness_id: str,
        handler: Callable[[ExportBundle, HarnessTask], Awaitable[HarnessTaskResult]],
    ) -> None:
        self._handlers[harness_id] = handler

    def disconnect(self, harness_id: str) -> None:
        self._handlers.pop(harness_id, None)

    async def spawn(
        self,
        harness: HarnessAdvertisement,
        bundle: ExportBundle,
        task: HarnessTask,
    ) -> HarnessTaskResult:
        handler = self._handlers.get(harness.harness_id)
        if handler is None:
            raise HarnessUnavailableError(f"harness {harness.harness_id!r} is not connected")
        return await handler(bundle, task)


class HTTPHarnessTransport:
    """HTTP transport: POST the export bundle + task to the harness endpoint.

    ``POST {endpoint}/v1/harness/sessions`` with the SPEC-208 export bundle
    (MCP manifest + SKILL.md) and the task dict; bearer-authenticated with
    ``harness_token``. Connection/transport failures and 502/503/504 map to
    :class:`HarnessUnavailableError`; any other non-2xx status raises
    :class:`ForeignHarnessError` (propagated, not swallowed).
    """

    _UNAVAILABLE_STATUSES = frozenset({502, 503, 504})

    def __init__(
        self,
        *,
        harness_token: str = "",
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self._harness_token = harness_token
        self._client = client
        self._timeout_s = timeout_s

    async def spawn(
        self,
        harness: HarnessAdvertisement,
        bundle: ExportBundle,
        task: HarnessTask,
    ) -> HarnessTaskResult:
        if self._client is not None:
            return await self._post(self._client, harness, bundle, task)
        async with shared_client(timeout=self._timeout_s) as client:
            return await self._post(client, harness, bundle, task)

    async def _post(
        self,
        client: httpx.AsyncClient,
        harness: HarnessAdvertisement,
        bundle: ExportBundle,
        task: HarnessTask,
    ) -> HarnessTaskResult:
        url = f"{harness.endpoint.rstrip('/')}/v1/harness/sessions"
        headers: dict[str, str] = {}
        if self._harness_token:
            headers["Authorization"] = f"Bearer {self._harness_token}"
        payload = {
            "agent": {"mcp_manifest": bundle.mcp_manifest, "skill_md": bundle.skill_md},
            "task": task.to_dict(),
        }
        try:
            response = await client.post(url, json=payload, headers=headers)
        except httpx.TransportError as exc:
            raise HarnessUnavailableError(
                f"harness {harness.harness_id!r} unreachable at {url}: {exc}"
            ) from exc
        if response.status_code in self._UNAVAILABLE_STATUSES:
            raise HarnessUnavailableError(
                f"harness {harness.harness_id!r} unavailable (HTTP {response.status_code})"
            )
        if response.status_code >= 400:
            raise ForeignHarnessError(
                f"harness {harness.harness_id!r} rejected the spawn "
                f"(HTTP {response.status_code}): {response.text[:500]}"
            )
        body = response.json()
        if not isinstance(body, dict):
            raise ForeignHarnessError(
                f"harness {harness.harness_id!r} returned a non-object result"
            )
        result = HarnessTaskResult.from_dict(body)
        if not result.harness_id:
            result.harness_id = harness.harness_id
        if not result.task_id:
            result.task_id = task.id
        return result


# --------------------------------------------------------------------------
# Agent source (feeds SPEC-208's export_agent)
# --------------------------------------------------------------------------


@runtime_checkable
class AgentSource(Protocol):
    """Resolves an agent name to the identity + skills that export_agent needs."""

    async def resolve(self, agent_name: str) -> tuple[AgentIdentity, list[SkillDefinition]]: ...


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------


@runtime_checkable
class HarnessResultComparator(Protocol):
    """Pick the best result from a cross-harness wave.

    Same shape as ``maistro.orchestrator.waves.ensemble.ResultComparator``,
    specialized to :class:`HarnessTaskResult` (WaveResult's typing is
    wave-specific, so the protocol is mirrored rather than imported).
    """

    def compare(self, results: list[HarnessTaskResult]) -> HarnessTaskResult: ...


class QualityHarnessComparator:
    """Highest ``metadata["quality_score"]`` wins; ties keep input order."""

    def compare(self, results: list[HarnessTaskResult]) -> HarnessTaskResult:
        if not results:
            raise AllHarnessesFailedError([])
        return max(results, key=lambda r: r.quality_score)


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------


class HierarchicalOrchestrator:
    """Parent-harness orchestration: spawn agents on foreign harnesses.

    Injected collaborators (protocol-driven DI):
      - ``registry`` discovers foreign harnesses;
      - ``transport`` ships the exported agent + task and returns the result;
      - ``agent_source`` resolves agent names for SPEC-208's ``export_agent``;
      - ``comparator`` picks the winner of a cross-harness wave.
    """

    def __init__(
        self,
        *,
        registry: HarnessRegistry,
        transport: HarnessTransport,
        agent_source: AgentSource,
        comparator: HarnessResultComparator | None = None,
    ) -> None:
        self._registry = registry
        self._transport = transport
        self._agent_source = agent_source
        self._comparator: HarnessResultComparator = comparator or QualityHarnessComparator()

    async def export_agent(self, agent_name: str) -> ExportBundle:
        """Export ``agent_name`` in the SPEC-208 portable format."""
        identity, skills = await self._agent_source.resolve(agent_name)
        return export_agent(identity, skills)

    async def spawn_on_harness(
        self,
        agent_name: str,
        harness_id: str,
        task: HarnessTask,
    ) -> HarnessTaskResult:
        """Export the agent, run it on ``harness_id``, and collect the result.

        A foreign-harness error envelope raises :class:`ForeignHarnessError`
        — errors are propagated, never returned as a silent failure.
        """
        harness = await self._registry.get_harness(harness_id)
        bundle = await self.export_agent(agent_name)
        result = await self._transport.spawn(harness, bundle, task)
        if result.error is not None:
            raise ForeignHarnessError(
                f"harness {harness_id!r} failed task {task.id!r}: {result.error}"
            )
        return result

    async def spawn_wave_across_harnesses(
        self,
        agents: list[str],
        harnesses: list[str],
        task: HarnessTask,
    ) -> HarnessTaskResult:
        """Parallel wave: agent[i] on harness[i]; best result wins.

        Failures are gathered (``return_exceptions=True``) so one dead harness
        never sinks the wave; :class:`AllHarnessesFailedError` only when every
        spawn failed. Cancellation propagates (a cancelled wave is a crash,
        not a comparable failure — same rule as ``waves/ensemble.py``).
        """
        if len(agents) != len(harnesses):
            raise ValueError(
                f"agents ({len(agents)}) and harnesses ({len(harnesses)}) must pair 1:1"
            )
        gathered = await asyncio.gather(
            *(
                self.spawn_on_harness(agent, harness_id, task)
                for agent, harness_id in zip(agents, harnesses, strict=True)
            ),
            return_exceptions=True,
        )
        successes: list[HarnessTaskResult] = []
        failures: list[BaseException] = []
        for outcome in gathered:
            if isinstance(outcome, asyncio.CancelledError):
                raise outcome
            if isinstance(outcome, BaseException):
                failures.append(outcome)
            else:
                successes.append(outcome)
        if not successes:
            raise AllHarnessesFailedError(failures)
        return self._comparator.compare(successes)

    async def spawn_with_fallback(
        self,
        agent_name: str,
        harnesses: list[str],  # ordered by preference
        task: HarnessTask,
    ) -> HarnessTaskResult:
        """Try harnesses in order; skip unavailable ones, propagate real errors.

        Only :class:`HarnessUnavailableError` advances to the next harness —
        a harness that *ran* the task and failed (:class:`ForeignHarnessError`)
        propagates immediately. :class:`NoAvailableHarnessError` when the
        whole preference list is down.
        """
        for harness_id in harnesses:
            try:
                return await self.spawn_on_harness(agent_name, harness_id, task)
            except HarnessUnavailableError:
                continue
        raise NoAvailableHarnessError(harnesses)


async def rank_harnesses(
    registry: HarnessRegistry,
    *,
    capability: str = "",
    agent_name: str = "",
    by: str = "cost",
) -> list[HarnessAdvertisement]:
    """Rank the discovered harnesses for a spawn (cheapest/fastest first).

    Filters on an advertised ``capability`` and/or an agent already present in
    the harness's ``agent_roster``, then sorts by ``cost_multiplier`` (default)
    or ``latency_multiplier`` — the natural input for ``spawn_with_fallback``'s
    ordered preference list.
    """
    if by not in ("cost", "latency"):
        raise ValueError(f"by must be 'cost' or 'latency', got {by!r}")
    harnesses = await registry.list_harnesses()
    if capability:
        harnesses = [h for h in harnesses if capability in h.capabilities]
    if agent_name:
        harnesses = [h for h in harnesses if agent_name in h.agent_roster]
    if by == "latency":
        return sorted(harnesses, key=lambda h: h.latency_multiplier)
    return sorted(harnesses, key=lambda h: h.cost_multiplier)


__all__ = [
    "AgentSource",
    "AllHarnessesFailedError",
    "ForeignHarnessError",
    "HTTPHarnessTransport",
    "HarnessAdvertisement",
    "HarnessRegistry",
    "HarnessResultComparator",
    "HarnessTask",
    "HarnessTaskResult",
    "HarnessTransport",
    "HarnessUnavailableError",
    "HierarchicalOrchestrator",
    "HierarchyError",
    "InMemoryHarnessRegistry",
    "LoopbackHarnessTransport",
    "NoAvailableHarnessError",
    "QualityHarnessComparator",
    "rank_harnesses",
]

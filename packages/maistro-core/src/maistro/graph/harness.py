"""Harness adapter protocol — spawn external agent harnesses as DAG nodes.

A "harness" is any agent execution environment that can receive a task,
run it asynchronously, and report back a result: Claude Code sessions,
remote Conductor instances, LangChain agents, generic HTTP endpoints, etc.

`HarnessAdapter` is the DI boundary. Concrete adapters (ClaudeCodeAdapter,
ConductorHttpAdapter, ...) live in hive-conductor or downstream products
and are wired into `AgentSpawnHarnessNode` at startup. For a provider that
speaks the SPEC-208 ``HarnessRunner`` session protocol (OpenClaw, Pi,
opencode, ...), :class:`HarnessRunnerDispatchAdapter` below is the one
bridging adapter — wrap, don't clone (issue #1613, M1-D).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from maistro.agents.spec.agent_spec import AgentRole as SpecAgentRole
from maistro.agents.spec.agent_spec import AgentSpec
from maistro.capabilities.slots.harness_runner import HarnessRunner
from maistro.capabilities.types import Unavailable
from maistro.graph.harness_executor import _extract_summary


class HarnessKind(StrEnum):
    CLAUDE_CODE = "claude_code"
    CONDUCTOR = "conductor"
    GENERIC_HTTP = "generic_http"
    IN_PROCESS = "in_process"


@dataclass(frozen=True)
class HarnessRequest:
    harness_type: str
    task: str
    context: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 3600
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessHandle:
    handle_id: str
    harness_type: str
    dispatched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # Provider-supplied dispatch provenance (issue #1613): the governed
    # Invocation merges this into its persisted result so the row records the
    # harness session id, workspace hint, and anything else the adapter vouches
    # for — not just an opaque handle. Additive with a default so older
    # adapters (and every downstream product) keep constructing handles.
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessResult:
    handle_id: str
    success: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class HarnessAdapter(Protocol):
    """Protocol every harness backend implements.

    `dispatch` fires the task and returns a handle immediately (the DAG node
    then pauses). `poll` checks for a result on resume. `cancel` is called if
    the run is cancelled before the harness completes.
    """

    async def dispatch(self, request: HarnessRequest) -> HarnessHandle: ...

    async def poll(self, handle: HarnessHandle) -> HarnessResult | None:
        """Return the result if complete, None if still running."""
        ...

    async def cancel(self, handle: HarnessHandle) -> None: ...


class HarnessRunnerDispatchAdapter:
    """Adapt one ``HarnessRunner`` provider to the spawn node's dispatch seam.

    Covers the full :class:`HarnessAdapter` surface: ``dispatch`` runs the one
    bounded turn and records its outcome (the session is already terminal when
    ``dispatch`` returns — its ``finally`` stopped it), ``poll`` replays that
    recorded outcome without re-dispatching or re-entering the provider, and
    ``cancel`` is a documented no-op for the same reason. Waking a *paused
    durable run* with this evidence is the harness waker's job (issue #1192);
    the bridge only guarantees the evidence is there when that lands.

    The provider is expected fully guarded — i.e. the
    :class:`~maistro.capabilities.SafeHarnessRunner` wrapper (Warden inbound,
    ActionGate outbound) resolved through ``resolve_harness_runner`` — or a
    test double with the same session protocol. This class adds no policy of
    its own; it only shapes one turn and records dispatch provenance.
    """

    def __init__(self, runner: HarnessRunner, *, workdir: str = ".") -> None:
        self._runner = runner
        self._default_workdir = workdir
        # Completed turns by handle id: the bounded turn's outcome is final at
        # dispatch time, so poll replays the memo instead of re-entering the
        # provider. A failed turn memoizes nothing — the Attempt failed.
        self._completed: dict[str, HarnessResult] = {}

    @property
    def provider_name(self) -> str:
        return self._runner.name

    async def dispatch(self, request: HarnessRequest) -> HarnessHandle:
        workdir = str(request.metadata.get("workdir") or "") or self._default_workdir
        spec = AgentSpec(
            role=SpecAgentRole.CODER,
            task_id=request.harness_type,
            subtask_id=request.harness_type,
            description=request.task,
        )
        session = await self._runner.start_session(spec, workdir=workdir)
        try:
            envelope = await self._runner.send(session, _turn_messages(request))
        finally:
            # One dispatch, one bounded session: whether the turn succeeded,
            # failed, or was cancelled mid-flight, the session is stopped here
            # so no orphan harness process can outlive the Attempt.
            await self._runner.stop(session)
        if isinstance(envelope, Unavailable):
            raise RuntimeError(
                f"harness provider {request.harness_type!r} lost its session: {envelope.reason}"
            )
        result = HarnessResult(
            handle_id=f"harness-{session}",
            success=True,
            # Result payload (issue #1613): the bounded turn's outcome is
            # known at dispatch time, so the governed Invocation row can
            # record it — harness id, session/workspace hint, and result
            # on one canonical row.
            output=_extract_summary(envelope),
            metadata={
                "session_id": session,
                "workdir": workdir,
                "provider": self._runner.name,
                "exit_code": envelope.get("exit_code"),
            },
        )
        self._completed[result.handle_id] = result
        return HarnessHandle(
            handle_id=result.handle_id,
            harness_type=request.harness_type,
            detail={
                "session_id": session,
                "workdir": workdir,
                "provider": self._runner.name,
                "output": result.output,
                "exit_code": envelope.get("exit_code"),
            },
        )

    async def poll(self, handle: HarnessHandle) -> HarnessResult | None:
        """Replay the completed turn; ``None`` for a handle we never dispatched.

        No re-dispatch and no provider round-trip: the turn is terminal, its
        outcome was recorded at dispatch time. An unknown handle means the
        caller is polling a dispatch this adapter never made — reported as
        "still nothing", leaving any transported answer in charge.
        """
        return self._completed.get(handle.handle_id)

    async def cancel(self, handle: HarnessHandle) -> None:
        """Nothing in flight: the bounded turn is terminal after dispatch."""
        return None


def _turn_messages(request: HarnessRequest) -> list[dict[str, str]]:
    """Shape the harness task (plus optional context) into turn messages."""
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "You are executing one task dispatched by the maistro "
                "orchestrator as a governed harness node."
            ),
        },
        {"role": "user", "content": request.task},
    ]
    if request.context:
        messages.append(
            {"role": "user", "content": f"Task context: {_compact_json(request.context)}"}
        )
    return messages


def _compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)

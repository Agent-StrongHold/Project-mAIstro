"""Admitting a chat turn as a canonical Run (#131, ADR-082226-c126).

The chat twin of `maistro.tasks.admission`. Same seam, same one-node Graph, same
intent table — the point of #41 is that work has one execution identity
regardless of which door it came through, and a chat turn that admitted through
some parallel mechanism would be canonical in shape only.

Two things differ from the task path, and both come from the ADR:

**One Run per turn, not per session.** A `Run` pins an immutable
`GraphSnapshot` and every `NodeRun` must name a node present in it, so turn N of
a conversation is not in a snapshot taken at turn 1. And a Run has a terminal
lifecycle where a conversation has none — a session-Run would sit `RUNNING` for
as long as the user might come back, which is precisely the signal recovery
scans and `ix_canonical_runs_live` read as "a process died mid-flight". The
conversation travels in provenance instead, as `task_id` already does.

**The Run carries a retention deadline.** Chat turns arrive at a rate a
conversation sets, not a rate a human sets, so unbounded retention here is a
leak. See `maistro.runs.retention` for why the policy lives at the admitting
seam rather than in the store.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from maistro.runs.admission import (
    REQUEST_ID_KEY,
    SESSION_ID_KEY,
    USER_ID_KEY,
    admit_direct_work,
)
from maistro.runs.binding import ProjectBinding
from maistro.runs.lifecycle import InvalidLifecycleTransition
from maistro.runs.model import Run, RunStatus
from maistro.runs.retention import RetentionPolicy, RunRetentionSweeper
from maistro.runs.task_kinds import resolve_direct_work

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.agents.intents import IntentRegistry
    from maistro.projects.scope_store import ProjectScopeStore
    from maistro.runs.store import RunStore

#: `admission_source` value for work that entered through a chat turn.
CHAT_TURN_SOURCE = "chat_turn"

#: Provenance key recording the classified task type the turn routed on. Not the
#: same as the node kind, which is always `agent.delegate_remote`; this is what
#: the classifier decided, and it is the only record of that decision once the
#: Run outlives the request.
TASK_TYPE_KEY = "task_type"


class ChatRunAdmitter:
    """Admit chat turns as canonical Runs in one bound Workspace/Project."""

    def __init__(
        self,
        run_store: RunStore,
        *,
        workspace_id: str,
        project_id: str | None = None,
        project_store: ProjectScopeStore | None = None,
        intents: IntentRegistry | None = None,
        retention: RetentionPolicy | None = None,
        sweeper: RunRetentionSweeper | None = None,
    ) -> None:
        self._runs = run_store
        self._binding = ProjectBinding(
            workspace_id=workspace_id,
            project_id=project_id,
            project_store=project_store,
        )
        self._intents = intents
        self._retention = retention if retention is not None else RetentionPolicy()
        self._sweeper = (
            sweeper if sweeper is not None else RunRetentionSweeper(run_store, self._retention)
        )

    @property
    def retention(self) -> RetentionPolicy:
        return self._retention

    @property
    def sweeper(self) -> RunRetentionSweeper:
        return self._sweeper

    async def admit_chat_turn(
        self,
        *,
        prompt: str,
        task_type: str = "",
        agent_name: str = "",
        session_id: str | None = None,
        request_id: str | None = None,
        user_id: str | None = None,
        persona_id: str | None = None,
    ) -> Run:
        """Admit one chat turn and return its canonical Run, already RUNNING.

        The Run is walked `CREATED -> QUEUED -> RUNNING` here rather than left
        for the caller. `route_request()` is synchronous — there is no queue and
        no receipt, so by the time this returns the work genuinely is running,
        and leaving the Run in `CREATED` would mean the spine disagreed with
        reality from the first instant. `QUEUED` is passed through because the
        lifecycle requires it (`CREATED -> RUNNING` is not a legal edge); a chat
        turn is queued for zero time, which is a true statement about a queue it
        never entered.

        Sweeping rides on this call, after the Run exists: retention is
        housekeeping and must never be the reason a chat turn was refused.
        """
        work = resolve_direct_work(
            description=prompt,
            task_type=task_type,
            agent_id=agent_name,
            registry=self._intents,
        )
        provenance: dict[str, Any] = {}
        if session_id:
            provenance[SESSION_ID_KEY] = session_id
        if request_id:
            provenance[REQUEST_ID_KEY] = request_id
        if user_id:
            provenance[USER_ID_KEY] = user_id
        if task_type:
            provenance[TASK_TYPE_KEY] = task_type
        run = await admit_direct_work(
            self._runs,
            workspace_id=self._binding.workspace_id,
            project_id=await self._binding.project_id(),
            node_type=work.node_type,
            name=work.name,
            source=CHAT_TURN_SOURCE,
            parameters=work.parameters,
            description=prompt,
            actor_principal_id=user_id or None,
            persona_id=persona_id,
            provenance=provenance,
            retention_expires_at=self._retention.deadline(),
        )
        await self._runs.transition_run(run.run_id, RunStatus.QUEUED)
        running = await self._runs.transition_run(run.run_id, RunStatus.RUNNING)
        await self._sweeper.maybe_sweep()
        return running

    async def record_outcome(
        self,
        run_id: str,
        status: RunStatus,
        *,
        result: object | None = None,
        error: str | None = None,
    ) -> bool:
        """Close a chat turn's Run. False if the Run refused or does not resolve.

        The caller must not treat False as "close enough". A Run that does not
        resolve means the receipt carries a run_id nothing can find, and a Run
        that refused the transition means something else already closed it —
        both are divergences between the record and the work, and both are what
        this seam exists to surface rather than paper over.
        """
        run = await self._runs.get_run(run_id)
        if run is None:
            return False
        if run.status is status:
            return True
        try:
            await self._runs.transition_run(run_id, status, result=result, error=error)
        except InvalidLifecycleTransition:
            return False
        return True


__all__ = [
    "CHAT_TURN_SOURCE",
    "TASK_TYPE_KEY",
    "ChatRunAdmitter",
]

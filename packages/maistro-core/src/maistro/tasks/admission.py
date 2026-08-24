"""Binding the task queue to the canonical Run spine (#41).

`maistro.runs.admission` knows how to turn one unit of work into a Run, and
`maistro.runs.task_kinds` knows what node kind a task admits as. Neither knows
anything about tasks, deliberately: the runs package must not learn the shape of
every entry point that will eventually feed it. This module is the adapter that
does know both sides, and it lives on the tasks side because that is the side
that depends on the other.

The Workspace/Project a task lands in is a binding, not a property of the task.
`TaskCreate.workspace` is a filesystem path for the sandbox — it names where code
is checked out, not which Workspace owns the work — so the admitter is
constructed with the Workspace it admits into, and resolves that Workspace's Root
Project when no Project is named. Nothing infers scope from a task field; getting
that wrong would file work in the wrong tenant's Project, which is exactly the
failure the scope tree exists to prevent.

A process may nonetheless serve more than one Workspace — the Conductor does,
because a Hive user belongs to several (#158). That is what
:class:`WorkspaceRoutingAdmitter` is for: the *submission* names the Workspace,
having been authorized by whoever accepted it, and the router hands the task to
the :class:`TaskRunAdmitter` bound to that Workspace, building one on first use.
Each bound admitter still knows exactly one Workspace and one Project, so the
invariant above is intact; the routing is a layer above it, not a hole in it. A
bound admitter handed a Workspace that is not its own refuses rather than filing
the work anyway, because "quietly used the wrong Project" is the failure mode
worth being loud about.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any, Protocol

from maistro.runs.admission import admit_direct_work
from maistro.runs.lifecycle import RUN_TRANSITIONS, InvalidLifecycleTransition
from maistro.runs.model import TERMINAL_RUN_STATUSES, RunStatus
from maistro.runs.task_kinds import resolve_direct_work
from maistro.tasks.models import TaskStatus

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.agents.intents import IntentRegistry
    from maistro.projects.scope_store import ProjectScopeStore
    from maistro.runs.store import RunStore
    from maistro.tasks.models import TaskResponse

#: How a task's state machine reads on the canonical Run.
#:
#: The task machine is finer-grained than the Run's on purpose — planning,
#: coding, reviewing and testing are phases of one execution, not four. They all
#: read as RUNNING, and a transition between them is a no-op on the Run rather
#: than an illegal one. The Run's own lifecycle already refuses RUNNING ->
#: RUNNING, so collapsing them here is what keeps the receipt's extra detail
#: from looking like a lifecycle disagreement.
RUN_STATUS_BY_TASK_STATUS: dict[TaskStatus, RunStatus] = {
    TaskStatus.QUEUED: RunStatus.QUEUED,
    TaskStatus.PLANNING: RunStatus.RUNNING,
    TaskStatus.CODING: RunStatus.RUNNING,
    TaskStatus.REVIEWING: RunStatus.RUNNING,
    TaskStatus.TESTING: RunStatus.RUNNING,
    TaskStatus.COMPLETED: RunStatus.COMPLETED,
    TaskStatus.FAILED: RunStatus.FAILED,
    TaskStatus.CANCELLED: RunStatus.CANCELLED,
}

#: `admission_source` value for work that entered through the task queue.
TASK_QUEUE_SOURCE = "task_queue"

#: Provenance keys correlating the Run back to the receipt that admitted it.
TASK_ID_KEY = "task_id"
SESSION_ID_KEY = "session_id"


class WorkspaceNotAdmissible(ValueError):
    """An admitter was asked to file work in a Workspace it is not bound to."""


class TaskAdmitter(Protocol):
    """What :class:`~maistro.tasks.queue.TaskQueue` needs to admit a task."""

    async def admit(self, task: TaskResponse, *, workspace_id: str | None = None) -> str:
        """Admit one queued task and return its canonical ``run_id``.

        ``workspace_id`` is the Workspace the *submission* named, already
        authorized by whoever accepted it. None means "this deployment's
        default Workspace" — the pre-#158 behaviour, and what every caller that
        has no Workspace of its own still passes.
        """
        ...

    async def record_transition(
        self,
        run_id: str,
        status: TaskStatus,
        *,
        result: object | None = None,
        error: str | None = None,
    ) -> bool:
        """Advance the Run to match a task transition. False if it refused."""
        ...


class TaskRunAdmitter:
    """Admit queued tasks as canonical Runs in one bound Workspace/Project."""

    def __init__(
        self,
        run_store: RunStore,
        *,
        workspace_id: str,
        project_id: str | None = None,
        project_store: ProjectScopeStore | None = None,
        intents: IntentRegistry | None = None,
    ) -> None:
        if not workspace_id.strip():
            raise ValueError("workspace_id must be a non-empty string")
        if project_id is None and project_store is None:
            raise ValueError(
                "TaskRunAdmitter needs either an explicit project_id or a project_store "
                "to resolve the Workspace's Root Project"
            )
        self._runs = run_store
        self._workspace_id = workspace_id
        self._project_id = project_id
        self._projects = project_store
        self._intents = intents

    async def _resolve_project_id(self) -> str:
        if self._project_id is not None:
            return self._project_id
        if self._projects is None:  # pragma: no cover - guarded in __init__
            raise RuntimeError("TaskRunAdmitter has no project_store to resolve a Project")
        root = await self._projects.root_for_workspace(self._workspace_id)
        # Cached: a Workspace's Root Project is created once and never moves,
        # so re-resolving it on every submission is a store round-trip for an
        # answer that cannot have changed.
        self._project_id = root.project_id
        return self._project_id

    @property
    def workspace_id(self) -> str:
        """The single Workspace this admitter files work in."""
        return self._workspace_id

    async def admit(self, task: TaskResponse, *, workspace_id: str | None = None) -> str:
        """Admit one queued task as a Run and return its ``run_id``.

        ``workspace_id`` may name this admitter's own Workspace, redundantly,
        or nothing at all. Any other value is refused: this admitter resolved
        one Root Project at construction and cannot honour a different
        Workspace, and silently filing the work in the bound one would put a
        Run in a Project its submitter never named.
        """
        if workspace_id is not None and workspace_id != self._workspace_id:
            raise WorkspaceNotAdmissible(
                f"admitter is bound to Workspace {self._workspace_id!r} and cannot "
                f"admit into {workspace_id!r}"
            )
        work = resolve_direct_work(
            description=task.description,
            task_type=task.task_type,
            agent_id=task.agent_id,
            registry=self._intents,
        )
        provenance: dict[str, Any] = {TASK_ID_KEY: task.task_id}
        if task.session_id:
            provenance[SESSION_ID_KEY] = task.session_id
        if task.user_id:
            provenance["user_id"] = task.user_id
        run = await admit_direct_work(
            self._runs,
            workspace_id=self._workspace_id,
            project_id=await self._resolve_project_id(),
            node_type=work.node_type,
            name=work.name,
            source=TASK_QUEUE_SOURCE,
            parameters=work.parameters,
            description=task.description,
            actor_principal_id=task.user_id or None,
            provenance=provenance,
        )
        # The receipt is born QUEUED, so the Run is too. Leaving it CREATED
        # would mean the two disagreed from the first instant about a task that
        # is, by then, genuinely queued.
        #
        # Two commits on a durable store, and a failure between them would leave
        # a CREATED Run whose provenance names a task receipt that was never
        # queued. Compensate rather than leak: a Run that could not be queued is
        # cancelled, which is true and terminal. The remaining window — process
        # death between the two commits — needs a create-in-queued-state
        # operation on the RunStore protocol, which is #132's to add along with
        # the durable backend.
        try:
            await self._runs.transition_run(run.run_id, RunStatus.QUEUED)
        except BaseException:
            with contextlib.suppress(Exception):
                await self._runs.transition_run(run.run_id, RunStatus.CANCELLED)
            raise
        return run.run_id

    async def record_transition(
        self,
        run_id: str,
        status: TaskStatus,
        *,
        result: object | None = None,
        error: str | None = None,
    ) -> bool:
        """Advance the Run to match one task transition.

        Returns False when the Run refuses, and the caller must then refuse the
        task transition too. That is what "the Run is authoritative" buys: the
        receipt cannot record a state the execution identity rejected, so the
        two can never tell different stories about the same work.

        A transition the Run is already in is not a refusal — it is the finer
        task machine moving between phases of one execution. A Run that does not
        resolve *is* a refusal: a receipt carrying a run_id nothing can find is
        an orphaned identity, and letting it advance anyway is the exact
        divergence this seam exists to prevent. (Returning True there was a bug:
        it made "no Run" indistinguishable from "already in that state".)

        ``result`` and ``error`` carry the terminal outcome onto the Run. Without
        them every terminal Run reported result=None and error=None forever,
        including failed work, so a caller who followed the run_id learned that
        the work ended and nothing about how.
        """
        target = RUN_STATUS_BY_TASK_STATUS[status]
        run = await self._runs.get_run(run_id)
        if run is None:
            return False
        if run.status is target:
            return True
        if (
            run.status is RunStatus.WAITING
            and target in TERMINAL_RUN_STATUSES
            and target not in RUN_TRANSITIONS[RunStatus.WAITING]
        ):
            # A failed or timed-out Attempt parks its NodeRun, and a Run with no
            # other active node then parks too (#143). The receipt is still the
            # domain here and it says the work is over — but WAITING has no edge
            # to COMPLETED or FAILED, so the Run has to be resumed before it can
            # be terminalized. Without this the receipt of every failed task
            # stayed stuck at CODING, with its error written nowhere.
            try:
                await self._runs.transition_run(run_id, RunStatus.RUNNING)
            except InvalidLifecycleTransition:
                return False
        try:
            await self._runs.transition_run(run_id, target, result=result, error=error)
        except InvalidLifecycleTransition:
            return False
        return True


class WorkspaceRoutingAdmitter:
    """Route each submission to the :class:`TaskRunAdmitter` for its Workspace.

    One Conductor process serves every Workspace its users belong to, so the
    Workspace cannot be fixed at wiring time the way it is for a single-tenant
    server. It is fixed per *submission* instead, and this router keeps one
    bound admitter per Workspace so the "one Workspace, one Project" invariant
    survives intact underneath.

    Root Projects are created on first use rather than up front, because the set
    of Workspaces is not known at startup — a Workspace created this afternoon
    must be admittable this afternoon. The default Workspace is still primed
    eagerly by :func:`maistro.runs.wiring.wire_execution_spine`, so a
    misconfigured scope store fails at startup rather than on somebody's first
    task.
    """

    def __init__(
        self,
        run_store: RunStore,
        project_store: ProjectScopeStore,
        *,
        default_workspace_id: str,
        intents: IntentRegistry | None = None,
    ) -> None:
        if not default_workspace_id.strip():
            raise ValueError("default_workspace_id must be a non-empty string")
        self._runs = run_store
        self._projects = project_store
        self._default_workspace_id = default_workspace_id
        self._intents = intents
        self._by_workspace: dict[str, TaskRunAdmitter] = {}
        # Two concurrent first submissions for one Workspace would otherwise
        # both create a Root Project. `create_root` is idempotent, so the
        # damage would be a wasted round-trip rather than two roots — but they
        # would also build two admitters, and the loser's cached project_id
        # would be thrown away mid-flight.
        self._lock = asyncio.Lock()

    @property
    def default_workspace_id(self) -> str:
        """The Workspace a submission that names none lands in."""
        return self._default_workspace_id

    async def admitter_for(self, workspace_id: str | None = None) -> TaskRunAdmitter:
        """The bound admitter for one Workspace, building it on first use."""
        # `is None`, not falsiness. An empty string is a *named* Workspace that
        # happens to be blank, and the API documents only None as meaning the
        # default — folding the two together let `?workspace_id=` file into the
        # default here while the HTTP backend refused the same value, and made
        # `admitter_for("")` contradict the blank check below.
        if workspace_id is None:
            resolved = self._default_workspace_id.strip()
        else:
            resolved = workspace_id.strip()
        if not resolved:
            raise ValueError("workspace_id must be a non-empty string")
        cached = self._by_workspace.get(resolved)
        if cached is not None:
            return cached
        async with self._lock:
            cached = self._by_workspace.get(resolved)
            if cached is not None:
                return cached
            root = await self._projects.create_root(resolved)
            admitter = TaskRunAdmitter(
                self._runs,
                workspace_id=resolved,
                project_id=root.project_id,
                intents=self._intents,
            )
            self._by_workspace[resolved] = admitter
            return admitter

    async def admit(self, task: TaskResponse, *, workspace_id: str | None = None) -> str:
        """Admit one task into the Workspace the submission named."""
        admitter = await self.admitter_for(workspace_id)
        return await admitter.admit(task)

    async def record_transition(
        self,
        run_id: str,
        status: TaskStatus,
        *,
        result: object | None = None,
        error: str | None = None,
    ) -> bool:
        """Advance the Run to match a task transition.

        Workspace-independent on purpose: by the time a task transitions, its
        Run exists and already knows which Project it is filed in. Looking the
        Workspace up again to reach the same run store would only invite the
        two answers to disagree. Delegating through the default admitter keeps
        one implementation of the refusal semantics rather than a second copy.
        """
        admitter = await self.admitter_for(None)
        return await admitter.record_transition(run_id, status, result=result, error=error)


__all__ = [
    "RUN_STATUS_BY_TASK_STATUS",
    "SESSION_ID_KEY",
    "TASK_ID_KEY",
    "TASK_QUEUE_SOURCE",
    "TaskAdmitter",
    "TaskRunAdmitter",
    "WorkspaceNotAdmissible",
    "WorkspaceRoutingAdmitter",
]

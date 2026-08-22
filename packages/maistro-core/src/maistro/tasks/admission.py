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
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from maistro.runs.admission import admit_direct_work
from maistro.runs.lifecycle import InvalidLifecycleTransition
from maistro.runs.model import RunStatus
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


class TaskAdmitter(Protocol):
    """What :class:`~maistro.tasks.queue.TaskQueue` needs to admit a task."""

    async def admit(self, task: TaskResponse) -> str:
        """Admit one queued task and return its canonical ``run_id``."""
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

    async def admit(self, task: TaskResponse) -> str:
        """Admit one queued task as a Run and return its ``run_id``."""
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
            # The receipt is born QUEUED, so the Run is created QUEUED. Creating
            # it CREATED and transitioning afterwards was two commits on a
            # durable store, and a failure between them left a CREATED Run whose
            # provenance named a task receipt that was never queued — with no
            # recovery scan looking for it.
            initial_status=RunStatus.QUEUED,
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
        try:
            await self._runs.transition_run(run_id, target, result=result, error=error)
        except InvalidLifecycleTransition:
            return False
        return True


__all__ = [
    "RUN_STATUS_BY_TASK_STATUS",
    "SESSION_ID_KEY",
    "TASK_ID_KEY",
    "TASK_QUEUE_SOURCE",
    "TaskAdmitter",
    "TaskRunAdmitter",
]

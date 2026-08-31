"""Canonical execution composition for the reachable Turing chat surface (#753).

Turing owns conversation/self-model/memory state. The platform execution spine
owns Workspace/Project/Run/NodeRun/Attempt identity. This module only composes
those existing public contracts for the standalone Turing backend; it does not
introduce a Turing lifecycle or activate dormant cognition.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Any, ClassVar

from pydantic import BaseModel

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    DurableRunRecord,
    InMemoryGraphContinuationStore,
    run_durable_graph,
)
from maistro.graph.nodes import BaseNode, NodeContext
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.chat_admission import ADMISSION_INCOMPLETE, MAX_RETAINED_CHAT_RUNS
from maistro.runs.model import (
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_RUN_STATUSES,
    AttemptStatus,
    RunStatus,
)
from maistro.runs.retention import RetentionPolicy, RunRetentionSweeper
from maistro.runs.sources import ADMISSION_SOURCE, CHAT_SOURCE
from maistro.workspaces.store import InMemoryWorkspaceStore
from maistro_turing.runtime import TuringChatSession

logger = logging.getLogger(__name__)

_CHAT_NODE_ID = "turing-chat-turn"
_CHAT_NODE_KIND = "turing.chat_turn"
_CANCELLED_ERROR = "execution cancelled"


class TuringAdmissionUnavailable(RuntimeError):
    """Canonical audit admission failed before Turing dispatched the chat turn."""


class _ChatInput(BaseModel):
    message: str


class _ChatOutput(BaseModel):
    reply: str


class _ChatNode(BaseNode[_ChatInput, _ChatOutput]):
    """Execute one Turing domain chat turn under canonical Attempt evidence."""

    kind: ClassVar[str] = _CHAT_NODE_KIND
    kind_category: ClassVar = "sync.llm"
    input_schema: ClassVar[type[BaseModel]] = _ChatInput
    output_schema: ClassVar[type[BaseModel]] = _ChatOutput
    display_name: ClassVar[str] = "Turing chat turn"
    description: ClassVar[str] = "Execute one reachable Turing chat request."
    idempotent: ClassVar[bool] = False
    external_io: ClassVar[bool] = True

    def __init__(self, session: TuringChatSession) -> None:
        self._session = session

    async def _execute(self, inputs: _ChatInput, ctx: NodeContext) -> _ChatOutput:
        return _ChatOutput(reply=await self._session.handle_message(inputs.message))


class TuringExecutionPlane:
    """Compose canonical in-memory ownership/execution stores for this service.

    The standalone backend is already explicitly process-local. Using the
    canonical in-memory stores therefore improves identity semantics without
    pretending this slice adds restart durability. A durable deployment can
    replace these implementations through the same public store contracts.

    Chat admission still follows the canonical chat retention contract: the Run
    is marked with ``CHAT_SOURCE``, gets a durable retention deadline, and is
    tracked in a small per-process window so high-volume turns do not evict
    longer-lived task Runs from a shared store.
    """

    def __init__(
        self,
        *,
        max_retained: int = MAX_RETAINED_CHAT_RUNS,
        retention: RetentionPolicy | None = None,
    ) -> None:
        if max_retained < 1:
            raise ValueError("max_retained must be >= 1")
        self.project_store = InMemoryProjectScopeStore()
        self.workspace_store = InMemoryWorkspaceStore(project_store=self.project_store)
        self.run_store = InMemoryRunStore(project_store=self.project_store)
        self.durable_store = CanonicalDurableRunStore(
            self.run_store,
            InMemoryGraphContinuationStore(),
        )
        self._workspace_by_user: dict[str, str] = {}
        self._scope_lock = asyncio.Lock()
        self._retained_runs: OrderedDict[str, None] = OrderedDict()
        self._retention_lock = asyncio.Lock()
        self._max_retained = max_retained
        self._retention = retention if retention is not None else RetentionPolicy()
        self._retention_sweeper = RunRetentionSweeper(self.run_store, self._retention)

    @property
    def retained(self) -> int:
        """How many Turing chat Runs this process still tracks."""
        return len(self._retained_runs)

    async def _scope_for(self, user_id: str) -> tuple[str, str]:
        async with self._scope_lock:
            workspace_id = self._workspace_by_user.get(user_id)
            if workspace_id is None:
                workspace = await self.workspace_store.create(
                    creator_user_id=user_id,
                    name=f"Turing workspace for {user_id}",
                    description="Canonical scope for the standalone Turing chat surface.",
                )
                workspace_id = workspace.workspace_id
                self._workspace_by_user[user_id] = workspace_id
            root = await self.project_store.root_for_workspace(workspace_id)
            return workspace_id, root.project_id

    async def _track_admission(self, run_id: str) -> None:
        self._retained_runs[run_id] = None
        async with self._retention_lock:
            for retained_id in list(self._retained_runs):
                if len(self._retained_runs) <= self._max_retained:
                    break
                retained = await self.run_store.get_run(retained_id)
                if retained is None:
                    self._retained_runs.pop(retained_id, None)
                    continue
                if retained.status not in TERMINAL_RUN_STATUSES:
                    continue
                await self.run_store.delete_run(retained_id)
                self._retained_runs.pop(retained_id, None)
        await self._retention_sweeper.maybe_sweep()

    async def _clear_continuation(self, run_id: str) -> None:
        """Clear runnable frontier after a compensated/cancelled Turing Run."""
        try:
            record = await self.durable_store.get(run_id)
            if record is None:
                return
            state = record.graph_state.model_copy(update={"active_node_ids": ()})
            await self.durable_store.update(
                record.model_copy(
                    update={
                        "graph_state": state,
                        "resume_at": None,
                        "version": record.version + 1,
                    }
                )
            )
        except Exception:
            logger.warning("Turing continuation cleanup failed for Run %s", run_id, exc_info=True)

    async def _cancel_incomplete_admission(self, run_id: str | None) -> None:
        """Compensate a Run persisted before canonical graph admission completed."""
        if run_id is None:
            return
        try:
            current = await self.run_store.get_run(run_id)
            if current is None or current.status in TERMINAL_RUN_STATUSES:
                return
            if current.status not in {RunStatus.CREATED, RunStatus.QUEUED}:
                return
            await self.run_store.transition_run(
                run_id,
                RunStatus.CANCELLED,
                error=ADMISSION_INCOMPLETE,
            )
            await self._clear_continuation(run_id)
        except Exception:
            logger.warning(
                "stranded Turing chat Run %s could not be compensated",
                run_id,
                exc_info=True,
            )

    async def _cancel_execution(self, run_id: str) -> None:
        """Best-effort outer cancellation guard around durable Graph execution."""
        try:
            for node_run in await self.run_store.list_node_runs(run_id):
                for attempt in await self.run_store.list_attempts(node_run.node_run_id):
                    if attempt.status in TERMINAL_ATTEMPT_STATUSES:
                        continue
                    lease = attempt.execution_lease
                    token = lease.fencing_token if lease is not None else None
                    await self.run_store.transition_attempt(
                        attempt.attempt_id,
                        AttemptStatus.CANCELLED,
                        error=_CANCELLED_ERROR,
                        fencing_token=token,
                    )
                current_node = await self.run_store.get_node_run(node_run.node_run_id)
                if current_node is not None and current_node.status not in TERMINAL_RUN_STATUSES:
                    await self.run_store.transition_node_run(
                        current_node.node_run_id,
                        RunStatus.CANCELLED,
                        error=_CANCELLED_ERROR,
                    )

            current = await self.run_store.get_run(run_id)
            if current is not None and current.status not in TERMINAL_RUN_STATUSES:
                await self.run_store.transition_run(
                    run_id,
                    RunStatus.CANCELLED,
                    error=_CANCELLED_ERROR,
                )
            await self._clear_continuation(run_id)
        except Exception:
            logger.warning("Turing cancellation cleanup failed for Run %s", run_id, exc_info=True)

    async def run_chat(
        self,
        *,
        session: TuringChatSession,
        user_id: str,
        session_id: str,
        message: str,
    ) -> DurableRunRecord:
        """Execute one chat request as one canonical Graph/Run.

        Failure before node resolution is an audit-admission failure: no provider
        work has been dispatched, so the HTTP boundary may preserve chat
        availability by executing the domain turn without a Run. Once the node
        has been resolved, failures belong to canonical execution and are never
        replayed outside the spine.
        """
        admitted_run_id: str | None = None
        try:
            workspace_id, project_id = await self._scope_for(user_id)
            graph = Graph(
                workspace_id=workspace_id,
                project_id=project_id,
                name="Turing chat turn",
                description="One request on the reachable standalone Turing chat surface.",
                nodes=[
                    Node(
                        node_id=_CHAT_NODE_ID,
                        node_type=_CHAT_NODE_KIND,
                        name="Turing chat turn",
                        parameters={"message": message},
                        policies={"max_attempts": 1},
                    )
                ],
                metadata={
                    "entry_node": _CHAT_NODE_ID,
                    "execution_owner": "canonical_run",
                    "product": "turing",
                },
            )
            provenance = {
                ADMISSION_SOURCE: CHAT_SOURCE,
                "product": "turing",
                "session_id": session_id,
            }
            admitted = await self.run_store.create_run(
                graph,
                actor_principal_id=user_id,
                provenance=provenance,
                retention_expires_at=self._retention.deadline(),
                initial_status=RunStatus.QUEUED,
            )
            admitted_run_id = admitted.run_id
            await self._track_admission(admitted.run_id)
        except asyncio.CancelledError:
            await asyncio.shield(self._cancel_incomplete_admission(admitted_run_id))
            raise
        except Exception as exc:
            await self._cancel_incomplete_admission(admitted_run_id)
            raise TuringAdmissionUnavailable("canonical Turing chat admission failed") from exc

        node = _ChatNode(session)
        dispatch_prepared = False

        def resolve(node_id: str, _graph: Graph) -> BaseNode[Any, Any]:
            nonlocal dispatch_prepared
            # Resolver entry means canonical execution has moved beyond audit
            # admission. From here on an exception is an execution/programming
            # failure and must never replay the user turn outside the spine.
            dispatch_prepared = True
            if node_id != _CHAT_NODE_ID:
                raise KeyError(f"unknown Turing canonical node {node_id!r}")
            return node

        try:
            return await run_durable_graph(
                graph,
                store=self.durable_store,
                node_resolver=resolve,
                actor_principal_id=user_id,
                run_id=admitted.run_id,
                provenance=provenance,
                run_store=self.run_store,
            )
        except asyncio.CancelledError:
            await asyncio.shield(self._cancel_execution(admitted.run_id))
            raise
        except Exception as exc:
            if not dispatch_prepared:
                await self._cancel_incomplete_admission(admitted.run_id)
                raise TuringAdmissionUnavailable(
                    "canonical Turing chat checkpoint admission failed"
                ) from exc
            raise


_execution_plane = TuringExecutionPlane()


def get_execution_plane() -> TuringExecutionPlane:
    """Return the process-local canonical execution composition."""
    return _execution_plane


def reset_execution_plane() -> TuringExecutionPlane:
    """Replace process-local execution composition; used for test isolation."""
    global _execution_plane
    _execution_plane = TuringExecutionPlane()
    return _execution_plane


__all__ = [
    "TuringAdmissionUnavailable",
    "TuringExecutionPlane",
    "get_execution_plane",
    "reset_execution_plane",
]

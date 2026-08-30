"""Canonical execution composition for the reachable Turing chat surface (#753).

Turing owns conversation/self-model/memory state. The platform execution spine
owns Workspace/Project/Run/NodeRun/Attempt identity. This module only composes
those existing public contracts for the standalone Turing backend; it does not
introduce a Turing lifecycle or activate dormant cognition.
"""

from __future__ import annotations

import asyncio
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
from maistro.runs.model import RunStatus
from maistro.workspaces.store import InMemoryWorkspaceStore
from maistro_turing.runtime import TuringChatSession

_CHAT_NODE_ID = "turing-chat-turn"
_CHAT_NODE_KIND = "turing.chat_turn"


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
    """

    def __init__(self) -> None:
        self.project_store = InMemoryProjectScopeStore()
        self.workspace_store = InMemoryWorkspaceStore(project_store=self.project_store)
        self.run_store = InMemoryRunStore(project_store=self.project_store)
        self.durable_store = CanonicalDurableRunStore(
            self.run_store,
            InMemoryGraphContinuationStore(),
        )
        self._workspace_by_user: dict[str, str] = {}
        self._scope_lock = asyncio.Lock()

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

    async def run_chat(
        self,
        *,
        session: TuringChatSession,
        user_id: str,
        session_id: str,
        message: str,
    ) -> DurableRunRecord:
        """Execute one chat request as one canonical Graph/Run."""
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
            "admission_source": "turing",
            "product": "turing",
            "session_id": session_id,
        }
        admitted = await self.run_store.create_run(
            graph,
            actor_principal_id=user_id,
            provenance=provenance,
            initial_status=RunStatus.QUEUED,
        )
        node = _ChatNode(session)

        def resolve(node_id: str, _graph: Graph) -> BaseNode[Any, Any]:
            if node_id != _CHAT_NODE_ID:
                raise KeyError(f"unknown Turing canonical node {node_id!r}")
            return node

        return await run_durable_graph(
            graph,
            store=self.durable_store,
            node_resolver=resolve,
            actor_principal_id=user_id,
            run_id=admitted.run_id,
            provenance=provenance,
            run_store=self.run_store,
        )


_execution_plane = TuringExecutionPlane()


def get_execution_plane() -> TuringExecutionPlane:
    """Return the process-local canonical execution composition."""
    return _execution_plane


def reset_execution_plane() -> TuringExecutionPlane:
    """Replace process-local execution composition; used for test isolation."""
    global _execution_plane
    _execution_plane = TuringExecutionPlane()
    return _execution_plane


__all__ = ["TuringExecutionPlane", "get_execution_plane", "reset_execution_plane"]

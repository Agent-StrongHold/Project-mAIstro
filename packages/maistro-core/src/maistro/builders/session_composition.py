"""The shipped Builders local-session execution composition.

The interactive Builders TUI (``maistro.cli._builders_tui``) is the product
surface for local Builder runs. This module is that surface's execution
composition, kept free of TUI/framework imports so it has exactly one
identity that product code and closeout evidence both consume (#49/#459):

durable SQLite spine -> canonical ``BuilderPipeline`` -> one agent-turn
stage on the canonical Graph -> Run -> NodeRun -> Attempt spine.

Nothing here may grow a second execution authority: the pipeline always
carries the durable stores handed to it, so a local session cannot fall
back to evidence-free in-process execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from maistro.builders.graph import PipelineNode
from maistro.builders.pipeline import BuilderPipeline

__all__ = ["SessionSpine", "TurnDispatcher", "build_session_pipeline", "open_session_spine"]


class TurnRunnerProtocol(Protocol):
    """The agent-loop boundary the shipped composition dispatches through.

    ``maistro_bootstrap.builders.agent_loop.TurnRunner`` is the production
    implementation; the boundary is protocol-typed so the composition stays
    importable (and testable) without the bootstrap package installed.
    """

    async def execute_turn(self, messages: list[dict[str, Any]]) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class SessionSpine:
    """The durable execution spine one local Builders session executes on."""

    run_store: Any
    durable_store: Any
    workspace_id: str
    project_id: str


class TurnDispatcher:
    """Adapt one interactive agent turn to the canonical Builders stage seam."""

    def __init__(self, runner: TurnRunnerProtocol) -> None:
        self._runner = runner

    def supports(self, agent_name: str, node_name: str) -> bool:
        return True

    async def run(
        self,
        *,
        run_id: str,
        node_name: str,
        agent_name: str,
        prompt: str,
        context: dict[str, Any],
    ) -> Any:
        from maistro.builders.graph_executor import DispatchResult

        result = await self._runner.execute_turn(
            messages=[
                {"role": "system", "content": "You are a coding assistant."},
                {"role": "user", "content": prompt},
            ]
        )
        return DispatchResult(ok=True, output=str(result.get("content", "done")))


async def open_session_spine(connection: Any, *, workspace_id: str) -> SessionSpine:
    """Wire the durable spine a local Builders session executes on.

    The caller owns the ``aiosqlite`` connection (and its lifecycle); this
    factory only performs the supported wiring: the canonical execution
    spine for the session's Workspace and the durable Run store adapter the
    pipeline projects onto.
    """
    from maistro.graph.durable_runs import CanonicalDurableRunStore
    from maistro.runs.wiring import wire_execution_spine

    stores = await wire_execution_spine(connection, workspace_id=workspace_id)
    project_store, run_store, _admitter, _templates, _schedules, continuations = stores
    project = await project_store.root_for_workspace(workspace_id)
    durable_store = CanonicalDurableRunStore(run_store, continuations)
    return SessionSpine(
        run_store=run_store,
        durable_store=durable_store,
        workspace_id=workspace_id,
        project_id=project.project_id,
    )


def build_session_pipeline(runner: TurnRunnerProtocol, *, spine: SessionSpine) -> BuilderPipeline:
    """Construct the shipped one-turn Builders pipeline on a durable spine.

    This is the exact composition the Builders TUI runs per user turn: one
    ``chat_turn`` stage driven through the canonical executor with the
    session's durable stores, so every local turn leaves canonical
    Run/NodeRun/Attempt evidence.
    """
    return BuilderPipeline(
        TurnDispatcher(runner),
        nodes=[
            PipelineNode(
                name="chat_turn",
                agent_name="builder",
                prompt_template="{title}",
            )
        ],
        run_store=spine.run_store,
        durable_store=spine.durable_store,
        workspace_id=spine.workspace_id,
        project_id=spine.project_id,
    )

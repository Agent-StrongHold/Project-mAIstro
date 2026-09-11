"""Canonical execution seam for the shipped ``maistro builders`` client.

The interactive client still uses the bootstrap package's sandbox-aware
``TurnRunner`` for model/tool mechanics. This module makes that mechanics
runner a dispatcher for the same canonical Builders adapter used by the
pipeline, so a chat turn cannot become a second execution authority.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any
from uuid import uuid4

from maistro.builders.graph import PipelineGraph, PipelineNode, RunContext
from maistro.builders.graph_executor import (
    CanonicalGraphPipelineExecutor,
    DispatchResult,
    PipelineDispatcher,
)
from maistro.builders.pipeline import PipelineRun, PipelineStage
from maistro.graph.durable_runs import CanonicalDurableRunStore, InMemoryGraphContinuationStore
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.store import InMemoryRunStore, RunStore


class _TurnDispatcher(PipelineDispatcher):
    """Adapt one bootstrap TurnRunner call to a Builders stage dispatch."""

    def __init__(self, session: Any, config: Any, messages: list[dict[str, Any]], llm: Any) -> None:
        self._session = session
        self._config = config
        self._messages = messages
        self._llm = llm
        self.result: dict[str, Any] | None = None

    def supports(self, agent_name: str, node_name: str) -> bool:
        return node_name == "turn"

    async def run(
        self,
        *,
        run_id: str,
        node_name: str,
        agent_name: str,
        prompt: str,
        context: RunContext,
    ) -> DispatchResult:
        # Importing bootstrap lazily keeps maistro-core usable without the
        # optional interactive builders extra.
        agent_loop = import_module("maistro_bootstrap.builders.agent_loop")
        turn_runner = agent_loop.TurnRunner
        runner = turn_runner(session=self._session, config=self._config)
        if self._llm is not None:
            runner.set_llm(self._llm)
        self.result = await runner.execute_turn(messages=list(self._messages))
        content = self.result.get("content", "")
        return DispatchResult(ok=True, output=content if isinstance(content, str) else str(content))


@dataclass
class CanonicalBuilderTurnExecutor:
    """Run interactive Builder turns through canonical durable execution."""

    workspace_id: str
    project_id: str | None = None
    run_store: RunStore | None = None
    durable_store: CanonicalDurableRunStore | None = None
    actor_principal_id: str | None = None

    def __post_init__(self) -> None:
        self._project_store: InMemoryProjectScopeStore | None = None
        if self.run_store is None:
            self._project_store = InMemoryProjectScopeStore()
            self.run_store = InMemoryRunStore(project_store=self._project_store)
        if self.durable_store is None:
            assert self.run_store is not None
            self.durable_store = CanonicalDurableRunStore(
                self.run_store,
                InMemoryGraphContinuationStore(),
            )
        self.last_record: Any | None = None

    async def execute_turn(
        self,
        *,
        session: Any,
        config: Any,
        messages: list[dict[str, Any]],
        llm: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        if self.project_id is None:
            if self._project_store is None:
                raise ValueError("project_id is required when run_store is injected")
            self.project_id = (await self._project_store.create_root(self.workspace_id)).project_id
        assert self.run_store is not None
        assert self.durable_store is not None

        dispatcher = _TurnDispatcher(session, config, messages, llm)
        graph = PipelineGraph(
            [
                PipelineNode(
                    name="turn",
                    agent_name="builder-agent",
                    prompt_template="{prompt}",
                )
            ]
        )
        run_id = f"builder-turn-{uuid4().hex}"
        prompt = str(messages[-1].get("content", "")) if messages else ""
        run = PipelineRun(
            id=run_id,
            issue_number=0,
            title=prompt or "Interactive Builders turn",
            repo=str(getattr(session, "workspace_path", "") or ""),
            stages=[PipelineStage("turn", "builder-agent", "{prompt}")],
        )
        run.context.update({"prompt": prompt, "messages": messages})
        executor = CanonicalGraphPipelineExecutor(
            dispatcher,
            run_store=self.run_store,
            durable_store=self.durable_store,
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            actor_principal_id=self.actor_principal_id,
        )
        self.last_record = await executor.execute(graph, run)
        result = dict(dispatcher.result or {})
        result["canonical_run_id"] = run.canonical_run_id
        result["canonical_graph_id"] = run.canonical_graph_id
        return result


__all__ = ["CanonicalBuilderTurnExecutor"]

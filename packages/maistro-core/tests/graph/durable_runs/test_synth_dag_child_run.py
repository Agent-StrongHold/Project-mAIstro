"""Canonical child-Run coverage for `agent.synth_dag` (#520)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from maistro.graph.definitions import Graph, Node
from maistro.graph.durable_runs import InMemoryDurableRunStore, RunStatus, run_durable_graph
from maistro.graph.nodes.agent_synth_dag import AgentSynthDagNode
from maistro.graph.synth import SynthRequest, SynthResult
from maistro.graph.types import AgentRole, GraphConfig, PlanOutput
from maistro.security.dag_shape.proportionality import ProportionalityVerdict


class _AlwaysJustified:
    async def judge(self, shape: Any) -> ProportionalityVerdict:
        return ProportionalityVerdict(justified=True, reason="focused child graph")


class _OneRoleSynthesizer:
    async def synthesize(self, request: SynthRequest) -> SynthResult:
        config = GraphConfig(nodes=[AgentRole.PLANNER], edges=[], entry=AgentRole.PLANNER)
        return SynthResult(
            graph_config=config,
            rationale="one canonical child role is sufficient",
            synthesized_kinds=[AgentRole.PLANNER.value],
        )


class _RecursiveSynthesizer:
    async def synthesize(self, request: SynthRequest) -> SynthResult:
        config = GraphConfig(nodes=["agent.synth_dag"], edges=[], entry="agent.synth_dag")
        return SynthResult(
            graph_config=config,
            rationale="exercise the hard recursion boundary",
            synthesized_kinds=["agent.synth_dag"],
        )


async def _planner_llm(messages: list[dict[str, str]], **kwargs: Any) -> str:
    return PlanOutput(summary="child complete", subtasks=[], estimated_files=[]).model_dump_json()


def _parent_graph() -> Graph:
    return Graph(
        workspace_id="workspace-520",
        project_id="project-520",
        name="parent synth graph",
        nodes=[
            Node(
                node_id="synth",
                node_type="agent.synth_dag",
                parameters={"objective": "plan the child work"},
            )
        ],
        metadata={"entry_node": "synth"},
    )


async def test_synthesized_subgraph_is_canonical_child_run_with_attempts() -> None:
    store = InMemoryDurableRunStore()
    synth_node = AgentSynthDagNode(
        synthesizer=_OneRoleSynthesizer(),
        llm_call=_planner_llm,
        proportionality_judge=_AlwaysJustified(),
    )

    def resolver(node_id: str, graph: Graph) -> AgentSynthDagNode:
        spec = next(node for node in graph.nodes if node.node_id == node_id)
        assert spec.node_type == "agent.synth_dag"
        return synth_node

    parent = await run_durable_graph(_parent_graph(), store=store, node_resolver=resolver)
    assert parent.run.status is RunStatus.COMPLETED
    assert len(parent.node_runs) == 1
    assert len(parent.attempts) == 1

    parent_result = parent.node_runs[0].result
    assert parent_result is not None
    child_run_id = str(parent_result["child_run_id"])
    assert child_run_id

    child = await store.get(child_run_id)
    assert child is not None
    assert child.run.status is RunStatus.COMPLETED
    assert child.run.workspace_id == parent.run.workspace_id
    assert child.run.project_id == parent.run.project_id
    assert child.run.parent_run_id == parent.run_id
    assert child.run.parent_node_run_id == parent.node_runs[0].node_run_id
    assert child.run.provenance["admission_source"] == "graph.child_run"
    assert child.graph_state.blackboard_snapshot["metadata"]["synth_depth"] == 1

    assert len(child.node_runs) == 1
    assert child.node_runs[0].status is RunStatus.COMPLETED
    assert len(child.attempts) == 1
    assert child.attempts[0].node_run_id == child.node_runs[0].node_run_id
    assert child.attempts[0].status.value == "completed"


async def test_synth_depth_crosses_child_run_boundary_and_blocks_grandchild() -> None:
    store = InMemoryDurableRunStore()
    synth_node = AgentSynthDagNode(
        synthesizer=_RecursiveSynthesizer(),
        llm_call=_planner_llm,
        proportionality_judge=_AlwaysJustified(),
        max_depth=1,
    )

    def resolver(node_id: str, graph: Graph) -> AgentSynthDagNode:
        spec = next(node for node in graph.nodes if node.node_id == node_id)
        assert spec.node_type == "agent.synth_dag"
        return synth_node

    parent = await run_durable_graph(_parent_graph(), store=store, node_resolver=resolver)
    assert parent.run.status is RunStatus.COMPLETED

    runs = await store.list_for_project("project-520", limit=10)
    assert len(runs) == 2  # parent + one child; depth-1 child cannot create a grandchild
    child = next(record for record in runs if record.run.parent_run_id == parent.run_id)
    child_result = child.node_runs[0].result
    assert child_result is not None
    assert child_result["success"] is False
    assert child_result["dispatched"] is False
    assert "recursion depth cap reached" in str(child_result["error"])


def test_durable_graph_execution_tree_has_no_legacy_run_graph_callers() -> None:
    root = Path(__file__).resolve().parents[3] / "src" / "maistro" / "graph"
    offenders: list[str] = []
    for relative in ("durable_runs", "nodes"):
        for path in (root / relative).rglob("*.py"):
            if "run_graph(" in path.read_text():
                offenders.append(path.relative_to(root).as_posix())
    assert offenders == []

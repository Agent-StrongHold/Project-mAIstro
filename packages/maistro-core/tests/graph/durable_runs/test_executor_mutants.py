"""Mutation-sensitive tests for canonical durable graph execution."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel

from maistro.graph.definitions import Graph
from maistro.graph.durable_runs import InMemoryDurableRunStore, RunStatus
from maistro.graph.durable_runs.executor import (
    _actually_spawned,
    _build_ctx,
    _ensure_frontier_node_runs,
    _initial_inputs,
    _maybe_increment_synth_depth,
    _new_run,
    _result_output,
    _walk,
    run_durable_graph,
)
from maistro.graph.nodes import BaseNode, NodeContext
from maistro.graph.nodes.base import NodeResult
from maistro.runs.lifecycle import transition_node_run
from maistro.runs.model import NodeRun

from .._canonical_helpers import durable_record, graph_from_dag


class _In(BaseModel):
    text: str = "x"


class _Out(BaseModel):
    text: str


class _SynthOut(BaseModel):
    success: bool = False
    dispatched: bool = False


class _EchoNode(BaseNode[_In, _Out]):
    kind: ClassVar[str] = "test.executor_mutants.echo"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        return _Out(text=inputs.text)


class _CountingNode(_EchoNode):
    kind: ClassVar[str] = "test.executor_mutants.counting"
    runs: ClassVar[int] = 0

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        type(self).runs += 1
        return await super()._execute(inputs, ctx)


def _resolver(node_id: str, graph: Graph) -> BaseNode[Any, Any]:
    node = next(item for item in graph.nodes if item.node_id == node_id)
    if node.node_type == _CountingNode.kind:
        return _CountingNode()
    return _EchoNode()


def _one_node_graph(kind: str = _EchoNode.kind) -> Graph:
    return graph_from_dag(
        {
            "id": "one",
            "nodes": [{"id": "n1", "kind": kind, "inputs": {"text": "hi"}}],
            "edges": [],
            "entry_node": "n1",
        }
    )


def _cycle_dag(kind: str = _CountingNode.kind) -> dict[str, Any]:
    return {
        "id": "cycle",
        "nodes": [
            {"id": "n1", "kind": kind, "inputs": {"text": "a"}},
            {"id": "n2", "kind": kind, "inputs": {"text": "b"}},
        ],
        "edges": [
            {"from_node": "n1", "to_node": "n2"},
            {"from_node": "n2", "to_node": "n1"},
        ],
        "entry_node": "n1",
    }


class TestStepBudget:
    async def test_budget_runs_exactly_max_steps_nodes(self) -> None:
        _CountingNode.runs = 0
        store = InMemoryDurableRunStore()
        record = durable_record(
            _cycle_dag(),
            run_id="r-budget",
            active_node_id="n1",
        )
        await store.create(record)
        result = await _walk(record, store=store, node_resolver=_resolver, max_steps=3)
        assert result.status is RunStatus.FAILED
        assert _CountingNode.runs == 3
        assert result.run.error is not None
        assert "max_steps=3" in result.run.error

    async def test_default_step_budget_is_256(self) -> None:
        _CountingNode.runs = 0
        store = InMemoryDurableRunStore()
        record = durable_record(
            _cycle_dag(),
            run_id="r-default",
            active_node_id="n1",
        )
        await store.create(record)
        result = await _walk(record, store=store, node_resolver=_resolver)
        assert result.status is RunStatus.FAILED
        assert _CountingNode.runs == 256
        assert result.run.error is not None
        assert "max_steps=256" in result.run.error


class TestCanonicalNodeRunCreation:
    async def test_fresh_node_creates_running_node_run_and_visit(self) -> None:
        store = InMemoryDurableRunStore()
        record = durable_record(
            {"id": "one", "nodes": [{"id": "n1", "kind": _EchoNode.kind}], "edges": []},
            run_id="r-fresh",
            active_node_id="n1",
            version=2,
        )
        await store.create(record)
        updated, node_runs = await _ensure_frontier_node_runs(record, ("n1",), store=store)
        node_run = node_runs[0]
        assert updated.version == 3
        assert node_run.ordinal == 1
        assert node_run.status is RunStatus.RUNNING
        assert updated.graph_state.visit_counts == {"n1": 1}

    async def test_waiting_node_run_is_reused_without_new_visit(self) -> None:
        node_run = NodeRun(run_id="r-reuse", node_id="n1", ordinal=1)
        node_run = transition_node_run(node_run, RunStatus.QUEUED)
        node_run = transition_node_run(node_run, RunStatus.RUNNING)
        node_run = transition_node_run(node_run, RunStatus.WAITING)
        record = durable_record(
            {"id": "one", "nodes": [{"id": "n1", "kind": _EchoNode.kind}], "edges": []},
            run_id="r-reuse",
            status=RunStatus.WAITING,
            active_node_id="n1",
            node_runs=(node_run,),
            version=4,
        )
        store = InMemoryDurableRunStore()
        await store.create(record)
        updated, node_runs = await _ensure_frontier_node_runs(record, ("n1",), store=store)
        resumed = node_runs[0]
        assert resumed.node_run_id == node_run.node_run_id
        assert resumed.status is RunStatus.RUNNING
        assert len(updated.node_runs) == 1
        assert updated.version == 5

    async def test_completed_prior_visit_creates_second_ordinal(self) -> None:
        node_run = NodeRun(run_id="r-repeat", node_id="n1", ordinal=1)
        node_run = transition_node_run(node_run, RunStatus.QUEUED)
        node_run = transition_node_run(node_run, RunStatus.RUNNING)
        node_run = transition_node_run(node_run, RunStatus.COMPLETED, result={"text": "old"})
        record = durable_record(
            {"id": "one", "nodes": [{"id": "n1", "kind": _EchoNode.kind}], "edges": []},
            run_id="r-repeat",
            active_node_id="n1",
            node_runs=(node_run,),
        )
        store = InMemoryDurableRunStore()
        await store.create(record)
        updated, node_runs = await _ensure_frontier_node_runs(record, ("n1",), store=store)
        repeated = node_runs[0]
        assert repeated.node_run_id != node_run.node_run_id
        assert repeated.ordinal == 2
        assert len(updated.node_runs) == 2


class TestResultOutput:
    def test_result_output_preserves_mapping(self) -> None:
        payload = {"text": "a"}
        assert _result_output(NodeResult(success=True, output=payload)) == payload

    def test_result_output_serializes_pydantic_model(self) -> None:
        assert _result_output(NodeResult(success=True, output=_Out(text="a"))) == {"text": "a"}


class TestSynthDepth:
    def test_synth_depth_increments_exactly_once_from_three(self) -> None:
        record = durable_record(
            {"id": "one", "nodes": [{"id": "n1", "kind": "agent.synth_dag"}], "edges": []},
            run_id="r-depth",
            blackboard_snapshot={"metadata": {"synth_depth": 3}},
        )
        spec = record.run.graph.materialize().nodes[0]
        updated = _maybe_increment_synth_depth(
            record,
            spec,
            NodeResult(success=True, output=_SynthOut(success=True)),
        )
        assert updated.graph_state.blackboard_snapshot["metadata"]["synth_depth"] == 4

    def test_refused_synth_does_not_count_as_spawn(self) -> None:
        result = NodeResult(success=True, output=_SynthOut(success=False, dispatched=False))
        assert _actually_spawned("agent.synth_dag", result) is False

    def test_dispatched_failed_synth_counts_as_spawn(self) -> None:
        result = NodeResult(success=True, output=_SynthOut(success=False, dispatched=True))
        assert _actually_spawned("agent.synth_dag", result) is True

    def test_missing_synth_flags_default_to_spawned(self) -> None:
        result = NodeResult(success=True, output=_Out(text="x"))
        assert _actually_spawned("agent.synth_dag", result) is True

    def test_non_synth_kind_counts_unconditionally(self) -> None:
        result = NodeResult(success=True, output=_SynthOut(success=False, dispatched=False))
        assert _actually_spawned("agent.spawn_harness", result) is True

    def test_missing_synth_depth_reads_as_zero(self) -> None:
        record = durable_record(
            {"id": "one", "nodes": [{"id": "n1", "kind": _EchoNode.kind}], "edges": []},
            run_id="r-nodepth",
            blackboard_snapshot={"metadata": {"other": 1}},
        )
        assert _build_ctx(record, "n1").metadata["synth_depth"] == 0


class TestInitialInputsAndIdentity:
    def test_initial_inputs_are_copied_from_graph_state_metadata(self) -> None:
        record = durable_record(
            {"id": "one", "nodes": [{"id": "n1", "kind": _EchoNode.kind}], "edges": []},
            run_id="r-inputs",
            metadata={"initial_inputs": {"text": "hi"}, "hitl_answers": {}},
        )
        assert _initial_inputs(record) == {"text": "hi"}

    def test_generated_canonical_run_id_is_full_uuid_hex(self) -> None:
        run = _new_run(_one_node_graph(), run_id=None, actor_principal_id=None)
        assert len(run.run_id) == 32
        int(run.run_id, 16)

    def test_explicit_run_id_is_preserved(self) -> None:
        run = _new_run(_one_node_graph(), run_id="explicit", actor_principal_id="alice")
        assert run.run_id == "explicit"
        assert run.actor_principal_id == "alice"

    async def test_public_run_persists_canonical_result(self) -> None:
        store = InMemoryDurableRunStore()
        result = await run_durable_graph(
            _one_node_graph(),
            store=store,
            node_resolver=_resolver,
            inputs={"text": "hi"},
        )
        assert result.status is RunStatus.COMPLETED
        assert result.run.result == {"text": "hi"}
        assert result.node_runs[0].result == {"text": "hi"}

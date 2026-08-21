"""Gap and mutation-sensitive coverage for canonical durable graph execution."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph.definitions import Graph
from maistro.graph.durable_runs import InMemoryDurableRunStore, RunStatus
from maistro.graph.durable_runs.executor import (
    _build_ctx,
    _ensure_frontier_node_runs,
    _entry_node,
    _mark_completed,
    _mark_failed,
    _next_node,
    _node_spec,
    _walk,
    resume_durable_graph,
)
from maistro.graph.nodes import BaseNode, NodeContext
from maistro.graph.nodes.base import NodeResult
from maistro.runs.lifecycle import transition_node_run
from maistro.runs.model import NodeRun

from .._canonical_helpers import durable_record, graph_from_dag


class _EchoIn(BaseModel):
    text: str = "x"


class _EchoOut(BaseModel):
    text: str


class _EchoNode(BaseNode[_EchoIn, _EchoOut]):
    kind: ClassVar[str] = "test.executor_gaps.echo"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _EchoIn
    output_schema: ClassVar[type[BaseModel]] = _EchoOut

    async def _execute(self, inputs: _EchoIn, ctx: NodeContext) -> _EchoOut:
        return _EchoOut(text=inputs.text)


def _resolver(node_id: str, graph: Graph) -> _EchoNode:
    assert _node_spec(graph, node_id) is not None
    return _EchoNode()


def _record_for(
    run_id: str,
    *,
    dag: dict[str, Any] | None = None,
    status: RunStatus = RunStatus.RUNNING,
    active_node_id: str | None = None,
    node_runs: tuple[NodeRun, ...] = (),
    blackboard_snapshot: dict[str, Any] | None = None,
    version: int = 1,
):  # type: ignore[no-untyped-def]
    fixture = dag or {
        "id": "d1",
        "nodes": [{"id": "n1", "kind": _EchoNode.kind}],
        "edges": [],
    }
    return durable_record(
        fixture,
        run_id=run_id,
        status=status,
        active_node_id=active_node_id,
        node_runs=node_runs,
        blackboard_snapshot=blackboard_snapshot,
        version=version,
    )


class TestResumeDurableGraphGuards:
    async def test_missing_run_raises_key_error(self) -> None:
        store = InMemoryDurableRunStore()
        with pytest.raises(KeyError, match="no such run"):
            await resume_durable_graph("nope", store=store, node_resolver=_resolver)

    async def test_completed_run_raises_value_error(self) -> None:
        store = InMemoryDurableRunStore()
        await store.create(_record_for("r-completed", status=RunStatus.COMPLETED))
        with pytest.raises(ValueError, match="cannot resume run"):
            await resume_durable_graph("r-completed", store=store, node_resolver=_resolver)

    async def test_paused_hitl_requires_answer_before_resume(self) -> None:
        store = InMemoryDurableRunStore()
        await store.create(_record_for("r-paused", status=RunStatus.PAUSED, active_node_id="n1"))
        with pytest.raises(ValueError, match="receive an answer"):
            await resume_durable_graph("r-paused", store=store, node_resolver=_resolver)

    async def test_waiting_empty_frontier_resumes_and_completes(self) -> None:
        store = InMemoryDurableRunStore()
        await store.create(_record_for("r-waiting", status=RunStatus.WAITING))
        result = await resume_durable_graph("r-waiting", store=store, node_resolver=_resolver)
        assert result.status is RunStatus.COMPLETED


class TestEntryNode:
    def test_explicit_entry_node_wins(self) -> None:
        graph = graph_from_dag(
            {
                "entry_node": "start",
                "nodes": [{"id": "other"}, {"id": "start"}],
                "edges": [],
            }
        )
        assert _entry_node(graph) == "start"

    def test_first_root_is_used_without_explicit_entry(self) -> None:
        graph = graph_from_dag(
            {
                "nodes": [{"id": "downstream"}, {"id": "root"}],
                "edges": [{"from_node": "root", "to_node": "downstream"}],
            }
        )
        assert _entry_node(graph) == "root"

    def test_no_nodes_raises_value_error(self) -> None:
        graph = graph_from_dag({"nodes": [], "edges": []})
        with pytest.raises(ValueError, match="no nodes"):
            _entry_node(graph)

    def test_unknown_explicit_entry_is_rejected(self) -> None:
        graph = graph_from_dag({"entry_node": "missing", "nodes": [{"id": "n1"}], "edges": []})
        with pytest.raises(ValueError, match="does not exist"):
            _entry_node(graph)


class TestNodeSpecAndRouting:
    def test_no_matching_node_returns_none(self) -> None:
        graph = graph_from_dag({"nodes": [{"id": "a"}], "edges": []})
        assert _node_spec(graph, "b") is None

    def test_unmatched_conditional_edges_do_not_route(self) -> None:
        graph = graph_from_dag(
            {
                "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
                "edges": [
                    {"from_node": "a", "to_node": "b", "condition": "x == 1"},
                    {"from_node": "a", "to_node": "c", "condition": "x == 2"},
                ],
            }
        )
        target, decisions = _next_node(
            graph,
            "a",
            "node-run-a",
            NodeResult(success=True, status="completed", output=None),
        )
        assert target is None
        assert len(decisions) == 2
        assert all(not decision.selected for decision in decisions)

    def test_false_condition_falls_through_to_unconditional_edge(self) -> None:
        graph = graph_from_dag(
            {
                "nodes": [{"id": "a"}, {"id": "guarded"}, {"id": "plain"}],
                "edges": [
                    {"from_node": "a", "to_node": "guarded", "condition": "x > 1"},
                    {"from_node": "a", "to_node": "plain"},
                ],
            }
        )
        target, decisions = _next_node(
            graph,
            "a",
            "node-run-a",
            NodeResult(success=True, output={}),
        )
        assert target == "plain"
        assert [decision.selected for decision in decisions] == [False, True]

    def test_no_outgoing_edges_returns_none_without_decisions(self) -> None:
        graph = graph_from_dag(
            {
                "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
                "edges": [{"from_node": "b", "to_node": "c"}],
            }
        )
        target, decisions = _next_node(
            graph,
            "a",
            "node-run-a",
            NodeResult(success=True, output={}),
        )
        assert target is None
        assert decisions == ()


class TestContextAndBlackboard:
    def test_malformed_blackboard_snapshot_falls_back_to_none(self) -> None:
        record = _record_for(
            "r-ctx",
            blackboard_snapshot={"metadata": "not-a-dict-and-not-iterable-pairs"},
        )
        ctx = _build_ctx(record, "n1")
        assert ctx.blackboard is None
        assert ctx.metadata["synth_depth"] == 0


class TestStepBudgetExhaustion:
    @staticmethod
    def _cycle_dag() -> dict[str, Any]:
        return {
            "id": "cycle-dag",
            "nodes": [
                {"id": "n1", "kind": _EchoNode.kind, "inputs": {"text": "hello"}},
                {"id": "n2", "kind": _EchoNode.kind, "inputs": {"text": "b"}},
            ],
            "edges": [
                {"from_node": "n1", "to_node": "n2"},
                {"from_node": "n2", "to_node": "n1"},
            ],
            "entry_node": "n1",
        }

    async def test_cycling_graph_is_marked_failed_not_completed(self) -> None:
        store = InMemoryDurableRunStore()
        record = _record_for(
            "r-cycle",
            dag=self._cycle_dag(),
            active_node_id="n1",
        )
        await store.create(record)
        result = await _walk(record, store=store, node_resolver=_resolver, max_steps=8)
        assert result.status is RunStatus.FAILED
        assert result.run.error is not None
        assert result.run.error.startswith("StepBudgetExhausted:")
        assert "max_steps=8" in result.run.error

    async def test_graph_that_really_finishes_is_completed(self) -> None:
        store = InMemoryDurableRunStore()
        dag = {
            "id": "linear-dag",
            "nodes": [{"id": "n1", "kind": _EchoNode.kind, "inputs": {"text": "hi"}}],
            "edges": [],
            "entry_node": "n1",
        }
        record = _record_for("r-done", dag=dag, active_node_id="n1")
        await store.create(record)
        result = await _walk(record, store=store, node_resolver=_resolver, max_steps=8)
        assert result.status is RunStatus.COMPLETED


class TestCanonicalNodeRunPersistence:
    async def test_nonterminal_node_run_is_reused_on_resume(self) -> None:
        existing = NodeRun(run_id="r1", node_id="n1", ordinal=1)
        existing = transition_node_run(existing, RunStatus.QUEUED)
        existing = transition_node_run(existing, RunStatus.RUNNING)
        existing = transition_node_run(existing, RunStatus.WAITING)
        record = _record_for(
            "r1",
            status=RunStatus.WAITING,
            active_node_id="n1",
            node_runs=(existing,),
        )
        store = InMemoryDurableRunStore()
        await store.create(record)

        updated, node_runs = await _ensure_frontier_node_runs(record, ("n1",), store=store)
        node_run = node_runs[0]
        assert node_run.node_run_id == existing.node_run_id
        assert node_run.status is RunStatus.RUNNING
        assert len(updated.node_runs) == 1

    async def test_terminal_prior_visit_creates_new_node_run(self) -> None:
        existing = NodeRun(run_id="r1", node_id="n1", ordinal=1)
        existing = transition_node_run(existing, RunStatus.QUEUED)
        existing = transition_node_run(existing, RunStatus.RUNNING)
        existing = transition_node_run(existing, RunStatus.COMPLETED, result={"text": "old"})
        record = _record_for(
            "r1",
            active_node_id="n1",
            node_runs=(existing,),
        )
        store = InMemoryDurableRunStore()
        await store.create(record)

        updated, node_runs = await _ensure_frontier_node_runs(record, ("n1",), store=store)
        node_run = node_runs[0]
        assert node_run.node_run_id != existing.node_run_id
        assert node_run.ordinal == 2
        assert node_run.status is RunStatus.RUNNING
        assert len(updated.node_runs) == 2
        assert updated.graph_state.visit_counts["n1"] == 1


class TestCheckpointVersionAndErrors:
    async def test_mark_completed_bumps_version_by_exactly_one(self) -> None:
        store = InMemoryDurableRunStore()
        record = _record_for("r-ver", version=7)
        await store.create(record)
        result = await _mark_completed(record, store=store)
        assert result.version == 8
        assert result.status is RunStatus.COMPLETED
        assert result.active_node_id is None

    async def test_mark_failed_bumps_version_by_exactly_one(self) -> None:
        store = InMemoryDurableRunStore()
        record = _record_for("r-ver-f", version=2)
        await store.create(record)
        result = await _mark_failed(
            record,
            error_code="X",
            error_message="boom",
            store=store,
        )
        assert result.version == 3
        assert result.status is RunStatus.FAILED
        assert result.run.error == "X: boom"

    async def test_error_message_is_truncated_to_exactly_512_chars(self) -> None:
        store = InMemoryDurableRunStore()
        record = _record_for("r-long")
        await store.create(record)
        result = await _mark_failed(
            record,
            error_code="X",
            error_message="z" * 5_000,
            store=store,
        )
        assert result.run.error is not None
        assert len(result.run.error) == 512

    async def test_short_error_message_is_not_padded_or_trimmed(self) -> None:
        store = InMemoryDurableRunStore()
        record = _record_for("r-short")
        await store.create(record)
        result = await _mark_failed(
            record,
            error_code="X",
            error_message="short",
            store=store,
        )
        assert result.run.error == "X: short"

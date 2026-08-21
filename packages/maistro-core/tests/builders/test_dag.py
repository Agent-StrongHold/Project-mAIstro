"""Tests for maistro.builders.dag — SPEC-070226-82ea (ADR-099).

Covers: full pipeline run to approval, gate-failure loop-back to the correct
stage, max-iteration termination (never hangs), coverage-gate branching, the
review gate's approve vs needs-changes paths, DAG validation, and conversion
to the ADR-062 GraphSpec.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from maistro.builders.dag import (
    BuildersDAG,
    Gate,
    StageResult,
    StageSpec,
    builders_dag_to_graph,
    coverage_gate,
    default_builders_dag,
    review_gate,
    run_builders_dag,
    to_pipeline_graph,
)
from maistro.builders.graph import RunContext
from maistro.builders.graph_executor import DispatchResult
from maistro.graph.node import IterationBudget
from maistro.graph.types import AgentRole, GraphConfig


class ScriptedDispatcher:
    """Dispatcher returning scripted outputs per node, per call.

    ``script[node]`` is a list of outputs consumed one per call; the last
    entry repeats once exhausted. ``context_writes[node]`` is a list of dicts
    merged into the run context on each call (simulating hooks that record
    coverage or approval metrics).
    """

    def __init__(
        self,
        script: dict[str, list[str]] | None = None,
        context_writes: dict[str, list[dict[str, Any]]] | None = None,
        fail_nodes: set[str] | None = None,
    ) -> None:
        self.script = script or {}
        self.context_writes = context_writes or {}
        self.fail_nodes = fail_nodes or set()
        self.calls: list[str] = []

    def supports(self, agent_name: str, node_name: str) -> bool:
        return True

    async def run(
        self,
        *,
        run_id: str,
        node_name: str,
        agent_name: str,
        prompt: str,
        context: RunContext,
    ) -> DispatchResult:
        self.calls.append(node_name)
        if node_name in self.fail_nodes:
            return DispatchResult(ok=False, error=f"{node_name} exploded")
        n = self.calls.count(node_name) - 1
        outputs = self.script.get(node_name, [f"{node_name} output"])
        output = outputs[min(n, len(outputs) - 1)]
        writes = self.context_writes.get(node_name)
        if writes:
            context.update(writes[min(n, len(writes) - 1)])
        return DispatchResult(ok=True, output=output)

    def count(self, node: str) -> int:
        return self.calls.count(node)


def run(coro: Any) -> Any:
    return asyncio.run(asyncio.wait_for(coro, timeout=10))


# ── Full pipeline ────────────────────────────────────────────────────────────


def test_full_pipeline_runs_to_approval() -> None:
    dag = default_builders_dag()
    dispatcher = ScriptedDispatcher(
        script={"review": ["APPROVED"]},
        context_writes={"test": [{"coverage": 95}]},
    )
    result = run(run_builders_dag(dag, dispatcher, params={"title": "Add widget"}))

    assert result.ok
    assert result.failure is None
    assert result.run.status == "completed"
    assert result.output == "APPROVED"  # terminal stage is review
    # First pass: revise skipped, each other stage ran exactly once.
    assert dispatcher.calls == ["design", "test", "implement", "review"]
    assert result.run.skipped_stages == ["revise"]
    assert result.run.revisions == {}


def test_full_pipeline_output_and_context() -> None:
    dag = default_builders_dag()
    dispatcher = ScriptedDispatcher(
        script={"design": ["the spec"], "implement": ["the code"], "review": ["LGTM"]},
        context_writes={"test": [{"coverage": 100}]},
    )
    result = run(run_builders_dag(dag, dispatcher, params={"title": "T"}))
    assert result.ok
    assert result.run.context["design"] == "the spec"
    assert result.run.context["implement"] == "the code"


# ── Review gate: approve vs needs-changes ────────────────────────────────────


def test_review_needs_changes_loops_back_to_revise() -> None:
    dag = default_builders_dag()
    dispatcher = ScriptedDispatcher(
        script={"review": ["Violation: no error handling", "APPROVED"]},
        context_writes={"test": [{"coverage": 90}]},
    )
    result = run(run_builders_dag(dag, dispatcher, params={"title": "T"}))

    assert result.ok
    # Second pass re-runs the revise target and its descendants.
    assert dispatcher.calls == [
        "design",
        "test",
        "implement",
        "review",  # needs changes → loop back to revise
        "revise",
        "test",
        "implement",
        "review",  # approved
    ]
    assert dispatcher.count("design") == 1  # ancestor of revise is untouched
    assert result.run.revisions == {"review": 1}
    # Feedback was injected for the revise pass.
    assert result.run.context["review_feedback"] == "Violation: no error handling"


def test_review_gate_prefers_explicit_boolean() -> None:
    gate = review_gate()
    approved = StageResult(stage="review", output="looks bad", context={"approved": True})
    rejected = StageResult(stage="review", output="APPROVED", context={"approved": False})
    assert gate.predicate(approved) is True
    assert gate.predicate(rejected) is False


def test_review_gate_text_fallback() -> None:
    gate = review_gate()
    assert gate.predicate(StageResult(stage="review", output="LGTM!", context={})) is True
    assert gate.predicate(StageResult(stage="review", output="2 violations", context={})) is False


def test_review_gate_exhausted_continue_completes_run() -> None:
    # Default review gate policy is "continue": after max_iterations failed
    # reviews the run force-forwards instead of failing (escalation path).
    dag = default_builders_dag(review=review_gate(max_iterations=2, exhausted="continue"))
    dispatcher = ScriptedDispatcher(
        script={"review": ["Violation: bad"]},
        context_writes={"test": [{"coverage": 90}]},
    )
    result = run(run_builders_dag(dag, dispatcher, params={"title": "T"}))
    assert result.ok
    assert result.run.status == "completed"
    assert "review" in result.run.gate_exhausted
    assert dispatcher.count("review") == 3  # initial + 2 revisions


# ── Max-iteration termination (never hangs) ──────────────────────────────────


def test_max_iterations_terminates_with_gate_exhausted_failure() -> None:
    dag = default_builders_dag(review=review_gate(max_iterations=2, exhausted="fail"))
    dispatcher = ScriptedDispatcher(
        script={"review": ["Violation: always bad"]},
        context_writes={"test": [{"coverage": 90}]},
    )
    result = run(run_builders_dag(dag, dispatcher, params={"title": "T"}))

    assert not result.ok
    assert result.failure is not None
    assert result.failure.kind == "gate_exhausted"
    assert result.failure.stage == "review"
    # iterations never exceed the limit: initial pass + max_iterations revisions
    assert dispatcher.count("review") == 3
    assert result.run.revisions["review"] == 2


@pytest.mark.parametrize("max_iterations", [0, 1, 2, 3])
def test_loop_never_exceeds_iteration_limit(max_iterations: int) -> None:
    dag = default_builders_dag(review=review_gate(max_iterations=max_iterations, exhausted="fail"))
    dispatcher = ScriptedDispatcher(
        script={"review": ["Violation"]},
        context_writes={"test": [{"coverage": 90}]},
    )
    result = run(run_builders_dag(dag, dispatcher, params={"title": "T"}))
    assert not result.ok
    assert dispatcher.count("review") == 1 + max_iterations


def test_tiny_budget_halts_run() -> None:
    dag = default_builders_dag()
    dispatcher = ScriptedDispatcher(context_writes={"test": [{"coverage": 90}]})
    result = run(
        run_builders_dag(
            dag, dispatcher, params={"title": "T"}, budget=IterationBudget(max_iterations=2)
        )
    )
    assert not result.ok
    assert result.failure is not None
    assert result.failure.kind == "budget_exhausted"
    assert len(dispatcher.calls) <= 2


# ── Coverage gate branching ──────────────────────────────────────────────────


def test_coverage_below_threshold_loops_back_then_passes() -> None:
    dag = default_builders_dag(coverage=coverage_gate(80))
    dispatcher = ScriptedDispatcher(
        script={"review": ["APPROVED"]},
        context_writes={"test": [{"coverage": 55}, {"coverage": 92}]},
    )
    result = run(run_builders_dag(dag, dispatcher, params={"title": "T"}))

    assert result.ok
    # coverage 55 < 80 → loop back to revise; second test pass reports 92.
    assert dispatcher.calls == ["design", "test", "revise", "test", "implement", "review"]
    assert dispatcher.count("test") == 2
    assert dispatcher.count("revise") == 1
    assert dispatcher.count("implement") == 1  # implement only ran after gate passed
    assert result.run.revisions == {"test": 1}
    assert "test_feedback" in result.run.context


def test_coverage_at_or_above_threshold_proceeds() -> None:
    dag = default_builders_dag(coverage=coverage_gate(80))
    dispatcher = ScriptedDispatcher(
        script={"review": ["APPROVED"]},
        context_writes={"test": [{"coverage": 80}]},
    )
    result = run(run_builders_dag(dag, dispatcher, params={"title": "T"}))
    assert result.ok
    assert dispatcher.count("test") == 1


def test_coverage_gate_predicate_branching() -> None:
    gate = coverage_gate(80)
    low = StageResult(stage="test", output="", context={"coverage": 79.9})
    high = StageResult(stage="test", output="", context={"coverage": 80.0})
    missing = StageResult(stage="test", output="", context={})
    boolean = StageResult(stage="test", output="", context={"coverage": True})
    assert gate.predicate(low) is False
    assert gate.predicate(high) is True
    assert gate.predicate(missing) is True  # no measurement → not gated
    assert gate.predicate(boolean) is True  # bools aren't coverage figures


# ── Stage failure and validation ─────────────────────────────────────────────


def test_stage_failure_reports_typed_failure() -> None:
    dag = default_builders_dag()
    dispatcher = ScriptedDispatcher(fail_nodes={"implement"})
    result = run(run_builders_dag(dag, dispatcher, params={"title": "T"}))
    assert not result.ok
    assert result.failure is not None
    assert result.failure.kind == "stage_failed"
    assert result.failure.stage == "implement"
    assert "exploded" in result.failure.detail


def _stage(name: str, **kw: Any) -> StageSpec:
    return StageSpec(name=name, agent_name="a", prompt_template=name, **kw)


def test_validate_rejects_gate_without_loop_target() -> None:
    dag = BuildersDAG(
        stages=(_stage("a"), _stage("b")),
        edges=(("a", "b"),),
        gates={"b": review_gate()},
        loop_targets={},
    )
    errors = dag.validate()
    assert any("no loop_target" in e for e in errors)


def test_validate_rejects_non_ancestor_loop_target() -> None:
    dag = BuildersDAG(
        stages=(_stage("a"), _stage("b"), _stage("c")),
        edges=(("a", "b"),),
        gates={"b": review_gate()},
        loop_targets={"b": "c"},  # c is not an ancestor of b
    )
    errors = dag.validate()
    assert any("not an ancestor" in e for e in errors)


def test_validate_rejects_undeclared_and_duplicate_stages() -> None:
    dag = BuildersDAG(
        stages=(_stage("a"), _stage("a")),
        edges=(("a", "ghost"),),
    )
    errors = dag.validate()
    assert any("Duplicate" in e for e in errors)
    assert any("ghost" in e for e in errors)


def test_invalid_dag_fails_before_dispatch() -> None:
    dag = BuildersDAG(stages=(_stage("a"),), edges=(("a", "ghost"),))
    dispatcher = ScriptedDispatcher()
    result = run(run_builders_dag(dag, dispatcher))
    assert not result.ok
    assert result.failure is not None
    assert result.failure.kind == "invalid_graph"
    assert dispatcher.calls == []


def test_loop_target_on_ungated_stage_rejected() -> None:
    dag = BuildersDAG(
        stages=(_stage("a"), _stage("b")),
        edges=(("a", "b"),),
        loop_targets={"b": "a"},
    )
    assert any("ungated" in e for e in dag.validate())


# ── Gate iteration counter ───────────────────────────────────────────────────


def test_gate_sees_incrementing_iterations() -> None:
    seen: list[int] = []

    def pred(result: StageResult) -> bool:
        seen.append(result.iterations)
        return result.iterations >= 2  # pass on the third evaluation

    dag = default_builders_dag(review=Gate(name="g", predicate=pred, max_iterations=5))
    dispatcher = ScriptedDispatcher(context_writes={"test": [{"coverage": 90}]})
    result = run(run_builders_dag(dag, dispatcher, params={"title": "T"}))
    assert result.ok
    assert seen == [0, 1, 2]


# ── Lowering and ADR-062 conversion ──────────────────────────────────────────


def test_to_pipeline_graph_preserves_structure() -> None:
    dag = default_builders_dag()
    graph = to_pipeline_graph(dag)
    assert graph.validate() == []
    assert len(graph) == 5
    by_name = {n.name: n for n in graph}
    assert by_name["test"].depends_on == ("revise",)
    assert by_name["review"].revise_target == "revise"
    assert by_name["review"].gate is not None
    assert by_name["review"].gate_exhausted == "continue"
    assert by_name["design"].gate is None


def test_builders_dag_to_graph_spec() -> None:
    dag = default_builders_dag()
    spec = builders_dag_to_graph(dag)
    assert isinstance(spec, GraphConfig)
    assert spec.entry == AgentRole.PLANNER
    assert set(spec.nodes) == {AgentRole.PLANNER, AgentRole.CODER, AgentRole.REVIEWER}
    # Forward flow plus the conditional review→coder loop-back edge.
    conds = {(e.from_role, e.to_role, e.condition) for e in spec.edges}
    assert (AgentRole.PLANNER, AgentRole.CODER, None) in conds
    assert (AgentRole.CODER, AgentRole.REVIEWER, None) in conds
    assert (AgentRole.REVIEWER, AgentRole.CODER, "review.approved is False") in conds
    # Bounded iteration maps onto max_cycles.
    assert spec.max_cycles == 1 + max(g.max_iterations for g in dag.gates.values())


def test_terminal_stages() -> None:
    dag = default_builders_dag()
    assert dag.terminal_stages() == ("review",)
    assert dag.stage("design").agent_name == "quartermaster"
    with pytest.raises(KeyError):
        dag.stage("nope")

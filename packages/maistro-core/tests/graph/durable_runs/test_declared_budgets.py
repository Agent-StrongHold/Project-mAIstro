"""Declared execution-budget policy: cycles and per-node timeouts (#1184).

The claims proven here, against the canonical durable walker:

- A declared ``max_cycles`` graph budget bounds the traversal frontiers (the
  incumbent ``GraphConfig`` wave semantics) and changes execution behavior
  when its value changes: smaller budgets stop the walk strictly earlier.
  Exhaustion fails the Run with the budget named — never a truncation reported
  as success — and a budget covering the DAG's depth completes it.
- Out-of-envelope declared values are clamped by the bounded policy, and the
  effective value is what the Run reports.
- A declared per-node ``timeout_s`` becomes the canonical ExecutionRuntime
  deadline: the Attempt records ``deadline_at`` and settles ``TIMED_OUT`` when
  the runtime fires, so no product-side transport constant governs the
  deadline anymore. Changing the declared value changes whether work survives;
  out-of-envelope values clamp; undeclared nodes keep today's no-deadline
  behavior.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph.durable_runs import InMemoryDurableRunStore, RunStatus, attempt_executor
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes import BaseNode, NodeContext, get_node, register_node
from maistro.graph.policies import (
    DEFAULT_NODE_TIMEOUT_S,
    MAX_DAG_CYCLES,
    MAX_NODE_TIMEOUT_S,
    MIN_DAG_CYCLES,
    MIN_NODE_TIMEOUT_S,
    declared_dag_max_cycles,
    declared_node_timeout_s,
    resolve_max_cycles,
    resolve_node_timeout_s,
)
from maistro.runs.model import AttemptStatus
from maistro.runtime import PythonExecutionRuntime

from .._canonical_helpers import graph_from_dag, run_at_status

# ADR-100126-b118 claims these proofs as its behavioral contract evidence.
pytestmark = pytest.mark.contract("behavioral")

# --- policy resolution rules --------------------------------------------------


def test_resolve_max_cycles_clamps_into_the_published_envelope() -> None:
    assert resolve_max_cycles(1) == 1
    assert resolve_max_cycles(10) == 10
    assert resolve_max_cycles(999) == MAX_DAG_CYCLES
    assert resolve_max_cycles(0) == MIN_DAG_CYCLES
    assert resolve_max_cycles(-7) == MIN_DAG_CYCLES
    assert resolve_max_cycles(3.9) == 3
    assert resolve_max_cycles("7") == 7


def test_unreadable_cycle_declarations_buy_the_tightest_cap_not_the_loosest() -> None:
    assert resolve_max_cycles("abc") == MIN_DAG_CYCLES
    assert resolve_max_cycles(True) == MIN_DAG_CYCLES
    assert resolve_max_cycles(None) == MIN_DAG_CYCLES
    assert resolve_max_cycles(float("nan")) == MIN_DAG_CYCLES


def test_resolve_node_timeout_clamps_into_the_published_envelope() -> None:
    assert resolve_node_timeout_s(30) == 30.0
    assert resolve_node_timeout_s(0.2) == MIN_NODE_TIMEOUT_S
    assert resolve_node_timeout_s(10**6) == MAX_NODE_TIMEOUT_S
    assert resolve_node_timeout_s("45") == 45.0


def test_unreadable_or_nonpositive_timeouts_resolve_to_the_incumbent_default() -> None:
    # A garbage deadline falls back to the incumbent deadline instead of
    # terminating legitimate work early; a non-positive one cannot be honored
    # at all and gets the same answer.
    for garbage in ("abc", None, True, 0, -5, float("nan")):
        assert resolve_node_timeout_s(garbage) == DEFAULT_NODE_TIMEOUT_S


def test_declared_accessors_distinguish_declared_from_undeclared() -> None:
    assert declared_dag_max_cycles({}) is None
    assert declared_dag_max_cycles({"max_cycles": 999}) == MAX_DAG_CYCLES
    # The adapter-recorded spelling resolves to the same bounded budget.
    assert declared_dag_max_cycles({"max_cycles_effective": 999}) == MAX_DAG_CYCLES
    assert declared_node_timeout_s({}) is None
    assert declared_node_timeout_s({"timeout_s": 10**6}) == MAX_NODE_TIMEOUT_S
    # "declares nothing" is the walker's no-deadline state, never the default.
    assert declared_node_timeout_s({"max_attempts": 3}) is None


# --- fixtures -----------------------------------------------------------------


class _EmptyIn(BaseModel):
    pass


class _StepOut(BaseModel):
    step: str


class _ReviewOut(BaseModel):
    approved: bool


class _StepNode(BaseNode[_EmptyIn, _StepOut]):
    kind: ClassVar[str] = "test.budget.step"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _EmptyIn
    output_schema: ClassVar[type[BaseModel]] = _StepOut

    async def _execute(self, inputs: _EmptyIn, ctx: NodeContext) -> _StepOut:
        return _StepOut(step="ok")


class _NeverApproveNode(BaseNode[_EmptyIn, _ReviewOut]):
    kind: ClassVar[str] = "test.budget.never_approve"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _EmptyIn
    output_schema: ClassVar[type[BaseModel]] = _ReviewOut

    async def _execute(self, inputs: _EmptyIn, ctx: NodeContext) -> _ReviewOut:
        return _ReviewOut(approved=False)


class _SlowNode(BaseNode[_EmptyIn, _StepOut]):
    kind: ClassVar[str] = "test.budget.slow"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _EmptyIn
    output_schema: ClassVar[type[BaseModel]] = _StepOut

    sleep_s: ClassVar[float] = 1.2

    async def _execute(self, inputs: _EmptyIn, ctx: NodeContext) -> _StepOut:
        await asyncio.sleep(type(self).sleep_s)
        return _StepOut(step="slept")


for _cls in (_StepNode, _NeverApproveNode, _SlowNode):
    with contextlib.suppress(ValueError):
        register_node(_cls)


def _resolver(node_id: str, dag: dict[str, Any]) -> BaseNode[Any, Any]:
    for raw in dag["nodes"]:
        if raw["id"] == node_id:
            return get_node(raw["kind"])()
    raise KeyError(node_id)


def _endless_loop_dag(max_cycles: Any = None) -> dict[str, Any]:
    """A two-node loop whose back edge never stops selecting."""
    dag: dict[str, Any] = {
        "id": "budget-endless-loop",
        "name": "endless loop",
        "entry_node": "step",
        "nodes": [
            {"id": "step", "kind": _StepNode.kind},
            {"id": "review", "kind": _NeverApproveNode.kind},
        ],
        "edges": [
            {"id": "step-review", "from_node": "step", "to_node": "review"},
            {
                "id": "review-step",
                "from_node": "review",
                "to_node": "step",
                "condition": "approved == False",
            },
        ],
    }
    if max_cycles is not None:
        dag["metadata"] = {"max_cycles": max_cycles}
    return dag


def _linear_dag(max_cycles: Any = None) -> dict[str, Any]:
    """A four-node chain with no back edges — linear depth, zero re-entries."""
    dag: dict[str, Any] = {
        "id": "budget-linear",
        "name": "linear chain",
        "entry_node": "a",
        "nodes": [
            {"id": "a", "kind": _StepNode.kind},
            {"id": "b", "kind": _StepNode.kind},
            {"id": "c", "kind": _StepNode.kind},
            {"id": "d", "kind": _StepNode.kind},
        ],
        "edges": [
            {"id": "ab", "from_node": "a", "to_node": "b"},
            {"id": "bc", "from_node": "b", "to_node": "c"},
            {"id": "cd", "from_node": "c", "to_node": "d"},
        ],
    }
    if max_cycles is not None:
        dag["metadata"] = {"max_cycles": max_cycles}
    return dag


def _slow_linear_dag() -> dict[str, Any]:
    """A one-node chain whose body sleeps past a tight declared deadline."""
    return {
        "id": "budget-slow-linear",
        "name": "slow node",
        "entry_node": "a",
        "nodes": [{"id": "a", "kind": _SlowNode.kind}],
        "edges": [],
    }


def _slow_loop_dag() -> dict[str, Any]:
    """A loop whose body sleeps, so a declared deadline fires mid-loop."""
    return {
        "id": "budget-slow-loop",
        "name": "slow loop",
        "entry_node": "step",
        "nodes": [
            {"id": "step", "kind": _SlowNode.kind},
            {"id": "review", "kind": _NeverApproveNode.kind},
        ],
        "edges": [
            {"id": "step-review", "from_node": "step", "to_node": "review"},
            {
                "id": "review-step",
                "from_node": "review",
                "to_node": "step",
                "condition": "approved == False",
            },
        ],
    }


def _record(
    dag: dict[str, Any],
    *,
    run_id: str,
    policies: dict[str, dict[str, Any]] | None = None,
) -> DurableRunRecord:
    """Build a running durable envelope, optionally declaring node policies."""
    graph = graph_from_dag(dag)
    if policies:
        graph = graph.model_copy(
            update={
                "nodes": [
                    node.model_copy(update={"policies": policies.get(node.node_id, {})})
                    for node in graph.nodes
                ]
            }
        )
    run = run_at_status(graph, run_id=run_id)
    state = GraphExecutionState(
        run_id=run_id,
        active_node_ids=(str(dag["entry_node"]),),
        metadata={"initial_inputs": {}, "hitl_answers": {}},
    )
    return DurableRunRecord(run=run, graph_state=state, version=1)


async def _walk(dag: dict[str, Any], *, run_id: str, max_steps: int = 64, **kwargs: Any):
    store = InMemoryDurableRunStore()
    record = _record(dag, run_id=run_id, **kwargs)
    await store.create(record)
    return await asyncio.wait_for(
        attempt_executor._walk(
            record,
            store=store,
            node_resolver=lambda node_id, _graph: _resolver(node_id, dag),
            runtime=PythonExecutionRuntime(),
            max_steps=max_steps,
        ),
        timeout=30.0,
    )


# --- declared cycle budget ----------------------------------------------------


async def test_declared_cycle_budget_fails_the_loop_with_the_budget_named() -> None:
    result = await _walk(_endless_loop_dag(max_cycles=2), run_id="r-budget-2", max_steps=64)

    assert result.status is RunStatus.FAILED
    assert result.run.error is not None
    assert result.run.error.startswith("CycleBudgetExhausted:")
    assert "max_cycles=2" in result.run.error
    # Bounded waves, not an instant refusal: the loop body ran first.
    completed = [run for run in result.node_runs if run.status is RunStatus.COMPLETED]
    assert completed
    assert result.graph_state.cycle == 2


async def test_changing_the_declared_budget_changes_how_much_loop_work_runs() -> None:
    tight = await _walk(_endless_loop_dag(max_cycles=1), run_id="r-budget-1", max_steps=64)
    loose = await _walk(_endless_loop_dag(max_cycles=3), run_id="r-budget-3", max_steps=64)

    assert tight.status is RunStatus.FAILED
    assert loose.status is RunStatus.FAILED
    assert "max_cycles=1" in (tight.run.error or "")
    assert "max_cycles=3" in (loose.run.error or "")
    tight_runs = len(tight.node_runs)
    loose_runs = len(loose.node_runs)
    assert tight_runs < loose_runs, "the smaller budget must stop the loop strictly earlier"


async def test_a_budget_covering_the_depth_completes_a_loop_free_dag() -> None:
    # Four sequential nodes = four waves; a declared budget of exactly the
    # depth covers the work and the DAG completes.
    result = await _walk(_linear_dag(max_cycles=4), run_id="r-budget-linear-ok", max_steps=64)

    assert result.status is RunStatus.COMPLETED
    assert {run.node_id for run in result.node_runs} == {"a", "b", "c", "d"}


async def test_a_shallow_budget_fails_closed_naming_the_shortfall() -> None:
    # The incumbent GraphConfig semantics, enforced: two waves cannot cover a
    # four-node chain, and the Run says so instead of silently truncating.
    result = await _walk(_linear_dag(max_cycles=2), run_id="r-budget-linear-short", max_steps=64)

    assert result.status is RunStatus.FAILED
    assert (result.run.error or "").startswith("CycleBudgetExhausted:")
    assert "max_cycles=2" in (result.run.error or "")
    assert {run.node_id for run in result.node_runs} == {"a", "b"}


async def test_out_of_envelope_budgets_clamp_to_the_documented_bounds() -> None:
    huge = await _walk(_endless_loop_dag(max_cycles=999), run_id="r-budget-999", max_steps=64)
    garbage = await _walk(_endless_loop_dag(max_cycles="abc"), run_id="r-budget-garbage")

    assert huge.status is RunStatus.FAILED
    assert "max_cycles=20" in (huge.run.error or "")
    assert garbage.status is RunStatus.FAILED
    assert "max_cycles=1" in (garbage.run.error or "")


async def test_undeclared_budget_leaves_the_step_floor_as_the_only_bound() -> None:
    result = await _walk(_endless_loop_dag(), run_id="r-budget-none", max_steps=6)

    # No declared budget: the incumbent step-budget posture is unchanged.
    assert result.status is RunStatus.FAILED
    assert (result.run.error or "").startswith("StepBudgetExhausted:")


# --- declared per-node timeout ------------------------------------------------


async def test_declared_node_timeout_is_enforced_by_the_canonical_runtime() -> None:
    started = time.monotonic()
    result = await _walk(
        _slow_loop_dag(),
        run_id="r-timeout-declared",
        policies={"step": {"timeout_s": 1}},
    )
    elapsed = time.monotonic() - started

    assert result.status is RunStatus.FAILED
    assert (result.run.error or "").startswith("AttemptDeadlineExceeded:")
    timed_out = [
        attempt for attempt in result.attempts if attempt.status is AttemptStatus.TIMED_OUT
    ]
    assert timed_out, "the expired Attempt must settle TIMED_OUT"
    assert all(attempt.deadline_at is not None for attempt in timed_out)
    # The enforcement is the declared value, not the incumbent 120s constant.
    assert elapsed < 30.0


async def test_changing_the_declared_timeout_changes_whether_work_survives() -> None:
    tight = await _walk(
        _slow_loop_dag(),
        run_id="r-timeout-tight",
        policies={"step": {"timeout_s": 1}},
    )
    loose = await _walk(
        _slow_linear_dag(),
        run_id="r-timeout-loose",
        policies={"a": {"timeout_s": 10}},
    )

    assert tight.status is RunStatus.FAILED
    assert any(a.status is AttemptStatus.TIMED_OUT for a in tight.attempts)
    assert loose.status is RunStatus.COMPLETED
    assert all(a.deadline_at is not None for a in loose.attempts)


async def test_out_of_envelope_timeout_clamps_to_the_ceiling() -> None:
    result = await _walk(
        _slow_linear_dag(),
        run_id="r-timeout-clamp",
        policies={"a": {"timeout_s": 10**6}},
    )

    assert result.status is RunStatus.COMPLETED
    first = result.attempts[0]
    assert first.deadline_at is not None
    span = (first.deadline_at - first.created_at).total_seconds()
    assert MAX_NODE_TIMEOUT_S - 10 <= span <= MAX_NODE_TIMEOUT_S + 10


async def test_undeclared_timeout_keeps_the_no_deadline_behavior() -> None:
    result = await _walk(_slow_linear_dag(), run_id="r-timeout-undeclared")

    assert result.status is RunStatus.COMPLETED
    assert all(attempt.deadline_at is None for attempt in result.attempts)
    assert all(attempt.status is AttemptStatus.COMPLETED for attempt in result.attempts)

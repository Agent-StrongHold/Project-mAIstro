"""M8-D1 planning-strategy benchmark (#925): the recorded cells.

Every expectation below was pinned from a measured run of the deterministic
policy/world/harness, then kept as a regression pin: if any structure starts
spending more model calls, losing plan inspectability, or failing an
injection cell it used to survive, a pin here breaks and names the cell.

The benchmark compares structures, not model quality: all three arms run the
same competent policy (``_policy.PolicyModel``) over the same deterministic
world (``_world``) under one matched budget (``_harness.BenchBudget``).
"""

from __future__ import annotations

import pytest

from maistro.agents.strategies.plan_execute import PlanExecuteStrategy
from maistro.agents.strategies.react import ReactStrategy
from maistro.graph.node import IterationBudget
from maistro.graph.types import PlanOutput

from ._harness import (
    _RUNNERS,
    BUDGET,
    GRAPH,
    PLAN_EXECUTE,
    REACT,
    STRATEGIES,
    _new_cell,
    p95,
    run_cell,
    sweep,
)
from ._world import DEAD_END, build_corpus

CORPUS = {spec.goal_id: spec for spec in build_corpus()}

#: Pinned from the recorded baseline run (see
#: docs/research/925-planning-strategy-benchmark.md). llm_calls: React pays
#: one call per program step plus one final-answer turn; plan-and-execute
#: pays one planner call plus two calls per subtask loop (tool turn + close);
#: Graph pays a constant three (planner, coder, reviewer) whatever the
#: program length. tool_calls equal each Goal's minimal program everywhere.
PINNED_CLEAN_CELLS: dict[tuple[str, str], dict[str, int]] = {
    (REACT, "lookup-db-host"): {"llm_calls": 3, "tool_calls": 2},
    (PLAN_EXECUTE, "lookup-db-host"): {"llm_calls": 5, "tool_calls": 2},
    (GRAPH, "lookup-db-host"): {"llm_calls": 3, "tool_calls": 2},
    (REACT, "rotate-api-key"): {"llm_calls": 5, "tool_calls": 4},
    (PLAN_EXECUTE, "rotate-api-key"): {"llm_calls": 9, "tool_calls": 4},
    (GRAPH, "rotate-api-key"): {"llm_calls": 3, "tool_calls": 4},
    (REACT, "inventory-audit"): {"llm_calls": 6, "tool_calls": 5},
    (PLAN_EXECUTE, "inventory-audit"): {"llm_calls": 11, "tool_calls": 5},
    (GRAPH, "inventory-audit"): {"llm_calls": 3, "tool_calls": 5},
    (REACT, "ghost-dependency"): {"llm_calls": 2, "tool_calls": 1},
    (PLAN_EXECUTE, "ghost-dependency"): {"llm_calls": 3, "tool_calls": 1},
    (GRAPH, "ghost-dependency"): {"llm_calls": 3, "tool_calls": 1},
}


async def _cell(strategy: str, goal_id: str):
    return await run_cell(CORPUS[goal_id], strategy)


# --- the matrix: every Goal x every strategy succeeds within matched budgets


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("goal_id", list(CORPUS))
async def test_matrix_cell_succeeds_within_pinned_costs(strategy: str, goal_id: str) -> None:
    metrics = await _cell(strategy, goal_id)
    assert metrics.error is None, f"{strategy}/{goal_id} surfaced: {metrics.error}"
    assert metrics.success, f"{strategy}/{goal_id} did not achieve the Goal"
    assert metrics.recovered

    pinned = PINNED_CLEAN_CELLS[(strategy, goal_id)]
    assert metrics.llm_calls == pinned["llm_calls"], (
        f"{strategy}/{goal_id} model-call cost drifted: "
        f"{metrics.llm_calls} != pinned {pinned['llm_calls']}"
    )
    assert metrics.tool_calls == pinned["tool_calls"]
    assert metrics.wasted_tool_calls == 0
    assert metrics.llm_calls <= BUDGET.max_model_calls
    assert metrics.tool_calls <= BUDGET.max_tool_calls


async def test_every_cell_reports_tool_errors_from_the_shared_ledger() -> None:
    """Dead-end goals must show their one lookup error in every arm's ledger."""
    for goal_id in ("lookup-db-host", "ghost-dependency"):
        for strategy in STRATEGIES:
            metrics = await _cell(strategy, goal_id)
            expected_errors = 1 if CORPUS[goal_id].goal_class == DEAD_END else 0
            assert metrics.tool_errors == expected_errors, (
                f"{strategy}/{goal_id}: ledger recorded {metrics.tool_errors} errors"
            )


# --- structural cost findings


async def test_graph_cost_is_constant_while_loop_costs_scale_with_program() -> None:
    """The headline cost finding: Graph pays 3 model calls per Goal whatever
    the program length; the loop arms scale with it."""
    short = await _cell(GRAPH, "lookup-db-host")
    long = await _cell(GRAPH, "inventory-audit")
    assert short.llm_calls == long.llm_calls == 3

    react_short = await _cell(REACT, "lookup-db-host")
    react_long = await _cell(REACT, "inventory-audit")
    assert react_long.llm_calls > react_short.llm_calls

    plan_short = await _cell(PLAN_EXECUTE, "lookup-db-host")
    plan_long = await _cell(PLAN_EXECUTE, "inventory-audit")
    assert plan_long.llm_calls > plan_short.llm_calls

    # per-Goal: Graph is never more expensive than the loops on the long
    # program, and the loops are never more expensive than Graph on the
    # dead end (where Graph still pays its verification step).
    assert long.llm_calls <= react_long.llm_calls
    assert long.llm_calls <= plan_long.llm_calls


async def test_only_graph_carries_a_verification_step() -> None:
    for goal_id in CORPUS:
        graph = await _cell(GRAPH, goal_id)
        assert graph.verification_steps == 1, goal_id
        assert graph.run_success is True
        assert graph.detail["graph_phase"] == "completed"
        for loop_arm in (REACT, PLAN_EXECUTE):
            metrics = await _cell(loop_arm, goal_id)
            assert metrics.verification_steps == 0, f"{loop_arm}/{goal_id}"


# --- dead-end behavior: report, never guess


@pytest.mark.parametrize("strategy", STRATEGIES)
async def test_dead_end_is_reported_not_guessed(strategy: str) -> None:
    metrics = await _cell(strategy, "ghost-dependency")
    assert metrics.success
    assert metrics.tool_errors == 1
    assert metrics.wasted_tool_calls == 0


# --- plan inspectability: what can an operator read before execution?


async def test_plan_inspectability_differs_by_structure() -> None:
    """Graph exposes a typed plan object; plan-and-execute a parseable plan
    text; ReAct ships no plan artifact at all."""
    for goal_id in ("rotate-api-key", "inventory-audit"):
        spec = CORPUS[goal_id]
        react = await _cell(REACT, goal_id)
        assert react.plan_artifact == "none"
        assert react.plan_steps == 0

        plan_exec = await _cell(PLAN_EXECUTE, goal_id)
        assert plan_exec.plan_artifact == "text"
        assert plan_exec.plan_steps == spec.minimal_tool_calls

        graph = await _cell(GRAPH, goal_id)
        assert graph.plan_artifact == "structured"
        assert graph.plan_steps == spec.minimal_tool_calls
        # the structured plan is a real typed model, not a string
        assert isinstance(graph.detail["plan_output"], PlanOutput)


# --- recovery after injected failure


async def _cell_with_tool_fault(strategy: str):
    spec = CORPUS["rotate-api-key"]
    world, policy = _new_cell(spec, strategy=strategy)
    world.ledger.fail_next_lookup("secrets.api.current", times=1)
    return await _RUNNERS[strategy](spec, world, policy)


@pytest.mark.parametrize("strategy", STRATEGIES)
async def test_transient_tool_fault_is_recovered_by_every_structure(
    strategy: str,
) -> None:
    metrics = await _cell_with_tool_fault(strategy)
    assert metrics.recovered, f"{strategy} did not recover: {metrics.error}"
    assert metrics.success
    assert metrics.tool_errors == 1
    assert metrics.wasted_tool_calls == 1
    # every arm needed exactly one extra tool call to get past the fault
    assert metrics.tool_calls == CORPUS["rotate-api-key"].minimal_tool_calls + 1


async def test_provider_fault_pins_the_recovery_asymmetry() -> None:
    """A transient provider failure is recovered only by the canonical Graph
    arm, whose NodeRun retry machinery owns retryable errors. The loop arms
    surface the exception at the strategy layer -- recovery there belongs to
    callers (the agent envelope catches but does not retry)."""
    timeout = TimeoutError("simulated provider timeout (injected)")

    def armed(strategy: str, call: int):
        spec = CORPUS["rotate-api-key"]
        world, policy = _new_cell(spec, strategy=strategy)
        policy.fail_on_call[call] = timeout
        return _RUNNERS[strategy](spec, world, policy)

    react = await armed(REACT, 2)
    assert react.recovered is False and react.success is False
    assert react.error is not None and "TimeoutError" in react.error

    plan_planner = await armed(PLAN_EXECUTE, 1)
    assert plan_planner.recovered is False and plan_planner.success is False

    plan_executor = await armed(PLAN_EXECUTE, 2)
    assert plan_executor.recovered is False and plan_executor.success is False

    graph = await armed(GRAPH, 2)
    assert graph.recovered and graph.success
    assert graph.retries >= 1, "the coder NodeRun should have retried the timeout"
    assert graph.llm_calls == 4  # planner + failed coder + retried coder + reviewer


# --- matched budgets


async def test_all_arms_run_under_the_same_budget_object() -> None:
    """The arms are structurally budget-matched: same model, same retry
    allowance, same caps -- this pins the fairness of every cost comparison."""
    assert BUDGET.max_model_calls == BUDGET.max_tool_calls == 16
    assert BUDGET.max_retries == 3

    react_strategy = ReactStrategy(max_rounds=BUDGET.react_max_rounds)
    assert react_strategy.max_rounds == BUDGET.react_max_rounds

    planner = PlanExecuteStrategy(max_subtasks=BUDGET.max_subtasks)
    assert planner.max_subtasks == BUDGET.max_subtasks

    run_budget = IterationBudget(BUDGET.max_model_calls)
    assert run_budget.max_iterations == BUDGET.max_model_calls

    for metrics in await sweep():
        assert metrics.llm_calls <= BUDGET.max_model_calls
        assert metrics.tool_calls <= BUDGET.max_tool_calls


# --- determinism


async def test_repeatability_three_sweeps_are_identical() -> None:
    """Repeatability: the whole benchmark is deterministic -- three sweeps
    produce byte-identical metric vectors, so any future drift is a code
    change, not noise."""
    first = await sweep()
    for _ in range(2):
        again = await sweep()
        assert [m.latency_vector() for m in again] == [m.latency_vector() for m in first]


async def test_p95_simulated_latency_matches_recomputation() -> None:
    """p95 is a deterministic function of the synthetic latency model
    (calls x per-call constants), never a wall-clock read, and identical
    across sweeps."""
    cells = await sweep()
    latencies = [m.simulated_latency_ms for m in cells]
    expected = p95(latencies)
    recomputed = p95([m.simulated_latency() for m in cells])
    assert expected == recomputed

    again = await sweep()
    assert p95([m.simulated_latency_ms for m in again]) == expected
    # and every cell's latency is exactly its structural cost model
    for metrics in cells:
        assert metrics.simulated_latency_ms == metrics.simulated_latency()

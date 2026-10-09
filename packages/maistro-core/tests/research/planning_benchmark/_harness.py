"""The three benchmark arms and their shared metric frame.

Each driver runs one Goal through one shipped production structure:

- ``run_react``         -- ``maistro.agents.strategies.react.ReactStrategy``
  (interleaved LLM/tool loop, tool results fed back each round);
- ``run_plan_execute``  -- ``maistro.agents.strategies.plan_execute.PlanExecuteStrategy``
  produces the explicit plan, then one ``ReactStrategy`` executor loop runs per
  planned subtask (the strategy's own documented shape: "Uses sub-agents for
  each subtask");
- ``run_graph``         -- ``maistro.graph.GraphRun`` planner -> coder ->
  reviewer, the canonical Graph execution (Run -> NodeRun, retries, iteration
  budget), driven through its normal ``llm_call`` surface.

Budgets are matched: every arm gets the same model name, the same retry
allowance, and the same hard caps on model calls and tool calls from one
``BenchBudget``. Costs are read from the shared ``ToolLedger`` and the shared
policy's call counter -- never from an arm's self-report -- and "latency" is
the deterministic synthetic constant below, never a wall-clock read.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from maistro.agents.strategies.plan_execute import PlanExecuteStrategy
from maistro.agents.strategies.react import ReactStrategy
from maistro.graph.node import IterationBudget
from maistro.graph.run import GraphRun
from maistro.graph.types import AgentRole, GraphConfig, GraphEdge, GraphTask
from maistro.resilience.backoff import BackoffConfig
from maistro.security._types import AuthContext
from maistro.security.sentinel.policy import Sentinel
from maistro.security.warden.detector import Warden

from ._policy import PolicyModel
from ._world import DEAD_END, GoalSpec, GoalWorld, ToolLedger

REACT = "react"
PLAN_EXECUTE = "plan_execute"
GRAPH = "graph"
STRATEGIES: tuple[str, ...] = (REACT, PLAN_EXECUTE, GRAPH)


@dataclass(frozen=True)
class BenchBudget:
    """The one budget every arm shares. Caps, retries, and cost constants."""

    model_name: str = "bench-model"
    #: hard cap on model calls for any single cell (asserted post-run)
    max_model_calls: int = 16
    #: hard cap on tool calls for any single cell (asserted post-run)
    max_tool_calls: int = 16
    #: retry allowance, identical everywhere (graph nodes; react round slack)
    max_retries: int = 3
    max_subtasks: int = 8
    react_max_rounds: int = 8
    graph_max_cycles: int = 4
    prompt_tokens_per_call: int = 40
    completion_tokens_per_call: int = 30
    #: synthetic structure-proportional latency model (never wall-clock)
    llm_latency_ms: float = 50.0
    tool_latency_ms: float = 5.0


BUDGET = BenchBudget()

#: Standalone strategy callers must authorize every tool through a real
#: Sentinel (the same gate production standalone callers face). All three
#: benchmark tools are explicitly granted to the operator role.
_BENCH_AUTH = AuthContext(user_id="bench-operator", roles=frozenset({"operator"}))
_BENCH_SENTINEL = Sentinel(
    warden=Warden(),
    permission_table={
        "lookup": frozenset({"operator"}),
        "combine": frozenset({"operator"}),
        "submit": frozenset({"operator"}),
    },
)

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "Read one key from the fact base.",
            "parameters": {
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "combine",
            "description": "Join string parts with '|'.",
            "parameters": {
                "type": "object",
                "properties": {"parts": {"type": "array", "items": {"type": "string"}}},
                "required": ["parts"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit",
            "description": "Submit the final answer for the goal.",
            "parameters": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        },
    },
]

_PLAN_LINE_RE = re.compile(r"^(\d+)\.\s+(.+)$", re.MULTILINE)


def parse_plan_lines(plan_text: str) -> list[tuple[int, str]]:
    """Numbered lines of a plan-execute plan, in order."""
    return [(int(m.group(1)), m.group(2).strip()) for m in _PLAN_LINE_RE.finditer(plan_text)]


def goal_achieved(spec: GoalSpec, world: GoalWorld, final_text: str) -> bool:
    """The Goal-level oracle, identical for every arm.

    Normal goals: the expected answer was submitted through the world's
    ``submit`` tool. Dead-end goals: the arm reported the infeasibility
    instead of guessing.
    """
    if spec.goal_class == DEAD_END:
        return "infeasible" in final_text and spec.expected_answer in final_text
    return spec.expected_answer in world.submitted_answers()


@dataclass
class StrategyMetrics:
    """One benchmark cell's measured outcome, arm-agnostic."""

    strategy: str
    goal_id: str
    goal_class: str
    success: bool = False
    #: completed the Goal despite an armed injection
    recovered: bool = True
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    wasted_tool_calls: int = 0
    #: "structured" | "text" | "none" -- was an inspectable plan produced?
    plan_artifact: str = "none"
    plan_steps: int = 0
    verification_steps: int = 0
    simulated_latency_ms: float = 0.0
    retries: int = 0
    #: the graph machinery's own run-level verdict, when the arm is Graph
    run_success: bool | None = None
    error: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def latency_vector(self) -> tuple[Any, ...]:
        """Every field as one comparable vector (repeatability oracle)."""
        return (
            self.strategy,
            self.goal_id,
            self.goal_class,
            self.success,
            self.recovered,
            self.llm_calls,
            self.input_tokens,
            self.output_tokens,
            self.tool_calls,
            self.tool_errors,
            self.wasted_tool_calls,
            self.plan_artifact,
            self.plan_steps,
            self.verification_steps,
            self.simulated_latency_ms,
            self.retries,
            self.run_success,
            self.error,
        )

    def simulated_latency(self) -> float:
        return self.llm_calls * BUDGET.llm_latency_ms + self.tool_calls * BUDGET.tool_latency_ms


def _new_cell(spec: GoalSpec, *, strategy: str) -> tuple[GoalWorld, PolicyModel]:
    ledger = ToolLedger()
    world = GoalWorld(ledger)
    policy = PolicyModel(
        spec,
        world,
        prompt_tokens_per_call=BUDGET.prompt_tokens_per_call,
        completion_tokens_per_call=BUDGET.completion_tokens_per_call,
    )
    del strategy
    return world, policy


def _finalize(
    metrics: StrategyMetrics,
    spec: GoalSpec,
    world: GoalWorld,
    policy: PolicyModel,
    final_text: str,
) -> StrategyMetrics:
    metrics.llm_calls = policy.llm_calls
    metrics.tool_calls = world.ledger.tool_calls
    metrics.tool_errors = world.ledger.tool_errors
    metrics.wasted_tool_calls = metrics.tool_calls - spec.minimal_tool_calls
    metrics.success = goal_achieved(spec, world, final_text)
    metrics.simulated_latency_ms = metrics.simulated_latency()
    return metrics


def _failed_metrics(
    strategy: str, spec: GoalSpec, world: GoalWorld, policy: PolicyModel, exc: Exception
) -> StrategyMetrics:
    """A cell where the structure surfaced an exception: nothing recovered."""
    metrics = StrategyMetrics(
        strategy=strategy,
        goal_id=spec.goal_id,
        goal_class=spec.goal_class,
        success=False,
        recovered=False,
        error=repr(exc),
    )
    return _finalize(metrics, spec, world, policy, "")


async def run_react(spec: GoalSpec, world: GoalWorld, policy: PolicyModel) -> StrategyMetrics:
    """Arm 1: one interleaved ReAct loop over the shared tools."""
    metrics = StrategyMetrics(strategy=REACT, goal_id=spec.goal_id, goal_class=spec.goal_class)
    strategy = ReactStrategy(max_rounds=BUDGET.react_max_rounds)
    messages = [
        {"role": "system", "content": "You are a benchmark agent. Use the tools to answer."},
        {"role": "user", "content": spec.question},
    ]
    try:
        result = await strategy.reason(
            messages,
            BUDGET.model_name,
            policy,
            tools=TOOL_SCHEMAS,
            tool_executor=world.execute,
            sentinel=_BENCH_SENTINEL,
            auth=_BENCH_AUTH,
        )
    except Exception as exc:
        return _failed_metrics(REACT, spec, world, policy, exc)
    metrics.detail["tool_rounds"] = len(result.tool_history)
    metrics.input_tokens = result.input_tokens
    metrics.output_tokens = result.output_tokens
    return _finalize(metrics, spec, world, policy, result.response or "")


_SUBTASK_PREFIX = "Execute subtask: "


async def run_plan_execute(
    spec: GoalSpec, world: GoalWorld, policy: PolicyModel
) -> StrategyMetrics:
    """Arm 2: explicit plan, then one executor loop per planned subtask."""
    metrics = StrategyMetrics(
        strategy=PLAN_EXECUTE, goal_id=spec.goal_id, goal_class=spec.goal_class
    )
    planner = PlanExecuteStrategy(max_subtasks=BUDGET.max_subtasks)
    try:
        plan_result = await planner.reason(
            [{"role": "user", "content": spec.question}], BUDGET.model_name, policy
        )
        plan_text = plan_result.response or ""
        lines = parse_plan_lines(plan_text)
        metrics.plan_artifact = "text"
        metrics.plan_steps = len(lines)
        final_text = plan_text
        for number, line in lines:
            loop = ReactStrategy(max_rounds=2)
            loop_result = await loop.reason(
                [
                    {
                        "role": "system",
                        "content": "You are a benchmark subtask executor. Complete exactly "
                        "your subtask using the tools.",
                    },
                    {"role": "user", "content": f"{_SUBTASK_PREFIX}{number}. {line}"},
                ],
                BUDGET.model_name,
                policy,
                tools=TOOL_SCHEMAS,
                tool_executor=world.execute,
                sentinel=_BENCH_SENTINEL,
                auth=_BENCH_AUTH,
            )
            metrics.input_tokens += loop_result.input_tokens
            metrics.output_tokens += loop_result.output_tokens
            if loop_result.response:
                final_text = loop_result.response
    except Exception as exc:
        return _failed_metrics(PLAN_EXECUTE, spec, world, policy, exc)
    metrics.detail["executor_loops"] = len(lines)
    return _finalize(metrics, spec, world, policy, final_text)


async def run_graph(spec: GoalSpec, world: GoalWorld, policy: PolicyModel) -> StrategyMetrics:
    """Arm 3: the canonical Graph planner -> coder -> reviewer pipeline.

    Execution is the shipped ``GraphRun``/``NodeRun`` machinery exactly as
    production drives it: node retries, circuit breaker, iteration budget,
    edge routing. The benchmark adds no execution authority.
    """
    metrics = StrategyMetrics(strategy=GRAPH, goal_id=spec.goal_id, goal_class=spec.goal_class)
    config = GraphConfig(
        nodes=[AgentRole.PLANNER, AgentRole.CODER, AgentRole.REVIEWER],
        edges=[
            GraphEdge(from_role=AgentRole.PLANNER, to_role=AgentRole.CODER),
            GraphEdge(from_role=AgentRole.CODER, to_role=AgentRole.REVIEWER),
            GraphEdge(from_role=AgentRole.REVIEWER, to_role=None),
        ],
        entry=AgentRole.PLANNER,
        max_cycles=BUDGET.graph_max_cycles,
    )
    run = GraphRun(task=GraphTask(description=spec.question, workspace="bench"), config=config)
    run.iteration_budget = IterationBudget(BUDGET.max_model_calls)
    try:
        result = await run.start(
            policy.graph_llm_call,
            model=BUDGET.model_name,
            timeout=30.0,
            max_retries=BUDGET.max_retries,
            backoff_config=BackoffConfig(base_delay=0.0, max_delay=0.0, jitter_factor=0.0),
        )
    except Exception as exc:
        return _failed_metrics(GRAPH, spec, world, policy, exc)

    metrics.run_success = result.success
    metrics.plan_artifact = "structured"
    metrics.plan_steps = len(run.plan.subtasks) if run.plan is not None else 0
    metrics.detail["plan_output"] = run.plan
    metrics.verification_steps = len(run.node_runs_for_role(AgentRole.REVIEWER))
    metrics.retries = sum(nr.retry_count for nr in run.node_runs)
    metrics.input_tokens = sum(nr.tokens_in for nr in run.node_runs)
    metrics.output_tokens = sum(nr.tokens_out for nr in run.node_runs)
    metrics.detail["node_runs"] = len(run.node_runs)
    metrics.detail["graph_phase"] = run.phase.value
    final_text = result.code.description if result.code is not None else ""
    return _finalize(metrics, spec, world, policy, final_text)


_RUNNERS = {
    REACT: run_react,
    PLAN_EXECUTE: run_plan_execute,
    GRAPH: run_graph,
}


async def run_cell(spec: GoalSpec, strategy: str) -> StrategyMetrics:
    """One (Goal, strategy) cell with a fresh world, ledger, and policy."""
    world, policy = _new_cell(spec, strategy=strategy)
    return await _RUNNERS[strategy](spec, world, policy)


async def sweep() -> list[StrategyMetrics]:
    """The full matrix: every Goal x every strategy, fresh state per cell."""
    from ._world import build_corpus

    cells: list[StrategyMetrics] = []
    for spec in build_corpus():
        for strategy in STRATEGIES:
            cells.append(await run_cell(spec, strategy))
    return cells


def p95(values: list[float]) -> float:
    """Nearest-rank p95 over a deterministic sample (no interpolation)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = math.ceil(0.95 * len(ordered))
    return ordered[rank - 1]

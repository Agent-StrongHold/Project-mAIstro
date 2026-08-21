from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import structlog

import maistro.graph.conditions as graph_conditions
from maistro.graph.events import (
    GraphEvent,
    cycle_started,
    graph_completed,
    graph_failed,
    graph_started,
)
from maistro.graph.node import (
    IterationBudget,
    NodeExecutor,
    NodeRun,
    _blackboard_prefix,
    _build_system_prompt,
    _to_agent_role,
)
from maistro.graph.phases import TERMINAL_GRAPH_PHASES, GraphPhase, NodePhase
from maistro.graph.strategy import get_strategy
from maistro.graph.types import (
    AgentRole,
    CodeOutput,
    GraphBlackboard,
    GraphConfig,
    GraphTask,
    HyperagentOutput,
    NodeConfig,
    PlanOutput,
    ReviewOutput,
)
from maistro.resilience.backoff import BackoffConfig

logger = structlog.get_logger()
_MISSING = graph_conditions.MISSING


def _get_temperature(
    role: AgentRole | str,
    node_config: NodeConfig | None = None,
    default: float | None = None,
) -> float | None:
    if node_config and node_config.temperature is not None:
        return node_config.temperature
    return default


def _resolve_path(
    path: str,
    plan: PlanOutput | None,
    code: CodeOutput | None,
    review: ReviewOutput | None,
) -> object:
    parts = path.split(".", 1)
    if len(parts) != 2:
        return _MISSING
    namespace, attr = parts
    obj: object = {"plan": plan, "code": code, "review": review}.get(namespace)
    if obj is None:
        return _MISSING
    return getattr(obj, attr, _MISSING)


def _parse_rhs(value: str) -> object:
    """Compatibility wrapper for the shared graph predicate literal parser."""
    return graph_conditions.parse_condition_rhs(value)


def _compare(lhs: object, operator: str, rhs: object) -> bool:
    """Compatibility wrapper for the shared graph predicate comparator."""
    return graph_conditions.compare_condition_values(lhs, operator, rhs)


def evaluate_condition(
    condition: str,
    plan: PlanOutput | None,
    code: CodeOutput | None,
    review: ReviewOutput | None,
) -> bool:
    return graph_conditions.evaluate_predicate(
        condition,
        lambda path: _resolve_path(path, plan, code, review),
    )


def _role_str(role: AgentRole | str) -> str:
    """Render a role (enum or raw kind string) as its string identifier."""
    return role.value if isinstance(role, AgentRole) else role


def _next_nodes(
    config: GraphConfig,
    current: AgentRole | str,
    plan: PlanOutput | None,
    code: CodeOutput | None,
    review: ReviewOutput | None,
) -> list[AgentRole | str]:
    sequential: AgentRole | str | None = None
    parallel: list[AgentRole | str] = []

    for edge in config.edges:
        if edge.from_role != current:
            continue
        if edge.to_role is None:
            continue
        cond_met = edge.condition is None or evaluate_condition(edge.condition, plan, code, review)
        if not cond_met:
            continue
        if edge.parallel:
            parallel.append(edge.to_role)
        elif sequential is None:
            sequential = edge.to_role

    result = [] if sequential is None else [sequential]
    result.extend(parallel)
    return result


def _build_final_answer(review: ReviewOutput | None, plan: PlanOutput | None) -> str:
    if review and review.approved:
        return f"Task completed. Review score: {review.score}/10."
    if review:
        issues = "; ".join(review.issues[:2]) if review.issues else "unspecified issues"
        return f"Review not approved (score: {review.score}/10): {issues}"
    if plan:
        return plan.summary
    return ""


@dataclass
class GraphRun:
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task: GraphTask = field(default_factory=lambda: GraphTask(description="", workspace=""))
    config: GraphConfig | None = None

    phase: GraphPhase = GraphPhase.IDLE
    phase_log: list[tuple[GraphPhase, float]] = field(default_factory=list)

    blackboard: GraphBlackboard | None = None
    iteration_budget: IterationBudget | None = None

    node_runs: list[NodeRun] = field(default_factory=list)

    plan: PlanOutput | None = None
    code: CodeOutput | None = None
    review: ReviewOutput | None = None

    result: HyperagentOutput | None = None
    classified_error: Any | None = None

    event_callbacks: list[Callable[[GraphEvent], Awaitable[None]]] = field(default_factory=list)

    # Per-role executor overrides (SPEC-208 §5): when a node's role is present
    # here, the node is driven by this executor (e.g. a foreign harness) instead
    # of ``llm_call``. Keyed by role string so arbitrary node kinds also match.
    node_executors: dict[str, NodeExecutor] = field(default_factory=dict)

    _cancel_requested: bool = field(default=False, repr=False)

    def _transition(self, new_phase: GraphPhase) -> None:
        now = time.monotonic()
        self.phase_log.append((self.phase, now))
        self.phase = new_phase
        logger.info(
            "graph_phase_transition",
            run_id=self.run_id,
            new=new_phase.value,
        )

    def cancel(self) -> None:
        self._cancel_requested = True
        if self.phase == GraphPhase.RUNNING:
            self._transition(GraphPhase.CANCELLING)
        for nr in self.node_runs:
            if nr.phase in (NodePhase.RUNNING, NodePhase.RETRYING, NodePhase.PENDING):
                nr.cancel()

    def node_runs_for_role(self, role: AgentRole) -> list[NodeRun]:
        return [nr for nr in self.node_runs if nr.role == role]

    def latest_node_run(self, role: AgentRole) -> NodeRun | None:
        runs = self.node_runs_for_role(role)
        return runs[-1] if runs else None

    def duration_s(self) -> float:
        if not self.phase_log:
            return 0.0
        start = self.phase_log[0][1]
        end = self.phase_log[-1][1] if self.phase in TERMINAL_GRAPH_PHASES else time.monotonic()
        return end - start

    def total_tokens(self) -> int:
        return sum(nr.tokens_in + nr.tokens_out for nr in self.node_runs)

    def success_rate(self) -> float:
        if not self.node_runs:
            return 0.0
        succeeded = sum(1 for nr in self.node_runs if nr.phase == NodePhase.SUCCEEDED)
        return succeeded / len(self.node_runs)

    async def _emit(self, event: GraphEvent) -> None:
        for cb in self.event_callbacks:
            try:
                await cb(event)
            except Exception:
                logger.warning("event_callback_error", event_type=event.type)

    async def start(
        self,
        llm_call: Callable[..., Awaitable[str]],
        model: str = "default",
        temperature: float | None = None,
        timeout: float = 120.0,
        max_retries: int = 3,
        backoff_config: BackoffConfig | None = None,
    ) -> HyperagentOutput:
        if self.phase != GraphPhase.IDLE:
            return self._build_result()

        try:
            return await self._execute(
                llm_call, model, temperature, timeout, max_retries, backoff_config
            )
        except asyncio.CancelledError:
            self._transition(GraphPhase.CANCELLING)
            for nr in self.node_runs:
                if nr.phase in (NodePhase.RUNNING, NodePhase.RETRYING):
                    nr.cancel()
            self._transition(GraphPhase.FAILED)
            return self._build_result()
        except Exception as exc:
            from maistro.resilience.classifier import classify_error

            self.classified_error = classify_error(exc)
            self._transition(GraphPhase.FAILED)
            return self._build_result()

    async def _execute(
        self,
        llm_call: Callable[..., Awaitable[str]],
        model: str,
        temperature: float | None,
        timeout: float,
        max_retries: int,
        backoff_config: BackoffConfig | None,
    ) -> HyperagentOutput:
        config = (
            self.config
            or self.task.graph_config
            or GraphConfig(nodes=[AgentRole.PLANNER, AgentRole.CODER, AgentRole.REVIEWER])
        )

        self._transition(GraphPhase.RUNNING)
        self.blackboard = GraphBlackboard(
            task_objective=self.task.description,
            workspace=self.task.workspace,
        )

        budget = self.iteration_budget or IterationBudget(
            max_iterations=config.max_cycles * len(config.nodes) * 3
        )

        await self._emit(
            graph_started(
                self.run_id,
                nodes=[_role_str(n) for n in config.nodes],
                entry=_role_str(config.entry),
                model=model,
            )
        )

        if config.run_scout:
            await self._run_scout(
                llm_call, model, temperature, timeout, max_retries, backoff_config, budget
            )

        active: list[AgentRole | str] = [config.entry]
        cycle = 0

        while active and cycle < config.max_cycles and not self._cancel_requested:
            await self._emit(
                cycle_started(
                    self.run_id,
                    cycle=cycle,
                    active=[_role_str(a) for a in active],
                )
            )

            node_runs = [
                self._create_node_run(
                    role,
                    config,
                    model,
                    temperature,
                    max_retries,
                    llm_call,
                    timeout,
                    backoff_config,
                    budget,
                    cycle,
                )
                for role in active
            ]

            await asyncio.gather(
                *[
                    nr.execute(
                        llm_call,
                        timeout=timeout,
                        backoff_config=backoff_config,
                        iteration_budget=budget,
                    )
                    for nr in node_runs
                ],
                return_exceptions=True,
            )

            self.node_runs.extend(node_runs)
            self._update_pipeline_state(node_runs)

            active = self._route_next(node_runs, config, cycle)
            cycle += 1

        success = bool(self.node_runs) and all(
            nr.phase == NodePhase.SUCCEEDED for nr in self.node_runs
        )

        if self._cancel_requested:
            self._transition(GraphPhase.FAILED)
        elif success:
            self._transition(GraphPhase.COMPLETED)
        else:
            self._transition(GraphPhase.FAILED)

        result = self._build_result()

        if self.phase == GraphPhase.COMPLETED:
            await self._emit(
                graph_completed(
                    self.run_id,
                    success=success,
                    cycles=cycle,
                    review_score=self.review.score if self.review else None,
                )
            )
        else:
            await self._emit(
                graph_failed(
                    self.run_id,
                    cycles=cycle,
                    failed_nodes=[
                        nr.role.value for nr in self.node_runs if nr.phase == NodePhase.FAILED
                    ],
                )
            )

        return result

    def _create_node_run(
        self,
        role: AgentRole | str,
        config: GraphConfig,
        model: str,
        temperature: float | None,
        max_retries: int,
        llm_call: Callable[..., Awaitable[str]],
        timeout: float,
        backoff_config: BackoffConfig | None,
        budget: IterationBudget,
        cycle: int,
    ) -> NodeRun:
        strategy = get_strategy(role)
        node_config = config.node_configs.get(_role_str(role))
        role_enum = _to_agent_role(role) or AgentRole.PLANNER

        system_prompt = _build_system_prompt(role, node_config)
        bb = self.blackboard or GraphBlackboard(
            task_objective=self.task.description,
            workspace=self.task.workspace,
        )
        user_prompt = _blackboard_prefix(role, bb) + strategy.build_user_prompt(
            self.task,
            bb,
            self.plan,
            self.code,
            self.review,
        )

        nr = NodeRun(
            run_id=self.run_id,
            role=role_enum,
            strategy=strategy,
            beam_width=node_config.beam_width if node_config else 1,
            model=model,
            temperature=_get_temperature(role, node_config, temperature),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            blackboard_snapshot=self.blackboard.model_copy() if self.blackboard else None,
            node_config=node_config,
            max_retries=max_retries,
            executor=self.node_executors.get(_role_str(role)),
            _emit_event=self._emit,
        )
        return nr

    async def _run_scout(
        self,
        llm_call: Callable[..., Awaitable[str]],
        model: str,
        temperature: float | None,
        timeout: float,
        max_retries: int,
        backoff_config: BackoffConfig | None,
        budget: IterationBudget,
    ) -> None:
        nr = self._create_node_run(
            AgentRole.SCOUT,
            self.config or GraphConfig(nodes=[]),
            model,
            temperature,
            max_retries,
            llm_call,
            timeout,
            backoff_config,
            budget,
            -1,
        )
        await nr.execute(
            llm_call, timeout=timeout, backoff_config=backoff_config, iteration_budget=budget
        )
        self.node_runs.append(nr)

        if nr.parsed_output is not None and self.blackboard is not None and nr.strategy is not None:
            self.blackboard = nr.strategy.update_blackboard(nr.parsed_output, self.blackboard)

    def _update_pipeline_state(self, node_runs: list[NodeRun]) -> None:
        for nr in node_runs:
            if nr.parsed_output is None:
                continue
            if nr.role == AgentRole.PLANNER and isinstance(nr.parsed_output, PlanOutput):
                self.plan = nr.parsed_output
            elif nr.role == AgentRole.CODER and isinstance(nr.parsed_output, CodeOutput):
                self.code = nr.parsed_output
            elif nr.role == AgentRole.REVIEWER and isinstance(nr.parsed_output, ReviewOutput):
                self.review = nr.parsed_output

    def _route_next(
        self,
        node_runs: list[NodeRun],
        config: GraphConfig,
        cycle: int,
    ) -> list[AgentRole | str]:
        seen: set[AgentRole | str] = set()
        next_active: list[AgentRole | str] = []

        for nr in node_runs:
            if nr.phase != NodePhase.SUCCEEDED:
                continue
            nexts = _next_nodes(config, nr.role, self.plan, self.code, self.review)
            for nxt in nexts:
                if nxt not in seen:
                    next_active.append(nxt)
                    seen.add(nxt)

        return next_active

    def _build_result(self) -> HyperagentOutput:
        config = self.config or self.task.graph_config
        node_results = [nr.to_result() for nr in self.node_runs]
        success = all(r.success for r in node_results) if node_results else False
        final_answer = _build_final_answer(self.review, self.plan)

        result = HyperagentOutput(
            plan=self.plan,
            code=self.code,
            review=self.review,
            final_answer=final_answer,
            success=success,
            graph_config=config,
            node_results=node_results,
            total_cycles=sum(1 for nr in self.node_runs if nr.role != AgentRole.SCOUT),
            blackboard=self.blackboard,
        )
        self.result = result
        return result

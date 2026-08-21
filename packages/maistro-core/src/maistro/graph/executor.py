from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from maistro.graph.events import GraphEvent
from maistro.graph.node import NodeExecutor
from maistro.graph.run import GraphRun, evaluate_condition
from maistro.graph.types import (
    GraphConfig,
    GraphTask,
    HyperagentOutput,
)
from maistro.resilience.p1 import (
    CompactedRetry,
    InMemoryResiliencePolicyStore,
    ResiliencePolicyStore,
    RetryAttempt,
    RetryBudget,
    classify_error_code,
    compact_attempts,
)

T = TypeVar("T")


def _compacted_detail(entries: list[CompactedRetry | RetryAttempt]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for entry in entries:
        if isinstance(entry, CompactedRetry):
            out.append(entry.to_dict())
        else:
            out.append(
                {
                    "error_code": entry.error_code,
                    "count": 1,
                    "first_timestamp": entry.timestamp,
                    "last_timestamp": entry.timestamp,
                    "common_cause": entry.message,
                }
            )
    return out


async def execute_with_resilience(
    operation: Callable[[], Awaitable[T]],
    *,
    run_id: str = "",
    node_id: str = "",
    role: str = "",
    agent_id: str = "*",
    layer: str = "*",
    budget: RetryBudget | None = None,
    policy_store: ResiliencePolicyStore | None = None,
    emit: Callable[[GraphEvent], Awaitable[None]] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> T:
    """Execute ``operation`` under P1 resilience (ADR-066 / SPEC-070226-af02).

    Retry loop with depth enforcement via :class:`RetryBudget` (fails after
    exactly ``budget.max_retries`` failed attempts) and control-scope gating:
    the :class:`ResiliencePolicyStore` is consulted on *every* retry decision.

    Events (all tagged ``source: "resilience.p1"``, delivered via ``emit``):

    - ``node.retry_attempted`` — on every failed attempt.
    - ``node.retry_exhausted`` — when the budget or policy stops retrying;
      carries the compacted attempt history.
    - ``node.escalated`` — when the policy escalates; the original exception
      propagates to the parent/orchestrator (not retried locally).
    """
    budget = budget if budget is not None else RetryBudget()
    store: ResiliencePolicyStore = (
        policy_store if policy_store is not None else InMemoryResiliencePolicyStore()
    )
    do_sleep = sleep if sleep is not None else asyncio.sleep

    async def _emit(event: GraphEvent) -> None:
        if emit is not None:
            await emit(event)

    while True:
        try:
            return await operation()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            code = classify_error_code(exc)
            budget.record(exc, error_code=code)
            attempt = budget.current_attempt

            # Control-scope policy is consulted on EVERY retry decision.
            policy = await store.get(agent_id, layer, code)
            action = policy.decide(attempt, code)

            if action == "escalate":
                await _emit(
                    GraphEvent(
                        type="node.escalated",
                        run_id=run_id,
                        node_id=node_id or None,
                        role=role or None,
                        detail={
                            "source": "resilience.p1",
                            "attempt": attempt,
                            "error_code": code,
                            "reason": str(exc)[:200],
                            "escalate_to": "orchestrator",
                        },
                    )
                )
                raise

            delay = policy.backoff_for(attempt)
            await _emit(
                GraphEvent(
                    type="node.retry_attempted",
                    run_id=run_id,
                    node_id=node_id or None,
                    role=role or None,
                    detail={
                        "source": "resilience.p1",
                        "attempt": attempt,
                        "error_code": code,
                        "error": str(exc)[:200],
                        "backoff_seconds": delay,
                    },
                )
            )

            if budget.exhausted or action == "fail":
                compacted = compact_attempts(budget.attempts, budget.compaction_window_ms)
                await _emit(
                    GraphEvent(
                        type="node.retry_exhausted",
                        run_id=run_id,
                        node_id=node_id or None,
                        role=role or None,
                        detail={
                            "source": "resilience.p1",
                            "total_attempts": attempt,
                            "error_code": code,
                            "reason": "budget_exhausted" if budget.exhausted else "policy_fail",
                            "compacted": _compacted_detail(compacted),
                        },
                    )
                )
                raise

            await do_sleep(delay)


def _ensure_node_configs(config: GraphConfig | None, parallel_generations: int) -> None:
    """Backfill a NodeConfig for every role, applying the beam width when the
    caller asked for parallel generations. Mutates ``config`` in place."""
    if config is None:
        return
    from maistro.graph.types import NodeConfig as _NC

    for role in config.nodes:
        if role not in config.node_configs:
            config.node_configs[role] = _NC(role=role)
        if parallel_generations > 1:
            config.node_configs[role].beam_width = parallel_generations


async def run_graph(
    task: GraphTask,
    llm_call: Callable[..., Awaitable[str]],
    *,
    model: str = "default",
    max_retries: int = 3,
    timeout: float = 120.0,
    initial_backoff: float = 1.0,
    parallel_generations: int = 1,
    temperature: float | None = None,
    run_id: str | None = None,
    event_callbacks: list[Callable[[Any], Awaitable[None]]] | None = None,
    node_executors: dict[str, NodeExecutor] | None = None,
) -> HyperagentOutput:
    from maistro.resilience.backoff import BackoffConfig

    backoff_config = BackoffConfig(base_delay=initial_backoff)

    config = task.graph_config
    _ensure_node_configs(config, parallel_generations)

    graph_run = GraphRun(
        run_id=run_id or "",
        task=task,
        config=config,
        event_callbacks=event_callbacks or [],
        node_executors=node_executors or {},
    )

    return await graph_run.start(
        llm_call,
        model=model,
        temperature=temperature,
        timeout=timeout,
        max_retries=max_retries,
        backoff_config=backoff_config,
    )


__all__ = ["GraphRun", "evaluate_condition", "execute_with_resilience", "run_graph"]

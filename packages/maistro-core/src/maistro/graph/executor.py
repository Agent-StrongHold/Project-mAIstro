from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from maistro.graph.events import GraphEvent
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


__all__ = ["execute_with_resilience"]

"""Idempotent, retrying dispatch over a Channel (SPEC-251 / ADR-047)."""

from __future__ import annotations

import asyncio

from maistro.agents.circuit_breaker import CircuitBreaker
from maistro.delivery.registry import ChannelRegistry
from maistro.delivery.types import DeliveryPayload, DeliveryResult, DeliveryTarget
from maistro.resilience.backoff import jittered_backoff


def _delivery_key(target: DeliveryTarget, payload: DeliveryPayload) -> str:
    task_id = payload.metadata.get("task_id", "")
    return f"{task_id}:{target.channel}:{target.address}"


async def dispatch(
    registry: ChannelRegistry,
    target: DeliveryTarget,
    payload: DeliveryPayload,
    *,
    breaker: CircuitBreaker | None = None,
    max_attempts: int = 3,
    seen_keys: set[str] | None = None,
) -> DeliveryResult:
    key = _delivery_key(target, payload)
    if seen_keys is not None:
        if key in seen_keys:
            return DeliveryResult(
                target=target,
                status="dropped",
                provider_message_id=None,
                error=None,
                attempts=0,
            )
        seen_keys.add(key)

    if breaker is not None and not breaker.allow_request():
        return DeliveryResult(
            target=target, status="dropped", provider_message_id=None, error=None, attempts=0
        )

    channel = registry.get(target.channel)

    last_error: str | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = await channel.send(target, payload)
        except Exception as exc:
            last_error = str(exc)
            if breaker is not None:
                breaker.record_failure()
            if attempt < max_attempts:
                await asyncio.sleep(jittered_backoff(attempt))
            continue
        if breaker is not None:
            breaker.record_success()
        return DeliveryResult(
            target=target,
            status="sent",
            provider_message_id=result.provider_message_id,
            error=None,
            attempts=attempt,
        )

    return DeliveryResult(
        target=target,
        status="failed",
        provider_message_id=None,
        error=last_error,
        attempts=max_attempts,
    )

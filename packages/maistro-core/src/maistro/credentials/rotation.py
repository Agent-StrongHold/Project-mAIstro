from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from maistro.credentials.pool import CredentialPool
from maistro.credentials.types import CredentialRecord, PoolExhaustedError
from maistro.resilience.backoff import BackoffConfig, jittered_backoff
from maistro.resilience.classifier import ClassifiedError, classify_error

T = TypeVar("T")

_DEFAULT_RATE_LIMIT_COOLDOWN = 60.0
_DEFAULT_BILLING_COOLDOWN = 3600.0
_DEFAULT_MAX_RETRIES = 3


@dataclass
class RotationResult(Generic[T]):
    value: T
    key_id: str
    attempts: int = 1
    key_rotations: int = 0
    retries_on_current_key: int = 0


def _resolve_cooldown(
    classified: ClassifiedError,
    retry_after: float | None = None,
) -> tuple[float, bool]:
    detail = classified.detail
    status_code = detail.get("status_code", 0) if isinstance(detail, dict) else 0

    if status_code == 402:
        return _DEFAULT_BILLING_COOLDOWN, False
    if status_code == 401 or status_code == 403:
        return 0.0, True
    if status_code == 429 or classified.category.value == "rate_limit":
        if retry_after and retry_after > 0:
            return min(_DEFAULT_RATE_LIMIT_COOLDOWN, retry_after), False
        return _DEFAULT_RATE_LIMIT_COOLDOWN, False

    return 0.0, False


async def execute_with_pool(
    pool: CredentialPool,
    call_fn: Callable[[CredentialRecord], Awaitable[T]],
    *,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    backoff_config: BackoffConfig | None = None,
    max_key_rotations: int | None = None,
) -> RotationResult[T]:
    backoff_config = backoff_config or BackoffConfig()
    max_rotations = max_key_rotations if max_key_rotations is not None else pool.size
    rotations = 0

    while rotations < max_rotations:
        credential = pool.select()

        for attempt in range(max_retries):
            try:
                result = await call_fn(credential)
                pool.record_success(credential.key_id)
                return RotationResult(
                    value=result,
                    key_id=credential.key_id,
                    attempts=rotations * max_retries + attempt + 1,
                    key_rotations=rotations,
                    retries_on_current_key=attempt,
                )
            except Exception as exc:
                classified = classify_error(exc)

                retry_after = getattr(classified, "retry_after_seconds", None)
                cooldown, should_block = _resolve_cooldown(classified, retry_after)

                if classified.retryable and attempt < max_retries - 1:
                    delay = jittered_backoff(attempt, base_delay=0.5, max_delay=8.0)
                    await asyncio.sleep(delay)
                    continue

                if cooldown > 0 or should_block:
                    pool.record_failure(
                        credential.key_id,
                        status_code=classified.detail.get("status_code", 0)
                        if isinstance(classified.detail, dict)
                        else 0,
                        error_code=classified.category.value,
                        cooldown_seconds=cooldown,
                        block=should_block,
                    )
                    break

                pool.record_failure(
                    credential.key_id,
                    error_code=classified.category.value,
                )
                raise

        rotations += 1

    raise PoolExhaustedError(
        message=f"Exhausted {rotations} key rotations for {pool.provider}",
        provider=pool.provider,
        total_keys=pool.size,
    )

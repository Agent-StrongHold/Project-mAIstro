"""Jittered exponential backoff with configurable ceiling.

Prevents thundering herd after provider outages by adding random jitter
to retry delays and enforcing a maximum delay cap.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class BackoffConfig:
    base_delay: float = 1.0
    max_delay: float = 60.0
    max_attempts: int = 3
    jitter_factor: float = 0.5


def jittered_backoff(
    attempt: int,
    *,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter_factor: float = 0.5,
) -> float:
    if attempt < 1:
        return 0.0
    raw = base_delay * (2 ** (attempt - 1))
    capped = min(raw, max_delay)
    jitter = capped * jitter_factor * random.random()  # nosec B311 — backoff jitter, not crypto
    return float(min(capped + jitter, max_delay))


def compute_backoff(
    attempt: int,
    config: BackoffConfig,
    *,
    retry_after: float | None = None,
) -> float:
    if retry_after is not None and retry_after > config.max_delay:
        return -1.0
    if retry_after is not None:
        return min(retry_after, config.max_delay)
    return jittered_backoff(
        attempt,
        base_delay=config.base_delay,
        max_delay=config.max_delay,
        jitter_factor=config.jitter_factor,
    )

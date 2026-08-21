from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from maistro.resilience.classifier import classify_error


class OperationStage(StrEnum):
    READ = "read"
    EVALUATE = "evaluate"
    WRITE = "write"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    base_delay: float
    max_delay: float
    retryable: bool = True


STAGE_POLICIES: dict[OperationStage, RetryPolicy] = {
    OperationStage.READ: RetryPolicy(
        max_attempts=3,
        base_delay=0.25,
        max_delay=2.0,
    ),
    OperationStage.EVALUATE: RetryPolicy(
        max_attempts=2,
        base_delay=1.0,
        max_delay=8.0,
    ),
    OperationStage.WRITE: RetryPolicy(
        max_attempts=1,
        base_delay=0.0,
        max_delay=0.0,
        retryable=False,
    ),
}


def get_policy(stage: OperationStage) -> RetryPolicy:
    return STAGE_POLICIES[stage]


def should_retry(stage: OperationStage, attempt: int, error: Exception) -> bool:
    policy = get_policy(stage)
    if attempt >= policy.max_attempts:
        return False
    if not policy.retryable:
        return False
    classified = classify_error(error)
    return classified.retryable


def get_delay(stage: OperationStage, attempt: int) -> float:
    policy = get_policy(stage)
    if policy.base_delay == 0.0:
        return 0.0
    if stage == OperationStage.READ:
        return policy.base_delay
    delay = policy.base_delay * (2**attempt)
    return float(min(delay, policy.max_delay))

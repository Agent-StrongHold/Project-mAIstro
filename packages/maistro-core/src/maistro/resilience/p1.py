"""P1 resilience: retry depth enforcement, attempt compaction, control-scope policy.

Implements ADR-066 / SPEC-070226-af02 on top of the existing ADR-038
primitives (``maistro.resilience.classifier`` and ``maistro.resilience.backoff``).

Public pieces:

- :func:`classify_error_code` — map exceptions to the four P1 error codes
  (``rate_limit``, ``timeout``, ``llm_refusal``, ``unknown``) via the
  ADR-038 classifier.
- :class:`RetryBudget` — max retry depth + attempt history + compaction window.
- :class:`CompactedRetry` / :func:`compact_attempts` — merge runs of
  same-error-code attempts within the compaction window into one signal.
- :class:`ResiliencePolicy` — per (agent_id, layer, error_code) decision:
  ``retry`` | ``escalate`` | ``fail``, with exponential/linear backoff.
- :class:`ResiliencePolicyStore` protocol + :class:`InMemoryResiliencePolicyStore`
  with wildcard fallback and operator-set defaults.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol

from maistro.resilience.classifier import ErrorCategory, classify_error

RetryAction = Literal["retry", "escalate", "fail"]
BackoffStrategy = Literal["exponential", "linear"]

WILDCARD = "*"

#: The P1 error codes (SPEC-070226-af02).
P1_ERROR_CODES: frozenset[str] = frozenset({"rate_limit", "timeout", "llm_refusal", "unknown"})


class Layer(StrEnum):
    """Coarse architectural layer for policy scoping."""

    FOUNDATION = "foundation"
    ORCHESTRATION = "orchestration"
    AGENTS = "agents"
    TOOLS = "tools"
    ANY = WILDCARD


#: All policy-scopable layers, most-specific first (``ANY`` is the wildcard).
LAYERS: tuple[Layer, ...] = (
    Layer.FOUNDATION,
    Layer.ORCHESTRATION,
    Layer.AGENTS,
    Layer.TOOLS,
    Layer.ANY,
)


def classify_error_code(error: Exception) -> str:
    """Map an exception to a P1 error code via the ADR-038 classifier.

    ``rate_limit`` | ``timeout`` | ``llm_refusal`` | ``unknown``.
    """
    category = classify_error(error).category
    if category is ErrorCategory.RATE_LIMIT:
        return "rate_limit"
    if category is ErrorCategory.TIMEOUT:
        return "timeout"
    if category is ErrorCategory.CONTENT_FILTER:
        return "llm_refusal"
    return "unknown"


@dataclass(frozen=True)
class RetryAttempt:
    """One failed execution attempt recorded on a :class:`RetryBudget`."""

    error_code: str
    message: str
    timestamp: float


@dataclass
class RetryBudget:
    """Retry depth budget with attempt history.

    ``max_retries`` is the total number of *failed attempts* allowed: a node
    with ``max_retries=3`` executes at most 3 times and fails after exactly
    3 failed attempts (no off-by-one).
    """

    max_retries: int = 3
    compaction_window_ms: int = 5000
    attempts: list[RetryAttempt] = field(default_factory=list)

    @property
    def current_attempt(self) -> int:
        """Number of failed attempts recorded so far."""
        return len(self.attempts)

    @property
    def exhausted(self) -> bool:
        return len(self.attempts) >= self.max_retries

    @property
    def remaining(self) -> int:
        return max(0, self.max_retries - len(self.attempts))

    def record(
        self,
        error: Exception,
        *,
        error_code: str | None = None,
        timestamp: float | None = None,
    ) -> RetryAttempt:
        """Record a failed attempt and return it."""
        attempt = RetryAttempt(
            error_code=error_code if error_code is not None else classify_error_code(error),
            message=str(error)[:200],
            timestamp=time.monotonic() if timestamp is None else timestamp,
        )
        self.attempts.append(attempt)
        return attempt


@dataclass(frozen=True)
class CompactedRetry:
    """Several same-error-code attempts within one compaction window."""

    error_code: str
    count: int
    first_timestamp: float
    last_timestamp: float
    common_cause: str

    def to_dict(self) -> dict[str, object]:
        return {
            "error_code": self.error_code,
            "count": self.count,
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "common_cause": self.common_cause,
        }


def compact_attempts(
    attempts: list[RetryAttempt],
    window_ms: int,
) -> list[CompactedRetry | RetryAttempt]:
    """Merge consecutive same-error-code attempts within ``window_ms`` of the
    group's first attempt into a single :class:`CompactedRetry`.

    Single attempts are never compacted: a group of size 1 is returned as the
    original :class:`RetryAttempt` (so every ``CompactedRetry`` has
    ``count >= 2``). Attempts of a different code, or outside the window,
    start a new group.
    """
    out: list[CompactedRetry | RetryAttempt] = []
    i = 0
    while i < len(attempts):
        first = attempts[i]
        j = i + 1
        while (
            j < len(attempts)
            and attempts[j].error_code == first.error_code
            and (attempts[j].timestamp - first.timestamp) * 1000.0 < window_ms
        ):
            j += 1
        group = attempts[i:j]
        if len(group) >= 2:
            out.append(
                CompactedRetry(
                    error_code=first.error_code,
                    count=len(group),
                    first_timestamp=first.timestamp,
                    last_timestamp=group[-1].timestamp,
                    common_cause=first.message,
                )
            )
        else:
            out.append(first)
        i = j
    return out


def exponential_backoff(attempt: int, *, base_delay: float = 2.0, max_delay: float = 60.0) -> float:
    """Deterministic exponential backoff: 2s, 4s, 8s… for attempts 1, 2, 3…"""
    if attempt < 1:
        return 0.0
    return float(min(base_delay * (2 ** (attempt - 1)), max_delay))


def linear_backoff(attempt: int, *, base_delay: float = 2.0, max_delay: float = 60.0) -> float:
    """Deterministic linear backoff: 2s, 4s, 6s… for attempts 1, 2, 3…"""
    if attempt < 1:
        return 0.0
    return float(min(base_delay * attempt, max_delay))


@dataclass(frozen=True)
class ResiliencePolicy:
    """Control-scope policy for one (agent_id, layer, error_code) scope.

    ``decide`` is consulted on *every* retry decision: escalation codes win,
    then the policy's own retry ceiling, otherwise retry.
    """

    agent_id: str = WILDCARD
    layer: str = WILDCARD
    error_code: str = WILDCARD
    max_p1_retries: int = 3
    backoff_strategy: BackoffStrategy = "exponential"
    base_delay_s: float = 2.0
    max_delay_s: float = 60.0
    escalate_on: frozenset[str] = frozenset()

    def decide(self, attempt: int, error: Exception | str) -> RetryAction:
        """Decide what to do after failed attempt number ``attempt`` (1-based).

        ``error`` may be an exception (classified via
        :func:`classify_error_code`) or an already-classified error code.
        """
        code = error if isinstance(error, str) else classify_error_code(error)
        if code in self.escalate_on:
            return "escalate"
        if attempt >= self.max_p1_retries:
            return "fail"
        return "retry"

    def backoff_for(self, attempt: int) -> float:
        """Backoff delay (seconds) before retry number ``attempt`` (1-based)."""
        if self.backoff_strategy == "linear":
            return linear_backoff(attempt, base_delay=self.base_delay_s, max_delay=self.max_delay_s)
        return exponential_backoff(
            attempt, base_delay=self.base_delay_s, max_delay=self.max_delay_s
        )


class ResiliencePolicyStore(Protocol):
    """(agent_id, layer, error_code) → :class:`ResiliencePolicy` lookup."""

    async def get(self, agent_id: str, layer: str, error_code: str) -> ResiliencePolicy: ...


#: Fallback when no policy matches: exponential backoff, no escalation.
DEFAULT_POLICY = ResiliencePolicy()


def default_policies() -> dict[tuple[str, str, str], ResiliencePolicy]:
    """Operator-set defaults: escalate LLM refusals; retry transients harder."""
    return {
        (WILDCARD, WILDCARD, "llm_refusal"): ResiliencePolicy(
            error_code="llm_refusal",
            escalate_on=frozenset({"llm_refusal"}),
        ),
        (WILDCARD, Layer.TOOLS.value, "rate_limit"): ResiliencePolicy(
            layer=Layer.TOOLS.value,
            error_code="rate_limit",
            max_p1_retries=5,
        ),
    }


class InMemoryResiliencePolicyStore:
    """In-memory :class:`ResiliencePolicyStore` with wildcard fallback.

    Lookup order (most → least specific), then :attr:`DEFAULT_POLICY`:
    exact, (agent, layer, *), (agent, *, code), (*, layer, code),
    (agent, *, *), (*, layer, *), (*, *, code), (*, *, *).
    """

    def __init__(
        self,
        policies: dict[tuple[str, str, str], ResiliencePolicy] | None = None,
        *,
        default: ResiliencePolicy = DEFAULT_POLICY,
        include_defaults: bool = True,
    ) -> None:
        self._policies: dict[tuple[str, str, str], ResiliencePolicy] = (
            default_policies() if include_defaults else {}
        )
        if policies:
            self._policies.update(policies)
        self._default = default

    def set(self, policy: ResiliencePolicy) -> None:
        self._policies[(policy.agent_id, policy.layer, policy.error_code)] = policy

    async def get(self, agent_id: str, layer: str, error_code: str) -> ResiliencePolicy:
        for key in (
            (agent_id, layer, error_code),
            (agent_id, layer, WILDCARD),
            (agent_id, WILDCARD, error_code),
            (WILDCARD, layer, error_code),
            (agent_id, WILDCARD, WILDCARD),
            (WILDCARD, layer, WILDCARD),
            (WILDCARD, WILDCARD, error_code),
            (WILDCARD, WILDCARD, WILDCARD),
        ):
            found = self._policies.get(key)
            if found is not None:
                return found
        return self._default


__all__ = [
    "DEFAULT_POLICY",
    "LAYERS",
    "P1_ERROR_CODES",
    "WILDCARD",
    "BackoffStrategy",
    "CompactedRetry",
    "InMemoryResiliencePolicyStore",
    "Layer",
    "ResiliencePolicy",
    "ResiliencePolicyStore",
    "RetryAction",
    "RetryAttempt",
    "RetryBudget",
    "classify_error_code",
    "compact_attempts",
    "default_policies",
    "exponential_backoff",
    "linear_backoff",
]

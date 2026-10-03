"""Canvas job retry policy — backoff schedule and poison classification.

One module owns both halves of the retry decision the runner and the store
make, so the receipt's fate cannot drift between the code path that requeues
a job (``CanvasJobRunner.tick_once``, ``PgCanvasStore.reap_expired_leases``)
and the code path that explains the failure to the user
(``CanvasExecutor._sanitise_error``).

Backoff
-------
A requeued job is not claimable again until ``next_retry_at`` — an exponential
``base * factor**(attempt-1)`` delay capped at ``cap``. The delay is computed
from the attempt number the store just charged (``claim_next_pending``
increments ``attempts`` atomically with the claim), and it is persisted on the
row so it survives process death: a requeued job whose worker dies before the
next claim cannot lose its backoff and hammer the provider in a tight loop.

Poison jobs
-----------
A failure the provider classifies as permanent — an authentication or
authorization fault — can never succeed on retry, so requeueing it would only
burn the remaining attempt budget before reaching the same terminal state.
``classify_failure`` marks those ``PERMANENT``; the runner terminalizes a
poison job immediately through the same canonical reconciliation the retry
ceiling uses, instead of requeueing it. Every other failure class stays
retryable: rate limits, unavailability, and timeouts are exactly the faults a
retry exists for.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class JobFailureClass(Enum):
    """Why a provider call failed, at the granularity the retry policy needs.

    ``AUTH`` is the one permanently-unretryable class: retrying a job whose
    provider credentials are wrong cannot succeed, only delay the receipt's
    terminal failure. The remaining classes map one-to-one onto
    ``_sanitise_error``'s user-facing messages, from the same keyword match.
    """

    RATE_LIMITED = auto()
    UNAVAILABLE = auto()
    AUTH = auto()
    TIMEOUT = auto()
    UNKNOWN = auto()


#: The failure classes a requeue can never turn into a success. Terminalizing
#: immediately (poison handling) is the only honest outcome for these.
PERMANENT_FAILURE_CLASSES = frozenset({JobFailureClass.AUTH})


def classify_failure(exc: BaseException) -> JobFailureClass:
    """Classify a job failure from the single keyword match ``_sanitise_error`` uses.

    A typed ``TimeoutError`` takes precedence, matching the sanitiser; opaque
    execution IDs can contain HTTP-like digits without being provider errors.
    For untyped errors, order matters: rate-limit and availability
    markers are checked before the authentication markers because a provider
    body may legitimately contain both (a 503 page behind an authenticated
    gateway is an availability fault, not an auth one).
    """
    if isinstance(exc, TimeoutError):
        return JobFailureClass.TIMEOUT
    raw = str(exc)
    lower = raw.lower()
    if "429" in raw or "rate_limit" in lower or "too many" in lower or "ratelimit" in lower:
        return JobFailureClass.RATE_LIMITED
    if "503" in raw or "service unavailable" in lower:
        return JobFailureClass.UNAVAILABLE
    if "401" in raw or "403" in raw or "unauthorized" in lower or "forbidden" in lower:
        return JobFailureClass.AUTH
    if "timeout" in lower or "timed out" in lower:
        return JobFailureClass.TIMEOUT
    return JobFailureClass.UNKNOWN


@dataclass(frozen=True)
class RetryBackoff:
    """Exponential retry delay: ``min(cap, base * factor**(attempt - 1))``.

    ``attempt`` is the attempt number the store charged for the failure being
    retried (1-indexed), so the first requeue waits ``base`` seconds, the
    second ``base * factor``, and so on until ``cap``. Both bounds are
    constructor state rather than module constants so composition (and tests)
    can tune the schedule without edits here; the durable column the delay is
    written to keeps whichever schedule the writing process was configured
    with, which is the one its store and runner share.
    """

    base_seconds: float = 2.0
    factor: float = 2.0
    cap_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.base_seconds < 0:
            raise ValueError("retry base_seconds must be non-negative")
        if self.factor < 1.0:
            raise ValueError("retry factor must be >= 1")
        if self.cap_seconds < self.base_seconds:
            raise ValueError("retry cap_seconds must be >= base_seconds")

    def delay_for_attempt(self, attempt: int) -> float:
        """Delay in seconds after ``attempt`` (1-indexed) failed.

        ``max(attempt, 1)`` guards a row whose attempt counter has not been
        charged yet: attempt 0 would otherwise produce a *longer* delay than
        attempt 1 (``factor**-1``), making the first retry slower than the
        second for no reason.
        """
        if attempt < 1:
            attempt = 1
        return min(self.cap_seconds, self.base_seconds * self.factor ** (attempt - 1))


#: The schedule every production component defaults to. One tuple so the
#: runner's ctor defaults and the store's ctor defaults cannot disagree.
DEFAULT_RETRY_BACKOFF = RetryBackoff()

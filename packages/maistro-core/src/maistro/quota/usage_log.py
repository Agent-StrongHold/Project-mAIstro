"""Local usage cache — the only thing ever read on the hot path.

One event log per scope key answers "how much of unit X was recorded in
[start, end)" for any range, so RPS/RPM/RPH/RPD/TPM/TPD all fall out of the
same primitive instead of needing a separate tracker per dimension. Every
real decision (`cycles_remaining`, a dispatch gate) reads only from here —
the provider's own API is consulted rarely, via reconciliation
(`reconciliation.py`), which compares against this log but never mutates it:
this is a pure record of what we actually observed locally.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field

from maistro.quota.rate_profile import LimitUnit

_TOKEN_UNITS: tuple[LimitUnit, ...] = (
    LimitUnit.INPUT_TOKENS,
    LimitUnit.OUTPUT_TOKENS,
    LimitUnit.TOTAL_TOKENS,
    LimitUnit.IMAGES,
)


@dataclass(frozen=True)
class UsageEvent:
    timestamp: float
    input_tokens: int = 0
    output_tokens: int = 0
    images: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


# Per-unit accessor, keyed by LimitUnit — turns sum_between's dispatch into a
# single lookup + generator sum instead of an if/elif chain per unit.
_UNIT_EXTRACTORS: dict[LimitUnit, Callable[[UsageEvent], float]] = {
    LimitUnit.REQUESTS: lambda e: 1.0,
    LimitUnit.INPUT_TOKENS: lambda e: float(e.input_tokens),
    LimitUnit.OUTPUT_TOKENS: lambda e: float(e.output_tokens),
    LimitUnit.TOTAL_TOKENS: lambda e: float(e.total_tokens),
    LimitUnit.IMAGES: lambda e: float(e.images),
    LimitUnit.CREDITS_USD: lambda e: e.cost_usd,
}


@dataclass
class _ScopeLog:
    events: deque[UsageEvent] = field(default_factory=deque)


class InMemoryUsageLog:
    """Sliding-window usage log, one independent window per scope key.

    `max_retention_s` should be at least as large as the longest configured
    window (typically a day) — events older than that are pruned since no
    constraint can query further back.
    """

    def __init__(self, max_retention_s: float = 86_400.0) -> None:
        self._max_retention_s = max_retention_s
        self._scopes: dict[str, _ScopeLog] = defaultdict(_ScopeLog)

    def record(
        self,
        scope_key: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        images: int = 0,
        cost_usd: float = 0.0,
        now: float | None = None,
    ) -> None:
        now = now if now is not None else time.time()
        log = self._scopes[scope_key]
        log.events.append(
            UsageEvent(
                timestamp=now,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                images=images,
                cost_usd=cost_usd,
            )
        )
        self._prune(log, now)

    def _prune(self, log: _ScopeLog, now: float) -> None:
        cutoff = now - self._max_retention_s
        while log.events and log.events[0].timestamp < cutoff:
            log.events.popleft()

    def sum_between(self, scope_key: str, unit: LimitUnit, start_ts: float, end_ts: float) -> float:
        """Raw local total of `unit` usage recorded in (start_ts, end_ts].

        Exclusive on the start, inclusive on the end — so a `count_since(...,
        now=now)` query (where `end_ts` is always "this instant") counts an
        event recorded exactly now, and adjacent windows built from
        successive checkpoints (`(t0, t1]` then `(t1, t2]`) never double-count
        or drop an event that lands exactly on the shared boundary.
        """
        log = self._scopes.get(scope_key)
        if log is None:
            return 0.0
        extractor = _UNIT_EXTRACTORS[unit]
        recent = (e for e in log.events if start_ts < e.timestamp <= end_ts)
        return sum(extractor(e) for e in recent)

    def count_since(self, scope_key: str, seconds_ago: float, *, now: float | None = None) -> float:
        now = now if now is not None else time.time()
        return self.sum_between(scope_key, LimitUnit.REQUESTS, now - seconds_ago, now)

    def tokens_since(
        self,
        scope_key: str,
        seconds_ago: float,
        unit: LimitUnit,
        *,
        now: float | None = None,
    ) -> float:
        if unit not in _TOKEN_UNITS:
            raise ValueError(f"tokens_since is for token/image units, got {unit}")
        now = now if now is not None else time.time()
        return self.sum_between(scope_key, unit, now - seconds_ago, now)

    def scope_keys(self) -> tuple[str, ...]:
        """All scope keys currently tracked. Read-only introspection for
        persistence layers (`sqlite_usage_log.py`) -- never used on the hot
        path itself, which only ever calls `record`/`sum_between`/etc."""
        return tuple(self._scopes.keys())

    def events_for(self, scope_key: str) -> tuple[UsageEvent, ...]:
        """All currently-retained events for `scope_key`, oldest first (already
        pruned to `max_retention_s`). Read-only introspection, same audience
        as `scope_keys`."""
        log = self._scopes.get(scope_key)
        return tuple(log.events) if log is not None else ()


_default_usage_log: InMemoryUsageLog | None = None


def get_default_usage_log() -> InMemoryUsageLog:
    """The process-wide shared usage log, lazily constructed on first use.

    Mirrors `config/settings.py`'s `get_yaml_config`/`set_yaml_config` module-
    level-singleton pattern. Exists because not every caller that needs a
    quota-aware node (`RsiQuotaPaceTriggerNode`) or a full DI `Container` --
    hive-conductor imports maistro-core pieces directly rather than
    constructing one (confirmed: `daily_status_runner.py` has no `Container`
    in scope at all), so a `Container`-independent shared instance is the only
    thing every real caller can actually reach.
    """
    global _default_usage_log
    if _default_usage_log is None:
        _default_usage_log = InMemoryUsageLog()
    return _default_usage_log


def set_default_usage_log(log: InMemoryUsageLog | None) -> None:
    """Override (or, with `None`, reset) the process-wide shared usage log --
    primarily a test seam, mirroring `set_yaml_config`."""
    global _default_usage_log
    _default_usage_log = log

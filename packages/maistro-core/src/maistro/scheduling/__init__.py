"""Recurring work: cron recurrence, fire semantics, and schedule persistence.

A Schedule is a *definition* — when to fire, and which GraphTemplate to
instantiate. Firing produces a canonical Run, so scheduled work is the same
durable object as interactive work and there is no second execution lifecycle
to keep in sync. See the recurrence-and-scheduling ADR.
"""

from maistro.scheduling.cron import CronExpression, CronParseError, minimum_gap, parse_cron
from maistro.scheduling.engine import (
    FireDecision,
    ScheduleEvaluation,
    SkippedFire,
    SkipReason,
    evaluate,
)
from maistro.scheduling.model import (
    DEFAULT_CATCHUP_WINDOW_SECONDS,
    OverlapPolicy,
    Schedule,
)
from maistro.scheduling.store import (
    InMemoryScheduleStore,
    ScheduleStore,
    SqliteScheduleStore,
)

__all__ = [
    "DEFAULT_CATCHUP_WINDOW_SECONDS",
    "CronExpression",
    "CronParseError",
    "FireDecision",
    "InMemoryScheduleStore",
    "OverlapPolicy",
    "Schedule",
    "ScheduleEvaluation",
    "ScheduleStore",
    "SkipReason",
    "SkippedFire",
    "SqliteScheduleStore",
    "evaluate",
    "minimum_gap",
    "parse_cron",
]

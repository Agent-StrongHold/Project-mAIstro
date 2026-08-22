"""Recurring work: cron recurrence, fire semantics, and schedule persistence.

A Schedule is a *definition* — when to fire, and which GraphTemplate to
instantiate. Firing produces a canonical Run, so scheduled work is the same
durable object as interactive work and there is no second execution lifecycle
to keep in sync. See the recurrence-and-scheduling ADR.
"""

from maistro.scheduling.admission import (
    CATCHUP_KEY,
    SCHEDULE_ID_KEY,
    SCHEDULE_SOURCE,
    SCHEDULED_FOR_KEY,
    ScheduleRunAdmitter,
)
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
    "CATCHUP_KEY",
    "DEFAULT_CATCHUP_WINDOW_SECONDS",
    "SCHEDULED_FOR_KEY",
    "SCHEDULE_ID_KEY",
    "SCHEDULE_SOURCE",
    "CronExpression",
    "CronParseError",
    "FireDecision",
    "InMemoryScheduleStore",
    "OverlapPolicy",
    "Schedule",
    "ScheduleEvaluation",
    "ScheduleRunAdmitter",
    "ScheduleStore",
    "SkipReason",
    "SkippedFire",
    "SqliteScheduleStore",
    "evaluate",
    "minimum_gap",
    "parse_cron",
]

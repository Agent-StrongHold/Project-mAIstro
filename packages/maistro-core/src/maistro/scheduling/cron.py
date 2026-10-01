"""POSIX 5-field cron: parsing, matching, and timezone-aware next-fire.

This is the single cron dialect for the engine. It replaces two disagreeing
hand-rolled matchers, each wrong in a different way: one indexed day-of-week
by Python's ``date.weekday()`` (Monday=0), so every ``0``-means-Sunday
expression fired a day late, and ANDed day-of-month with day-of-week, so
``0 0 1 * 1`` meant "the 1st, and only when it is a Monday" (roughly once
every seven months) instead of POSIX's "the 1st, or any Monday"; the other
validated a day-of-week range of 0-7 those matchers could never satisfy.

Semantics implemented here (Vixie/POSIX):

- Day-of-week is **Sunday=0** through Saturday=6, with 7 also accepted as
  Sunday.
- When **both** day-of-month and day-of-week are restricted (neither is
  ``*``), a day matches if **either** field matches. When only one is
  restricted, that one governs. This OR rule is the single most commonly
  mis-implemented part of cron.
- Three-letter month and day names (``JAN``..``DEC``, ``SUN``..``SAT``) are
  accepted case-insensitively.
- Fields accept ``*``, ``a``, ``a-b``, ``a-b/s``, ``*/s`` and comma-separated
  lists of those. A bare ``a/s`` is accepted as ``a-max/s``.

Timezone and DST (see the recurrence ADR):

- Recurrence is evaluated in the schedule's **wall time**, so "07:00 every
  weekday" stays 07:00 across a DST transition rather than drifting an hour.
- A wall time that **does not exist** (spring-forward gap) is skipped; the
  schedule fires at its next valid occurrence rather than silently at a time
  the user never asked for.
- A wall time that occurs **twice** (fall-back) fires **once**, on the first
  (pre-transition) occurrence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

__all__ = [
    "CronExpression",
    "CronParseError",
    "minimum_gap",
    "parse_cron",
]

_FIELD_COUNT: Final = 5
# Defensive bound on the next-fire search. The walk advances a whole month,
# day, or hour whenever the coarser field cannot match, so a real expression
# converges in well under a thousand steps even for `0 0 29 2 *` (Feb 29,
# up to eight years out). Anything beyond this is a bug, not a slow schedule.
_MAX_SEARCH_STEPS: Final = 100_000

_MONTH_NAMES: Final = {
    name: index
    for index, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}
_DOW_NAMES: Final = {
    name: index for index, name in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))
}

_STEP_RE: Final = re.compile(r"^(?P<base>[^/]+)/(?P<step>\d+)$")
_RANGE_RE: Final = re.compile(r"^(?P<lo>[^-]+)-(?P<hi>.+)$")


class CronParseError(ValueError):
    """Raised when an expression is not a valid 5-field POSIX cron string."""


@dataclass(frozen=True)
class _Field:
    """One parsed cron field: the set of values it matches, and whether it is
    unrestricted (``*``), which the day-of-month/day-of-week OR rule needs."""

    values: frozenset[int]
    restricted: bool


def _resolve_name(token: str, names: dict[str, int]) -> str:
    return str(names[token]) if token in names else token


def _parse_int(token: str, *, low: int, high: int, field: str) -> int:
    try:
        value = int(token)
    except ValueError:
        raise CronParseError(f"{field}: {token!r} is not a number or known name") from None
    if not low <= value <= high:
        raise CronParseError(f"{field}: {value} is outside {low}-{high}")
    return value


def _parse_term(term: str, *, low: int, high: int, field: str, names: dict[str, int]) -> set[int]:
    """Parse one comma-separated term: `*`, `a`, `a-b`, and any with `/step`."""
    step = 1
    if match := _STEP_RE.match(term):
        term = match.group("base")
        step = int(match.group("step"))
        if step < 1:
            raise CronParseError(f"{field}: step must be >= 1, got {step}")

    if term == "*":
        return set(range(low, high + 1, step))

    if match := _RANGE_RE.match(term):
        start = _parse_int(_resolve_name(match.group("lo"), names), low=low, high=high, field=field)
        end = _parse_int(_resolve_name(match.group("hi"), names), low=low, high=high, field=field)
        if start > end:
            raise CronParseError(f"{field}: range {start}-{end} is inverted")
        return set(range(start, end + 1, step))

    value = _parse_int(_resolve_name(term, names), low=low, high=high, field=field)
    # `a/s` with no upper bound means "from a to the field maximum, by s".
    return set(range(value, high + 1, step)) if step > 1 else {value}


def _parse_field(
    raw: str, *, low: int, high: int, field: str, names: dict[str, int] | None = None
) -> _Field:
    token = raw.strip().lower()
    if not token:
        raise CronParseError(f"{field}: empty field")
    resolved_names = names or {}
    values: set[int] = set()
    for term in token.split(","):
        values |= _parse_term(term.strip(), low=low, high=high, field=field, names=resolved_names)
    if not values:
        raise CronParseError(f"{field}: matches nothing")
    return _Field(values=frozenset(values), restricted=token != "*")


@dataclass(frozen=True)
class CronExpression:
    """A parsed 5-field cron expression."""

    source: str
    minute: _Field
    hour: _Field
    day_of_month: _Field
    month: _Field
    day_of_week: _Field

    def _day_matches(self, moment: datetime) -> bool:
        """POSIX day rule: OR the day fields when both are restricted."""
        # date.weekday() is Monday=0; cron is Sunday=0.
        dow = (moment.weekday() + 1) % 7
        dom_hit = moment.day in self.day_of_month.values
        dow_hit = dow in self.day_of_week.values
        if self.day_of_month.restricted and self.day_of_week.restricted:
            return dom_hit or dow_hit
        if self.day_of_month.restricted:
            return dom_hit
        if self.day_of_week.restricted:
            return dow_hit
        return True

    def matches(self, moment: datetime) -> bool:
        """Whether this expression fires at ``moment``'s wall-clock minute."""
        return (
            moment.minute in self.minute.values
            and moment.hour in self.hour.values
            and moment.month in self.month.values
            and self._day_matches(moment)
        )

    def next_fire(self, after: datetime, *, timezone: str = "UTC") -> datetime:
        """First fire strictly after ``after``, as an aware datetime.

        ``after`` may be naive (read as wall time in ``timezone``) or aware
        (converted into ``timezone`` first). Wall times that do not exist in
        the zone are skipped; times that occur twice fire on the first.
        """
        zone = _zone(timezone)
        local = after.astimezone(zone) if after.tzinfo is not None else after.replace(tzinfo=zone)
        # Search in naive wall time so DST shifts do not move the nominal hour.
        cursor = local.replace(tzinfo=None, second=0, microsecond=0) + timedelta(minutes=1)

        for _ in range(_MAX_SEARCH_STEPS):
            if cursor.month not in self.month.values:
                cursor = _start_of_next_month(cursor)
                continue
            if not self._day_matches(cursor):
                cursor = _start_of_next_day(cursor)
                continue
            if cursor.hour not in self.hour.values:
                cursor = (cursor + timedelta(hours=1)).replace(minute=0)
                continue
            if cursor.minute not in self.minute.values:
                cursor += timedelta(minutes=1)
                continue
            aware = cursor.replace(tzinfo=zone)
            if _exists_in_zone(aware, zone):
                return aware
            # Spring-forward gap: this wall minute never happens here.
            cursor += timedelta(minutes=1)

        raise CronParseError(f"{self.source!r}: no fire time found within the search bound")


def _zone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except Exception as exc:  # any zoneinfo failure means the name is unusable
        raise CronParseError(f"unknown timezone {timezone!r}") from exc


def _exists_in_zone(aware: datetime, zone: ZoneInfo) -> bool:
    """False for wall times inside a spring-forward gap.

    A nonexistent local time does not survive a round trip through UTC: it is
    interpreted with the pre-transition offset on the way out and comes back
    as a different wall time. This is the standard detection and needs no
    direct consultation of the tz database.
    """
    round_tripped = aware.astimezone(UTC).astimezone(zone)
    return round_tripped.replace(tzinfo=None) == aware.replace(tzinfo=None)


def _start_of_next_month(moment: datetime) -> datetime:
    year, month = (moment.year + 1, 1) if moment.month == 12 else (moment.year, moment.month + 1)
    return moment.replace(year=year, month=month, day=1, hour=0, minute=0)


def _start_of_next_day(moment: datetime) -> datetime:
    return (moment + timedelta(days=1)).replace(hour=0, minute=0)


def parse_cron(expression: str) -> CronExpression:
    """Parse a 5-field POSIX cron expression, or raise ``CronParseError``."""
    parts = expression.strip().split()
    if len(parts) != _FIELD_COUNT:
        raise CronParseError(
            f"expected {_FIELD_COUNT} fields (minute hour day-of-month month day-of-week), "
            f"got {len(parts)}: {expression!r}"
        )
    minute, hour, dom, month, dow = parts
    parsed_dow = _parse_field(dow, low=0, high=7, field="day-of-week", names=_DOW_NAMES)
    # POSIX accepts 7 for Sunday; normalise so matching only ever sees 0-6.
    normalised = frozenset(0 if value == 7 else value for value in parsed_dow.values)
    return CronExpression(
        source=expression.strip(),
        minute=_parse_field(minute, low=0, high=59, field="minute"),
        hour=_parse_field(hour, low=0, high=23, field="hour"),
        day_of_month=_parse_field(dom, low=1, high=31, field="day-of-month"),
        month=_parse_field(month, low=1, high=12, field="month", names=_MONTH_NAMES),
        day_of_week=_Field(values=normalised, restricted=parsed_dow.restricted),
    )


# Sampling must follow the fires, not a fixed calendar window. A window
# anchored in January sees nothing at all for a month-restricted expression
# like `0,10 0 1 3 *` and would report it as unbounded — which is the
# dangerous direction, since a product floor would then accept a schedule
# that actually fires ten minutes apart. Four years covers the leap cycle,
# and the fire cap bounds the walk for dense expressions.
_GAP_HORIZON_DAYS: Final = 4 * 366
_GAP_MAX_FIRES: Final = 512


def minimum_gap(expression: str, *, timezone: str = "UTC") -> timedelta:
    """Shortest interval between consecutive fires of ``expression``.

    Products use this to refuse schedules that would run too often. It is
    computed from real consecutive fire times, so it accounts for every field
    — the day-of-month and day-of-week fields included, which a minute-and-
    hour-only estimate silently ignores.

    Returns ``timedelta.max`` only when the expression fires at most once in
    four years, which is the genuinely unbounded case.
    """
    parsed = parse_cron(expression)
    # A fixed, arbitrary start: gaps are a property of the expression, and
    # anchoring makes the answer deterministic.
    cursor = datetime(2027, 1, 1, tzinfo=_zone(timezone))
    horizon = cursor + timedelta(days=_GAP_HORIZON_DAYS)
    smallest = timedelta.max
    previous: datetime | None = None
    for _ in range(_GAP_MAX_FIRES):
        cursor = parsed.next_fire(cursor, timezone=timezone)
        if cursor > horizon:
            break
        if previous is not None:
            smallest = min(smallest, cursor - previous)
        previous = cursor
    return smallest

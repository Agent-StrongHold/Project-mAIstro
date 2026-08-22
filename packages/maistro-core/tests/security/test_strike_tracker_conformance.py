"""One suite, both strike trackers (#134).

`PgStrikeTracker` described itself as replacing `InMemoryStrikeTracker` and was
not substitutable at all: `get()` returned a dict where `Gate` does attribute
access on a `StrikeRecord`, and `record_violation()` returned three keys where
`Gate` reads six. Wiring it would have raised AttributeError on the *first
security violation* — the worst place to discover anything.

What let that stand was the shape of the tests. The old `test_pg_strikes.py`
mocked the asyncpg pool and asserted on SQL strings and dict keys, so it could
not notice that the return type was wrong for the only caller. It is replaced by
this: the same bodies against both implementations, with the PostgreSQL one
talking to a real server.

The escalation ladder is security behaviour, so the cases below are written as
the properties a reviewer would want to check by hand — strike one warns, strike
two locks with an expiry, strike three disables and stays disabled.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from maistro.protocols import StrikeTracker
from maistro.security.strikes import (
    DISABLED,
    ELEVATED,
    LOCKED,
    NORMAL,
    InMemoryStrikeTracker,
)
from maistro.testing.postgres import postgres_dsn

FLAGS = ("prompt_injection",)


@pytest.fixture(params=["memory", "postgres"])
async def tracker(request: pytest.FixtureRequest, pg_pool: Any) -> Any:
    if request.param == "memory":
        yield InMemoryStrikeTracker()
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.security.pg_strikes import PgStrikeTracker

    yield PgStrikeTracker(pg_pool)


async def _strike(tracker: Any, user_id: str = "u1", times: int = 1) -> Any:
    record = None
    for _ in range(times):
        record = await tracker.record_violation(user_id=user_id, flags=FLAGS)
    return record


# ── the protocol itself ───────────────────────────────────────────


def test_both_satisfy_the_protocol(tracker: Any) -> None:
    assert isinstance(tracker, StrikeTracker)


async def test_a_clean_user_has_no_record(tracker: Any) -> None:
    assert await tracker.get("never-offended") is None


# ── the escalation ladder ─────────────────────────────────────────


async def test_strike_one_elevates_without_locking(tracker: Any) -> None:
    record = await _strike(tracker)

    assert record.strike_count == 1
    assert record.scrutiny_level == ELEVATED
    assert record.is_locked is False
    assert record.disabled is False


async def test_strike_two_locks_with_an_expiry(tracker: Any) -> None:
    record = await _strike(tracker, times=2)

    assert record.strike_count == 2
    assert record.scrutiny_level == LOCKED
    assert record.is_locked is True
    assert record.disabled is False
    assert record.locked_until is not None
    assert record.locked_until > datetime.now(UTC)


async def test_strike_three_disables(tracker: Any) -> None:
    record = await _strike(tracker, times=3)

    assert record.strike_count == 3
    assert record.scrutiny_level == DISABLED
    assert record.disabled is True
    assert record.is_locked is True


async def test_further_strikes_keep_the_account_disabled(tracker: Any) -> None:
    """An account cannot climb back down the ladder by offending more."""
    record = await _strike(tracker, times=5)

    assert record.strike_count == 5
    assert record.disabled is True


async def test_the_ladder_is_per_user(tracker: Any) -> None:
    await _strike(tracker, user_id="u1", times=3)
    await _strike(tracker, user_id="u2", times=1)

    assert (await tracker.get("u1")).disabled is True
    assert (await tracker.get("u2")).disabled is False


# ── what Gate actually reads ──────────────────────────────────────


async def test_the_record_carries_everything_gate_reads(tracker: Any) -> None:
    """`Gate` turns this straight into the response a blocked user sees: the
    strike number, the scrutiny level and when the lockout lifts. A summary
    with fewer fields is the defect this issue was filed about."""
    record = await _strike(tracker, times=2)

    assert record.user_id == "u1"
    assert isinstance(record.strike_count, int)
    assert isinstance(record.scrutiny_level, str)
    assert isinstance(record.disabled, bool)
    assert isinstance(record.is_locked, bool)
    assert record.locked_until is not None
    assert record.locked_until.isoformat()


async def test_record_violation_and_get_agree(tracker: Any) -> None:
    """The record handed back must be the record that was stored — otherwise a
    caller acts on one state and the next reader sees another."""
    written = await _strike(tracker, times=2)
    read = await tracker.get("u1")

    assert read is not None
    assert (read.strike_count, read.scrutiny_level, read.disabled) == (
        written.strike_count,
        written.scrutiny_level,
        written.disabled,
    )


async def test_locked_until_is_timezone_aware(tracker: Any) -> None:
    """`Gate` compares it against `datetime.now(UTC)`; a naive value raises."""
    record = await _strike(tracker, times=2)

    assert record.locked_until is not None
    assert record.locked_until.tzinfo is not None
    assert record.is_locked is True


# ── administrative recovery ───────────────────────────────────────


async def test_unlock_lifts_the_lockout_without_forgiving_the_strikes(tracker: Any) -> None:
    await _strike(tracker, times=2)

    record = await tracker.unlock("u1")

    assert record is not None
    assert record.is_locked is False
    assert record.locked_until is None
    assert record.strike_count == 2, "unlocking is not forgiveness"
    assert record.scrutiny_level == ELEVATED


async def test_unlock_does_not_re_enable_a_disabled_account(tracker: Any) -> None:
    """Different remedies for different rungs — an unlock must not quietly
    perform the more privileged action."""
    await _strike(tracker, times=3)

    record = await tracker.unlock("u1")

    assert record is not None
    assert record.disabled is True
    assert record.is_locked is True


async def test_enable_restores_a_disabled_account(tracker: Any) -> None:
    await _strike(tracker, times=3)

    record = await tracker.enable("u1")

    assert record is not None
    assert record.disabled is False
    assert record.is_locked is False
    assert record.scrutiny_level == ELEVATED


async def test_removing_all_strikes_returns_to_normal(tracker: Any) -> None:
    await _strike(tracker, times=3)

    record = await tracker.remove_strikes("u1")

    assert record is not None
    assert record.strike_count == 0
    assert record.scrutiny_level == NORMAL
    assert record.disabled is False
    assert record.is_locked is False


async def test_removing_some_strikes_recomputes_the_rung(tracker: Any) -> None:
    await _strike(tracker, times=3)

    record = await tracker.remove_strikes("u1", count=2)

    assert record is not None
    assert record.strike_count == 1
    assert record.scrutiny_level == ELEVATED
    assert record.disabled is False


async def test_removing_strikes_from_an_unknown_user_is_none(tracker: Any) -> None:
    assert await tracker.remove_strikes("never-offended") is None
    assert await tracker.unlock("never-offended") is None
    assert await tracker.enable("never-offended") is None


# ── appeals ───────────────────────────────────────────────────────


async def test_an_appeal_needs_something_to_appeal_against(tracker: Any) -> None:
    assert await tracker.submit_appeal("never-offended", "please") is False


async def test_an_appeal_is_recorded(tracker: Any) -> None:
    await _strike(tracker)

    assert await tracker.submit_appeal("u1", "it was a false positive") is True

    record = await tracker.get("u1")
    assert record is not None
    assert record.last_appeal == "it was a false positive"


# ── durability, which only one of them has ────────────────────────


async def test_the_ladder_survives_a_restart_on_postgres(pg_pool: Any) -> None:
    """A lockout that resets on restart is a lockout an attacker clears by
    waiting for a deploy. The in-memory tracker cannot pass this, which is why
    it is not parametrized here."""
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.security.pg_strikes import PgStrikeTracker

    await PgStrikeTracker(pg_pool).record_violation(user_id="persisted", flags=FLAGS)
    await PgStrikeTracker(pg_pool).record_violation(user_id="persisted", flags=FLAGS)

    # A third tracker object, standing in for a restarted process.
    record = await PgStrikeTracker(pg_pool).get("persisted")

    assert record is not None
    assert record.strike_count == 2
    assert record.is_locked is True


def test_postgres_is_covered_when_configured() -> None:
    if not postgres_dsn():
        pytest.skip("no PostgreSQL configured; the parametrized cases skip by design")
    pytest.importorskip("asyncpg")

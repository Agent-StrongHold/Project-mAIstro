"""One suite over both strike trackers (#134).

`PgStrikeTracker` said it "replaces InMemoryStrikeTracker" and did not: both its
methods returned `dict` while `Gate` does attribute access on the result, so
wiring the durable tracker raised `AttributeError` on the **first security
violation** — on the path whose entire job is to hold under attack.

Nothing caught it because "same interface" was a docstring. It is a checked
claim here: the test bodies below are parametrised over both implementations,
so a divergence fails rather than waiting for a deployment to find it.

The PostgreSQL leg needs a real server and skips without
`MAISTRO_TEST_DATABASE_URL`. Skipping keeps the suite runnable on a laptop, and
is also exactly how this defect survived — so treat a skipped leg as untested,
not as passing.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from maistro.protocols.strikes import StrikeTracker
from maistro.security.strikes import DISABLED, ELEVATED, LOCKED, InMemoryStrikeTracker

DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")


def _require_postgres() -> str:
    """The URL, or a skip — unless the caller declared a server is guaranteed.

    `MAISTRO_REQUIRE_PG_LEGS` is set by the `strike-ladder` CI job, which owns a
    postgres service container. There, "no URL" means the job is misconfigured,
    and skipping would leave it green with the durable tracker never run — the
    same silence that let `PgStrikeTracker` ship returning `dict`. Everywhere
    else (a laptop, the plain `test` job) skipping is the right answer.
    """
    if DATABASE_URL:
        return DATABASE_URL
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_DATABASE_URL is empty: "
            "the PostgreSQL leg cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_DATABASE_URL is unset; the PostgreSQL leg needs a real server")


@pytest.fixture(params=["memory", "postgres"])
async def tracker(request):
    if request.param == "memory":
        return InMemoryStrikeTracker()
    url = _require_postgres()
    from maistro.security.pg_strikes import PgStrikeTracker

    pg = PgStrikeTracker(db_url=url)
    pool = await pg._get_pool()
    # Truncate rather than drop: `_get_pool` creates the schema, and each test
    # needs an empty ladder without racing the CREATE TABLE IF NOT EXISTS.
    await pool.execute("TRUNCATE security_violations, security_strikes CASCADE")
    return pg


class TestBothSatisfyTheProtocol:
    def test_the_in_memory_tracker_is_a_strike_tracker(self):
        assert isinstance(InMemoryStrikeTracker(), StrikeTracker)

    def test_the_postgres_tracker_is_a_strike_tracker(self):
        from maistro.security.pg_strikes import PgStrikeTracker

        assert isinstance(PgStrikeTracker(db_url="postgresql://unused"), StrikeTracker)


class TestTheLadder:
    """The escalation `Gate` reports to callers, identical on both."""

    async def test_an_unknown_user_has_no_record(self, tracker):
        assert await tracker.get("nobody") is None

    async def test_the_first_strike_elevates(self, tracker):
        record = await tracker.record_violation(user_id="u1", flags=("injection",))
        assert record.strike_count == 1
        assert record.scrutiny_level == ELEVATED
        assert record.disabled is False
        assert record.locked_until is None
        assert record.is_locked is False

    async def test_the_second_strike_locks(self, tracker):
        """The rung that matters most, and the one the dict form could not
        report: `record_violation` returned `{"strike_count": 2}` with no
        `locked_until`, so the caller was told about a strike while the account
        was locked."""
        await tracker.record_violation(user_id="u1", flags=("injection",))
        record = await tracker.record_violation(user_id="u1", flags=("injection",))
        assert record.strike_count == 2
        assert record.scrutiny_level == LOCKED
        assert record.locked_until is not None
        assert record.locked_until > datetime.now(UTC)
        assert record.is_locked is True
        assert record.disabled is False

    async def test_the_third_strike_disables(self, tracker):
        for _ in range(3):
            record = await tracker.record_violation(user_id="u1", flags=("injection",))
        assert record.strike_count == 3
        assert record.scrutiny_level == DISABLED
        assert record.disabled is True
        assert record.is_locked is True

    async def test_the_returned_record_matches_a_subsequent_get(self, tracker):
        """`Gate` reports from the `record_violation` return value and admits
        from the `get` value. If those disagree, the response describes a state
        the account is not in."""
        written = await tracker.record_violation(user_id="u1", flags=("injection",))
        await tracker.record_violation(user_id="u1", flags=("injection",))
        written = await tracker.record_violation(user_id="u1", flags=("injection",))
        read = await tracker.get("u1")
        assert read is not None
        assert (read.strike_count, read.scrutiny_level, read.disabled) == (
            written.strike_count,
            written.scrutiny_level,
            written.disabled,
        )
        assert read.is_locked == written.is_locked

    async def test_users_do_not_share_a_ladder(self, tracker):
        await tracker.record_violation(user_id="u1", flags=("injection",))
        await tracker.record_violation(user_id="u1", flags=("injection",))
        other = await tracker.record_violation(user_id="u2", flags=("injection",))
        assert other.strike_count == 1
        assert other.is_locked is False


class TestTheAttributesGateReads:
    """Every attribute `security/gate.py` touches, on both implementations.

    Written against the *call sites* rather than the dataclass: the defect was
    a return type that satisfied nobody's test while satisfying the docstring,
    and this is the list that would have caught it.
    """

    @pytest.mark.parametrize(
        "attribute",
        ["strike_count", "scrutiny_level", "locked_until", "disabled", "is_locked"],
    )
    async def test_record_violation_returns_it(self, tracker, attribute):
        record = await tracker.record_violation(user_id="u1", flags=("injection",))
        assert hasattr(record, attribute), f"Gate reads .{attribute} off this value"

    @pytest.mark.parametrize(
        "attribute",
        ["strike_count", "scrutiny_level", "locked_until", "disabled", "is_locked"],
    )
    async def test_get_returns_it(self, tracker, attribute):
        await tracker.record_violation(user_id="u1", flags=("injection",))
        record = await tracker.get("u1")
        assert hasattr(record, attribute), f"Gate reads .{attribute} off this value"


class TestViolationsAreRecorded:
    async def test_each_violation_is_kept_with_its_flags(self, tracker):
        await tracker.record_violation(
            user_id="u1", flags=("injection", "exfil"), boundary="tool_output", detail="probe"
        )
        record = await tracker.get("u1")
        assert record is not None
        assert len(record.violations) == 1
        violation = record.violations[0]
        assert set(violation.flags) == {"injection", "exfil"}
        assert violation.boundary == "tool_output"
        assert violation.detail == "probe"

    async def test_last_violation_at_advances(self, tracker):
        first = await tracker.record_violation(user_id="u1", flags=("injection",))
        second = await tracker.record_violation(user_id="u1", flags=("injection",))
        assert first.last_violation_at is not None
        assert second.last_violation_at is not None
        assert second.last_violation_at >= first.last_violation_at


class TestDurability:
    """The reason the PostgreSQL tracker exists at all."""

    async def test_a_lockout_survives_a_new_tracker_instance(self, tracker):
        """A fresh instance stands in for a restart. On the in-memory tracker
        this is trivially false, so the assertion is scoped to the durable one
        — and stated rather than skipped silently, because "lockout survives a
        restart" is the acceptance criterion this whole change is for."""
        await tracker.record_violation(user_id="u1", flags=("injection",))
        await tracker.record_violation(user_id="u1", flags=("injection",))
        assert (await tracker.get("u1")).is_locked is True

        if isinstance(tracker, InMemoryStrikeTracker):
            fresh = InMemoryStrikeTracker()
            assert await fresh.get("u1") is None, "in-memory state is per-process, by design"
            return

        from maistro.security.pg_strikes import PgStrikeTracker

        reborn = PgStrikeTracker(db_url=DATABASE_URL)
        record = await reborn.get("u1")
        assert record is not None, "the lockout did not survive"
        assert record.is_locked is True
        assert record.strike_count == 2

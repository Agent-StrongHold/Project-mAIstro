"""Coverage for maistro.security.strikes.InMemoryStrikeTracker (was 0%)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from maistro.security.strikes import (
    DISABLED,
    ELEVATED,
    LOCKED,
    NORMAL,
    InMemoryStrikeTracker,
)


async def test_get_unknown_user_returns_none() -> None:
    tracker = InMemoryStrikeTracker()
    assert await tracker.get("nobody") is None


async def test_first_violation_elevates_scrutiny_without_locking() -> None:
    tracker = InMemoryStrikeTracker()
    record = await tracker.record_violation(user_id="u1", flags=("pii",), boundary="user_input")

    assert record.strike_count == 1
    assert record.scrutiny_level == ELEVATED
    assert record.disabled is False
    assert record.is_locked is False
    assert len(record.violations) == 1
    assert record.violations[0].flags == ("pii",)
    assert record.violations[0].boundary == "user_input"


async def test_second_violation_locks_account_for_8_hours() -> None:
    tracker = InMemoryStrikeTracker()
    await tracker.record_violation(user_id="u1", flags=("a",))
    record = await tracker.record_violation(user_id="u1", flags=("b",))

    assert record.strike_count == 2
    assert record.scrutiny_level == LOCKED
    assert record.is_locked is True
    assert record.locked_until is not None
    delta = record.locked_until - datetime.now(UTC)
    assert timedelta(hours=7, minutes=58) < delta <= timedelta(hours=8)


async def test_third_violation_disables_account_permanently() -> None:
    tracker = InMemoryStrikeTracker()
    for _ in range(3):
        record = await tracker.record_violation(user_id="u1", flags=("x",))

    assert record.strike_count == 3
    assert record.scrutiny_level == DISABLED
    assert record.disabled is True
    assert record.is_locked is True


async def test_disabled_account_remains_locked_even_without_locked_until() -> None:
    tracker = InMemoryStrikeTracker()
    for _ in range(3):
        await tracker.record_violation(user_id="u1", flags=("x",))
    record = await tracker.get("u1")
    assert record is not None
    record.locked_until = None
    assert record.is_locked is True  # disabled overrides lack of lockout timestamp


async def test_lockout_expires_after_window() -> None:
    tracker = InMemoryStrikeTracker()
    await tracker.record_violation(user_id="u1", flags=("a",))
    record = await tracker.record_violation(user_id="u1", flags=("b",))
    assert record.is_locked is True

    record.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    assert record.is_locked is False


async def test_submit_appeal_fails_for_unknown_user() -> None:
    tracker = InMemoryStrikeTracker()
    assert await tracker.submit_appeal("ghost", "please reinstate me") is False


async def test_submit_appeal_fails_for_user_with_zero_strikes() -> None:
    # A record with strike_count 0 never exists fresh out of record_violation,
    # so reach that state via remove_strikes instead.
    tracker = InMemoryStrikeTracker()
    await tracker.record_violation(user_id="clean", flags=("x",))
    await tracker.remove_strikes("clean")
    assert await tracker.submit_appeal("clean", "text") is False


async def test_submit_appeal_succeeds_and_records_text() -> None:
    tracker = InMemoryStrikeTracker()
    await tracker.record_violation(user_id="u1", flags=("a",))

    ok = await tracker.submit_appeal("u1", "it was a false positive")
    assert ok is True

    record = await tracker.get("u1")
    assert record is not None
    assert record.last_appeal == "it was a false positive"
    assert record.last_appeal_at is not None


async def test_remove_strikes_unknown_user_returns_none() -> None:
    tracker = InMemoryStrikeTracker()
    assert await tracker.remove_strikes("ghost") is None


async def test_remove_strikes_full_reset_clears_disabled_and_lock() -> None:
    tracker = InMemoryStrikeTracker()
    for _ in range(3):
        await tracker.record_violation(user_id="u1", flags=("x",))

    record = await tracker.remove_strikes("u1")
    assert record is not None
    assert record.strike_count == 0
    assert record.scrutiny_level == NORMAL
    assert record.disabled is False
    assert record.locked_until is None


async def test_remove_strikes_partial_count_recalculates_level() -> None:
    tracker = InMemoryStrikeTracker()
    for _ in range(3):
        await tracker.record_violation(user_id="u1", flags=("x",))

    record = await tracker.remove_strikes("u1", count=1)
    assert record is not None
    assert record.strike_count == 2
    assert record.scrutiny_level == LOCKED
    # _recalculate_level's count==2 branch never clears `disabled` -- dropping from
    # 3 strikes to 2 leaves the account disabled until `enable()` is called explicitly.
    assert record.disabled is True


async def test_remove_strikes_never_goes_negative() -> None:
    tracker = InMemoryStrikeTracker()
    await tracker.record_violation(user_id="u1", flags=("x",))
    record = await tracker.remove_strikes("u1", count=99)
    assert record is not None
    assert record.strike_count == 0


async def test_unlock_unknown_user_returns_none() -> None:
    tracker = InMemoryStrikeTracker()
    assert await tracker.unlock("ghost") is None


async def test_unlock_clears_lock_but_keeps_elevated_if_strikes_remain() -> None:
    tracker = InMemoryStrikeTracker()
    await tracker.record_violation(user_id="u1", flags=("a",))
    await tracker.record_violation(user_id="u1", flags=("b",))

    record = await tracker.unlock("u1")
    assert record is not None
    assert record.locked_until is None
    assert record.scrutiny_level == ELEVATED
    assert record.is_locked is False


async def test_unlock_does_not_clear_disabled_state() -> None:
    tracker = InMemoryStrikeTracker()
    for _ in range(3):
        await tracker.record_violation(user_id="u1", flags=("x",))

    record = await tracker.unlock("u1")
    assert record is not None
    assert record.disabled is True
    assert record.is_locked is True  # unlock() doesn't touch `disabled`; enable() does


async def test_enable_unknown_user_returns_none() -> None:
    tracker = InMemoryStrikeTracker()
    assert await tracker.enable("ghost") is None


async def test_enable_clears_disabled_and_lock() -> None:
    tracker = InMemoryStrikeTracker()
    for _ in range(3):
        await tracker.record_violation(user_id="u1", flags=("x",))

    record = await tracker.enable("u1")
    assert record is not None
    assert record.disabled is False
    assert record.locked_until is None
    assert record.scrutiny_level == ELEVATED
    assert record.is_locked is False


async def test_to_dict_serializes_all_fields() -> None:
    tracker = InMemoryStrikeTracker()
    await tracker.record_violation(user_id="u1", flags=("a", "b"), detail="bad input")
    record = await tracker.get("u1")
    assert record is not None

    d = record.to_dict()
    assert d["user_id"] == "u1"
    assert d["strike_count"] == 1
    assert d["scrutiny_level"] == ELEVATED
    assert d["disabled"] is False
    assert d["is_locked"] is False
    assert d["violation_count"] == 1
    assert d["last_violation_at"] is not None
    assert d["locked_until"] is None


async def test_violations_accumulate_across_multiple_records() -> None:
    tracker = InMemoryStrikeTracker()
    await tracker.record_violation(user_id="u1", flags=("a",), detail="first")
    await tracker.record_violation(user_id="u1", flags=("b",), detail="second")

    record = await tracker.get("u1")
    assert record is not None
    assert len(record.violations) == 2
    assert [v.detail for v in record.violations] == ["first", "second"]

"""Gate works against either tracker (#134).

The defect was not in `PgStrikeTracker` alone — it was that `Gate` did attribute
access on whatever it was handed, and nothing checked the two agreed. So the
test that matters is not "the tracker returns the right type" but "the caller
that broke works with both".

`Gate.process_input` reads six fields off the record when it blocks. All six are
read here, through `Gate`, against each implementation.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.security._types import AuthContext
from maistro.security.gate import Gate
from maistro.security.strikes import InMemoryStrikeTracker
from maistro.security.warden.detector import Warden

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


def _auth(user_id: str = "u1") -> AuthContext:
    return AuthContext(user_id=user_id, username=user_id)


async def test_a_clean_user_passes_the_strike_check(tracker: Any) -> None:
    gate = Gate(warden=Warden(), strike_tracker=tracker)

    result = await gate.process_input("hello there", auth=_auth())

    assert result.blocked is False


async def test_a_locked_user_is_blocked_with_the_lockout_details(tracker: Any) -> None:
    """The exact path that used to raise AttributeError: `record.is_locked`,
    `record.locked_until`, `record.disabled`, `record.strike_count` and
    `record.scrutiny_level`, all read off whatever the tracker returned."""
    await tracker.record_violation(user_id="u1", flags=FLAGS)
    await tracker.record_violation(user_id="u1", flags=FLAGS)
    gate = Gate(warden=Warden(), strike_tracker=tracker)

    result = await gate.process_input("hello there", auth=_auth())

    assert result.blocked is True
    assert "locked" in result.block_reason.lower()
    assert result.strike_number == 2
    assert result.locked_until, "the user must be told when the lockout lifts"


async def test_a_disabled_user_is_told_an_administrator_must_act(tracker: Any) -> None:
    for _ in range(3):
        await tracker.record_violation(user_id="u1", flags=FLAGS)
    gate = Gate(warden=Warden(), strike_tracker=tracker)

    result = await gate.process_input("hello there", auth=_auth())

    assert result.blocked is True
    assert result.account_disabled is True
    assert "administrator" in result.block_reason.lower()


async def test_an_unlocked_user_passes_again(tracker: Any) -> None:
    await tracker.record_violation(user_id="u1", flags=FLAGS)
    await tracker.record_violation(user_id="u1", flags=FLAGS)
    await tracker.unlock("u1")
    gate = Gate(warden=Warden(), strike_tracker=tracker)

    result = await gate.process_input("hello there", auth=_auth())

    assert result.blocked is False


async def test_one_users_lockout_does_not_block_another(tracker: Any) -> None:
    await tracker.record_violation(user_id="u1", flags=FLAGS)
    await tracker.record_violation(user_id="u1", flags=FLAGS)
    gate = Gate(warden=Warden(), strike_tracker=tracker)

    result = await gate.process_input("hello there", auth=_auth("u2"))

    assert result.blocked is False


async def test_an_anonymous_caller_skips_the_strike_path(tracker: Any) -> None:
    """`Gate` derives user_id from auth and skips every strike path when it is
    empty — pinned so the durable tracker does not change that."""
    gate = Gate(warden=Warden(), strike_tracker=tracker)

    result = await gate.process_input("hello there", auth=None)

    assert result.blocked is False

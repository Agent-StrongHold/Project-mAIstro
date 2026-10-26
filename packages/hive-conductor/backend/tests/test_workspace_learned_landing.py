"""Learned-landing suggestion policy bands (#1050).

Exercises production ``record_immediate_landing_hop`` /
``decide_landing_suggestion`` in ``services.workspace_preferences`` (lockstep
with frontend ``landing.ts``). Changing streak, suppress, or profile cooldown
policy must fail these cases — not a second test-local authority. Learned
defaults are never applied silently; accept is explicit.
"""

from __future__ import annotations

import pytest
from services.workspace_preferences import (
    ALLOWED_LANDING_PATHS,
    DEFAULT_LANDING_PATH,
    LEARNED_STREAK_MIN,
    SUGGESTION_COOLDOWN_MS,
    decide_landing_suggestion,
    merge_suggestion_cooldown,
    record_immediate_landing_hop,
    suggestion_on_cooldown,
)


def test_streak_builds_on_same_target_and_resets_on_switch() -> None:
    p = record_immediate_landing_hop(None, "/goals", 1)
    assert p == {"path": "/goals", "streak": 1, "last_at_ms": 1}
    p = record_immediate_landing_hop(p, "/goals", 2)
    assert p is not None and p["streak"] == 2
    p = record_immediate_landing_hop(p, "/chat", 3)
    assert p == {"path": "/chat", "streak": 1, "last_at_ms": 3}


def test_proposal_requires_streak_and_respects_suppress_and_explicit() -> None:
    pattern = {"path": "/goals", "streak": LEARNED_STREAK_MIN, "last_at_ms": 1}
    show, detail = decide_landing_suggestion(
        pattern=pattern, explicit_default="/home", suppressed_paths=set()
    )
    assert show is True and detail == "/goals"

    show, reason = decide_landing_suggestion(
        pattern={"path": "/goals", "streak": LEARNED_STREAK_MIN - 1, "last_at_ms": 1},
        explicit_default="/home",
        suppressed_paths=set(),
    )
    assert show is False and reason == "insufficient"

    show, reason = decide_landing_suggestion(
        pattern=pattern, explicit_default="/home", suppressed_paths={"/goals"}
    )
    assert show is False and reason == "suppressed"

    show, reason = decide_landing_suggestion(
        pattern=pattern, explicit_default="/chat", suppressed_paths=set()
    )
    assert show is False and reason == "explicit"


def test_reject_cooldown_suppresses_nag_until_expiry() -> None:
    """Dismiss stores a profile cooldown — ignore does not nag every return."""
    now = 1_700_000_000_000
    cooldown = merge_suggestion_cooldown(None, "/goals", now_ms=now)
    assert cooldown["/goals"] == now + SUGGESTION_COOLDOWN_MS
    assert suggestion_on_cooldown(cooldown, "/goals", now_ms=now + 1) is True
    assert (
        suggestion_on_cooldown(cooldown, "/goals", now_ms=now + SUGGESTION_COOLDOWN_MS + 1) is False
    )

    pattern = {"path": "/goals", "streak": LEARNED_STREAK_MIN, "last_at_ms": now}
    show, reason = decide_landing_suggestion(
        pattern=pattern,
        explicit_default="/home",
        suppressed_paths=set(),
        cooldown_until_by_path=cooldown,
        now_ms=now + 60_000,
    )
    assert show is False and reason == "cooldown"

    show, detail = decide_landing_suggestion(
        pattern=pattern,
        explicit_default="/home",
        suppressed_paths=set(),
        cooldown_until_by_path=cooldown,
        now_ms=now + SUGGESTION_COOLDOWN_MS + 1,
    )
    assert show is True and detail == "/goals"


@pytest.mark.parametrize("path", sorted(ALLOWED_LANDING_PATHS - {DEFAULT_LANDING_PATH}))
def test_every_landing_option_is_eligible(path: str) -> None:
    pattern = {"path": path, "streak": LEARNED_STREAK_MIN, "last_at_ms": 1}
    show, detail = decide_landing_suggestion(
        pattern=pattern, explicit_default="/home", suppressed_paths=set()
    )
    assert show is True and detail == path

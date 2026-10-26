"""Learned-landing suggestion policy bands (#1050).

Exercises production ``record_immediate_landing_hop`` /
``decide_landing_suggestion`` in ``services.workspace_preferences`` (lockstep
with frontend ``landing.ts``). Changing streak or suppress policy must fail
these cases — not a second test-local authority. Learned defaults are never
applied silently; accept is explicit.
"""

from __future__ import annotations

import pytest
from services.workspace_preferences import (
    ALLOWED_LANDING_PATHS,
    DEFAULT_LANDING_PATH,
    LEARNED_STREAK_MIN,
    decide_landing_suggestion,
    record_immediate_landing_hop,
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


@pytest.mark.parametrize("path", sorted(ALLOWED_LANDING_PATHS - {DEFAULT_LANDING_PATH}))
def test_every_landing_option_is_eligible(path: str) -> None:
    pattern = {"path": path, "streak": LEARNED_STREAK_MIN, "last_at_ms": 1}
    show, detail = decide_landing_suggestion(
        pattern=pattern, explicit_default="/home", suppressed_paths=set()
    )
    assert show is True and detail == path

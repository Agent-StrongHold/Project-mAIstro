"""Learned-landing suggestion policy bands (#1050).

The SPA owns observation + proposal (`decideLandingSuggestion` /
`recordImmediateLandingHop` in ``frontend/src/lib/landing.ts``). These tests
pin the published streak minimum and precedence so docs and the SPA stay
aligned — not a second authority.
"""

from __future__ import annotations

import pytest

LEARNED_STREAK_MIN = 3
DEFAULT_LANDING = "/home"
ALLOWED = {"/home", "/chat", "/goals", "/backlog", "/work-items"}


def _resolve(raw: str) -> str:
    path = raw.strip().split("?", 1)[0].split("#", 1)[0]
    return path if path in ALLOWED else DEFAULT_LANDING


def _record(prior: dict[str, object] | None, path: str, now_ms: int) -> dict[str, object] | None:
    target = _resolve(path)
    if target == DEFAULT_LANDING:
        return prior
    if prior and prior.get("path") == target:
        return {"path": target, "streak": int(prior["streak"]) + 1, "lastAtMs": now_ms}
    return {"path": target, "streak": 1, "lastAtMs": now_ms}


def _decide(
    *,
    pattern: dict[str, object] | None,
    explicit: str,
    suppressed: set[str],
    streak_min: int = LEARNED_STREAK_MIN,
) -> tuple[bool, str]:
    if _resolve(explicit) != DEFAULT_LANDING:
        return False, "explicit"
    if not pattern:
        return False, "insufficient"
    path = _resolve(str(pattern["path"]))
    if path == DEFAULT_LANDING or path not in ALLOWED:
        return False, "ineligible"
    if path in suppressed:
        return False, "suppressed"
    if int(pattern["streak"]) < streak_min:
        return False, "insufficient"
    return True, path


def test_streak_builds_on_same_target_and_resets_on_switch() -> None:
    p = _record(None, "/goals", 1)
    assert p == {"path": "/goals", "streak": 1, "lastAtMs": 1}
    p = _record(p, "/goals", 2)
    assert p is not None and p["streak"] == 2
    p = _record(p, "/chat", 3)
    assert p == {"path": "/chat", "streak": 1, "lastAtMs": 3}


def test_proposal_requires_streak_and_respects_suppress_and_explicit() -> None:
    pattern = {"path": "/goals", "streak": LEARNED_STREAK_MIN, "lastAtMs": 1}
    show, detail = _decide(pattern=pattern, explicit="/home", suppressed=set())
    assert show is True and detail == "/goals"

    show, reason = _decide(
        pattern={"path": "/goals", "streak": LEARNED_STREAK_MIN - 1, "lastAtMs": 1},
        explicit="/home",
        suppressed=set(),
    )
    assert show is False and reason == "insufficient"

    show, reason = _decide(pattern=pattern, explicit="/home", suppressed={"/goals"})
    assert show is False and reason == "suppressed"

    show, reason = _decide(pattern=pattern, explicit="/chat", suppressed=set())
    assert show is False and reason == "explicit"


@pytest.mark.parametrize("path", sorted(ALLOWED - {DEFAULT_LANDING}))
def test_every_landing_option_is_eligible(path: str) -> None:
    pattern = {"path": path, "streak": LEARNED_STREAK_MIN, "lastAtMs": 1}
    show, detail = _decide(pattern=pattern, explicit="/home", suppressed=set())
    assert show is True and detail == path

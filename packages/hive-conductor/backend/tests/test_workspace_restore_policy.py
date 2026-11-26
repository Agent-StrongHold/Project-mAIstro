"""Recent-return restore policy bands (#1050 / #1822).

Exercises production ``decide_landing`` / ``restore_window_ms`` in
``services.workspace_preferences`` (lockstep with frontend ``landing.ts``).
Changing or removing the stale-window / proportional-window logic must fail
these cases — not a second test-local authority.
"""

from __future__ import annotations

import pytest
from services.workspace_preferences import decide_landing, restore_window_ms


@pytest.mark.parametrize(
    ("band", "away_ms", "session_len", "expect_restore"),
    [
        ("off", 1_000, 60_000, False),
        ("brief", 10 * 60 * 1000, 60_000, True),
        ("brief", 20 * 60 * 1000, 60_000, False),
        ("balanced", 3 * 60 * 60 * 1000, 60_000, True),
        ("balanced", 5 * 60 * 60 * 1000, 60_000, False),
        # Long prior session: proportional half extends beyond the 4h absolute.
        ("balanced", 5 * 60 * 60 * 1000, 12 * 60 * 60 * 1000, True),
        ("generous", 20 * 60 * 60 * 1000, 60_000, True),
        ("generous", 30 * 60 * 60 * 1000, 60_000, False),
        ("generous", 30 * 60 * 60 * 1000, 40 * 60 * 60 * 1000, True),
    ],
)
def test_restore_window_bands(
    band: str, away_ms: int, session_len: int, expect_restore: bool
) -> None:
    left_at = 1_700_000_000_000
    session_started = left_at - session_len
    window = restore_window_ms(band, left_at_ms=left_at, session_started_at_ms=session_started)
    assert (away_ms <= window) is expect_restore

    decision = decide_landing(
        aggressiveness=band,
        default_landing="/home",
        recent={
            "path": "/chat",
            "left_at_ms": left_at,
            "session_started_at_ms": session_started,
        },
        now_ms=left_at + away_ms,
    )
    if expect_restore:
        assert decision == {"path": "/chat", "reason": "restore"}
    elif band == "off":
        assert decision == {"path": "/home", "reason": "off"}
    else:
        assert decision == {"path": "/home", "reason": "stale"}

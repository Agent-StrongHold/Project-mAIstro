"""Recent-return restore policy bands (#1050 / #1822).

The SPA owns the landing decision (`decideLanding` in
``frontend/src/lib/landing.ts``). These tests pin the same absolute windows
and proportional extensions so a drift between docs and the published bands
fails closed in CI — not a second authority.
"""

from __future__ import annotations

import pytest

# Mirror of frontend RESTORE_ABSOLUTE_MS — keep in lockstep with landing.ts.
RESTORE_ABSOLUTE_MS = {
    "off": 0,
    "brief": 15 * 60 * 1000,
    "balanced": 4 * 60 * 60 * 1000,
    "generous": 24 * 60 * 60 * 1000,
}


def _window_ms(aggressiveness: str, *, left_at: int, session_started: int) -> int:
    absolute = RESTORE_ABSOLUTE_MS[aggressiveness]
    if aggressiveness in {"balanced", "generous"} and 0 < session_started <= left_at:
        session_len = left_at - session_started
        proportion = 1.0 if aggressiveness == "generous" else 0.5
        return max(absolute, int(session_len * proportion))
    return absolute


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
    window = _window_ms(band, left_at=left_at, session_started=session_started)
    assert (away_ms <= window) is expect_restore

"""Defaults for the autonomous UI climber stay on loopback."""

from __future__ import annotations


def test_default_climb_url_is_loopback() -> None:
    from services import ui_auto_climb

    assert ui_auto_climb.DEFAULT_CLIMB_URL == "http://localhost:8101"
    # Binding the default at definition time is what coverage measures.
    assert ui_auto_climb.auto_climb.__defaults__[0] == ui_auto_climb.DEFAULT_CLIMB_URL

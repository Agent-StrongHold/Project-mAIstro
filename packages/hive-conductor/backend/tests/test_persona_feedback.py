"""services/persona_feedback.py — Persona/Workspace system, Phase I."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from models.persona_feedback import PersonaFeedback
from services.persona_feedback import summarize


def _feedback(**overrides: object) -> PersonaFeedback:
    defaults: dict[str, object] = {
        "id": "fb-1",
        "persona_template_id": "pm_fleet",
        "workspace_id": "ws-1",
        "user_id": "u1",
        "thumb": "up",
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return PersonaFeedback(**defaults)


def test_counts_thumbs_up_and_down() -> None:
    entries = [
        _feedback(id="1", thumb="up"),
        _feedback(id="2", thumb="up"),
        _feedback(id="3", thumb="down"),
    ]
    summary = summarize("pm_fleet", entries)
    assert summary.thumbs_up == 2
    assert summary.thumbs_down == 1


def test_ignores_feedback_for_other_personas() -> None:
    entries = [
        _feedback(id="1", persona_template_id="pm_fleet", thumb="up"),
        _feedback(id="2", persona_template_id="other_persona", thumb="down"),
    ]
    summary = summarize("pm_fleet", entries)
    assert summary.thumbs_up == 1
    assert summary.thumbs_down == 0
    assert [e.id for e in summary.recent] == ["1"]


def test_aggregates_across_different_workspaces_of_the_same_persona() -> None:
    """Phase I's acceptance bar: two workspaces of one persona both land in
    that persona's one aggregate."""
    entries = [
        _feedback(id="1", workspace_id="ws-a", thumb="up"),
        _feedback(id="2", workspace_id="ws-b", thumb="up"),
    ]
    summary = summarize("pm_fleet", entries)
    assert summary.thumbs_up == 2


def test_recent_is_most_recent_first_and_capped() -> None:
    now = datetime.now(UTC)
    entries = [_feedback(id=str(i), created_at=now + timedelta(minutes=i)) for i in range(3)]
    summary = summarize("pm_fleet", entries, recent_limit=2)
    assert [e.id for e in summary.recent] == ["2", "1"]


def test_empty_entries_yields_zero_counts() -> None:
    summary = summarize("pm_fleet", [])
    assert summary.thumbs_up == 0
    assert summary.thumbs_down == 0
    assert summary.recent == []

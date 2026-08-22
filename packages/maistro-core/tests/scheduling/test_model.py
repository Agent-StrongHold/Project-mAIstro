"""Schedule definition: scope, bounds, and unfireable expressions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro.scheduling.model import DEFAULT_CATCHUP_WINDOW_SECONDS, OverlapPolicy, Schedule


def _schedule(**overrides: object) -> Schedule:
    defaults: dict[str, object] = {
        "workspace_id": "w1",
        "project_id": "p1",
        "cron": "0 9 * * *",
        "graph_template_id": "daily-status",
    }
    return Schedule(**{**defaults, **overrides})  # type: ignore[arg-type]


def test_defaults_are_the_conservative_ones() -> None:
    schedule = _schedule()
    assert schedule.overlap_policy is OverlapPolicy.SKIP
    assert schedule.catchup_window_seconds == DEFAULT_CATCHUP_WINDOW_SECONDS
    assert schedule.max_runs is None and schedule.enabled is True


def test_schedule_points_at_a_definition_not_a_task() -> None:
    """The pointer is into the canonical definition layer; a Schedule owns no
    execution concept of its own."""
    fields = set(Schedule.model_fields)
    assert "graph_template_id" in fields
    assert "last_run_id" in fields
    assert not fields & {"task_template", "last_task_id", "prompt", "agent"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"workspace_id": "  "},
        {"project_id": ""},
        {"graph_template_id": ""},
        {"catchup_window_seconds": -1.0},
        {"max_runs": 0},
        {"runs_so_far": -1},
        {"cron": "not a cron"},
        {"cron": "0 9 * * 9"},
        {"timezone": "Mars/Olympus"},
    ],
)
def test_invalid_definitions_are_rejected_at_creation(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _schedule(**overrides)


def test_exhaustion_and_remaining_budget() -> None:
    assert _schedule().runs_remaining is None
    assert _schedule(max_runs=3, runs_so_far=1).runs_remaining == 2
    assert _schedule(max_runs=3, runs_so_far=3).exhausted is True
    assert _schedule(max_runs=3, runs_so_far=1).exhausted is False


def test_next_fire_after_honours_the_schedule_timezone() -> None:
    schedule = _schedule(cron="0 9 * * *", timezone="America/New_York")
    fire = schedule.next_fire_after(datetime(2026, 8, 21, 0, 0, tzinfo=UTC))
    assert fire.hour == 9
    assert fire.utcoffset() is not None and fire.utcoffset().total_seconds() == -4 * 3600

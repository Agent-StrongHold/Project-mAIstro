"""Tests for `maistro.builders.logger` — BuildersLogger action/XP/learning-event tracking."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from maistro.builders.logger import BuilderAction, BuildersLogger, LearningEvent


def test_log_builder_action_records_entry_with_expected_fields() -> None:
    log = BuildersLogger()
    log.log_builder_action("frank", "decompose", "split task into subtasks", xp_earned=10)
    actions = log.get_actions()
    assert len(actions) == 1
    action = actions[0]
    assert isinstance(action, BuilderAction)
    assert action.builder_name == "frank"
    assert action.action_type == "decompose"
    assert action.description == "split task into subtasks"
    assert action.xp_earned == 10
    assert action.metadata is None


def test_log_builder_action_passes_through_metadata() -> None:
    log = BuildersLogger()
    log.log_builder_action("mason", "review", "reviewed PR", metadata={"pr": 42})
    assert log.get_actions()[0].metadata == {"pr": 42}


def test_log_builder_action_default_xp_is_zero() -> None:
    log = BuildersLogger()
    log.log_builder_action("frank", "noop", "did nothing")
    assert log.get_actions()[0].xp_earned == 0
    assert log.get_xp_totals() == {"frank": 0}


def test_log_builder_action_accumulates_xp_per_builder() -> None:
    log = BuildersLogger()
    log.log_builder_action("frank", "a", "x", xp_earned=10)
    log.log_builder_action("frank", "b", "y", xp_earned=5)
    log.log_builder_action("mason", "c", "z", xp_earned=20)
    assert log.get_xp_totals() == {"frank": 15, "mason": 20}


def test_log_learning_promotion_records_entry_with_expected_fields() -> None:
    log = BuildersLogger()
    log.log_learning_promotion(
        "learn-1", "coder", "frank", "high confidence pattern", confidence=0.92
    )
    events = log.get_learning_events()
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, LearningEvent)
    assert event.learning_id == "learn-1"
    assert event.source_agent == "coder"
    assert event.promoted_by == "frank"
    assert event.reason == "high confidence pattern"
    assert event.confidence == 0.92


def test_get_actions_filters_by_builder_name() -> None:
    log = BuildersLogger()
    log.log_builder_action("frank", "a", "x")
    log.log_builder_action("mason", "b", "y")
    result = log.get_actions(builder_name="mason")
    assert len(result) == 1
    assert result[0].builder_name == "mason"


def test_get_actions_filters_by_since() -> None:
    log = BuildersLogger()
    log.log_builder_action("frank", "old", "before cutoff")
    cutoff = datetime.now(UTC)
    time.sleep(0.01)
    log.log_builder_action("frank", "new", "after cutoff")
    result = log.get_actions(since=cutoff)
    assert len(result) == 1
    assert result[0].action_type == "new"


def test_get_actions_respects_limit_returning_most_recent() -> None:
    log = BuildersLogger()
    for i in range(5):
        log.log_builder_action("frank", f"action{i}", "x")
    result = log.get_actions(limit=2)
    assert [a.action_type for a in result] == ["action3", "action4"]


def test_get_actions_limit_zero_returns_all() -> None:
    log = BuildersLogger()
    log.log_builder_action("frank", "a", "x")
    log.log_builder_action("frank", "b", "y")
    result = log.get_actions(limit=0)
    assert len(result) == 2


def test_get_actions_empty_log_returns_empty_list() -> None:
    log = BuildersLogger()
    assert log.get_actions() == []


def test_get_learning_events_filters_by_since() -> None:
    log = BuildersLogger()
    log.log_learning_promotion("old-1", "coder", "frank", "r", 0.5)
    cutoff = datetime.now(UTC)
    time.sleep(0.01)
    log.log_learning_promotion("new-1", "coder", "frank", "r", 0.5)
    result = log.get_learning_events(since=cutoff)
    assert len(result) == 1
    assert result[0].learning_id == "new-1"


def test_get_learning_events_respects_limit_returning_most_recent() -> None:
    log = BuildersLogger()
    for i in range(3):
        log.log_learning_promotion(f"learn-{i}", "coder", "frank", "r", 0.5)
    result = log.get_learning_events(limit=1)
    assert len(result) == 1
    assert result[0].learning_id == "learn-2"


def test_get_learning_events_limit_zero_returns_all() -> None:
    log = BuildersLogger()
    log.log_learning_promotion("learn-1", "coder", "frank", "r", 0.5)
    log.log_learning_promotion("learn-2", "coder", "frank", "r", 0.5)
    assert len(log.get_learning_events(limit=0)) == 2


def test_get_xp_totals_returns_copy_not_live_reference() -> None:
    log = BuildersLogger()
    log.log_builder_action("frank", "a", "x", xp_earned=10)
    totals = log.get_xp_totals()
    totals["frank"] = 999
    assert log.get_xp_totals() == {"frank": 10}


def test_get_stats_aggregates_counts_and_groups_actions_by_builder() -> None:
    log = BuildersLogger()
    log.log_builder_action("frank", "a", "x", xp_earned=10)
    log.log_builder_action("frank", "b", "y", xp_earned=5)
    log.log_builder_action("mason", "c", "z", xp_earned=20)
    log.log_learning_promotion("learn-1", "coder", "frank", "r", 0.5)

    stats = log.get_stats()
    assert stats["total_actions"] == 3
    assert stats["total_learning_events"] == 1
    assert stats["xp_totals"] == {"frank": 15, "mason": 20}
    assert [a.action_type for a in stats["actions_by_builder"]["frank"]] == ["a", "b"]
    assert [a.action_type for a in stats["actions_by_builder"]["mason"]] == ["c"]


def test_get_stats_empty_log() -> None:
    log = BuildersLogger()
    stats = log.get_stats()
    assert stats["total_actions"] == 0
    assert stats["total_learning_events"] == 0
    assert stats["actions_by_builder"] == {}
    assert stats["xp_totals"] == {}


def test_clear_resets_actions_learning_events_and_xp_totals() -> None:
    log = BuildersLogger()
    log.log_builder_action("frank", "a", "x", xp_earned=10)
    log.log_learning_promotion("learn-1", "coder", "frank", "r", 0.5)
    log.clear()
    assert log.get_actions() == []
    assert log.get_learning_events() == []
    assert log.get_xp_totals() == {}
    assert log.get_stats() == {
        "total_actions": 0,
        "total_learning_events": 0,
        "actions_by_builder": {},
        "xp_totals": {},
    }

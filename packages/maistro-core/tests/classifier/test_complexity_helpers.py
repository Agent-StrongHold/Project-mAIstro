"""Tests for coerce_priority, automation_min_tier, and planner_model_tier."""

from __future__ import annotations

from maistro.classifier.complexity import (
    automation_min_tier,
    coerce_priority,
    estimate_complexity,
    planner_model_tier,
)


class TestEstimateComplexityTaskTypeFallback:
    def test_code_task_type_with_no_signals_is_moderate(self) -> None:
        text = "please write me a simple function that adds two numbers together right now for me"
        assert len(text.split()) >= 15
        assert estimate_complexity(text, "code") == "moderate"

    def test_reasoning_task_type_with_no_signals_is_moderate(self) -> None:
        text = "please explain why the sky appears blue during a clear sunny day right now for me"
        assert estimate_complexity(text, "reasoning") == "moderate"

    def test_chat_task_type_with_no_signals_is_simple(self) -> None:
        text = "please explain why the sky appears blue during a clear sunny day right now for me"
        assert estimate_complexity(text, "chat") == "simple"


class TestCoercePriority:
    def test_valid_priority_returned(self) -> None:
        assert coerce_priority("P0") == "P0"
        assert coerce_priority("P5") == "P5"

    def test_invalid_priority_returns_none(self) -> None:
        assert coerce_priority("P9") is None

    def test_none_returns_none(self) -> None:
        assert coerce_priority(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert coerce_priority("") is None


class TestAutomationMinTier:
    def test_short_command_uses_base_min_tier(self) -> None:
        assert automation_min_tier("turn off the lights", "small") == "small"

    def test_short_command_all_filler_words(self) -> None:
        assert automation_min_tier("could you please", "small") == "small"

    def test_long_command_bumps_small_to_medium(self) -> None:
        result = automation_min_tier("turn off the living room lamp and kitchen light", "small")
        assert result == "medium"

    def test_long_command_keeps_tier_at_or_above_medium(self) -> None:
        result = automation_min_tier("turn off the living room lamp and kitchen light", "large")
        assert result == "large"

    def test_long_command_keeps_frontier(self) -> None:
        result = automation_min_tier("turn off the living room lamp and kitchen light", "frontier")
        assert result == "frontier"

    def test_long_command_medium_base_stays_medium(self) -> None:
        result = automation_min_tier("turn off the living room lamp and kitchen light", "medium")
        assert result == "medium"

    def test_unknown_base_tier_treated_as_zero_and_bumped(self) -> None:
        result = automation_min_tier(
            "turn off the living room lamp and kitchen light", "unknown-tier"
        )
        assert result == "medium"


class TestPlannerModelTier:
    def test_override_takes_priority(self) -> None:
        assert planner_model_tier("simple", override="frontier") == "frontier"

    def test_simple_maps_to_medium(self) -> None:
        assert planner_model_tier("simple") == "medium"

    def test_moderate_maps_to_large(self) -> None:
        assert planner_model_tier("moderate") == "large"

    def test_complex_maps_to_frontier(self) -> None:
        assert planner_model_tier("complex") == "frontier"

    def test_unknown_complexity_defaults_to_large(self) -> None:
        assert planner_model_tier("unknown") == "large"

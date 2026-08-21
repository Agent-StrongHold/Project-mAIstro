"""Tests for VariantSelector (ADR-007)."""

from __future__ import annotations

import random

from maistro.agents.recipes import AgentRecipe
from maistro.agents.spawner.variant_selector import VariantSelector
from maistro.agents.spec.agent_spec import AgentRole


def _recipe(variants: list[str], min_samples: int = 20) -> AgentRecipe:
    return AgentRecipe(
        name="test.prompt",
        role=AgentRole.CODER,
        prompt_name="test.prompt",
        prompt_variants=variants,
        min_samples_before_selection=min_samples,
        exploration_rate=0.0,  # disable exploration for deterministic tests
    )


class TestVariantSelector:
    def test_single_variant_always_returned(self) -> None:
        sel = VariantSelector()
        recipe = _recipe(["only-one"])
        for _ in range(10):
            assert sel.select(recipe) == "only-one"

    def test_empty_variants_returns_production(self) -> None:
        sel = VariantSelector()
        recipe = _recipe([])
        assert sel.select(recipe) == "production"

    def test_round_robin_covers_all_variants(self) -> None:
        sel = VariantSelector()
        recipe = _recipe(["a", "b", "c"], min_samples=30)
        seen = {sel.select(recipe) for _ in range(30)}
        assert seen == {"a", "b", "c"}

    def test_record_outcome_success_threshold(self) -> None:
        sel = VariantSelector(success_threshold=7.0)
        sel.record_outcome("test.prompt", "v1", 7.0)
        sel.record_outcome("test.prompt", "v1", 6.9)
        stats = sel.get_stats("test.prompt")
        assert stats["v1"].successes == 1
        assert stats["v1"].failures == 1

    def test_record_outcome_increments_runs(self) -> None:
        sel = VariantSelector()
        for _ in range(5):
            sel.record_outcome("my.prompt", "v1", 8.0)
        stats = sel.get_stats("my.prompt")
        assert stats["v1"].runs == 5

    def test_mean_score_incremental_update(self) -> None:
        sel = VariantSelector()
        sel.record_outcome("p", "v1", 8.0)
        sel.record_outcome("p", "v1", 6.0)
        stats = sel.get_stats("p")
        assert abs(stats["v1"].mean_score - 7.0) < 1e-9

    def test_thompson_sampling_favours_winner(self) -> None:
        random.seed(42)
        sel = VariantSelector(success_threshold=7.0)
        recipe = _recipe(["winner", "loser"], min_samples=0)

        # Give winner 90% success rate
        for _ in range(90):
            sel.record_outcome("test.prompt", "winner", 9.0)
        for _ in range(10):
            sel.record_outcome("test.prompt", "loser", 9.0)
        for _ in range(90):
            sel.record_outcome("test.prompt", "loser", 5.0)

        picks = [sel.select(recipe) for _ in range(50)]
        winner_count = picks.count("winner")
        assert winner_count > 35, f"Expected winner to dominate, got {winner_count}/50"

    def test_no_langfuse_no_exception(self) -> None:
        sel = VariantSelector(langfuse_client=None)
        recipe = _recipe(["a", "b"])
        sel.select(recipe)  # must not raise

    def test_stats_initially_empty(self) -> None:
        sel = VariantSelector()
        stats = sel.get_stats("nonexistent.prompt")
        assert stats == {}

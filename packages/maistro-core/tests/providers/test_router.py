"""Tests for CostAwareRouter selection, budgets, fallback chains, embeddings."""

from __future__ import annotations

import pytest

from maistro.providers import (
    CostAwareRouter,
    InMemoryProviderRegistry,
    ModelMetadata,
    ModelNotFoundError,
    NoEligibleModelError,
    RouterBudget,
    RoutingTask,
)

TASK = RoutingTask(task_type="general")


@pytest.fixture
def router(registry: InMemoryProviderRegistry) -> CostAwareRouter:
    return CostAwareRouter(registry)


class TestBudgetSelection:
    async def test_unconstrained_picks_lowest_latency(self, router: CostAwareRouter) -> None:
        model = await router.select(TASK)
        assert model.name == "gpt-3.5-turbo"  # 400ms is the fastest

    async def test_reasoning_required(self, router: CostAwareRouter) -> None:
        model = await router.select(TASK, RouterBudget(reasoning=True))
        assert model.name == "claude-3-opus"
        assert model.reasoning_capable

    async def test_max_cost_filters_expensive_models(self, router: CostAwareRouter) -> None:
        model = await router.select(TASK, RouterBudget(max_cost_cents=0.01))
        assert model.cost_per_1k_input <= 0.01

    async def test_max_latency_filters_slow_models(self, router: CostAwareRouter) -> None:
        model = await router.select(TASK, RouterBudget(max_latency_ms=1000))
        assert model.latency_p50_ms <= 1000

    async def test_combined_budget(self, router: CostAwareRouter) -> None:
        budget = RouterBudget(max_cost_cents=0.05, max_latency_ms=1500)
        model = await router.select(TASK, budget)
        assert model.cost_per_1k_input <= 0.05
        assert model.latency_p50_ms <= 1500

    async def test_impossible_budget_raises(self, router: CostAwareRouter) -> None:
        with pytest.raises(NoEligibleModelError):
            await router.select(TASK, RouterBudget(max_latency_ms=100))

    async def test_reasoning_plus_tight_cost_raises(self, router: CostAwareRouter) -> None:
        with pytest.raises(NoEligibleModelError):
            await router.select(TASK, RouterBudget(reasoning=True, max_cost_cents=0.01))

    @pytest.mark.parametrize(
        ("max_cost", "max_latency", "reasoning"),
        [
            (None, None, False),
            (0.2, None, True),
            (0.05, 5000, False),
            (None, 2000, False),
            (1.0, 3000, True),
        ],
    )
    async def test_selection_always_respects_constraints(
        self,
        router: CostAwareRouter,
        max_cost: float | None,
        max_latency: int | None,
        reasoning: bool,
    ) -> None:
        budget = RouterBudget(
            max_cost_cents=max_cost, max_latency_ms=max_latency, reasoning=reasoning
        )
        model = await router.select(TASK, budget)
        if max_cost is not None:
            assert model.cost_per_1k_input <= max_cost
        if max_latency is not None:
            assert model.latency_p50_ms <= max_latency
        if reasoning:
            assert model.reasoning_capable


class TestFallback:
    async def test_primary_unavailable_falls_back_to_chain(
        self, registry: InMemoryProviderRegistry, router: CostAwareRouter
    ) -> None:
        registry.mark_unavailable("claude-3-opus")
        # Reasoning constraint dropped: opus's chain leads to gpt-4-turbo.
        model = await router.select(TASK, RouterBudget(max_latency_ms=900))
        # Only opus satisfies <=900ms besides gpt-3.5; gpt-3.5 (400ms) still wins.
        assert model.name == "gpt-3.5-turbo"

    async def test_unavailable_primary_uses_secondary_in_chain(
        self, registry: InMemoryProviderRegistry, router: CostAwareRouter
    ) -> None:
        registry.mark_unavailable("gpt-3.5-turbo")
        registry.mark_unavailable("claude-3-opus")
        model = await router.select(TASK, RouterBudget(max_latency_ms=1500))
        assert model.name == "gpt-4-turbo"

    async def test_all_unavailable_raises(
        self, registry: InMemoryProviderRegistry, router: CostAwareRouter
    ) -> None:
        for name in ("claude-3-opus", "gpt-4-turbo", "gpt-3.5-turbo", "local-llama"):
            registry.mark_unavailable(name)
        with pytest.raises(NoEligibleModelError):
            await router.select(TASK)

    async def test_fallback_chain_resolution(self, router: CostAwareRouter) -> None:
        chain = await router.fallback_chain("claude-3-opus")
        assert [m.name for m in chain] == ["claude-3-opus", "gpt-4-turbo", "gpt-3.5-turbo"]

    async def test_fallback_chain_unknown_root_raises(self, router: CostAwareRouter) -> None:
        with pytest.raises(ModelNotFoundError):
            await router.fallback_chain("nope")

    async def test_fallback_chain_ignores_dangling_names(self) -> None:
        registry = InMemoryProviderRegistry(
            models=[
                ModelMetadata(
                    name="a",
                    provider="p",
                    cost_per_1k_input=0.1,
                    cost_per_1k_output=0.1,
                    latency_p50_ms=100,
                    fallback_to=("ghost",),
                ),
            ],
        )
        chain = await CostAwareRouter(registry).fallback_chain("a")
        assert [m.name for m in chain] == ["a"]

    async def test_fallback_chain_handles_cycles(self) -> None:
        registry = InMemoryProviderRegistry(
            models=[
                ModelMetadata(
                    name="a",
                    provider="p",
                    cost_per_1k_input=0.1,
                    cost_per_1k_output=0.1,
                    latency_p50_ms=100,
                    fallback_to=("b",),
                ),
                ModelMetadata(
                    name="b",
                    provider="p",
                    cost_per_1k_input=0.1,
                    cost_per_1k_output=0.1,
                    latency_p50_ms=200,
                    fallback_to=("a",),
                ),
            ],
        )
        chain = await CostAwareRouter(registry).fallback_chain("a")
        assert [m.name for m in chain] == ["a", "b"]

    async def test_fallback_respects_budget(
        self, registry: InMemoryProviderRegistry, router: CostAwareRouter
    ) -> None:
        # Opus is the only reasoning model; marking it unavailable means its
        # (non-reasoning) fallbacks must NOT be returned for a reasoning budget.
        registry.mark_unavailable("claude-3-opus")
        with pytest.raises(NoEligibleModelError):
            await router.select(TASK, RouterBudget(reasoning=True))


class TestEmbeddingSelection:
    async def test_picks_cheapest_that_fits(self, router: CostAwareRouter) -> None:
        model = await router.select_embedding(input_size_tokens=256)
        assert model.name == "local-minilm"  # free beats ada

    async def test_large_input_excludes_small_context_models(self, router: CostAwareRouter) -> None:
        model = await router.select_embedding(input_size_tokens=4000)
        assert model.name == "text-embedding-ada-002"

    async def test_too_large_input_raises(self, router: CostAwareRouter) -> None:
        with pytest.raises(NoEligibleModelError):
            await router.select_embedding(input_size_tokens=100_000)

    async def test_unavailable_embedding_skipped(
        self, registry: InMemoryProviderRegistry, router: CostAwareRouter
    ) -> None:
        registry.mark_unavailable("local-minilm")
        model = await router.select_embedding(input_size_tokens=256)
        assert model.name == "text-embedding-ada-002"

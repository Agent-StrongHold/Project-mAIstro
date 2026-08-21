"""Cost-aware router: budget-constrained model selection with fallback chains."""

from __future__ import annotations

from typing import TYPE_CHECKING

from maistro.providers.errors import ModelNotFoundError, NoEligibleModelError
from maistro.providers.types import RouterBudget

if TYPE_CHECKING:
    from maistro.providers.protocols import LLMProviderRegistry
    from maistro.providers.types import EmbeddingModelMetadata, ModelMetadata, RoutingTask


class CostAwareRouter:
    """Implements the LLMRouter protocol.

    Selection: filter by budget (cost, latency, reasoning), prefer the
    lowest-latency candidate, and fall through each candidate's fallback
    chain when the preferred model is unavailable (ADR-038).
    """

    def __init__(self, registry: LLMProviderRegistry) -> None:
        self._registry = registry

    async def select(
        self,
        task: RoutingTask,
        budget: RouterBudget | None = None,
    ) -> ModelMetadata:
        budget = budget or RouterBudget()
        models = await self._registry.list_models()
        candidates = [m for m in models if self._satisfies(m, budget)]
        if not candidates:
            raise NoEligibleModelError(budget)

        candidates.sort(key=lambda m: m.latency_p50_ms)
        tried: set[str] = set()
        for candidate in candidates:
            for model in await self.fallback_chain(candidate.name):
                if model.name in tried:
                    continue
                tried.add(model.name)
                if self._satisfies(model, budget) and self._registry.is_available(model.name):
                    return model
        raise NoEligibleModelError(budget, detail=f"all eligible models unavailable: {budget}")

    async def select_embedding(self, input_size_tokens: int) -> EmbeddingModelMetadata:
        """Pick the cheapest available embedding model that fits the input size."""
        models = await self._registry.list_embedding_models()
        candidates = [
            m
            for m in models
            if m.max_input_tokens >= input_size_tokens and self._registry.is_available(m.name)
        ]
        if not candidates:
            raise NoEligibleModelError(
                detail=f"no available embedding model for input of {input_size_tokens} tokens",
            )
        return min(candidates, key=lambda m: m.cost_per_1k_tokens)

    async def fallback_chain(self, name: str) -> list[ModelMetadata]:
        """Resolve the ordered fallback chain starting at a model (inclusive).

        Breadth-first over ``fallback_to``; cycles and duplicates are skipped;
        dangling fallback names are ignored.
        """
        chain: list[ModelMetadata] = []
        seen: set[str] = set()
        queue: list[str] = [name]
        first = True
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            try:
                model = await self._registry.get_model(current)
            except ModelNotFoundError:
                if first:
                    raise
                continue
            finally:
                first = False
            chain.append(model)
            queue.extend(model.fallback_to)
        return chain

    @staticmethod
    def _satisfies(model: ModelMetadata, budget: RouterBudget) -> bool:
        if budget.max_cost_cents is not None and model.cost_per_1k_input > budget.max_cost_cents:
            return False
        if budget.max_latency_ms is not None and model.latency_p50_ms > budget.max_latency_ms:
            return False
        return not (budget.reasoning and not model.reasoning_capable)

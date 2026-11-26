"""Cost-aware router: budget-constrained model selection with fallback chains."""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING

from maistro.providers.errors import ModelNotFoundError, NoEligibleModelError
from maistro.providers.types import RouterBudget

if TYPE_CHECKING:
    from maistro.providers.protocols import LLMProviderRegistry
    from maistro.providers.types import EmbeddingModelMetadata, ModelMetadata, RoutingTask


def _in_scope(name: str, scope: Collection[str] | None) -> bool:
    """Scope is a constraint, never a widening: an empty scope elects nothing."""

    return scope is None or name in scope


class CostAwareRouter:
    """Implements the LLMRouter protocol.

    Selection: filter by budget (cost, latency, reasoning), prefer the
    lowest-latency candidate, and fall through each candidate's fallback
    chain when the preferred model is unavailable (ADR-038). ``scope``
    optionally constrains every stage — candidates and fallback chains —
    to the given model names.
    """

    def __init__(self, registry: LLMProviderRegistry) -> None:
        self._registry = registry

    async def select(
        self,
        task: RoutingTask,
        budget: RouterBudget | None = None,
        scope: Collection[str] | None = None,
    ) -> ModelMetadata:
        budget = budget or RouterBudget()
        models = await self._registry.list_models()
        candidates = [m for m in models if self._satisfies(m, budget) and _in_scope(m.name, scope)]
        if not candidates:
            raise NoEligibleModelError(budget)

        candidates.sort(key=lambda m: m.latency_p50_ms)
        selected = await self._first_available_in_chains(candidates, budget, scope)
        if selected is None:
            raise NoEligibleModelError(budget, detail=f"all eligible models unavailable: {budget}")
        return selected

    async def _first_available_in_chains(
        self,
        candidates: list[ModelMetadata],
        budget: RouterBudget,
        scope: Collection[str] | None,
    ) -> ModelMetadata | None:
        """Walk each candidate's fallback chain for the first selectable model.

        Every chain member is considered once across candidates; scope is a
        constraint at this stage too, so a fallback outside the declared
        adapter's models cannot be elected by a scoped selection.
        """

        tried: set[str] = set()
        for candidate in candidates:
            for model in await self.fallback_chain(candidate.name):
                if model.name in tried:
                    continue
                tried.add(model.name)
                if (
                    self._satisfies(model, budget)
                    and _in_scope(model.name, scope)
                    and self._registry.is_available(model.name)
                ):
                    return model
        return None

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

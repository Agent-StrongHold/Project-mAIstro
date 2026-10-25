"""Abstract interfaces for provider registry and LLM routing (DI)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from maistro.providers.types import (
        EmbeddingModelMetadata,
        ModelMetadata,
        RouterBudget,
        RoutingTask,
    )


@runtime_checkable
class LLMProviderRegistry(Protocol):
    """Single source of truth for available LLM providers and models."""

    async def list_models(
        self,
        filter_by: dict[str, str] | None = None,
    ) -> list[ModelMetadata]:
        """List available models, optionally filtered by provider/tier."""
        ...

    async def get_model(self, name: str) -> ModelMetadata:
        """Fetch a specific model's metadata. Raises ModelNotFoundError."""
        ...

    async def list_embedding_models(self) -> list[EmbeddingModelMetadata]:
        """List all registered embedding models."""
        ...

    async def get_embedding_model(self, name: str) -> EmbeddingModelMetadata:
        """Fetch a specific embedding model's metadata. Raises ModelNotFoundError."""
        ...

    def is_available(self, name: str) -> bool:
        """Whether a model is currently available (not circuit-broken)."""
        ...


@runtime_checkable
class LLMRouter(Protocol):
    """Selects the best model for a task under budget constraints."""

    async def select(
        self,
        task: RoutingTask,
        budget: RouterBudget | None = None,
    ) -> ModelMetadata:
        """Select the best available model satisfying the budget."""
        ...

    async def select_embedding(self, input_size_tokens: int) -> EmbeddingModelMetadata:
        """Select an embedding model that can handle the input size."""
        ...

    async def fallback_chain(self, name: str) -> list[ModelMetadata]:
        """Resolve the ordered fallback chain starting at a model (inclusive)."""
        ...

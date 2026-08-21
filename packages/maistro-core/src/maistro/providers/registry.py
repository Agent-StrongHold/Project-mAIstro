"""In-memory implementation of the LLM provider registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from maistro.providers.errors import ModelNotFoundError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from maistro.providers.types import EmbeddingModelMetadata, ModelMetadata

_FILTERABLE_FIELDS = frozenset({"provider", "tier", "name"})


class InMemoryProviderRegistry:
    """Implements the LLMProviderRegistry protocol with dict-backed storage.

    Registration order is preserved (list_models ordering is deterministic);
    re-registering a name replaces the prior entry (no duplicates).
    """

    def __init__(
        self,
        models: Iterable[ModelMetadata] = (),
        embedding_models: Iterable[EmbeddingModelMetadata] = (),
    ) -> None:
        self._models: dict[str, ModelMetadata] = {}
        self._embeddings: dict[str, EmbeddingModelMetadata] = {}
        self._unavailable: set[str] = set()
        for model in models:
            self.register_model(model)
        for embedding in embedding_models:
            self.register_embedding_model(embedding)

    def register_model(self, model: ModelMetadata) -> None:
        self._models[model.name] = model

    def register_embedding_model(self, model: EmbeddingModelMetadata) -> None:
        self._embeddings[model.name] = model

    def mark_unavailable(self, name: str) -> None:
        """Mark a model as unavailable (e.g. circuit-broken per ADR-038)."""
        if name not in self._models and name not in self._embeddings:
            raise ModelNotFoundError(name)
        self._unavailable.add(name)

    def mark_available(self, name: str) -> None:
        """Clear the unavailable flag on a model."""
        self._unavailable.discard(name)

    def is_available(self, name: str) -> bool:
        return name not in self._unavailable

    async def list_models(
        self,
        filter_by: dict[str, str] | None = None,
    ) -> list[ModelMetadata]:
        models = list(self._models.values())
        if not filter_by:
            return models
        unknown = set(filter_by) - _FILTERABLE_FIELDS
        if unknown:
            msg = f"unsupported filter fields: {sorted(unknown)}"
            raise ValueError(msg)
        return [
            m for m in models if all(getattr(m, key) == value for key, value in filter_by.items())
        ]

    async def get_model(self, name: str) -> ModelMetadata:
        try:
            return self._models[name]
        except KeyError:
            raise ModelNotFoundError(name) from None

    async def list_embedding_models(self) -> list[EmbeddingModelMetadata]:
        return list(self._embeddings.values())

    async def get_embedding_model(self, name: str) -> EmbeddingModelMetadata:
        try:
            return self._embeddings[name]
        except KeyError:
            raise ModelNotFoundError(name) from None

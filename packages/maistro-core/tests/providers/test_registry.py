"""Tests for InMemoryProviderRegistry."""

from __future__ import annotations

import pytest

from maistro.providers import InMemoryProviderRegistry, ModelNotFoundError

from .fixtures_models import ALL_MODELS, GPT4, OPUS


class TestListModels:
    async def test_returns_all_configured_models(self, registry: InMemoryProviderRegistry) -> None:
        models = await registry.list_models()
        assert [m.name for m in models] == [m.name for m in ALL_MODELS]

    async def test_ordering_is_consistent(self, registry: InMemoryProviderRegistry) -> None:
        first = await registry.list_models()
        second = await registry.list_models()
        assert first == second

    async def test_no_duplicates_on_reregistration(
        self, registry: InMemoryProviderRegistry
    ) -> None:
        registry.register_model(OPUS)
        models = await registry.list_models()
        names = [m.name for m in models]
        assert len(names) == len(set(names))

    async def test_filter_by_provider(self, registry: InMemoryProviderRegistry) -> None:
        models = await registry.list_models(filter_by={"provider": "openai"})
        assert {m.name for m in models} == {"gpt-4-turbo", "gpt-3.5-turbo"}

    async def test_filter_by_tier(self, registry: InMemoryProviderRegistry) -> None:
        models = await registry.list_models(filter_by={"tier": "fast"})
        assert {m.name for m in models} == {"gpt-3.5-turbo", "local-llama"}

    async def test_filter_by_multiple_fields(self, registry: InMemoryProviderRegistry) -> None:
        models = await registry.list_models(filter_by={"provider": "openai", "tier": "powerful"})
        assert [m.name for m in models] == ["gpt-4-turbo"]

    async def test_unknown_filter_field_rejected(self, registry: InMemoryProviderRegistry) -> None:
        with pytest.raises(ValueError, match="unsupported filter"):
            await registry.list_models(filter_by={"bogus": "x"})


class TestGetModel:
    async def test_returns_metadata(self, registry: InMemoryProviderRegistry) -> None:
        assert await registry.get_model("gpt-4-turbo") == GPT4

    async def test_unknown_name_raises(self, registry: InMemoryProviderRegistry) -> None:
        with pytest.raises(ModelNotFoundError):
            await registry.get_model("does-not-exist")


class TestEmbeddingModels:
    async def test_list(self, registry: InMemoryProviderRegistry) -> None:
        models = await registry.list_embedding_models()
        assert {m.name for m in models} == {"text-embedding-ada-002", "local-minilm"}

    async def test_get(self, registry: InMemoryProviderRegistry) -> None:
        model = await registry.get_embedding_model("text-embedding-ada-002")
        assert model.dimension == 1536

    async def test_unknown_embedding_raises(self, registry: InMemoryProviderRegistry) -> None:
        with pytest.raises(ModelNotFoundError):
            await registry.get_embedding_model("nope")


class TestAvailability:
    async def test_available_by_default(self, registry: InMemoryProviderRegistry) -> None:
        assert registry.is_available("claude-3-opus")

    async def test_mark_unavailable_and_back(self, registry: InMemoryProviderRegistry) -> None:
        registry.mark_unavailable("claude-3-opus")
        assert not registry.is_available("claude-3-opus")
        registry.mark_available("claude-3-opus")
        assert registry.is_available("claude-3-opus")

    async def test_mark_unavailable_unknown_raises(
        self, registry: InMemoryProviderRegistry
    ) -> None:
        with pytest.raises(ModelNotFoundError):
            registry.mark_unavailable("nope")

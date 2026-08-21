"""Shared fixtures for provider registry/router tests."""

from __future__ import annotations

import pytest

from maistro.providers import InMemoryProviderRegistry

from .fixtures_models import ALL_EMBEDDINGS, ALL_MODELS


@pytest.fixture
def registry() -> InMemoryProviderRegistry:
    return InMemoryProviderRegistry(models=ALL_MODELS, embedding_models=ALL_EMBEDDINGS)

"""LLM provider/model registry, routing, and embeddings (ADR-079, SPEC-070226-cb8d)."""

from maistro.providers.config import load_provider_config, load_provider_registry
from maistro.providers.errors import (
    ModelNotFoundError,
    NoEligibleModelError,
    ProviderConfigError,
    ProviderError,
)
from maistro.providers.protocols import LLMProviderRegistry, LLMRouter
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import (
    EmbeddingModelMetadata,
    ModelMetadata,
    RouterBudget,
    RoutingTask,
    compute_cost_cents,
    compute_embedding_cost_cents,
)

__all__ = [
    "CostAwareRouter",
    "EmbeddingModelMetadata",
    "InMemoryProviderRegistry",
    "LLMProviderRegistry",
    "LLMRouter",
    "ModelMetadata",
    "ModelNotFoundError",
    "NoEligibleModelError",
    "ProviderConfigError",
    "ProviderError",
    "RouterBudget",
    "RoutingTask",
    "compute_cost_cents",
    "compute_embedding_cost_cents",
    "load_provider_config",
    "load_provider_registry",
]

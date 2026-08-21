"""Shared dataclasses for the LLM provider registry and router (ADR-079)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ModelTier = Literal["fast", "balanced", "powerful"]


@dataclass(frozen=True)
class ModelMetadata:
    """Metadata for a chat/completion model in the provider registry.

    Costs are in cents per 1000 tokens.
    """

    name: str  # "claude-3-opus", "gpt-4-turbo"
    provider: str  # "anthropic", "openai", "local"
    cost_per_1k_input: float  # cents
    cost_per_1k_output: float  # cents
    latency_p50_ms: int
    tier: ModelTier = "balanced"
    reasoning_capable: bool = False
    max_tokens: int = 4096
    fallback_to: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class EmbeddingModelMetadata:
    """Metadata for an embedding (vector generation) model."""

    name: str  # "text-embedding-ada-002"
    provider: str
    dimension: int
    cost_per_1k_tokens: float  # cents
    max_input_tokens: int = 8192


@dataclass(frozen=True)
class RouterBudget:
    """Budget constraints for model selection.

    Any unset constraint is unbounded. ``reasoning=True`` restricts
    selection to reasoning-capable models.
    """

    max_cost_cents: float | None = None
    max_latency_ms: int | None = None
    reasoning: bool = False


@dataclass(frozen=True)
class RoutingTask:
    """Minimal task descriptor the router selects a model for."""

    task_type: str = "general"
    description: str = ""


def compute_cost_cents(
    model: ModelMetadata,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Pure cost computation: registry metadata + token counts -> cost in cents."""
    if input_tokens < 0 or output_tokens < 0:
        msg = "token counts must be non-negative"
        raise ValueError(msg)
    return (
        input_tokens / 1000.0 * model.cost_per_1k_input
        + output_tokens / 1000.0 * model.cost_per_1k_output
    )


def compute_embedding_cost_cents(
    model: EmbeddingModelMetadata,
    input_tokens: int,
) -> float:
    """Pure cost computation for an embedding call, in cents."""
    if input_tokens < 0:
        msg = "token counts must be non-negative"
        raise ValueError(msg)
    return input_tokens / 1000.0 * model.cost_per_1k_tokens

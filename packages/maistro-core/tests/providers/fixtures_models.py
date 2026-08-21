"""Shared model metadata constants for provider tests."""

from __future__ import annotations

from maistro.providers import EmbeddingModelMetadata, ModelMetadata

OPUS = ModelMetadata(
    name="claude-3-opus",
    provider="anthropic",
    tier="powerful",
    cost_per_1k_input=0.15,
    cost_per_1k_output=0.75,
    latency_p50_ms=800,
    reasoning_capable=True,
    fallback_to=("gpt-4-turbo",),
)
GPT4 = ModelMetadata(
    name="gpt-4-turbo",
    provider="openai",
    tier="powerful",
    cost_per_1k_input=0.03,
    cost_per_1k_output=0.06,
    latency_p50_ms=1200,
    fallback_to=("gpt-3.5-turbo",),
)
GPT35 = ModelMetadata(
    name="gpt-3.5-turbo",
    provider="openai",
    tier="fast",
    cost_per_1k_input=0.001,
    cost_per_1k_output=0.002,
    latency_p50_ms=400,
)
LOCAL = ModelMetadata(
    name="local-llama",
    provider="local",
    tier="fast",
    cost_per_1k_input=0.0,
    cost_per_1k_output=0.0,
    latency_p50_ms=2500,
)

ADA = EmbeddingModelMetadata(
    name="text-embedding-ada-002",
    provider="openai",
    dimension=1536,
    cost_per_1k_tokens=0.0001,
    max_input_tokens=8192,
)
LOCAL_EMBED = EmbeddingModelMetadata(
    name="local-minilm",
    provider="local",
    dimension=384,
    cost_per_1k_tokens=0.0,
    max_input_tokens=512,
)

ALL_MODELS = [OPUS, GPT4, GPT35, LOCAL]
ALL_EMBEDDINGS = [ADA, LOCAL_EMBED]

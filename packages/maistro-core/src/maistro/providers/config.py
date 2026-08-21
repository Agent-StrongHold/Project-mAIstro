"""YAML config loader for provider model definitions (SPEC-070226-cb8d)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from maistro.providers.errors import ProviderConfigError
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.types import EmbeddingModelMetadata, ModelMetadata, ModelTier

_VALID_TIERS: frozenset[str] = frozenset({"fast", "balanced", "powerful"})


def _require(entry: dict[str, Any], key: str, section: str) -> Any:
    if key not in entry:
        msg = f"{section} entry missing required key {key!r}: {entry}"
        raise ProviderConfigError(msg)
    return entry[key]


def _parse_model(entry: Any) -> ModelMetadata:
    if not isinstance(entry, dict):
        msg = f"models entry must be a mapping, got: {entry!r}"
        raise ProviderConfigError(msg)
    tier = str(entry.get("tier", "balanced"))
    if tier not in _VALID_TIERS:
        msg = f"invalid tier {tier!r} for model {entry.get('name')!r}"
        raise ProviderConfigError(msg)
    tier_literal: ModelTier = tier  # type: ignore[assignment]
    fallback = entry.get("fallback", [])
    if not isinstance(fallback, list):
        msg = f"fallback must be a list for model {entry.get('name')!r}"
        raise ProviderConfigError(msg)
    try:
        return ModelMetadata(
            name=str(_require(entry, "name", "models")),
            provider=str(_require(entry, "provider", "models")),
            cost_per_1k_input=float(_require(entry, "cost_input", "models")),
            cost_per_1k_output=float(_require(entry, "cost_output", "models")),
            latency_p50_ms=int(_require(entry, "latency_p50_ms", "models")),
            tier=tier_literal,
            reasoning_capable=bool(entry.get("reasoning", False)),
            max_tokens=int(entry.get("max_tokens", 4096)),
            fallback_to=tuple(str(f) for f in fallback),
        )
    except (TypeError, ValueError) as exc:
        msg = f"invalid model entry {entry.get('name')!r}: {exc}"
        raise ProviderConfigError(msg) from exc


def _parse_embedding(entry: Any) -> EmbeddingModelMetadata:
    if not isinstance(entry, dict):
        msg = f"embeddings entry must be a mapping, got: {entry!r}"
        raise ProviderConfigError(msg)
    try:
        return EmbeddingModelMetadata(
            name=str(_require(entry, "name", "embeddings")),
            provider=str(_require(entry, "provider", "embeddings")),
            dimension=int(_require(entry, "dimension", "embeddings")),
            cost_per_1k_tokens=float(_require(entry, "cost_per_1k", "embeddings")),
            max_input_tokens=int(entry.get("max_input_tokens", 8192)),
        )
    except (TypeError, ValueError) as exc:
        msg = f"invalid embeddings entry {entry.get('name')!r}: {exc}"
        raise ProviderConfigError(msg) from exc


def load_provider_config(
    path: str | Path,
) -> tuple[list[ModelMetadata], list[EmbeddingModelMetadata]]:
    """Load and validate model/embedding definitions from a YAML file."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"invalid YAML in provider config {path}: {exc}"
        raise ProviderConfigError(msg) from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        msg = f"provider config root must be a mapping: {path}"
        raise ProviderConfigError(msg)

    models_raw = raw.get("models", [])
    embeddings_raw = raw.get("embeddings", [])
    if not isinstance(models_raw, list) or not isinstance(embeddings_raw, list):
        msg = f"'models' and 'embeddings' must be lists: {path}"
        raise ProviderConfigError(msg)

    return (
        [_parse_model(entry) for entry in models_raw],
        [_parse_embedding(entry) for entry in embeddings_raw],
    )


def load_provider_registry(path: str | Path) -> InMemoryProviderRegistry:
    """Convenience: YAML config file -> populated InMemoryProviderRegistry."""
    models, embeddings = load_provider_config(path)
    return InMemoryProviderRegistry(models=models, embedding_models=embeddings)

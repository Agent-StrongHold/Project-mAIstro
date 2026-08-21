"""Tests for the YAML provider config loader."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from maistro.providers import (
    ProviderConfigError,
    load_provider_config,
    load_provider_registry,
)

if TYPE_CHECKING:
    from pathlib import Path

VALID_YAML = """
models:
  - name: claude-3-opus
    provider: anthropic
    tier: powerful
    cost_input: 0.15
    cost_output: 0.75
    latency_p50_ms: 800
    reasoning: true
    fallback: [gpt-4-turbo]

  - name: gpt-4-turbo
    provider: openai
    tier: powerful
    cost_input: 0.03
    cost_output: 0.06
    latency_p50_ms: 1200
    reasoning: false
    fallback: [gpt-3.5-turbo]

embeddings:
  - name: text-embedding-ada-002
    provider: openai
    dimension: 1536
    cost_per_1k: 0.0001
"""


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "providers.yaml"
    p.write_text(content, encoding="utf-8")
    return p


class TestLoadProviderConfig:
    def test_loads_models_and_embeddings(self, tmp_path: Path) -> None:
        models, embeddings = load_provider_config(_write(tmp_path, VALID_YAML))
        assert [m.name for m in models] == ["claude-3-opus", "gpt-4-turbo"]
        opus = models[0]
        assert opus.provider == "anthropic"
        assert opus.tier == "powerful"
        assert opus.cost_per_1k_input == 0.15
        assert opus.cost_per_1k_output == 0.75
        assert opus.latency_p50_ms == 800
        assert opus.reasoning_capable is True
        assert opus.fallback_to == ("gpt-4-turbo",)
        assert len(embeddings) == 1
        assert embeddings[0].dimension == 1536
        assert embeddings[0].cost_per_1k_tokens == 0.0001

    def test_defaults_applied(self, tmp_path: Path) -> None:
        models, _ = load_provider_config(
            _write(
                tmp_path,
                "models:\n"
                "  - name: m\n"
                "    provider: p\n"
                "    cost_input: 0.1\n"
                "    cost_output: 0.2\n"
                "    latency_p50_ms: 100\n",
            ),
        )
        m = models[0]
        assert m.tier == "balanced"
        assert m.reasoning_capable is False
        assert m.max_tokens == 4096
        assert m.fallback_to == ()

    def test_empty_file_yields_empty_lists(self, tmp_path: Path) -> None:
        assert load_provider_config(_write(tmp_path, "")) == ([], [])

    def test_missing_required_key_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ProviderConfigError, match="cost_input"):
            load_provider_config(
                _write(
                    tmp_path,
                    "models:\n  - name: m\n    provider: p\n"
                    "    cost_output: 0.2\n    latency_p50_ms: 100\n",
                ),
            )

    def test_invalid_tier_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ProviderConfigError, match="tier"):
            load_provider_config(
                _write(
                    tmp_path,
                    "models:\n  - name: m\n    provider: p\n    tier: mega\n"
                    "    cost_input: 0.1\n    cost_output: 0.2\n    latency_p50_ms: 100\n",
                ),
            )

    def test_non_mapping_root_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ProviderConfigError, match="mapping"):
            load_provider_config(_write(tmp_path, "- just\n- a\n- list\n"))

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ProviderConfigError, match="invalid YAML"):
            load_provider_config(_write(tmp_path, "models: [unclosed\n  - oops: {"))

    def test_non_numeric_cost_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ProviderConfigError):
            load_provider_config(
                _write(
                    tmp_path,
                    "models:\n  - name: m\n    provider: p\n"
                    "    cost_input: cheap\n    cost_output: 0.2\n    latency_p50_ms: 100\n",
                ),
            )


class TestLoadProviderRegistry:
    async def test_registry_is_populated(self, tmp_path: Path) -> None:
        registry = load_provider_registry(_write(tmp_path, VALID_YAML))
        assert (await registry.get_model("claude-3-opus")).provider == "anthropic"
        assert (await registry.get_embedding_model("text-embedding-ada-002")).dimension == 1536

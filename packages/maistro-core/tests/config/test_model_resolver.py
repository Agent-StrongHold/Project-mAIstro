"""Tests for maistro.config.model_resolver — tier model -> Pydantic AI model string."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from maistro.config.model_resolver import resolve_model


def _fake_settings(
    *, litellm_base_url: str, ollama_base_url: str = "http://localhost:11434/v1"
) -> SimpleNamespace:
    return SimpleNamespace(
        litellm=SimpleNamespace(base_url=litellm_base_url),
        ollama_base_url=ollama_base_url,
    )


class TestResolveModel:
    def test_custom_litellm_base_url_preserves_the_complete_alias(self) -> None:
        settings = _fake_settings(litellm_base_url="https://litellm.example.com")
        with patch("maistro.config.model_resolver.get_settings", return_value=settings):
            model_name, base_url, use_json_mode = resolve_model(
                "openrouter/google/gemini-2.5-flash"
            )
        assert model_name == "openai:openrouter/google/gemini-2.5-flash"
        assert base_url == "https://litellm.example.com"
        assert use_json_mode is False

    def test_default_litellm_base_url_falls_through_to_ollama_check(self) -> None:
        settings = _fake_settings(litellm_base_url="http://localhost:4000")
        with patch("maistro.config.model_resolver.get_settings", return_value=settings):
            model_name, base_url, use_json_mode = resolve_model("ollama/llama3")
        assert model_name == "openai:llama3"
        assert base_url == "http://localhost:11434/v1"
        assert use_json_mode is True

    def test_ollama_prefix_strips_and_enables_json_mode(self) -> None:
        settings = _fake_settings(
            litellm_base_url="http://localhost:4000", ollama_base_url="http://my-ollama:11434/v1"
        )
        with patch("maistro.config.model_resolver.get_settings", return_value=settings):
            model_name, base_url, use_json_mode = resolve_model("ollama/mistral")
        assert model_name == "openai:mistral"
        assert base_url == "http://my-ollama:11434/v1"
        assert use_json_mode is True

    def test_empty_litellm_base_url_treated_as_unset(self) -> None:
        settings = _fake_settings(litellm_base_url="")
        with patch("maistro.config.model_resolver.get_settings", return_value=settings):
            model_name, base_url, use_json_mode = resolve_model("openai/gpt-4")
        assert model_name == "openai/gpt-4"
        assert base_url is None
        assert use_json_mode is False

    def test_default_litellm_url_remains_the_gateway_for_remote_models(self) -> None:
        settings = _fake_settings(litellm_base_url="http://localhost:4000")
        with patch("maistro.config.model_resolver.get_settings", return_value=settings):
            model_name, base_url, use_json_mode = resolve_model("anthropic/claude-3")
        assert model_name == "openai:anthropic/claude-3"
        assert base_url == "http://localhost:4000"
        assert use_json_mode is False

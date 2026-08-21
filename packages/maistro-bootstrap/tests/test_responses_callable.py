"""Key/base-URL resolution for the builders LiteLLM callable.

Least-privilege sandboxes carry only a LiteLLM *virtual* key, so the key
chain must accept LITELLM_API_KEY / LITELLM_VIRTUAL_KEY — otherwise the
agent silently degrades to stub responses.
"""

from __future__ import annotations

import pytest

from maistro_bootstrap.builders.responses_callable import (
    LiteLLMCallable,
    _api_key,
    _base_url,
)

_ALL_KEY_VARS = (
    "LITELLM_MASTER_KEY",
    "LITELLM_PROXY_KEY",
    "LITELLM_API_KEY",
    "LITELLM_VIRTUAL_KEY",
)
_ALL_URL_VARS = ("LITELLM_URL", "LITELLM_BASE_URL", "LITELLM_PROXY_URL")


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _ALL_KEY_VARS + _ALL_URL_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize("var", _ALL_KEY_VARS)
def test_api_key_accepts_every_alias(monkeypatch: pytest.MonkeyPatch, var: str) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv(var, "sk-test-123")
    assert _api_key() == "sk-test-123"


def test_api_key_precedence_master_over_virtual(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("LITELLM_VIRTUAL_KEY", "sk-virtual")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master")
    assert _api_key() == "sk-master"


def test_api_key_empty_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    assert _api_key() == ""


def test_virtual_key_alone_configures_callable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sandbox posture: base URL + virtual key only — no stub fallback."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("LITELLM_BASE_URL", "http://gateway.example:4000")
    monkeypatch.setenv("LITELLM_VIRTUAL_KEY", "sk-virtual")
    assert LiteLLMCallable()._is_configured() is True
    assert _base_url() == "http://gateway.example:4000"


def test_unconfigured_returns_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    result = LiteLLMCallable()(messages=[{"role": "user", "content": "hi"}])
    assert result["stop_reason"] == "end_turn"
    assert "not configured" in result["content"]

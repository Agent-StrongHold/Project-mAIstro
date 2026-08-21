"""Tests for the quota panel routes, repointed from conductor-router to LiteLLM.

These tests mock the LiteLLM proxy HTTP calls and assert that each handler maps
the LiteLLM response onto the documented response shape the React frontend
depends on, and that any error falls back gracefully (HTTP 200, fallback shape).
"""

from __future__ import annotations

import httpx
import pytest
from routes import quotas


@pytest.fixture(autouse=True)
def _litellm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure a LiteLLM base/key are set so handlers attempt the HTTP path."""
    monkeypatch.setenv("LITELLM_API_BASE", "http://litellm.test:4000")
    monkeypatch.setenv("LITELLM_API_KEY", "sk-litellm-test")
    # Stop any legacy router env from leaking into precedence.
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_KEY", raising=False)


def _fake_get(routes_map: dict[str, object]):
    """Build a fake httpx.get that dispatches on the request path."""

    def _get(url: str, **kwargs: object) -> httpx.Response:
        for path, payload in routes_map.items():
            if path in url:
                if isinstance(payload, Exception):
                    raise payload
                return httpx.Response(200, json=payload, request=httpx.Request("GET", url))
        return httpx.Response(404, json={}, request=httpx.Request("GET", url))

    return _get


# --------------------------------------------------------------------------- #
# /v1/quotas/models  -> LiteLLM /model/info
# --------------------------------------------------------------------------- #


def test_models_maps_litellm_model_info(authed_client, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "data": [
            {
                "model_name": "gpt-4",
                "litellm_params": {"model": "gpt-4"},
                "model_info": {
                    "litellm_provider": "openai",
                    "mode": "chat",
                    "max_input_tokens": 8192,
                    "max_tokens": 4096,
                },
            }
        ]
    }
    monkeypatch.setattr(httpx, "get", _fake_get({"/model/info": payload}))

    r = authed_client.get("/v1/quotas/models")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and len(data) == 1
    m = data[0]
    # Shape contract: every key the frontend ModelStat type expects must exist.
    for key in (
        "model",
        "provider",
        "tier",
        "quality",
        "speed",
        "usage_pct",
        "available",
        "context",
        "modality",
        "strengths",
    ):
        assert key in m
    assert m["model"] == "gpt-4"
    assert m["provider"] == "openai"
    assert m["context"] == 8192
    assert m["modality"] == "chat"
    assert m["available"] is True
    assert isinstance(m["strengths"], list)


def test_models_empty_data(authed_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", _fake_get({"/model/info": {"data": []}}))
    r = authed_client.get("/v1/quotas/models")
    assert r.status_code == 200
    assert r.json() == []


def test_models_missing_model_info_fields(authed_client, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"data": [{"model_name": "bare-model"}]}
    monkeypatch.setattr(httpx, "get", _fake_get({"/model/info": payload}))
    r = authed_client.get("/v1/quotas/models")
    assert r.status_code == 200
    m = r.json()[0]
    assert m["model"] == "bare-model"
    assert m["provider"] == "unknown"
    assert m["context"] is None
    assert m["modality"] is None


def test_models_fallback_on_error(authed_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", _fake_get({"/model/info": RuntimeError("boom")}))
    r = authed_client.get("/v1/quotas/models")
    assert r.status_code == 200
    assert r.json() == []


# --------------------------------------------------------------------------- #
# /v1/quotas/providers -> LiteLLM /global/spend/report
# --------------------------------------------------------------------------- #


def test_providers_aggregates_spend_by_provider(
    authed_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    spend = [
        {
            "api_key": "abc",
            "total_cost": 0.5,
            "total_input_tokens": 100,
            "total_output_tokens": 200,
            "model_details": [
                {
                    "model": "gpt-4",
                    "total_cost": 0.4,
                    "total_input_tokens": 80,
                    "total_output_tokens": 150,
                },
                {
                    "model": "claude-3",
                    "total_cost": 0.1,
                    "total_input_tokens": 20,
                    "total_output_tokens": 50,
                },
            ],
        }
    ]
    models_info = {
        "data": [
            {"model_name": "gpt-4", "model_info": {"litellm_provider": "openai"}},
            {"model_name": "claude-3", "model_info": {"litellm_provider": "anthropic"}},
        ]
    }
    monkeypatch.setattr(
        httpx,
        "get",
        _fake_get({"/global/spend/report": spend, "/model/info": models_info}),
    )

    r = authed_client.get("/v1/quotas/providers")
    assert r.status_code == 200
    data = r.json()
    by_provider = {p["provider"].lower(): p for p in data}
    assert "openai" in by_provider
    assert "anthropic" in by_provider
    # gpt-4: 80 + 150 = 230 tokens attributed to openai.
    assert by_provider["openai"]["used_tokens"] == 230
    assert by_provider["anthropic"]["used_tokens"] == 70
    # Shape contract.
    for p in data:
        for key in (
            "provider",
            "status",
            "billing_cycle",
            "cycle_key",
            "used_tokens",
            "free_tokens",
            "remaining_tokens",
            "limit",
            "usage_pct",
            "request_count",
            "unit",
        ):
            assert key in p
        assert p["unit"] == "tokens"


def test_providers_empty_spend(authed_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        _fake_get({"/global/spend/report": [], "/model/info": {"data": []}}),
    )
    r = authed_client.get("/v1/quotas/providers")
    assert r.status_code == 200
    assert r.json() == []


def test_providers_fallback_on_error(authed_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        _fake_get({"/global/spend/report": RuntimeError("down")}),
    )
    r = authed_client.get("/v1/quotas/providers")
    assert r.status_code == 200
    assert r.json() == []


def test_providers_unknown_model_provider(authed_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """A spend entry for a model not present in /model/info still aggregates."""
    spend = [
        {
            "model_details": [
                {"model": "mystery-model", "total_input_tokens": 10, "total_output_tokens": 5},
            ],
        }
    ]
    monkeypatch.setattr(
        httpx,
        "get",
        _fake_get({"/global/spend/report": spend, "/model/info": {"data": []}}),
    )
    r = authed_client.get("/v1/quotas/providers")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["used_tokens"] == 15


# --------------------------------------------------------------------------- #
# /v1/quotas/outcomes
# --------------------------------------------------------------------------- #


def test_outcomes_fallback_shape(authed_client, monkeypatch: pytest.MonkeyPatch) -> None:
    # LiteLLM has no documented success/failure-rate endpoint that maps to this
    # shape; the handler must still return the documented fallback structure.
    monkeypatch.setattr(
        httpx,
        "get",
        _fake_get({"/spend/logs": RuntimeError("no logs")}),
    )
    r = authed_client.get("/v1/quotas/outcomes")
    assert r.status_code == 200
    data = r.json()
    for key in ("total", "succeeded", "failed", "rate", "by_model", "days"):
        assert key in data
    assert data["total"] == 0
    assert isinstance(data["by_model"], dict)


def test_outcomes_no_litellm_config(authed_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LITELLM_API_BASE", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    monkeypatch.delenv("CONDUCTOR_ROUTER_URL", raising=False)
    r = authed_client.get("/v1/quotas/outcomes")
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_no_litellm_config_providers_and_models(
    authed_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no base URL configured anywhere, handlers return fallbacks, no raise."""
    monkeypatch.delenv("LITELLM_API_BASE", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    monkeypatch.delenv("CONDUCTOR_ROUTER_URL", raising=False)
    assert quotas._litellm_base() == ""
    assert authed_client.get("/v1/quotas/providers").json() == []
    assert authed_client.get("/v1/quotas/models").json() == []

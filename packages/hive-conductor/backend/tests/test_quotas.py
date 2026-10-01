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


def test_models_unavailable_is_503(authed_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unreachable LiteLLM proxy is 503 — unavailable, not empty (#389)."""
    monkeypatch.setattr(httpx, "get", _fake_get({"/model/info": RuntimeError("boom")}))
    r = authed_client.get("/v1/quotas/models")
    assert r.status_code == 503
    assert "model/info" in r.json()["detail"]


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


def test_providers_unavailable_is_503(authed_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unreachable LiteLLM proxy is 503 — unavailable, not empty (#389)."""
    monkeypatch.setattr(
        httpx,
        "get",
        _fake_get({"/global/spend/report": RuntimeError("down")}),
    )
    r = authed_client.get("/v1/quotas/providers")
    assert r.status_code == 503
    assert "spend/report" in r.json()["detail"]


def test_providers_unconfigured_is_503(authed_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LITELLM_API_BASE", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    monkeypatch.delenv("CONDUCTOR_ROUTER_URL", raising=False)
    r = authed_client.get("/v1/quotas/providers")
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"]


def test_providers_request_count_aggregated_from_usage(authed_client, monkeypatch) -> None:
    """request_count comes from each model's usage.api_requests (#389).

    The field used to be initialized to 0 and never incremented — a column
    of zeros no traffic could change. LiteLLM's spend report carries per-model
    request counts in `model_details[*].usage.api_requests`; they are summed
    per provider.
    """
    spend = [
        {
            "model_details": [
                {
                    "model": "gpt-4",
                    "total_input_tokens": 80,
                    "total_output_tokens": 150,
                    "usage": {"api_requests": 7},
                },
                {
                    "model": "claude-3",
                    "total_input_tokens": 20,
                    "total_output_tokens": 50,
                    "usage": {"api_requests": 3},
                },
            ]
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
    by_provider = {p["provider"].lower(): p for p in r.json()}
    assert by_provider["openai"]["request_count"] == 7
    assert by_provider["anthropic"]["request_count"] == 3


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


def test_outcomes_reads_canonical_store_empty_is_valid(
    authed_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zero outcomes with no recorded events is empty-valid, not canned (#389).

    The handler used to return a hard-coded zeroed structure regardless of
    any event; now the zeros come from the canonical outcome store, which is
    genuinely empty here (no LiteLLM config needed — the owner is the
    outcome store, not the gateway).
    """
    r = authed_client.get("/v1/quotas/outcomes")
    assert r.status_code == 200
    data = r.json()
    for key in ("total", "succeeded", "failed", "rate", "by_model", "days"):
        assert key in data
    assert data["total"] == 0
    assert isinstance(data["by_model"], dict)


async def test_outcomes_returns_seeded_non_empty_data(
    authed_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recorded outcome changes the panel: seeded query proves it (#389)."""
    from services import feedback_service

    from maistro.memory.outcomes import InMemoryOutcomeStore

    # A fresh store, so this proof is self-contained and leaks nothing.
    monkeypatch.setattr(feedback_service, "_store", InMemoryOutcomeStore())
    await feedback_service.record_thumb(
        user_id="u1",
        project_id="p1",
        run_id="r1",
        thumb="up",
    )
    r = authed_client.get("/v1/quotas/outcomes")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["succeeded"] == 1
    assert data["failed"] == 0
    assert data["rate"] == 1.0


async def test_outcomes_store_failure_is_503(authed_client, monkeypatch) -> None:
    """A store failure is unavailable (503), never a zeroed success (#389)."""
    from services import feedback_service

    class _Broken:
        async def get_task_completion_rate(self, *, days: int) -> dict:
            raise RuntimeError("store down")

    monkeypatch.setattr(feedback_service, "_store", _Broken())
    r = authed_client.get("/v1/quotas/outcomes")
    assert r.status_code == 503
    assert "outcome store" in r.json()["detail"]


def test_no_litellm_config_providers_and_models(
    authed_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no base URL configured anywhere, handlers refuse as 503 (#389).

    Unavailable is distinct from empty: with no usage source at all, a `200`
    empty payload would be indistinguishable from a configured, genuinely
    unused gateway. `503` names the missing configuration in the detail.
    """
    monkeypatch.delenv("LITELLM_API_BASE", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    monkeypatch.delenv("CONDUCTOR_ROUTER_URL", raising=False)
    assert quotas._litellm_base() == ""
    rp = authed_client.get("/v1/quotas/providers")
    assert rp.status_code == 503
    assert "not configured" in rp.json()["detail"]
    rm = authed_client.get("/v1/quotas/models")
    assert rm.status_code == 503
    assert "not configured" in rm.json()["detail"]

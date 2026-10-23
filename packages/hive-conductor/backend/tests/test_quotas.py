"""Tests for the quota panel routes, repointed from conductor-router to LiteLLM.

These tests mock the LiteLLM proxy HTTP calls and assert that each handler maps
the LiteLLM response onto the documented response shape the React frontend
depends on, and that any error falls back gracefully (HTTP 200, fallback shape).
"""

from __future__ import annotations

import httpx
import pytest
from services import provider_usage


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
    # Envelope: provenance first (#380).
    assert data["state"] == "ok"
    assert "/model/info" in data["source"]
    assert data["computed_at"]
    assert isinstance(data["models"], list) and len(data["models"]) == 1
    m = data["models"][0]
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
    data = r.json()
    # An empty registry is `no_data`, not an empty success page (#380).
    assert data["state"] == "no_data"
    assert data["models"] == []
    assert data["reason"]


def test_models_missing_model_info_fields(authed_client, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"data": [{"model_name": "bare-model"}]}
    monkeypatch.setattr(httpx, "get", _fake_get({"/model/info": payload}))
    r = authed_client.get("/v1/quotas/models")
    assert r.status_code == 200
    m = r.json()["models"][0]
    assert m["model"] == "bare-model"
    assert m["provider"] == "unknown"
    assert m["context"] is None
    assert m["modality"] is None
    # Scores the proxy does not expose stay unmeasured — no invented neutral
    # values that would render as real 0% bars or a fabricated tier (#380).
    assert m["tier"] is None
    assert m["quality"] is None
    assert m["speed"] is None
    assert m["usage_pct"] is None


def test_models_fallback_on_error(authed_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", _fake_get({"/model/info": RuntimeError("boom")}))
    r = authed_client.get("/v1/quotas/models")
    assert r.status_code == 200
    data = r.json()
    # An unreachable registry is an outage, distinguishable from an empty one.
    assert data["state"] == "error"
    assert data["reason"]
    assert "models" not in data


def test_models_error_when_registry_body_is_malformed(
    authed_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 200 `/model/info` body that is not a model list is `error`, not a 500.

    `data` reaching the mapping phase as something non-iterable-of-dicts (here
    a bare string) raises inside the row-mapping loop; the handler's second
    guard converts that into the error envelope so a lying proxy cannot turn
    into an unhandled 500 or, worse, a plausible empty panel.
    """
    monkeypatch.setattr(httpx, "get", _fake_get({"/model/info": {"data": "garbage"}}))
    r = authed_client.get("/v1/quotas/models")
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "error"
    assert "mapped" in data["reason"]
    assert "models" not in data


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
    # Envelope: provenance first (#380).
    assert data["state"] == "ok"
    assert "spend/report" in data["source"]
    assert data["window_days"] == provider_usage.SPEND_WINDOW_DAYS
    assert data["computed_at"]
    by_provider = {p["provider"].lower(): p for p in data["providers"]}
    assert "openai" in by_provider
    assert "anthropic" in by_provider
    # gpt-4: 80 + 150 = 230 tokens attributed to openai.
    assert by_provider["openai"]["used_tokens"] == 230
    assert by_provider["anthropic"]["used_tokens"] == 70
    # Shape contract.
    for p in data["providers"]:
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
        # LiteLLM has no free-token quota concept: unmeasured stays None (#380).
        assert p["free_tokens"] is None
        assert p["remaining_tokens"] is None
        assert p["usage_pct"] is None
        assert p["limit"] is None
    # The fake spend rows carry no num_requests: count stays unmeasured.
    assert by_provider["openai"]["request_count"] is None


def test_providers_counts_requests_when_reported(
    authed_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """num_requests in the report is summed; its absence is None, not 0."""
    spend = [
        {
            "model_details": [
                {
                    "model": "gpt-4",
                    "total_input_tokens": 10,
                    "total_output_tokens": 5,
                    "num_requests": 3,
                },
                {"model": "gpt-4", "total_input_tokens": 1, "total_output_tokens": 1},
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
    p = r.json()["providers"][0]
    assert p["request_count"] == 3


def test_providers_request_count_aggregated_from_usage(authed_client, monkeypatch) -> None:
    """request_count also comes from each model's usage.api_requests (#389).

    The field used to be initialized to 0 and never incremented — a column
    of zeros no traffic could change. Proxies report per-model request counts
    in different fields; `usage.api_requests` counts exactly like
    `num_requests`, and an entry read from neither source stays None.
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
    body = r.json()
    assert body["state"] == "ok"
    by_provider = {p["provider"].lower(): p for p in body["providers"]}
    assert by_provider["openai"]["request_count"] == 7
    assert by_provider["anthropic"]["request_count"] == 3


def test_providers_empty_spend(authed_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        _fake_get({"/global/spend/report": [], "/model/info": {"data": []}}),
    )
    r = authed_client.get("/v1/quotas/providers")
    assert r.status_code == 200
    data = r.json()
    # An empty report is `no_data` with a name, not an empty success page.
    assert data["state"] == "no_data"
    assert data["providers"] == []
    assert data["reason"]


def test_providers_fallback_on_error(authed_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        _fake_get({"/global/spend/report": RuntimeError("down")}),
    )
    r = authed_client.get("/v1/quotas/providers")
    assert r.status_code == 200
    data = r.json()
    # An outage is `error`, distinguishable from empty and from unconfigured.
    assert data["state"] == "error"
    assert data["reason"]
    assert "providers" not in data


def test_providers_error_when_report_is_malformed(
    authed_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 200 response whose body cannot be aggregated is `error`, not a 500.

    The fetch-time except catches an unreachable proxy; a second guard wraps
    the aggregation phase, because a malformed-but-HTTP-200 report (here: a
    token count the proxy rendered as a non-numeric string) would otherwise
    escape as an unhandled exception — which reads as a panel outage with no
    provenance, exactly the silent failure #380 forbids.
    """

    spend: list[object] = [
        {"model_details": [{"total_input_tokens": "not-a-number"}]},
    ]
    monkeypatch.setattr(
        httpx,
        "get",
        _fake_get({"/global/spend/report": spend, "/model/info": {"data": []}}),
    )
    r = authed_client.get("/v1/quotas/providers")
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "error"
    # The reason names the phase, not a fake zeroed page.
    assert "aggregated" in data["reason"]
    assert data["window_days"] == provider_usage.SPEND_WINDOW_DAYS
    assert "providers" not in data


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
    assert len(data["providers"]) == 1
    assert data["providers"][0]["used_tokens"] == 15


# --------------------------------------------------------------------------- #
# /v1/quotas/outcomes
# --------------------------------------------------------------------------- #


def test_outcomes_reads_canonical_store_empty_is_valid(
    authed_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No recorded outcomes is `no_data`, empty-valid — not canned (#389).

    The handler used to return a hard-coded zeroed structure regardless of
    any event; the zeros now come from the canonical outcome store, which is
    genuinely empty here (no LiteLLM config needed — the owner is the
    outcome store, not the gateway).
    """
    r = authed_client.get("/v1/quotas/outcomes")
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "no_data"
    assert data["source"]
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
    assert data["state"] == "ok"
    assert data["total"] == 1
    assert data["succeeded"] == 1
    assert data["failed"] == 0
    assert data["rate"] == 1.0


async def test_outcomes_store_failure_is_error(authed_client, monkeypatch) -> None:
    """A store failure is an explicit `error`, never a zeroed success (#389)."""
    from services import feedback_service

    class _Broken:
        async def get_task_completion_rate(self, *, days: int) -> dict:
            raise RuntimeError("store down")

    monkeypatch.setattr(feedback_service, "_store", _Broken())
    r = authed_client.get("/v1/quotas/outcomes")
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "error"
    assert "outcome store" in data["reason"]


def test_no_litellm_config_providers_and_models(
    authed_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no base URL configured anywhere, handlers say unavailable, no raise."""
    monkeypatch.delenv("LITELLM_API_BASE", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    monkeypatch.delenv("CONDUCTOR_ROUTER_URL", raising=False)
    assert provider_usage._litellm_base() == ""
    providers = authed_client.get("/v1/quotas/providers").json()
    models = authed_client.get("/v1/quotas/models").json()
    assert providers["state"] == "unavailable"
    assert providers["reason"]
    assert models["state"] == "unavailable"
    assert models["reason"]

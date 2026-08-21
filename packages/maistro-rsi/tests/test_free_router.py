"""Free-router → pinned genome model: resolve (OpenRouter-direct) → register
(litellm admin API) → pin. Each leg degrades to None so seeding never breaks;
the seam replaces the un-pinnable ``openrouter/free`` sentinel with a concrete,
gateway-routable $0 alias, one fresh pick per genome.
"""

from __future__ import annotations

import httpx
import pytest

from maistro_rsi import free_router as fr
from maistro_rsi.evolve_bridge import genome_to_competitor, seed_population


class _FakeResp:
    def __init__(self, status: int = 200, payload: object = None, text: str = "") -> None:
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "err",
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(self.status_code),
            )


# --- resolve (OpenRouter-direct) -------------------------------------------------


def test_resolve_returns_none_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert fr.resolve_concrete_free_model() is None


def test_resolve_reads_concrete_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    captured: dict[str, object] = {}

    def fake_post(url, *, json, headers, timeout):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["model"] = json["model"]
        return _FakeResp(payload={"model": "cohere/north-mini-code:free", "provider": "Cohere"})

    monkeypatch.setattr(httpx, "post", fake_post)
    got = fr.resolve_concrete_free_model()
    assert got == "cohere/north-mini-code:free"
    assert captured["url"] == fr._OPENROUTER_DIRECT
    assert captured["model"] == "openrouter/free"


def test_resolve_ignores_echoed_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    # The litellm gateway echoes the alias back — that is NOT a concrete pick.
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: _FakeResp(payload={"model": "openrouter/free"})
    )
    assert fr.resolve_concrete_free_model() is None


# --- register (litellm admin API) ------------------------------------------------


def test_register_posts_credential_bound_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LITELLM_URL", "http://gw:4000")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master")
    captured: dict[str, object] = {}

    def fake_post(url, *, json, headers, timeout):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["body"] = json
        return _FakeResp(status=200, payload={})

    monkeypatch.setattr(httpx, "post", fake_post)
    alias = fr.register_gateway_alias("cohere/north:free", credential="openrouter/*-cred")
    assert alias == "openrouter/cohere/north:free"
    assert captured["url"] == "http://gw:4000/model/new"
    body = captured["body"]
    assert body["model_name"] == "openrouter/cohere/north:free"
    assert body["litellm_params"]["model"] == "openrouter/cohere/north:free"
    assert body["litellm_params"]["litellm_credential_name"] == "openrouter/*-cred"


def test_register_skips_when_already_known(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LITELLM_URL", "http://gw:4000")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master")

    def boom(*a, **k):  # type: ignore[no-untyped-def]
        raise AssertionError("should not POST when alias already registered")

    monkeypatch.setattr(httpx, "post", boom)
    known = {"openrouter/openai/gpt-oss-120b:free"}
    assert (
        fr.register_gateway_alias("openai/gpt-oss-120b:free", credential="c", known=known)
        == "openrouter/openai/gpt-oss-120b:free"
    )


def test_register_double_prefixes_openrouter_owned_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    # An OpenRouter-OWNED model id (its own leading `openrouter/` is part of the
    # model, not the LiteLLM provider prefix) must still be prefixed, or LiteLLM
    # strips the segment and routes a different, non-existent model.
    monkeypatch.setenv("LITELLM_URL", "http://gw:4000")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master")
    captured: dict[str, object] = {}

    def fake_post(url, *, json, headers, timeout):  # type: ignore[no-untyped-def]
        captured["model_name"] = json["model_name"]
        return _FakeResp(status=200, payload={})

    monkeypatch.setattr(httpx, "post", fake_post)
    alias = fr.register_gateway_alias("openrouter/sonoma-dusk-alpha:free", credential="c")
    assert alias == "openrouter/openrouter/sonoma-dusk-alpha:free"
    assert captured["model_name"] == "openrouter/openrouter/sonoma-dusk-alpha:free"


def test_register_treats_duplicate_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LITELLM_URL", "http://gw:4000")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master")
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: _FakeResp(status=400, text="model already exists")
    )
    assert fr.register_gateway_alias("x/y:free", credential="c") == "openrouter/x/y:free"


def test_register_returns_none_on_hard_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LITELLM_URL", "http://gw:4000")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResp(status=500, text="boom"))
    assert fr.register_gateway_alias("x/y:free", credential="c") is None


def test_register_returns_none_without_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LITELLM_URL", raising=False)
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_KEY", raising=False)
    assert fr.register_gateway_alias("x/y:free", credential="c") is None


# --- expand_free_router ----------------------------------------------------------

# --- discover_openrouter_credential -------------------------------------------------


def test_discover_credential_uses_override(monkeypatch: pytest.MonkeyPatch) -> None:
    # When the environment variable LITELLM_OPENROUTER_CREDENTIAL is set, the function
    # should return it without performing any HTTP request.
    monkeypatch.setenv("LITELLM_OPENROUTER_CREDENTIAL", "my-override-cred")

    # If an HTTP request is made, raise to ensure it is not called.
    def boom(*a, **k):  # type: ignore[no-untyped-def]
        raise AssertionError("httpx.get should not be called when override env is set")

    monkeypatch.setattr(httpx, "get", boom)
    cred = fr._discover_openrouter_credential(base="http://gw", key="k", timeout=1.0)
    assert cred == "my-override-cred"


def test_discover_credential_finds_first_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    # No env override; the function should query the gateway and return the first
    # credential whose name starts with "openrouter/".
    monkeypatch.delenv("LITELLM_OPENROUTER_CREDENTIAL", raising=False)

    class _FakeResp2:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            pass

        def json(self) -> object:
            return self._payload

    def fake_get(url, *, headers, timeout):  # type: ignore[no-untyped-def]
        # Return a payload with a list of credential dicts.
        return _FakeResp2(
            payload={
                "credentials": [
                    {"credential_name": "not-openrouter/foo"},
                    {"credential_name": "openrouter/cred-1"},
                    {"credential_name": "openrouter/cred-2"},
                ]
            }
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    cred = fr._discover_openrouter_credential(base="http://gw", key="k", timeout=1.0)
    assert cred == "openrouter/cred-1"


def test_expand_is_noop_without_sentinel() -> None:
    models = ["cerebras-glm-4.7", "or-qwen36"]
    assert fr.expand_free_router(models, selector=None) == models


def test_expand_replaces_each_sentinel_with_a_fresh_pick() -> None:
    picks = iter(["openrouter/a:free", "openrouter/b:free"])
    resolved: set[str] = set()
    out = fr.expand_free_router(
        ["cerebras-glm-4.7", "openrouter/free", "or-free-router"],
        selector=lambda: next(picks),
        resolved=resolved,
    )
    assert out == ["cerebras-glm-4.7", "openrouter/a:free", "openrouter/b:free"]
    assert resolved == {"openrouter/a:free", "openrouter/b:free"}


def test_expand_falls_back_to_default_when_selector_yields_none() -> None:
    out = fr.expand_free_router(["openrouter/free"], selector=lambda: None)
    assert out == [fr.DEFAULT_FREE_MODEL]


def test_expand_free_count_yields_distinct_pool() -> None:
    # One sentinel, free_count=3 → three DISTINCT concrete aliases (the router can
    # repeat a pick; the pool must de-dup).
    seq = iter(["openrouter/a:free", "openrouter/a:free", "openrouter/b:free", "openrouter/c:free"])
    out = fr.expand_free_router(["openrouter/free"], selector=lambda: next(seq, None), free_count=3)
    assert out == ["openrouter/a:free", "openrouter/b:free", "openrouter/c:free"]


def test_expand_dedups_against_literal_roster_entries() -> None:
    out = fr.expand_free_router(
        ["openrouter/x:free", "or-free-router"], selector=lambda: "openrouter/x:free"
    )
    assert out == ["openrouter/x:free"]  # the pick collided with the literal — appears once


# --- _pick_distinct --------------------------------------------------------------


def test_pick_distinct_falls_back_to_default_when_selector_returns_none() -> None:
    # When the selector yields only None (unavailable), _pick_distinct should
    # fall back to a single DEFAULT_FREE_MODEL rather than returning an empty list.
    result = fr._pick_distinct(selector=lambda: None, count=3)
    assert result == [fr.DEFAULT_FREE_MODEL]
    # Even with count > 1, we only get ONE default fallback (keeps roster routable)
    assert len(result) == 1


# --- seeding integration ---------------------------------------------------------


def test_expanded_roster_seeds_concrete_models() -> None:
    # This branch expands the roster up-front, THEN seeds round-robin: no genome
    # ever carries a raw sentinel.
    from maistro_evolve.population import PopulationStore

    roster = fr.expand_free_router(
        ["openrouter/free", "cerebras-glm-4.7"], selector=lambda: "openrouter/z/z:free"
    )
    assert roster == ["openrouter/z/z:free", "cerebras-glm-4.7"]
    store = PopulationStore()
    seed_population(store, 4, models=roster)
    seeded = {node.model for g in store.list_all() for node in g.topology.nodes}
    assert seeded <= set(roster)
    assert not (seeded & fr.FREE_ROUTER_ALIASES)
    assert all(genome_to_competitor(g).model in roster for g in store.list_all())

"""Boy Scout coverage: services/mcp_client.py from 38% → 100%.

Covers:
- _normalize_site: empty / bare host / https prefix / trailing slash
- atlassian_site_url: reads ATLASSIAN_SITE_URL then JIRA_SITE_URL
- resolve_atlassian_token: env → returns; store → returns; missing → None
- resolve_atlassian_token: store lookup raises → swallowed + next provider
- resolve_atlassian_token: outer exception (import fail) → None
- test_jira_rest: no token → ok=False; no site → ok=False; invalid site
- test_jira_rest: 200 success path returns ok=True with displayName
- test_jira_rest: non-200 status → ok=False
- test_jira_rest: httpx error → ok=False
- test_mcp_server: rovo with successful jira probe → ok=True
- test_mcp_server: rovo with no jira but token present → env_token mode
- test_mcp_server: rovo with no jira no token → ok=False jira_rest shape
- test_mcp_server: local URL reachable → ok=True
- test_mcp_server: local URL httpx error → ok=False local
- test_mcp_server: local URL 5xx → ok=False local
- test_mcp_server: unknown URL → ok=False
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import httpx
import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# --- _normalize_site -----------------------------------------------------


def test_normalize_site_empty() -> None:
    from services.mcp_client import _normalize_site

    assert _normalize_site("") == ""
    assert _normalize_site("   ") == ""


def test_normalize_site_adds_https_prefix() -> None:
    from services.mcp_client import _normalize_site

    assert _normalize_site("example.atlassian.net") == "https://example.atlassian.net"


def test_normalize_site_strips_trailing_slash() -> None:
    from services.mcp_client import _normalize_site

    assert _normalize_site("https://x.atlassian.net/") == "https://x.atlassian.net"


def test_normalize_site_preserves_existing_https() -> None:
    from services.mcp_client import _normalize_site

    assert _normalize_site("https://foo.atlassian.net") == "https://foo.atlassian.net"


# --- atlassian_site_url --------------------------------------------------


def test_atlassian_site_url_reads_ATLASSIAN_SITE_URL_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.mcp_client import atlassian_site_url

    monkeypatch.setenv("ATLASSIAN_SITE_URL", "https://primary.atlassian.net")
    monkeypatch.setenv("JIRA_SITE_URL", "https://fallback.atlassian.net")
    assert atlassian_site_url() == "https://primary.atlassian.net"


def test_atlassian_site_url_falls_back_to_JIRA_SITE_URL(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.mcp_client import atlassian_site_url

    monkeypatch.delenv("ATLASSIAN_SITE_URL", raising=False)
    monkeypatch.setenv("JIRA_SITE_URL", "https://fallback.atlassian.net")
    assert atlassian_site_url() == "https://fallback.atlassian.net"


def test_atlassian_site_url_empty_when_neither_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.mcp_client import atlassian_site_url

    monkeypatch.delenv("ATLASSIAN_SITE_URL", raising=False)
    monkeypatch.delenv("JIRA_SITE_URL", raising=False)
    assert atlassian_site_url() == ""


# --- resolve_atlassian_token --------------------------------------------


def test_resolve_token_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.mcp_client import resolve_atlassian_token

    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "env-token-1")
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    assert resolve_atlassian_token(user_id="u1") == "env-token-1"


def test_resolve_token_from_jira_api_token_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.mcp_client import resolve_atlassian_token

    monkeypatch.delenv("ATLASSIAN_API_TOKEN", raising=False)
    monkeypatch.setenv("JIRA_API_TOKEN", "jira-fallback")
    assert resolve_atlassian_token(user_id="u1") == "jira-fallback"


def test_resolve_token_no_user_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.mcp_client import resolve_atlassian_token

    monkeypatch.delenv("ATLASSIAN_API_TOKEN", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    assert resolve_atlassian_token(user_id=None) is None


def test_resolve_token_from_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services import mcp_client
    from services import user_credentials as cred_svc

    monkeypatch.delenv("ATLASSIAN_API_TOKEN", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)

    class _Store:
        def has_secret(self, uid: str, provider: str) -> bool:
            return provider == "jira" and uid == "u1"

        def use_secret(self, uid: str, provider: str, cb: Any) -> Any:
            return cb("store-token")

    monkeypatch.setattr(cred_svc, "get_credential_store", lambda: _Store())
    assert mcp_client.resolve_atlassian_token(user_id="u1") == "store-token"


def test_resolve_token_store_none_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services import mcp_client
    from services import user_credentials as cred_svc

    monkeypatch.delenv("ATLASSIAN_API_TOKEN", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    monkeypatch.setattr(cred_svc, "get_credential_store", lambda: None)
    assert mcp_client.resolve_atlassian_token(user_id="u1") is None


def test_resolve_token_inner_exception_swallowed_per_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If has_secret/use_secret raises for one provider, the loop
    continues to the next."""
    from services import mcp_client
    from services import user_credentials as cred_svc

    monkeypatch.delenv("ATLASSIAN_API_TOKEN", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)

    class _Store:
        _calls = 0

        def has_secret(self, uid: str, provider: str) -> bool:
            self._calls += 1
            if provider == "jira":
                raise RuntimeError("synthetic")
            return provider == "atlassian_rovo_mcp"

        def use_secret(self, uid: str, provider: str, cb: Any) -> Any:
            return cb("rovo-token")

    monkeypatch.setattr(cred_svc, "get_credential_store", lambda: _Store())
    assert mcp_client.resolve_atlassian_token(user_id="u1") == "rovo-token"


def test_resolve_token_outer_exception_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the cred_svc import itself raises, returns None."""
    from services import mcp_client

    monkeypatch.delenv("ATLASSIAN_API_TOKEN", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)

    import types

    broken = types.ModuleType("services.user_credentials")

    def _bad(name: str) -> Any:
        raise ImportError("synthetic")

    broken.__getattr__ = _bad  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "services.user_credentials", broken)
    assert mcp_client.resolve_atlassian_token(user_id="u1") is None


# --- test_jira_rest -----------------------------------------------------


async def test_jira_rest_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.mcp_client import test_jira_rest

    monkeypatch.delenv("ATLASSIAN_API_TOKEN", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    out = await test_jira_rest(user_id=None)
    assert out["ok"] is False
    assert "No Jira/Rovo token" in out["detail"]


async def test_jira_rest_no_site(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.mcp_client import test_jira_rest

    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tk")
    monkeypatch.delenv("ATLASSIAN_SITE_URL", raising=False)
    monkeypatch.delenv("JIRA_SITE_URL", raising=False)
    out = await test_jira_rest(user_id=None)
    assert out["ok"] is False
    assert "ATLASSIAN_SITE_URL not set" in out["detail"]


async def test_jira_rest_invalid_site(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.mcp_client import test_jira_rest

    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tk")
    monkeypatch.setenv("ATLASSIAN_SITE_URL", "https://bogus.example.com")
    out = await test_jira_rest(user_id=None)
    assert out["ok"] is False
    assert "Invalid ATLASSIAN_SITE_URL" in out["detail"]


async def test_jira_rest_200_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.mcp_client import test_jira_rest

    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tk")
    monkeypatch.setenv("ATLASSIAN_SITE_URL", "https://x.atlassian.net")
    monkeypatch.delenv("ATLASSIAN_EMAIL", raising=False)
    monkeypatch.delenv("JIRA_EMAIL", raising=False)

    class _Resp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"displayName": "Test User"}

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def get(self, *a: Any, **kw: Any) -> _Resp:
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    out = await test_jira_rest(user_id=None)
    assert out["ok"] is True
    assert "Test User" in out["detail"]


async def test_jira_rest_non_200_status(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.mcp_client import test_jira_rest

    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tk")
    monkeypatch.setenv("ATLASSIAN_SITE_URL", "https://x.atlassian.net")
    monkeypatch.delenv("ATLASSIAN_EMAIL", raising=False)
    monkeypatch.delenv("JIRA_EMAIL", raising=False)

    class _Resp:
        status_code = 403

        def json(self) -> dict[str, Any]:
            return {}

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def get(self, *a: Any, **kw: Any) -> _Resp:
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    out = await test_jira_rest(user_id=None)
    assert out["ok"] is False
    assert "403" in out["detail"]


async def test_jira_rest_httpx_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.mcp_client import test_jira_rest

    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tk")
    monkeypatch.setenv("ATLASSIAN_SITE_URL", "https://x.atlassian.net")

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def get(self, *a: Any, **kw: Any) -> Any:
            raise httpx.HTTPError("connection refused")

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    out = await test_jira_rest(user_id=None)
    assert out["ok"] is False
    assert "Jira request failed" in out["detail"]


async def test_jira_rest_uses_email_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.mcp_client import test_jira_rest

    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tk")
    monkeypatch.setenv("ATLASSIAN_SITE_URL", "https://x.atlassian.net")
    monkeypatch.setenv("ATLASSIAN_EMAIL", "me@example.com")

    captured: dict[str, Any] = {}

    class _Resp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"displayName": "U"}

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def get(self, url: str, *, auth: Any) -> _Resp:
            captured["auth"] = auth
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    await test_jira_rest(user_id=None)
    assert captured["auth"] == ("me@example.com", "tk")


# --- test_mcp_server ----------------------------------------------------


async def test_mcp_server_rovo_with_successful_jira(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services import mcp_client

    async def _jira_ok(*, user_id: Any) -> dict[str, Any]:
        return {"ok": True, "mode": "jira_rest", "detail": "Connected as X"}

    monkeypatch.setattr(mcp_client, "test_jira_rest", _jira_ok)
    out = await mcp_client.test_mcp_server("mcp-atlassian-rovo")
    assert out["ok"] is True
    assert "Rovo MCP" in out["note"]


async def test_mcp_server_rovo_with_token_but_no_site(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services import mcp_client

    async def _jira_no(*, user_id: Any) -> dict[str, Any]:
        return {"ok": False, "mode": "jira_rest", "detail": "ATLASSIAN_SITE_URL not set"}

    monkeypatch.setattr(mcp_client, "test_jira_rest", _jira_no)
    monkeypatch.setattr(mcp_client, "resolve_atlassian_token", lambda user_id: "tk")
    out = await mcp_client.test_mcp_server("mcp-atlassian-rovo")
    assert out["ok"] is True
    assert out["mode"] == "env_token"


async def test_mcp_server_rovo_no_token_no_jira(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services import mcp_client

    async def _jira_no(*, user_id: Any) -> dict[str, Any]:
        return {"ok": False, "mode": "jira_rest", "detail": "No Jira token"}

    monkeypatch.setattr(mcp_client, "test_jira_rest", _jira_no)
    monkeypatch.setattr(mcp_client, "resolve_atlassian_token", lambda user_id: None)
    out = await mcp_client.test_mcp_server("mcp-atlassian-rovo")
    assert out["ok"] is False
    assert out["server_id"] == "mcp-atlassian-rovo"


async def test_mcp_server_local_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services import mcp_client

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def get(self, *a: Any, **kw: Any) -> _Resp:
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    out = await mcp_client.test_mcp_server(
        "mcp-something",
        url="http://127.0.0.1:9876",
    )
    assert out["ok"] is True
    assert out["mode"] == "http_local"


async def test_mcp_server_local_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services import mcp_client

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def get(self, *a: Any, **kw: Any) -> Any:
            raise httpx.HTTPError("refused")

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    out = await mcp_client.test_mcp_server(
        "mcp-something",
        url="http://127.0.0.1:9876",
    )
    assert out["ok"] is False
    assert "not running on loopback" in out["detail"]


async def test_mcp_server_local_5xx_is_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """500+ responses are NOT considered reachable (the route considers
    them down)."""
    from services import mcp_client

    class _Resp:
        status_code = 500

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def get(self, *a: Any, **kw: Any) -> _Resp:
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    out = await mcp_client.test_mcp_server(
        "mcp-something",
        url="http://127.0.0.1:9876",
    )
    assert out["ok"] is False


async def test_mcp_server_unknown_server_type() -> None:
    from services.mcp_client import test_mcp_server

    out = await test_mcp_server("mcp-mystery", url="https://elsewhere.com")
    assert out["ok"] is False
    assert "Unknown server type" in out["detail"]

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import pytest
import stores
from config import OAuthProviderSettings, Settings
from fastapi import HTTPException, Request, Response
from pydantic import ValidationError
from routes import auth
from routes.auth import LoginBody

TENANT = "11111111-2222-3333-4444-555555555555"
BASE = f"https://login.microsoftonline.com/{TENANT}"


@pytest.fixture(autouse=True)
def _restore_hive_stores() -> Iterator[None]:
    """Route-level tests here write module-level stores; restore them so
    later suites see an untouched baseline (test_oauth_product_wiring counts
    audit entries exactly)."""
    snapshots = {
        "users": dict(stores.users.items()),
        "sessions": dict(stores.sessions.items()),
        "audit_log": dict(stores.audit_log.items()),
        "oauth_identity_links": dict(stores.oauth_identity_links.items()),
    }
    yield
    for name, snapshot in snapshots.items():
        store = getattr(stores, name)
        for key in list(store.keys()):
            store.pop(key)
        for key, value in snapshot.items():
            store[key] = value


def _entra_provider() -> OAuthProviderSettings:
    return OAuthProviderSettings(
        authorization_url=f"{BASE}/oauth2/v2.0/authorize",
        token_url=f"{BASE}/oauth2/v2.0/token",
        client_id="maistro-client",
        jwks_url=f"{BASE}/discovery/v2.0/keys",
        issuer=f"{BASE}/v2.0",
        userinfo_url=None,
        scopes=("openid", "profile", "email"),
        client_secret_vault_key="HIVE_OAUTH_ENTRA_CLIENT_SECRET",
    )


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "query_string": b"",
            "server": ("test", 443),
            "scheme": "https",
        }
    )


def test_hybrid_is_compatibility_default_for_existing_oauth_configuration() -> None:
    settings = Settings(
        _env_file=None,
        oauth_providers={"entra": _entra_provider()},
        oauth_public_origin="https://maistro.example",
    )

    assert settings.human_auth_mode == "hybrid"


def test_entra_mode_requires_exactly_one_provider_named_entra() -> None:
    with pytest.raises(ValidationError, match="exactly one OAuth provider named entra"):
        Settings(
            _env_file=None,
            human_auth_mode="entra",
            oauth_providers={},
            oauth_public_origin="https://maistro.example",
        )

    with pytest.raises(ValidationError, match="exactly one OAuth provider named entra"):
        Settings(
            _env_file=None,
            human_auth_mode="entra",
            oauth_providers={"oidc": _entra_provider()},
            oauth_public_origin="https://maistro.example",
        )


def test_entra_mode_accepts_one_explicit_entra_provider() -> None:
    settings = Settings(
        _env_file=None,
        human_auth_mode="entra",
        oauth_providers={"entra": _entra_provider()},
        oauth_public_origin="https://maistro.example",
    )

    assert settings.human_auth_mode == "entra"
    assert set(settings.oauth_providers) == {"entra"}


def test_entra_only_route_rejects_password_login_before_password_lookup(monkeypatch) -> None:
    monkeypatch.setattr(auth, "_enforce", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(human_auth_mode="entra"),
    )
    monkeypatch.setattr(auth, "_users", lambda: pytest.fail("password lookup must not run"))

    with pytest.raises(HTTPException) as exc:
        auth.login(
            LoginBody(username="someone", password="irrelevant"),
            _request(),
            Response(),
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "Password login is disabled for this deployment."


@pytest.mark.asyncio
async def test_local_mode_blocks_oauth_before_service_state_allocation(monkeypatch) -> None:
    async def no_charge(_request: Request) -> None:
        return None

    monkeypatch.setattr(auth, "_charge_oauth_start", no_charge)
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(human_auth_mode="local"),
    )
    monkeypatch.setattr(
        auth,
        "get_oauth_login_service",
        lambda: pytest.fail("disabled OAuth must not allocate provider state"),
    )

    response = await auth.oauth_start("entra", _request())

    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_entra_mode_blocks_non_entra_provider_before_service(monkeypatch) -> None:
    async def no_charge(_request: Request) -> None:
        return None

    monkeypatch.setattr(auth, "_charge_oauth_start", no_charge)
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(human_auth_mode="entra"),
    )
    monkeypatch.setattr(
        auth,
        "get_oauth_login_service",
        lambda: pytest.fail("non-Entra provider must not be reachable"),
    )

    response = await auth.oauth_start("oidc", _request())

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_hybrid_mode_preserves_generic_oauth_start(monkeypatch) -> None:
    class Service:
        async def start(self, provider: str) -> tuple[str, str]:
            assert provider == "oidc"
            return "https://idp.example/authorize?state=state", "state"

    async def no_charge(_request: Request) -> None:
        return None

    monkeypatch.setattr(auth, "_charge_oauth_start", no_charge)
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(human_auth_mode="hybrid"),
    )
    monkeypatch.setattr(auth, "get_oauth_login_service", lambda: Service())

    response = await auth.oauth_start("oidc", _request())

    assert response.status_code == 303
    assert response.headers["location"].startswith("https://idp.example/authorize")

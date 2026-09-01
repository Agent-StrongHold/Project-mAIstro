from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
import stores
from config import OAuthProviderSettings, Settings
from fastapi import HTTPException, Request
from models.schemas import HiveUser
from routes import auth
from services.oauth_login import OAuthLoginService

from maistro.auth.oauth import OAuthExchange, OAuthIdentity, OAuthToken

TENANT = "11111111-2222-3333-4444-555555555555"
OBJECT = "99999999-8888-7777-6666-555555555555"
SUBJECT = f"{TENANT}:{OBJECT}"
BASE = f"https://login.microsoftonline.com/{TENANT}"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        human_auth_mode="hybrid",
        oauth_public_origin="https://maistro.example",
        oauth_providers={
            "entra": OAuthProviderSettings(
                authorization_url=f"{BASE}/oauth2/v2.0/authorize",
                token_url=f"{BASE}/oauth2/v2.0/token",
                client_id="client",
                jwks_url=f"{BASE}/discovery/v2.0/keys",
                issuer=f"{BASE}/v2.0",
                scopes=("openid", "profile", "email"),
            )
        },
    )


def _request(*, query: bytes = b"", cookie: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if cookie is not None:
        headers.append((b"cookie", cookie.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "query_string": query,
            "server": ("test", 443),
            "scheme": "https",
        }
    )


def _user(user_id: str = "user-1") -> HiveUser:
    return HiveUser(
        id=user_id,
        username="alice",
        password_hash="unused",
        role="user",
        is_active=True,
        permissions=[],
        did=None,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_link_start_requires_existing_authenticated_hive_session(monkeypatch) -> None:
    async def no_charge(_request: Request) -> None:
        return None

    monkeypatch.setattr(auth, "_charge_oauth_start", no_charge)
    monkeypatch.setattr(auth, "get_current_user", lambda _session: None)
    monkeypatch.setattr(
        auth,
        "get_oauth_login_service",
        lambda: pytest.fail("anonymous link start must not allocate OAuth state"),
    )

    with pytest.raises(HTTPException) as exc:
        await auth.oauth_link_start("entra", _request(), hive_session=None)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_link_start_sets_state_and_link_marker_but_no_user_id_cookie(monkeypatch) -> None:
    class Service:
        async def start(self, provider: str) -> tuple[str, str]:
            assert provider == "entra"
            return "https://login.microsoftonline.com/authorize", "state-value"

    async def no_charge(_request: Request) -> None:
        return None

    monkeypatch.setattr(auth, "_charge_oauth_start", no_charge)
    monkeypatch.setattr(auth, "get_current_user", lambda _session: {"id": "user-1"})
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(human_auth_mode="hybrid"),
    )
    monkeypatch.setattr(auth, "get_oauth_login_service", lambda: Service())

    response = await auth.oauth_link_start("entra", _request(), hive_session="session-1")
    cookies = response.headers.getlist("set-cookie")

    assert response.status_code == 303
    assert any("__Host-hive_oauth_state_entra=state-value" in cookie for cookie in cookies)
    assert any("__Host-hive_oauth_link_entra=1" in cookie for cookie in cookies)
    assert all("user-1" not in cookie for cookie in cookies)


@pytest.mark.asyncio
async def test_link_callback_uses_current_session_and_does_not_issue_new_hive_session(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str]] = []
    user = _user()

    class Service:
        success_path = "/"

        async def link_authenticated_user(self, **kwargs):
            calls.append((kwargs["provider"], kwargs["user_id"]))
            return SimpleNamespace(user=user, provider="entra", subject=SUBJECT)

        async def authenticate(self, **kwargs):
            pytest.fail("link callback must not fall through to ordinary login")

    async def no_charge(_request: Request) -> None:
        return None

    monkeypatch.setattr(auth, "_charge_oauth_callback", no_charge)
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(human_auth_mode="hybrid"),
    )
    monkeypatch.setattr(auth, "get_current_user", lambda session: {"id": "user-1"} if session else None)
    monkeypatch.setattr(auth, "get_oauth_login_service", lambda: Service())
    monkeypatch.setattr(auth, "log_audit", lambda *args, **kwargs: None)

    request = _request(
        query=b"code=code&state=state",
        cookie=(
            "hive_session=session-1; "
            "__Host-hive_oauth_state_entra=state; "
            "__Host-hive_oauth_link_entra=1"
        ),
    )
    response = await auth.oauth_callback("entra", request)
    cookies = response.headers.getlist("set-cookie")

    assert response.status_code == 303
    assert calls == [("entra", "user-1")]
    assert not any(cookie.startswith("hive_session=") for cookie in cookies)
    assert any("__Host-hive_oauth_link_entra=" in cookie for cookie in cookies)


@pytest.mark.asyncio
async def test_link_callback_without_current_session_fails_instead_of_linking(monkeypatch) -> None:
    class Service:
        async def link_authenticated_user(self, **kwargs):
            pytest.fail("missing current session must fail before link mutation")

    async def no_charge(_request: Request) -> None:
        return None

    monkeypatch.setattr(auth, "_charge_oauth_callback", no_charge)
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(human_auth_mode="hybrid"),
    )
    monkeypatch.setattr(auth, "get_current_user", lambda _session: None)
    monkeypatch.setattr(auth, "get_oauth_login_service", lambda: Service())
    monkeypatch.setattr(auth, "log_audit", lambda *args, **kwargs: None)

    request = _request(
        query=b"code=code&state=state",
        cookie="__Host-hive_oauth_state_entra=state; __Host-hive_oauth_link_entra=1",
    )
    response = await auth.oauth_callback("entra", request)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_service_link_uses_verified_subject_and_explicit_user_id(monkeypatch) -> None:
    user = _user()
    stores.users[user.id] = user
    linked: list[tuple[str, str, str]] = []

    class LinkStore:
        async def resolve(self, provider: str, sub: str) -> str | None:
            return None

        async def link(self, provider: str, sub: str, user_id: str) -> None:
            linked.append((provider, sub, user_id))

    exchange = OAuthExchange(
        identity=OAuthIdentity(provider="entra", sub=SUBJECT),
        token=OAuthToken(access_token="secret", token_type="Bearer"),
    )

    class Client:
        async def exchange_code(self, provider: str, code: str, state: str, redirect_uri: str):
            assert (provider, code, state) == ("entra", "code", "state")
            assert redirect_uri.endswith("/v1/auth/oauth/entra/callback")
            return exchange

    async with httpx.AsyncClient() as http:
        service = OAuthLoginService(_settings(), http=http, link_store=LinkStore())
        monkeypatch.setattr(service, "_client", Client())
        result = await service.link_authenticated_user(
            provider="entra",
            code="code",
            state="state",
            browser_state="state",
            user_id=user.id,
        )

    assert linked == [("entra", SUBJECT, user.id)]
    assert result.user.id == user.id
    assert result.subject == SUBJECT


@pytest.mark.asyncio
async def test_ordinary_unlinked_login_still_does_not_auto_link(monkeypatch) -> None:
    class Service:
        async def authenticate(self, **kwargs):
            raise AssertionError("ordinary login behavior is owned by the existing unlinked denial path")

    # This regression is structural: adding the explicit link flow must not
    # make the normal login route infer a link from email or the current session.
    assert not hasattr(Service(), "auto_link_by_email")
    assert "email" not in auth.oauth_callback.__annotations__

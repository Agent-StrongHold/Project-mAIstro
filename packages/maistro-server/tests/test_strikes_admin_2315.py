"""#2315 — admin strike recovery reads Container.strike_recovery."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from maistro.security.sentinel.authz_types import Principal
from maistro.security.strikes import StrikeRecord
from maistro_server.api import strikes
from maistro_server.api.auth import verify_api_key
from maistro_server.api.principal import AuthenticatedPrincipal


@pytest.fixture
def app_with_recovery() -> FastAPI:
    app = FastAPI()
    app.include_router(strikes.router, prefix="/v1")
    service = MagicMock()
    service.unlock = AsyncMock(
        return_value=StrikeRecord(user_id="target", strike_count=0, disabled=False)
    )
    service.enable = AsyncMock(
        return_value=StrikeRecord(user_id="target", strike_count=1, disabled=False)
    )
    service.remove_strikes = AsyncMock(
        return_value=StrikeRecord(user_id="target", strike_count=0, disabled=False)
    )
    container = MagicMock()
    container.strike_recovery = service
    app.state.container = container
    app.state._strike_service = service
    return app


def _override(app: FastAPI, principal: AuthenticatedPrincipal) -> None:
    app.dependency_overrides[verify_api_key] = lambda: principal


@pytest.mark.asyncio
async def test_admin_unlock_reads_container_strike_recovery(
    app_with_recovery: FastAPI,
) -> None:
    _override(
        app_with_recovery,
        AuthenticatedPrincipal(user_id="operator", token="t", roles=frozenset({"admin", "user"})),
    )
    transport = ASGITransport(app=app_with_recovery)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/v1/admin/strikes/target/unlock")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "target"
    assert body["is_locked"] is False
    service = app_with_recovery.state._strike_service
    service.unlock.assert_awaited_once()
    actor = service.unlock.await_args.args[0]
    assert isinstance(actor, Principal)
    assert actor.id == "operator"
    assert "admin" in actor.roles


@pytest.mark.asyncio
async def test_non_admin_is_forbidden(app_with_recovery: FastAPI) -> None:
    _override(
        app_with_recovery,
        AuthenticatedPrincipal(user_id="operator", token="t", roles=frozenset({"user"})),
    )
    transport = ASGITransport(app=app_with_recovery)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/v1/admin/strikes/target/unlock")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_missing_recovery_service_is_unavailable() -> None:
    app = FastAPI()
    app.include_router(strikes.router, prefix="/v1")
    container = MagicMock()
    container.strike_recovery = None
    app.state.container = container
    _override(
        app,
        AuthenticatedPrincipal(user_id="operator", token="t", roles=frozenset({"admin"})),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/v1/admin/strikes/target/unlock")
    assert resp.status_code == 503

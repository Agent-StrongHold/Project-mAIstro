"""Conductor-level proof that configured gateways seed the SSRF policy (#285)."""

from __future__ import annotations

import httpx
import pytest
from config import Settings
from main import _seed_outbound_policy

from maistro.http import aclose_shared_clients, override_transport, shared_client
from maistro.security.outbound import enforce_outbound_policy, reset_outbound_policy
from maistro.security.ssrf import SSRFBlockedError

_GATEWAY_ENV_ALIASES = (
    "LITELLM_API_BASE",
    "LITELLM_PROXY_URL",
    "LITELLM_BASE_URL",
    "LITELLM_URL",
    "MAISTRO_LLM_BASE_URL",
)


@pytest.fixture(autouse=True)
async def _clean_outbound_policy():
    reset_outbound_policy()
    await aclose_shared_clients()
    yield
    reset_outbound_policy()
    await aclose_shared_clients()


@pytest.mark.parametrize("env_name", _GATEWAY_ENV_ALIASES)
def test_every_gateway_environment_alias_maps_to_the_canonical_field(
    monkeypatch: pytest.MonkeyPatch, env_name: str
) -> None:
    for alias in _GATEWAY_ENV_ALIASES:
        monkeypatch.delenv(alias, raising=False)
    monkeypatch.setenv(env_name, "https://gateway.corp.example:8443/v1")

    settings = Settings(_env_file=None)

    assert settings.litellm_api_base == "https://gateway.corp.example:8443/v1"
    assert settings.maistro_llm_base_url == settings.litellm_api_base


@pytest.mark.parametrize(
    "gateway",
    [
        "http://10.40.0.8:4000/v1",
        "http://[fd00::40]:4000/v1",
        "https://gateway.corp.example:8443/v1",
    ],
)
async def test_configured_private_gateway_origin_is_allowed_without_widening(gateway: str) -> None:
    _seed_outbound_policy(Settings(_env_file=None, litellm_api_base=gateway))

    await enforce_outbound_policy(f"{gateway.rstrip('/')}/models")

    with pytest.raises(SSRFBlockedError):
        await enforce_outbound_policy("http://10.40.0.8:4999/admin")


async def test_unconfigured_hostname_resolving_private_remains_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_outbound_policy(
        Settings(_env_file=None, litellm_api_base="https://gateway.corp.example:8443/v1")
    )
    monkeypatch.setattr("maistro.security.ssrf._resolve", lambda _host: ["10.40.0.9"])

    with pytest.raises(SSRFBlockedError, match="internal address"):
        await enforce_outbound_policy("https://other.corp.example:8443/v1/models")


async def test_redirect_cannot_escape_the_configured_gateway_origin() -> None:
    class _Redirector(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.seen: list[str] = []

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.seen.append(str(request.url))
            return httpx.Response(
                302,
                headers={"Location": "http://10.40.0.99:4000/admin"},
                request=request,
            )

    _seed_outbound_policy(Settings(_env_file=None, litellm_api_base="http://10.40.0.8:4000/v1"))
    inner = _Redirector()

    with override_transport(inner), pytest.raises(SSRFBlockedError):
        async with shared_client(timeout=1.0, follow_redirects=True) as client:
            await client.get("http://10.40.0.8:4000/v1/models")

    assert inner.seen == ["http://10.40.0.8:4000/v1/models"]

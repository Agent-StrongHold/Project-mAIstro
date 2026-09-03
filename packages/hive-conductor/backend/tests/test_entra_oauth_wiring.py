from __future__ import annotations

from typing import Any

import httpx
import pytest
from services.entra_oauth import ProductIdTokenVerifier, entra_tenant_from_provider_config

from maistro.auth.entra import build_entra_provider_config
from maistro.auth.oauth import OAuthProviderConfig, OAuthTokenValidationError

TENANT = "11111111-2222-3333-4444-555555555555"
OBJECT = "99999999-8888-7777-6666-555555555555"
CLIENT = "maistro-enterprise-client"


class StubVerifier:
    def __init__(self, claims: dict[str, Any]) -> None:
        self.claims = claims
        self.calls: list[str] = []

    async def verify(
        self,
        id_token: str,
        config: OAuthProviderConfig,
        http: httpx.AsyncClient,
        nonce: str | None,
    ) -> dict[str, Any]:
        self.calls.append(config.name)
        return dict(self.claims)


def _entra() -> OAuthProviderConfig:
    return build_entra_provider_config(tenant_id=TENANT, client_id=CLIENT)


def test_product_config_extracts_only_concrete_matching_entra_tenant() -> None:
    assert entra_tenant_from_provider_config(_entra()) == TENANT


@pytest.mark.parametrize(
    "config",
    [
        OAuthProviderConfig(
            name="entra",
            authorization_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
            client_id=CLIENT,
            jwks_url="https://login.microsoftonline.com/common/discovery/v2.0/keys",
            issuer="https://login.microsoftonline.com/common/v2.0",
            require_id_token=True,
        ),
        OAuthProviderConfig(
            name="entra",
            authorization_url=f"https://evil.example/{TENANT}/oauth2/v2.0/authorize",
            token_url=f"https://evil.example/{TENANT}/oauth2/v2.0/token",
            client_id=CLIENT,
            jwks_url=f"https://evil.example/{TENANT}/discovery/v2.0/keys",
            issuer=f"https://evil.example/{TENANT}/v2.0",
            require_id_token=True,
        ),
    ],
)
def test_multitenant_alias_or_non_microsoft_entra_issuer_is_rejected(
    config: OAuthProviderConfig,
) -> None:
    with pytest.raises(OAuthTokenValidationError):
        entra_tenant_from_provider_config(config)


def test_cross_tenant_endpoint_mix_is_rejected() -> None:
    config = _entra()
    mixed = OAuthProviderConfig(
        **{
            **config.__dict__,
            "token_url": "https://login.microsoftonline.com/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/oauth2/v2.0/token",
        }
    )

    with pytest.raises(OAuthTokenValidationError, match="endpoints"):
        entra_tenant_from_provider_config(mixed)


def test_entra_userinfo_endpoint_is_rejected_to_keep_identity_on_verified_id_token() -> None:
    config = _entra()
    with_userinfo = OAuthProviderConfig(
        **{**config.__dict__, "userinfo_url": "https://graph.microsoft.com/oidc/userinfo"}
    )

    with pytest.raises(OAuthTokenValidationError, match="verified id_token"):
        entra_tenant_from_provider_config(with_userinfo)


@pytest.mark.asyncio
async def test_generic_provider_uses_generic_verifier_unchanged() -> None:
    generic = StubVerifier({"sub": "ordinary-subject"})
    verifier = ProductIdTokenVerifier(generic=generic)
    config = OAuthProviderConfig(
        name="oidc",
        authorization_url="https://idp.example/authorize",
        token_url="https://idp.example/token",
        client_id="client",
        jwks_url="https://idp.example/jwks",
        issuer="https://idp.example",
        require_id_token=True,
    )

    async with httpx.AsyncClient() as http:
        claims = await verifier.verify("token", config, http, "nonce")

    assert generic.calls == ["oidc"]
    assert claims["sub"] == "ordinary-subject"


@pytest.mark.asyncio
async def test_entra_provider_dispatches_verified_claims_to_tid_oid_normalization() -> None:
    generic = StubVerifier(
        {
            "sub": "pairwise-subject",
            "tid": TENANT,
            "oid": OBJECT,
            "email": "person@example.test",
        }
    )
    verifier = ProductIdTokenVerifier(generic=generic)

    async with httpx.AsyncClient() as http:
        claims = await verifier.verify("token", _entra(), http, "nonce")

    assert generic.calls == ["entra"]
    assert claims["sub"] == f"{TENANT}:{OBJECT}"
    assert claims["email"] == "person@example.test"


@pytest.mark.asyncio
async def test_entra_wrong_tid_is_denied_after_generic_crypto_verification() -> None:
    generic = StubVerifier(
        {
            "sub": "pairwise-subject",
            "tid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "oid": OBJECT,
        }
    )
    verifier = ProductIdTokenVerifier(generic=generic)

    async with httpx.AsyncClient() as http:
        with pytest.raises(OAuthTokenValidationError, match="tenant is not admitted"):
            await verifier.verify("token", _entra(), http, "nonce")

    assert generic.calls == ["entra"]

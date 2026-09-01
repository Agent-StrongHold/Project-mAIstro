from __future__ import annotations

from typing import Any

import httpx
import pytest

from maistro.auth.entra import (
    EntraIdTokenVerifier,
    EntraIdentityKey,
    build_entra_provider_config,
    canonical_entra_tenant_id,
)
from maistro.auth.oauth import OAuthProviderConfig, OAuthTokenValidationError

TENANT = "11111111-2222-3333-4444-555555555555"
OTHER_TENANT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OBJECT = "99999999-8888-7777-6666-555555555555"
CLIENT = "maistro-enterprise-client"


class StubVerifier:
    def __init__(self, claims: dict[str, Any]) -> None:
        self.claims = claims
        self.calls = 0

    async def verify(
        self,
        id_token: str,
        config: OAuthProviderConfig,
        http: httpx.AsyncClient,
        nonce: str | None,
    ) -> dict[str, Any]:
        self.calls += 1
        return dict(self.claims)


def test_build_entra_provider_config_is_tenant_specific_and_requires_id_token() -> None:
    config = build_entra_provider_config(tenant_id=TENANT.upper(), client_id=f" {CLIENT} ")

    base = f"https://login.microsoftonline.com/{TENANT}"
    assert config.name == "entra"
    assert config.authorization_url == f"{base}/oauth2/v2.0/authorize"
    assert config.token_url == f"{base}/oauth2/v2.0/token"
    assert config.jwks_url == f"{base}/discovery/v2.0/keys"
    assert config.issuer == f"{base}/v2.0"
    assert config.userinfo_url is None
    assert config.client_id == CLIENT
    assert config.require_id_token is True
    assert config.scopes == ("openid", "profile", "email")


@pytest.mark.parametrize("tenant", ["common", "organizations", "consumers", "", "not-a-uuid"])
def test_entra_tenant_must_be_one_explicit_directory(tenant: str) -> None:
    with pytest.raises(ValueError, match="concrete directory UUID"):
        canonical_entra_tenant_id(tenant)


@pytest.mark.asyncio
async def test_verifier_normalizes_verified_tid_oid_into_durable_subject() -> None:
    delegate = StubVerifier(
        {
            "sub": "pairwise-subject-that-must-not-own-the-link",
            "tid": TENANT.upper(),
            "oid": OBJECT.upper(),
            "email": "old-address@example.test",
        }
    )
    verifier = EntraIdTokenVerifier(tenant_id=TENANT, delegate=delegate)
    config = build_entra_provider_config(tenant_id=TENANT, client_id=CLIENT)

    async with httpx.AsyncClient() as http:
        claims = await verifier.verify("verified-upstream", config, http, "nonce")

    assert delegate.calls == 1
    assert claims["sub"] == f"{TENANT}:{OBJECT}"
    assert EntraIdentityKey.parse_subject(claims["sub"]) == EntraIdentityKey(TENANT, OBJECT)


@pytest.mark.asyncio
async def test_same_object_id_in_another_tenant_cannot_collide() -> None:
    admitted = EntraIdTokenVerifier(
        tenant_id=TENANT,
        delegate=StubVerifier({"sub": "x", "tid": TENANT, "oid": OBJECT}),
    )
    other = EntraIdTokenVerifier(
        tenant_id=OTHER_TENANT,
        delegate=StubVerifier({"sub": "x", "tid": OTHER_TENANT, "oid": OBJECT}),
    )
    admitted_config = build_entra_provider_config(tenant_id=TENANT, client_id=CLIENT)
    other_config = build_entra_provider_config(tenant_id=OTHER_TENANT, client_id=CLIENT)

    async with httpx.AsyncClient() as http:
        admitted_claims = await admitted.verify("token-a", admitted_config, http, "nonce-a")
        other_claims = await other.verify("token-b", other_config, http, "nonce-b")

    assert admitted_claims["sub"] != other_claims["sub"]
    assert admitted_claims["sub"].endswith(OBJECT)
    assert other_claims["sub"].endswith(OBJECT)


@pytest.mark.asyncio
async def test_wrong_tenant_fails_closed_after_normal_oidc_verification() -> None:
    verifier = EntraIdTokenVerifier(
        tenant_id=TENANT,
        delegate=StubVerifier({"sub": "x", "tid": OTHER_TENANT, "oid": OBJECT}),
    )
    config = build_entra_provider_config(tenant_id=TENANT, client_id=CLIENT)

    async with httpx.AsyncClient() as http:
        with pytest.raises(OAuthTokenValidationError, match="tenant is not admitted"):
            await verifier.verify("verified-upstream", config, http, "nonce")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claims", "claim"),
    [
        ({"sub": "x", "oid": OBJECT}, "tid"),
        ({"sub": "x", "tid": TENANT}, "oid"),
        ({"sub": "x", "tid": "common", "oid": OBJECT}, "tid"),
        ({"sub": "x", "tid": TENANT, "oid": "not-a-uuid"}, "oid"),
    ],
)
async def test_missing_or_non_uuid_entra_identity_claims_fail_closed(
    claims: dict[str, Any], claim: str
) -> None:
    verifier = EntraIdTokenVerifier(tenant_id=TENANT, delegate=StubVerifier(claims))
    config = build_entra_provider_config(tenant_id=TENANT, client_id=CLIENT)

    async with httpx.AsyncClient() as http:
        with pytest.raises(OAuthTokenValidationError, match=rf"valid {claim} claim"):
            await verifier.verify("verified-upstream", config, http, "nonce")


def test_email_or_upn_changes_do_not_participate_in_entra_identity_key() -> None:
    first = EntraIdentityKey.from_claims(
        {"tid": TENANT, "oid": OBJECT, "email": "one@example.test", "upn": "one@example.test"}
    )
    second = EntraIdentityKey.from_claims(
        {"tid": TENANT, "oid": OBJECT, "email": "two@example.test", "upn": "renamed@example.test"}
    )

    assert first == second
    assert first.subject == f"{TENANT}:{OBJECT}"


def test_parse_subject_rejects_ambiguous_or_non_uuid_values() -> None:
    for subject in (OBJECT, f"{TENANT}:{OBJECT}:extra", f"common:{OBJECT}"):
        with pytest.raises((ValueError, OAuthTokenValidationError)):
            EntraIdentityKey.parse_subject(subject)

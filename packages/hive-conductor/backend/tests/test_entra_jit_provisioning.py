"""Entra group-gated JIT provisioning is *reached* by the login path (#492).

`test_entra_entitlements.py` proves the policy engine's decisions in
isolation. These tests prove the product transaction exists: real settings
activate a validated policy, an unlinked verified Entra identity is admitted
as a new account only through an explicitly eligible group, the account
receives only the configured permissions, and every refusal — no eligible
group, a directory outage, a username conflict — leaves no account, no link,
and an audit record. A correct policy nothing calls is the shape #257 was
filed about; this file is the answer for #492.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx
import jwt as pyjwt
import pytest
import routes.auth as auth_routes
import stores
from config import Settings, get_settings
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from main import app
from pydantic import ValidationError
from services.entra_entitlements import (
    EntraEntitlementPolicyError,
    EntraGroupGrant,
    EntraGroupMembership,
    IncompleteGroupMembershipError,
    jit_policy_from_config,
)
from services.entra_jit import (
    ENTRA_JIT_UNUSABLE_PASSWORD_HASH,
    EntraJitProvisioner,
    GraphMembershipResolver,
    _candidate_username,
)
from services.oauth_login import HiveIdentityLinkStore, OAuthLoginService, _identity_link_key

from maistro.auth.oauth import OAuthExchange, OAuthIdentity, OAuthToken
from maistro.security.auth_throttle import AuthThrottle
from maistro.security.passwords import verify_password

_ENTRA_TENANT = "11111111-2222-3333-4444-555555555555"
_ENTRA_TENANT_BASE = f"https://login.microsoftonline.com/{_ENTRA_TENANT}"
_ENTRA_JWKS_URL = f"{_ENTRA_TENANT_BASE}/discovery/v2.0/keys"
_ENTRA_TOKEN_URL = f"{_ENTRA_TENANT_BASE}/oauth2/v2.0/token"
_ENTRA_ISSUER = f"{_ENTRA_TENANT_BASE}/v2.0"
_ENTRA_CLIENT_ID = "hive-entra-client"
_ENTRA_OID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_ENTRA_SUBJECT = f"{_ENTRA_TENANT}:{_ENTRA_OID}"
_PAIRWISE_SUB = "pairwise-sub-never-linked"

_PUBLIC_ORIGIN = "https://conductor.example.test"
_SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "entra-jit-test-key"

_GROUP_ELIGIBLE = "11111111-1111-1111-1111-111111111111"
_GROUP_OTHER_ELIGIBLE = "22222222-2222-2222-2222-222222222222"
_GROUP_UNKNOWN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

_POLICY_VERSION = "jit-test-v1"
_JIT_PERMISSIONS = ["dags.write", "runs.read"]


def _entra_provider_document() -> dict[str, dict[str, object]]:
    return {"entra": {"client_id": _ENTRA_CLIENT_ID, "entra_tenant_id": _ENTRA_TENANT}}


def _jit_groups_document() -> dict[str, dict[str, object]]:
    return {
        _GROUP_ELIGIBLE: {"role": "user", "permissions": _JIT_PERMISSIONS[:1]},
        _GROUP_OTHER_ELIGIBLE: {"role": "user", "permissions": _JIT_PERMISSIONS[1:]},
    }


def _b64_number(value: int) -> str:
    size = max(1, (value.bit_length() + 7) // 8)
    return base64.urlsafe_b64encode(value.to_bytes(size, "big")).rstrip(b"=").decode()


def _jwks() -> dict[str, object]:
    public = _SIGNING_KEY.public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": _KID,
                "use": "sig",
                "alg": "RS256",
                "n": _b64_number(public.n),
                "e": _b64_number(public.e),
            }
        ]
    }


def _entra_id_token(nonce: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {
            "iss": _ENTRA_ISSUER,
            "aud": _ENTRA_CLIENT_ID,
            "sub": _PAIRWISE_SUB,
            "exp": now + 300,
            "iat": now,
            "nonce": nonce,
            "tid": _ENTRA_TENANT,
            "oid": _ENTRA_OID,
            "name": "Ada Lovelace",
            "email": "ada@example.test",
            "email_verified": True,
        },
        _SIGNING_KEY,
        algorithm="RS256",
        headers={"kid": _KID},
    )


class FakeIdentityProvider:
    """Serve the tenant-specific Entra v2 token/JWKS endpoints."""

    def __init__(self) -> None:
        self.codes: dict[str, dict[str, object]] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == _ENTRA_JWKS_URL:
            return httpx.Response(200, json=_jwks())
        if url == _ENTRA_TOKEN_URL:
            form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
            body = self.codes.pop(form.get("code", ""), None)
            if body is None:
                return httpx.Response(
                    400, json={"error": "invalid_grant", "error_description": "unknown code"}
                )
            return httpx.Response(200, json=body)
        if url.startswith("https://graph.microsoft.com/v1.0/me/transitiveMemberOf"):
            # The production Graph resolver built by
            # `build_entra_jit_provisioner` talks to this origin; the token
            # proves the login's access token was the one presented.
            if request.headers.get("Authorization") != "Bearer jit-access-token":
                return httpx.Response(401, json={"error": {"code": "InvalidAuthenticationToken"}})
            return httpx.Response(
                200,
                json={
                    "value": [
                        {"id": _GROUP_ELIGIBLE, "@odata.type": "#microsoft.graph.group"},
                    ]
                },
            )
        return httpx.Response(404)


@dataclass
class StubResolver:
    """Membership evidence the tests control, source `resolver`."""

    membership: EntraGroupMembership | None = None
    failure: Exception | None = None

    async def resolve(self, access_token: str) -> EntraGroupMembership:
        assert access_token == "jit-access-token"
        if self.failure is not None:
            raise self.failure
        assert self.membership is not None
        return self.membership


def _policy() -> object:
    return jit_policy_from_config(
        enabled=True,
        policy_version=_POLICY_VERSION,
        groups={
            _GROUP_ELIGIBLE: EntraGroupGrant("user", frozenset(_JIT_PERMISSIONS[:1])),
            _GROUP_OTHER_ELIGIBLE: EntraGroupGrant("user", frozenset(_JIT_PERMISSIONS[1:])),
        },
    )


@dataclass
class JitHarness:
    idp: FakeIdentityProvider
    http: httpx.AsyncClient
    links: HiveIdentityLinkStore
    resolver: StubResolver
    service: OAuthLoginService
    users_before: set[str] = field(default_factory=set)


def _restore_store(store: object, snapshot: dict[str, object]) -> None:
    keys = list(store.keys())  # type: ignore[attr-defined]
    for key in keys:
        store.pop(key)  # type: ignore[attr-defined]
    for key, value in snapshot.items():
        store[key] = value  # type: ignore[index]


@pytest.fixture
def jit_harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[JitHarness]:
    snapshots = {
        "links": dict(stores.oauth_identity_links.items()),
        "sessions": dict(stores.sessions.items()),
        "audit": dict(stores.audit_log.items()),
        "users": dict(stores.users.items()),
        "claims": dict(stores.username_claims.items()),
    }
    stores.oauth_identity_links.clear()

    monkeypatch.setenv("OAUTH_PROVIDERS", json.dumps(_entra_provider_document()))
    monkeypatch.setenv("OAUTH_PUBLIC_ORIGIN", _PUBLIC_ORIGIN)
    monkeypatch.setenv("ENTRA_JIT_ENABLED", "true")
    monkeypatch.setenv("ENTRA_JIT_POLICY_VERSION", _POLICY_VERSION)
    monkeypatch.setenv("ENTRA_JIT_GROUPS", json.dumps(_jit_groups_document()))
    get_settings.cache_clear()
    monkeypatch.setattr(
        auth_routes,
        "_OAUTH_START_THROTTLE",
        AuthThrottle(auth_routes._OAUTH_START_LIMITS),
    )
    monkeypatch.setattr(
        auth_routes,
        "_OAUTH_CALLBACK_THROTTLE",
        AuthThrottle(auth_routes._OAUTH_START_LIMITS),
    )

    idp = FakeIdentityProvider()
    http = httpx.AsyncClient(transport=httpx.MockTransport(idp.handler))
    links = HiveIdentityLinkStore()
    resolver = StubResolver(membership=EntraGroupMembership.complete_resolver([_GROUP_ELIGIBLE]))
    harness = JitHarness(
        idp=idp,
        http=http,
        links=links,
        resolver=resolver,
        service=OAuthLoginService(
            get_settings(),
            http=http,
            link_store=links,
            # The stub resolver is the controllable membership seam; the
            # policy is the same one validated settings build.
            jit_provisioner=EntraJitProvisioner(
                _policy(),  # type: ignore[arg-type]
                resolver,  # type: ignore[arg-type]
                links=links,
            ),
        ),
    )
    harness.users_before = set(stores.users.keys())
    monkeypatch.setattr(auth_routes, "get_oauth_login_service", lambda: harness.service)
    yield harness

    asyncio.run(http.aclose())
    _restore_store(stores.oauth_identity_links, snapshots["links"])
    _restore_store(stores.sessions, snapshots["sessions"])
    _restore_store(stores.audit_log, snapshots["audit"])
    _restore_store(stores.users, snapshots["users"])
    _restore_store(stores.username_claims, snapshots["claims"])
    get_settings.cache_clear()


def _client() -> TestClient:
    return TestClient(app, base_url=_PUBLIC_ORIGIN)


def _begin(client: TestClient) -> tuple[str, str]:
    response = client.get("/v1/auth/oauth/entra/start", follow_redirects=False)
    assert response.status_code == 303, response.text
    query = parse_qs(urlparse(response.headers["location"]).query)
    return query["state"][0], query["nonce"][0]


def _callback(client: TestClient, code: str, state: str) -> httpx.Response:
    return client.get(
        "/v1/auth/oauth/entra/callback",
        params={"code": code, "state": state},
        follow_redirects=False,
    )


def _login_once(
    harness: JitHarness, client: TestClient, code: str = "entra-code"
) -> httpx.Response:
    state, nonce = _begin(client)
    harness.idp.codes[code] = {
        "access_token": "jit-access-token",
        "token_type": "Bearer",
        "id_token": _entra_id_token(nonce),
    }
    return _callback(client, code, state)


def _jit_audit_entries() -> list[dict[str, object]]:
    return [
        entry
        for entry in stores.audit_log.values()
        if isinstance(entry, dict) and entry.get("action") == "auth.entra.jit"
    ]


def _new_users(before: set[str]) -> list[object]:
    return [stores.users[key] for key in set(stores.users.keys()) - before]


class TestJitProvisioningAtTheLoginBoundary:
    @pytest.mark.contract("boundary")
    @pytest.mark.contract("behavioral")
    def test_an_eligible_unlinked_identity_is_provisioned_on_first_login(
        self, jit_harness: JitHarness
    ) -> None:
        client = _client()
        sessions_before = set(stores.sessions.keys())

        callback = _login_once(jit_harness, client)

        assert callback.status_code == 303, callback.text
        new_users = _new_users(jit_harness.users_before)
        assert len(new_users) == 1
        user = new_users[0]
        assert user.role == "user"  # type: ignore[attr-defined]
        assert user.is_active is True  # type: ignore[attr-defined]
        # Only the configured permission, from only the matched group mapping.
        assert user.permissions == _JIT_PERMISSIONS[:1]  # type: ignore[attr-defined]
        assert user.username == "Ada Lovelace".replace(" ", "-")  # type: ignore[attr-defined]
        # The account authenticates through Entra only.
        assert user.password_hash == ENTRA_JIT_UNUSABLE_PASSWORD_HASH  # type: ignore[attr-defined]
        assert verify_password("any password", user.password_hash) is False  # type: ignore[attr-defined]
        # The identity is durably linked to the new account.
        link_record = stores.oauth_identity_links.get(_identity_link_key("entra", _ENTRA_SUBJECT))
        assert isinstance(link_record, dict)
        assert link_record["local_user_id"] == user.id  # type: ignore[attr-defined]
        # A session was issued for the provisioned account.
        assert len(set(stores.sessions.keys()) - sessions_before) == 1
        entries = _jit_audit_entries()
        assert len(entries) == 1
        detail = entries[0]["detail"]  # type: ignore[index]
        assert detail["reason"] == "provisioned"
        assert detail["policy_version"] == _POLICY_VERSION
        assert detail["matched_group_ids"] == [_GROUP_ELIGIBLE]
        assert detail["membership_source"] == "resolver"
        assert entries[0]["actor"] == user.id  # type: ignore[index]

    @pytest.mark.contract("boundary")
    def test_enabled_settings_build_the_real_graph_resolver_and_provision(
        self, jit_harness: JitHarness
    ) -> None:
        # None of the other boundary tests exercise `build_entra_jit_provisioner`:
        # they inject a stub resolver, so a builder that read the wrong settings
        # (or omitted the Graph resolver) would still pass. Rebuild the service
        # exactly as production does, from the validated Settings object.
        jit_harness.service = OAuthLoginService(
            get_settings(),
            http=jit_harness.http,
            link_store=jit_harness.links,
        )
        assert jit_harness.service._jit is not None
        assert jit_harness.service._jit.applies_to("entra") is True
        assert jit_harness.service._jit.applies_to("oidc") is False

        client = _client()
        callback = _login_once(jit_harness, client, code="real-builder-code")

        assert callback.status_code == 303, callback.text
        new_users = _new_users(jit_harness.users_before)
        assert len(new_users) == 1
        assert new_users[0].permissions == _JIT_PERMISSIONS[:1]  # type: ignore[attr-defined]
        entries = _jit_audit_entries()
        assert entries[0]["detail"]["membership_source"] == "resolver"  # type: ignore[index]

    @pytest.mark.contract("boundary")
    def test_a_second_login_reuses_the_provisioned_account(self, jit_harness: JitHarness) -> None:
        client = _client()
        assert _login_once(jit_harness, client, code="first-code").status_code == 303

        second = _login_once(jit_harness, client, code="second-code")

        assert second.status_code == 303
        assert len(_new_users(jit_harness.users_before)) == 1

    @pytest.mark.contract("boundary")
    def test_an_unknown_group_is_refused_without_an_account_or_link(
        self, jit_harness: JitHarness
    ) -> None:
        jit_harness.resolver.membership = EntraGroupMembership.complete_resolver([_GROUP_UNKNOWN])
        client = _client()
        sessions_before = set(stores.sessions.keys())

        callback = _login_once(jit_harness, client)

        assert callback.status_code == 401
        assert _new_users(jit_harness.users_before) == []
        assert stores.oauth_identity_links.get(_identity_link_key("entra", _ENTRA_SUBJECT)) is None
        assert set(stores.sessions.keys()) == sessions_before
        entries = _jit_audit_entries()
        assert len(entries) == 1
        assert entries[0]["detail"]["reason"] == "not_eligible"  # type: ignore[index]
        assert entries[0]["actor"] == _ENTRA_SUBJECT  # type: ignore[index]

    @pytest.mark.contract("boundary")
    def test_a_directory_outage_refuses_rather_than_guessing_membership(
        self, jit_harness: JitHarness
    ) -> None:
        jit_harness.resolver.failure = IncompleteGroupMembershipError("Graph down")
        client = _client()

        callback = _login_once(jit_harness, client)

        assert callback.status_code == 401
        assert _new_users(jit_harness.users_before) == []
        entries = _jit_audit_entries()
        assert entries[0]["detail"]["reason"] == "incomplete_membership"  # type: ignore[index]

    @pytest.mark.contract("boundary")
    def test_a_taken_username_fails_closed_and_audits(self, jit_harness: JitHarness) -> None:
        # Occupy the username the identity would derive ("Ada-Lovelace").
        occupied = stores.users._model_class(
            id="occupied-user",
            username="Ada-Lovelace",
            password_hash=ENTRA_JIT_UNUSABLE_PASSWORD_HASH,
            role="user",
            is_active=True,
            permissions=[],
            created_at=datetime.now(UTC),
        )
        from services import username_registry

        username_registry.create_users([occupied])
        try:
            client = _client()

            callback = _login_once(jit_harness, client)

            assert callback.status_code == 401
            assert _new_users(jit_harness.users_before) == [occupied]
            entries = _jit_audit_entries()
            assert entries[0]["detail"]["reason"] == "username_conflict"  # type: ignore[index]
        finally:
            username_registry.rollback_users([occupied])

    def test_jit_disabled_refuses_unlinked_identities_exactly_as_before(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OAUTH_PROVIDERS", json.dumps(_entra_provider_document()))
        monkeypatch.setenv("OAUTH_PUBLIC_ORIGIN", _PUBLIC_ORIGIN)
        monkeypatch.delenv("ENTRA_JIT_ENABLED", raising=False)
        get_settings.cache_clear()
        idp = FakeIdentityProvider()
        http = httpx.AsyncClient(transport=httpx.MockTransport(idp.handler))
        links = HiveIdentityLinkStore()
        service = OAuthLoginService(get_settings(), http=http, link_store=links)
        assert service._jit is None
        asyncio.run(http.aclose())
        get_settings.cache_clear()


class TestJitConfigurationIsFailClosed:
    def test_enabling_jit_requires_the_entra_provider(self) -> None:
        with pytest.raises(ValidationError, match="requires the provider named entra"):
            Settings(
                _env_file=None,
                oauth_providers={},
                entra_jit_enabled=True,
                entra_jit_policy_version=_POLICY_VERSION,
                entra_jit_groups=_jit_groups_document(),
            )

    def test_enabling_jit_requires_groups_and_a_policy_version(self) -> None:
        with pytest.raises(ValidationError, match="entra_jit_groups"):
            Settings(
                _env_file=None,
                oauth_providers=_entra_provider_document(),
                oauth_public_origin=_PUBLIC_ORIGIN,
                entra_jit_enabled=True,
                entra_jit_policy_version="",
                entra_jit_groups=_jit_groups_document(),
            )

    def test_group_keys_must_be_group_object_uuids(self) -> None:
        with pytest.raises(ValidationError, match="group object UUIDs"):
            Settings(
                _env_file=None,
                oauth_providers=_entra_provider_document(),
                oauth_public_origin=_PUBLIC_ORIGIN,
                entra_jit_enabled=True,
                entra_jit_policy_version=_POLICY_VERSION,
                entra_jit_groups={"MAIstro Users": {"role": "user", "permissions": []}},
            )

    def test_case_variant_duplicate_group_ids_are_refused(self) -> None:
        # A lettered UUID: an all-digit one uppercases to itself and cannot
        # express the case-variant collision being refused here.
        group = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        groups = {
            group: {"role": "user", "permissions": []},
            group.upper(): {"role": "user", "permissions": []},
        }
        with pytest.raises(ValidationError, match="duplicate Entra group object ID"):
            Settings(
                _env_file=None,
                oauth_providers=_entra_provider_document(),
                oauth_public_origin=_PUBLIC_ORIGIN,
                entra_jit_enabled=True,
                entra_jit_policy_version=_POLICY_VERSION,
                entra_jit_groups=groups,
            )

    def test_a_permission_outside_the_ceiling_fails_at_configuration_time(self) -> None:
        with pytest.raises(ValidationError, match="outside the configured SSO ceiling"):
            Settings(
                _env_file=None,
                oauth_providers=_entra_provider_document(),
                oauth_public_origin=_PUBLIC_ORIGIN,
                entra_jit_enabled=True,
                entra_jit_policy_version=_POLICY_VERSION,
                entra_jit_groups=_jit_groups_document(),
                entra_jit_allowed_permissions=("dags.write",),
            )

    def test_the_mapping_only_ever_provisions_the_user_role(self) -> None:
        with pytest.raises(EntraEntitlementPolicyError, match="only provision role 'user'"):
            jit_policy_from_config(
                enabled=True,
                policy_version=_POLICY_VERSION,
                groups={
                    _GROUP_ELIGIBLE: EntraGroupGrant("operator", frozenset({"runs:cancel"})),
                },
            )

    def test_permission_tokens_are_validated_where_declared(self) -> None:
        with pytest.raises(ValidationError, match="lowercase tokens"):
            Settings(
                _env_file=None,
                oauth_providers=_entra_provider_document(),
                oauth_public_origin=_PUBLIC_ORIGIN,
                entra_jit_enabled=True,
                entra_jit_policy_version=_POLICY_VERSION,
                entra_jit_groups={
                    _GROUP_ELIGIBLE: {"role": "user", "permissions": ["Not A Permission"]},
                },
            )


class TestGraphMembershipResolver:
    def _resolver(self, handler) -> GraphMembershipResolver:
        return GraphMembershipResolver(
            http=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )

    def test_groups_are_read_and_paged_from_graph(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            assert request.headers["Authorization"] == "Bearer token-1"
            if "$skiptoken" not in url:
                page = [
                    {"id": _GROUP_ELIGIBLE, "@odata.type": "#microsoft.graph.group"},
                    {
                        "id": "00000000-0000-0000-0000-000000000000",
                        "@odata.type": "#microsoft.graph.administrativeUnit",
                    },
                ]
                return httpx.Response(
                    200,
                    json={
                        "value": page,
                        "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/transitiveMemberOf?$skiptoken=2",
                    },
                )
            return httpx.Response(
                200,
                json={
                    "value": [
                        {"id": _GROUP_OTHER_ELIGIBLE, "@odata.type": "#microsoft.graph.group"}
                    ]
                },
            )

        membership = asyncio.run(self._resolver(handler).resolve("token-1"))

        assert membership.complete is True
        assert membership.source == "resolver"
        assert set(membership.group_ids) == {_GROUP_ELIGIBLE, _GROUP_OTHER_ELIGIBLE}

    def test_a_graph_error_is_incomplete_membership_never_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": {"code": "ServiceUnavailable"}})

        with pytest.raises(IncompleteGroupMembershipError, match="http 503"):
            asyncio.run(self._resolver(handler).resolve("token-1"))

    def test_malformed_payloads_are_incomplete_membership(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>gateway</html>")

        with pytest.raises(IncompleteGroupMembershipError):
            asyncio.run(self._resolver(handler).resolve("token-1"))

    def test_endless_pagination_is_refused(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "value": [],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/transitiveMemberOf?$skiptoken=loop",
                },
            )

        with pytest.raises(IncompleteGroupMembershipError, match="exceeded"):
            asyncio.run(self._resolver(handler).resolve("token-1"))


class TestUsernameDerivation:
    def test_display_name_is_sanitized_into_a_username(self) -> None:
        identity = OAuthIdentity(provider="entra", sub=_ENTRA_SUBJECT, display_name="Ada Lovelace")
        assert _candidate_username(identity) == "Ada-Lovelace"

    def test_email_local_part_is_the_second_choice(self) -> None:
        identity = OAuthIdentity(
            provider="entra", sub=_ENTRA_SUBJECT, email="grace.hopper@example.test"
        )
        assert _candidate_username(identity) == "grace.hopper"

    def test_the_immutable_object_id_is_the_failover(self) -> None:
        identity = OAuthIdentity(provider="entra", sub=f"{_ENTRA_TENANT}:{_ENTRA_OID}")
        assert _candidate_username(identity) == f"entra-{_ENTRA_OID}"


class TestConcurrentLinkRace:
    @pytest.mark.asyncio
    async def test_a_lost_link_race_rolls_back_and_keeps_the_canonical_account(
        self, jit_harness: JitHarness
    ) -> None:
        from services.oauth_login import IdentityLinkConflictError

        canonical = stores.users._model_class(
            id="canonical-user",
            username="canonical",
            password_hash=ENTRA_JIT_UNUSABLE_PASSWORD_HASH,
            role="user",
            is_active=True,
            permissions=[],
            created_at=datetime.now(UTC),
        )
        stores.users["canonical-user"] = canonical
        try:
            original_link = jit_harness.links.link

            async def losing_link(provider: str, sub: str, user_id: str) -> None:
                # First writer won between our resolve and our link attempt.
                await original_link(provider, sub, canonical.id)
                raise IdentityLinkConflictError("identity is already linked")

            jit_harness.links.link = losing_link  # type: ignore[method-assign]
            provisioner = EntraJitProvisioner(
                _policy(),  # type: ignore[arg-type]
                jit_harness.resolver,  # type: ignore[arg-type]
                links=jit_harness.links,
            )
            exchange = OAuthExchange(
                identity=OAuthIdentity(
                    provider="entra", sub=_ENTRA_SUBJECT, display_name="Race Runner"
                ),
                token=OAuthToken(access_token="jit-access-token", token_type="Bearer"),
            )

            user = await provisioner.provision(exchange.identity, exchange)

            assert user is not None and user.id == canonical.id
            reasons = [
                entry["detail"]["reason"]  # type: ignore[index]
                for entry in _jit_audit_entries()
            ]
            assert "superseded_by_existing_link" in reasons
            # The duplicate allocation was rolled back, not orphaned.
            leftover = [
                u
                for u in stores.users.values()
                if u.username == "Race-Runner"  # type: ignore[attr-defined]
            ]
            assert leftover == []
        finally:
            stores.users.pop("canonical-user", None)

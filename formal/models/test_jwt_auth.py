"""I24: JWT Auth Provider — Hypothesis property-based tests."""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from maistro.security._types import AuthContext, IdentityKind
from maistro.security.auth_composite import AuthError, CredentialNotApplicable
from maistro.security.auth_jwt import JWTAuthProvider


def _make_provider(claims=None, kind_claim="kind"):
    base = {"sub": "user123", "preferred_username": "alice", "realm_access": {"roles": ["admin", "user"]}}
    if claims:
        base.update(claims)
    # The jwt_decode test seam is forbidden when a jwks_url is configured
    # (production config); the model must use the seam-only configuration.
    return JWTAuthProvider(
        jwks_url="",
        issuer="test",
        audience="test",
        kind_claim=kind_claim,
        jwt_decode=lambda token: base,
    )


# Fix #13 exception taxonomy: malformed/inapplicable credentials raise
# CredentialNotApplicable (composite chain tries the next provider);
# recognized-but-invalid credentials raise AuthError (chain aborts).


def test_missing_authorization_raises():
    provider = _make_provider()
    try:
        asyncio.run(provider.authenticate(None))
        raise AssertionError("Expected CredentialNotApplicable")
    except CredentialNotApplicable:
        pass


def test_non_bearer_raises():
    provider = _make_provider()
    try:
        asyncio.run(provider.authenticate("Basic abc123"))
        raise AssertionError("Expected CredentialNotApplicable")
    except CredentialNotApplicable:
        pass


def test_empty_token_raises():
    provider = _make_provider()
    try:
        asyncio.run(provider.authenticate("Bearer  "))
        raise AssertionError("Expected CredentialNotApplicable")
    except CredentialNotApplicable:
        pass


def test_missing_sub_raises():
    provider = _make_provider(claims={"sub": ""})
    try:
        asyncio.run(provider.authenticate("Bearer token"))
        raise AssertionError("Expected AuthError")
    except AuthError:
        pass


def test_valid_claims_return_auth_context():
    provider = _make_provider()
    ctx = asyncio.run(provider.authenticate("Bearer some.jwt.token"))
    assert isinstance(ctx, AuthContext)
    assert ctx.user_id == "user123"
    assert ctx.username == "alice"
    assert "admin" in ctx.roles
    assert "user" in ctx.roles
    assert ctx.auth_method == "jwt"


def test_dot_path_extraction():
    result = JWTAuthProvider._extract_nested({"a": {"b": {"c": "deep"}}}, "a.b.c")
    assert result == "deep"


def test_dot_path_top_level():
    result = JWTAuthProvider._extract_nested({"top": "val"}, "top")
    assert result == "val"


def test_dot_path_missing():
    result = JWTAuthProvider._extract_nested({"a": 1}, "x.y.z")
    assert result is None


def test_kind_service_account():
    provider = _make_provider(claims={"sub": "svc1", "kind": "service_account"})
    ctx = asyncio.run(provider.authenticate("Bearer t"))
    assert ctx.kind == IdentityKind.SERVICE_ACCOUNT


def test_kind_default_is_user():
    provider = _make_provider()
    ctx = asyncio.run(provider.authenticate("Bearer t"))
    assert ctx.kind == IdentityKind.USER


def test_role_extraction_from_list():
    provider = _make_provider(claims={"sub": "u", "realm_access": {"roles": ["r1", "r2"]}})
    ctx = asyncio.run(provider.authenticate("Bearer t"))
    assert ctx.roles == frozenset({"r1", "r2"})


def test_role_extraction_from_string():
    provider = _make_provider(claims={"sub": "u", "realm_access": {"roles": "single_role"}})
    provider._role_claim = "realm_access.roles"
    ctx = asyncio.run(provider.authenticate("Bearer t"))
    assert "single_role" in ctx.roles


def test_interactive_agent_kind_mapped():
    claims = {
        "sub": "agent1",
        "kind": "interactive_agent",
        "on_behalf_of": "real_user_42",
    }
    provider = _make_provider(claims=claims, kind_claim="kind")
    provider._role_claim = "realm_access.roles"
    ctx = asyncio.run(provider.authenticate("Bearer t"))
    assert ctx.kind == IdentityKind.INTERACTIVE_AGENT
    assert ctx.on_behalf_of == "real_user_42"


def test_service_account_kind_mapped():
    claims = {"sub": "svc1", "kind": "service_account", "on_behalf_of": "real_user"}
    provider = _make_provider(claims=claims, kind_claim="kind")
    provider._role_claim = "realm_access.roles"
    ctx = asyncio.run(provider.authenticate("Bearer t"))
    assert ctx.kind == IdentityKind.SERVICE_ACCOUNT
    assert ctx.on_behalf_of == ""


def test_on_behalf_of_empty_when_not_interactive():
    provider = _make_provider(claims={"sub": "u", "kind": "user"})
    ctx = asyncio.run(provider.authenticate("Bearer t"))
    assert ctx.on_behalf_of == ""


def test_interactive_agent_without_obo_claim():
    claims = {
        "sub": "agent1",
        "kind": "interactive_agent",
    }
    provider = _make_provider(claims=claims, kind_claim="kind")
    ctx = asyncio.run(provider.authenticate("Bearer t"))
    assert ctx.kind == IdentityKind.INTERACTIVE_AGENT
    assert ctx.on_behalf_of == ""


def test_interactive_agent_obo_preserved_exact():
    claims = {
        "sub": "agent_x",
        "kind": "interactive_agent",
        "on_behalf_of": "user-alice@example.com",
    }
    provider = _make_provider(claims=claims, kind_claim="kind")
    ctx = asyncio.run(provider.authenticate("Bearer t"))
    assert ctx.on_behalf_of == "user-alice@example.com"


def test_obo_delegation_chain_visible():
    claims = {
        "sub": "agent_scheduler",
        "preferred_username": "scheduler-bot",
        "kind": "interactive_agent",
        "on_behalf_of": "user_bob",
        "realm_access": {"roles": ["agent", "scheduler"]},
    }
    provider = _make_provider(claims=claims, kind_claim="kind")
    ctx = asyncio.run(provider.authenticate("Bearer t"))
    assert ctx.kind == IdentityKind.INTERACTIVE_AGENT
    assert ctx.user_id == "agent_scheduler"
    assert ctx.on_behalf_of == "user_bob"
    assert "agent" in ctx.roles
    assert "scheduler" in ctx.roles
    assert ctx.auth_method == "jwt"


@given(username=st.text(min_size=1, max_size=30))
@settings(max_examples=20)
def test_username_reflects_claim(username):
    provider = _make_provider(claims={"sub": "u", "preferred_username": username})
    ctx = asyncio.run(provider.authenticate("Bearer t"))
    assert ctx.username == username


@given(user_id=st.text(min_size=1, max_size=30))
@settings(max_examples=20)
def test_user_id_reflects_sub(user_id):
    provider = _make_provider(claims={"sub": user_id})
    ctx = asyncio.run(provider.authenticate("Bearer t"))
    assert ctx.user_id == user_id

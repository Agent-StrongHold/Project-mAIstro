"""I25: Static API Key + OpenWebUI Headers — Hypothesis property-based tests."""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from maistro.security._types import SYSTEM_AUTH, IdentityKind
from maistro.security.auth_static import StaticKeyAuthProvider


API_KEY = "sk-test-secret-key-abc123"


_ASCII = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


class StaticKeyMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.provider = StaticKeyAuthProvider(API_KEY)
        self.provider_ro = StaticKeyAuthProvider(API_KEY, read_only=True)

    @rule(
        token=st.text(min_size=0, max_size=40, alphabet=st.sampled_from(_ASCII)),
    )
    def try_authenticate(self, token):
        try:
            asyncio.run(self.provider.authenticate(f"Bearer {token}", headers={}))
            assert token == API_KEY
        except ValueError:
            assert token != API_KEY

    @invariant()
    def system_auth_on_correct_key(self):
        ctx = asyncio.run(self.provider.authenticate(f"Bearer {API_KEY}"))
        assert ctx.user_id == SYSTEM_AUTH.user_id
        assert ctx.kind == IdentityKind.SYSTEM

    @invariant()
    def read_only_has_user_role_only(self):
        ctx = asyncio.run(self.provider_ro.authenticate(f"Bearer {API_KEY}"))
        assert ctx.roles == frozenset({"user"})

    @invariant()
    def wrong_key_always_fails(self):
        try:
            asyncio.run(self.provider.authenticate("Bearer wrong-key"))
            raise AssertionError("Expected ValueError")
        except ValueError:
            pass


TestStaticKeyMachine = StaticKeyMachine.TestCase


def test_correct_key_returns_system_auth():
    provider = StaticKeyAuthProvider(API_KEY)
    ctx = asyncio.run(provider.authenticate(f"Bearer {API_KEY}"))
    assert ctx.user_id == "system"
    assert ctx.kind == IdentityKind.SYSTEM


def test_correct_key_read_only():
    provider = StaticKeyAuthProvider(API_KEY, read_only=True)
    ctx = asyncio.run(provider.authenticate(f"Bearer {API_KEY}"))
    assert ctx.roles == frozenset({"user"})


def test_wrong_key_raises():
    provider = StaticKeyAuthProvider(API_KEY)
    try:
        asyncio.run(provider.authenticate("Bearer wrong-key"))
        raise AssertionError("Expected ValueError")
    except ValueError:
        pass


def test_missing_authorization_raises():
    provider = StaticKeyAuthProvider(API_KEY)
    try:
        asyncio.run(provider.authenticate(None))
        raise AssertionError("Expected ValueError")
    except ValueError:
        pass


def test_non_bearer_raises():
    provider = StaticKeyAuthProvider(API_KEY)
    try:
        asyncio.run(provider.authenticate("Basic abc123"))
        raise AssertionError("Expected ValueError")
    except ValueError:
        pass


def test_owui_headers_are_ignored():
    """Fix #11: X-OpenWebUI-* headers are attacker-controlled and MUST NOT
    become the authenticated identity. Static key auth always returns the
    system identity regardless of headers."""
    provider = StaticKeyAuthProvider(API_KEY)
    headers = {
        "x-openwebui-user-id": "owui-user-42",
        "x-openwebui-user-email": "alice@test.com",
        "x-openwebui-user-name": "Alice",
    }
    ctx = asyncio.run(provider.authenticate(f"Bearer {API_KEY}", headers=headers))
    assert ctx.user_id == "system"
    assert ctx.kind == IdentityKind.SYSTEM
    assert "owui" not in ctx.user_id
    assert ctx.username != "Alice"


def test_owui_email_does_not_become_user_id():
    provider = StaticKeyAuthProvider(API_KEY)
    headers = {
        "x-openwebui-user-email": "bob@test.com",
        "x-openwebui-user-name": "Bob",
    }
    ctx = asyncio.run(provider.authenticate(f"Bearer {API_KEY}", headers=headers))
    assert ctx.user_id == "system"


def test_owui_auth_method_not_header_derived():
    provider = StaticKeyAuthProvider(API_KEY)
    headers = {"x-openwebui-user-id": "uid1", "x-openwebui-user-email": "e@e.com"}
    ctx = asyncio.run(provider.authenticate(f"Bearer {API_KEY}", headers=headers))
    assert ctx.auth_method != "openwebui_header"
    assert ctx == SYSTEM_AUTH


def test_empty_key_matches_empty_bearer():
    provider = StaticKeyAuthProvider("")
    ctx = asyncio.run(provider.authenticate("Bearer "))
    assert ctx.user_id == "system"


@given(key=st.text(min_size=1, max_size=40, alphabet=st.sampled_from(_ASCII)))
@settings(max_examples=30)
def test_only_correct_key_passes(key):
    provider = StaticKeyAuthProvider(API_KEY)
    if key == API_KEY:
        ctx = asyncio.run(provider.authenticate(f"Bearer {key}"))
        assert ctx.user_id == "system"
    else:
        try:
            asyncio.run(provider.authenticate(f"Bearer {key}"))
            raise AssertionError("Expected ValueError")
        except ValueError:
            pass

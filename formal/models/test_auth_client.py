"""I28: Service Key Client Headers — Hypothesis property-based tests."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from maistro.auth._types import Scope, ServiceIdentity
from maistro.auth.client import ServiceKeyClient


def _make_identity(scopes=None):
    return ServiceIdentity(
        name="test-service",
        key_hash="abc123hash",
        scopes=frozenset(scopes) if scopes else frozenset({Scope.CHAT_COMPLETIONS, Scope.MEMORY_READ}),
    )


class ServiceKeyClientMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.identity = _make_identity()
        self.client = ServiceKeyClient(identity=self.identity, key="sk-test-key-123")

    @rule(
        extra_key=st.text(min_size=1, max_size=20),
        extra_val=st.text(min_size=1, max_size=20),
    )
    def merge_extra_headers(self, extra_key, extra_val):
        merged = self.client._merge_headers({extra_key: extra_val})
        assert merged[extra_key] == extra_val
        assert "X-Service-Key" in merged

    @rule(stub=st.none())
    def merge_without_extra(self, stub):
        merged = self.client._merge_headers()
        assert "X-Service-Key" in merged
        assert "X-Service-Name" in merged
        assert "X-Service-Scopes" in merged

    @invariant()
    def base_headers_contain_key(self):
        assert self.client._base_headers["X-Service-Key"] == "sk-test-key-123"

    @invariant()
    def base_headers_contain_name(self):
        assert self.client._base_headers["X-Service-Name"] == "test-service"

    @invariant()
    def base_headers_contain_scopes(self):
        scopes_header = self.client._base_headers["X-Service-Scopes"]
        assert "llm:chat_completions" in scopes_header

    @invariant()
    def identity_property(self):
        assert self.client.identity is self.identity


TestServiceKeyClientMachine = ServiceKeyClientMachine.TestCase


def test_base_headers_contain_service_key():
    client = ServiceKeyClient(identity=_make_identity(), key="sk-abc")
    assert client._base_headers["X-Service-Key"] == "sk-abc"


def test_base_headers_contain_service_name():
    client = ServiceKeyClient(identity=_make_identity(), key="sk-abc")
    assert client._base_headers["X-Service-Name"] == "test-service"


def test_base_headers_contain_scopes():
    scopes = frozenset({Scope.CHAT_COMPLETIONS, Scope.MEMORY_READ})
    client = ServiceKeyClient(identity=_make_identity(scopes=scopes), key="sk-abc")
    scopes_header = client._base_headers["X-Service-Scopes"]
    assert "llm:chat_completions" in scopes_header
    assert "memory:read" in scopes_header


def test_merge_headers_with_extra():
    client = ServiceKeyClient(identity=_make_identity(), key="sk-abc")
    merged = client._merge_headers({"X-Custom": "val"})
    assert merged["X-Custom"] == "val"
    assert merged["X-Service-Key"] == "sk-abc"


def test_merge_headers_without_extra():
    client = ServiceKeyClient(identity=_make_identity(), key="sk-abc")
    merged = client._merge_headers()
    assert "X-Service-Key" in merged


def test_merge_headers_returns_copy():
    client = ServiceKeyClient(identity=_make_identity(), key="sk-abc")
    m1 = client._merge_headers()
    m1["extra"] = "added"
    m2 = client._merge_headers()
    assert "extra" not in m2


def test_identity_property():
    identity = _make_identity()
    client = ServiceKeyClient(identity=identity, key="sk-abc")
    assert client.identity is identity
    assert client.identity.name == "test-service"


def test_extra_headers_override_base():
    client = ServiceKeyClient(identity=_make_identity(), key="sk-abc")
    merged = client._merge_headers({"X-Service-Key": "overridden"})
    assert merged["X-Service-Key"] == "overridden"


@given(
    key=st.text(min_size=1, max_size=30),
    name=st.text(min_size=1, max_size=30),
)
@settings(max_examples=20)
def test_key_and_name_reflect_in_headers(key, name):
    identity = ServiceIdentity(name=name, key_hash="h", scopes=frozenset())
    client = ServiceKeyClient(identity=identity, key=key)
    assert client._base_headers["X-Service-Key"] == key
    assert client._base_headers["X-Service-Name"] == name


@given(scopes=st.sets(st.sampled_from(Scope), min_size=1, max_size=5))
@settings(max_examples=20)
def test_scopes_in_header(scopes):
    identity = ServiceIdentity(name="svc", key_hash="h", scopes=frozenset(scopes))
    client = ServiceKeyClient(identity=identity, key="k")
    header = client._base_headers["X-Service-Scopes"]
    for s in scopes:
        assert s.value in header

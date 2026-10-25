"""I14: Auth Provider — Service Key Authentication — Hypothesis property-based tests."""

from __future__ import annotations

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from maistro.auth.provider import ServiceKeyAuthProvider
from maistro.auth.registry import ServiceKeyRegistry


def _make_registry(key="sk-svc-test-key-123", scopes=("llm:*",)):
    reg = ServiceKeyRegistry()
    reg.load_dict(
        {
            "test-service": {"key": key, "scopes": list(scopes)},
        }
    )
    return reg


class AuthProviderMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.key = "sk-svc-machine-key-abc"
        self.registry = _make_registry(key=self.key)
        self.provider = ServiceKeyAuthProvider(self.registry)
        self.authentications = 0
        self.failures = 0

    @rule(
        key_suffix=st.text(min_size=0, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))),
    )
    def try_x_service_key(self, key_suffix):
        headers = {"x-service-key": key_suffix}
        identity = self.provider.authenticate(headers)
        self.authentications += 1
        if identity is not None:
            assert identity.name == "test-service"
        else:
            self.failures += 1

    @rule(
        token=st.text(min_size=0, max_size=30, alphabet=st.characters(whitelist_categories=("L", "N", "P"))),
    )
    def try_bearer(self, token):
        headers = {"authorization": f"Bearer {token}"}
        identity = self.provider.authenticate(headers)
        self.authentications += 1
        if identity is not None:
            assert identity.name == "test-service"

    @invariant()
    def failures_dont_exceed_attempts(self):
        assert self.failures <= self.authentications


TestAuthProviderMachine = AuthProviderMachine.TestCase


def test_valid_x_service_key():
    reg = _make_registry(key="my-secret-key")
    provider = ServiceKeyAuthProvider(reg)
    identity = provider.authenticate({"x-service-key": "my-secret-key"})
    assert identity is not None
    assert identity.name == "test-service"


def test_valid_bearer_sk_svc():
    reg = _make_registry(key="sk-svc-my-token-abc123")
    provider = ServiceKeyAuthProvider(reg)
    identity = provider.authenticate({"authorization": "Bearer sk-svc-my-token-abc123"})
    assert identity is not None
    assert identity.name == "test-service"


def test_invalid_key_returns_none():
    reg = _make_registry(key="correct-key")
    provider = ServiceKeyAuthProvider(reg)
    identity = provider.authenticate({"x-service-key": "wrong-key"})
    assert identity is None


def test_missing_key_returns_none():
    reg = _make_registry(key="some-key")
    provider = ServiceKeyAuthProvider(reg)
    identity = provider.authenticate({})
    assert identity is None


def test_bearer_without_sk_svc_prefix():
    reg = _make_registry(key="some-key")
    provider = ServiceKeyAuthProvider(reg)
    identity = provider.authenticate({"authorization": "Bearer regular-token-no-prefix"})
    assert identity is None


def test_case_sensitive_key():
    reg = _make_registry(key="MySecretKey123")
    provider = ServiceKeyAuthProvider(reg)
    assert provider.authenticate({"x-service-key": "MySecretKey123"}) is not None
    assert provider.authenticate({"x-service-key": "mysecretkey123"}) is None


@given(
    key=st.text(min_size=8, max_size=40, alphabet=st.characters(whitelist_categories=("L", "N"))),
)
@settings(max_examples=50)
def test_exact_key_match(key):
    reg = _make_registry(key=key)
    provider = ServiceKeyAuthProvider(reg)
    identity = provider.authenticate({"x-service-key": key})
    assert identity is not None


@given(
    key=st.text(min_size=8, max_size=40, alphabet=st.characters(whitelist_categories=("L", "N"))),
    wrong=st.text(min_size=8, max_size=40, alphabet=st.characters(whitelist_categories=("L", "N"))),
)
@settings(max_examples=50)
def test_wrong_key_rejected(key, wrong):
    assume(key != wrong)
    reg = _make_registry(key=key)
    provider = ServiceKeyAuthProvider(reg)
    identity = provider.authenticate({"x-service-key": wrong})
    assert identity is None


@given(
    key=st.text(min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("L", "N"))),
)
@settings(max_examples=30)
def test_empty_headers_returns_none(key):
    reg = _make_registry(key=key)
    provider = ServiceKeyAuthProvider(reg)
    assert provider.authenticate({}) is None


@given(
    key=st.text(min_size=8, max_size=40, alphabet=st.characters(whitelist_categories=("L", "N"))),
)
@settings(max_examples=30)
def test_bearer_sk_svc_prefix_accepted(key):
    svc_key = f"sk-svc-{key}"
    reg = _make_registry(key=svc_key)
    provider = ServiceKeyAuthProvider(reg)
    identity = provider.authenticate({"authorization": f"Bearer {svc_key}"})
    assert identity is not None


def test_x_service_key_takes_priority():
    reg = _make_registry(key="key-x")
    provider = ServiceKeyAuthProvider(reg)
    identity = provider.authenticate(
        {
            "x-service-key": "key-x",
            "authorization": "Bearer sk-svc-other",
        }
    )
    assert identity is not None
    assert identity.name == "test-service"

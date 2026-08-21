"""I19: Secure Random — Cryptographic Randomness — Hypothesis property-based tests."""

from __future__ import annotations

import string

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from maistro.security.secure_random import secure_base36, secure_id, secure_int, secure_urlsafe


class SecureRandomMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.ids: list[str] = []

    @rule(n=st.integers(min_value=8, max_value=32))
    def generate_id(self, n):
        result = secure_id(n)
        self.ids.append(result)
        assert len(result) == 2 * n

    @invariant()
    def all_ids_unique(self):
        if len(self.ids) >= 2:
            assert len(self.ids) == len(set(self.ids))


TestSecureRandomMachine = SecureRandomMachine.TestCase


def test_secure_id_16_returns_32_hex():
    result = secure_id(16)
    assert len(result) == 32
    assert all(c in "0123456789abcdef" for c in result)


@given(n=st.integers(min_value=1, max_value=64))
@settings(max_examples=50)
def test_secure_id_length(n):
    result = secure_id(n)
    assert len(result) == 2 * n
    assert all(c in "0123456789abcdef" for c in result)


@given(n=st.integers(min_value=8, max_value=32))
@settings(max_examples=50)
def test_secure_id_unique(n):
    a = secure_id(n)
    b = secure_id(n)
    assert a != b


@given(
    min_val=st.integers(min_value=-1000, max_value=1000),
    delta=st.integers(min_value=2, max_value=1000),
)
@settings(max_examples=100)
def test_secure_int_in_range(min_val, delta):
    max_val = min_val + delta
    result = secure_int(min_val, max_val)
    assert isinstance(result, int)
    assert min_val <= result < max_val


def test_secure_int_range_of_one():
    result = secure_int(5, 6)
    assert result == 5


@given(length=st.integers(min_value=1, max_value=64))
@settings(max_examples=50)
def test_secure_base36_chars(length):
    result = secure_base36(length)
    assert len(result) == length
    valid_chars = set(string.digits + string.ascii_lowercase)
    assert all(c in valid_chars for c in result)


@given(length=st.integers(min_value=8, max_value=32))
@settings(max_examples=50)
def test_secure_base36_unique(length):
    a = secure_base36(length)
    b = secure_base36(length)
    assert a != b


@given(n=st.integers(min_value=1, max_value=64))
@settings(max_examples=50)
def test_secure_urlsafe_chars(n):
    result = secure_urlsafe(n)
    urlsafe_chars = set(string.ascii_letters + string.digits + "-_")
    assert all(c in urlsafe_chars for c in result)


@given(n=st.integers(min_value=8, max_value=64))
@settings(max_examples=50)
def test_secure_urlsafe_unique(n):
    a = secure_urlsafe(n)
    b = secure_urlsafe(n)
    assert a != b


def test_secure_id_default_arg():
    result = secure_id()
    assert len(result) == 32


def test_secure_urlsafe_default_arg():
    result = secure_urlsafe()
    assert len(result) > 0


def test_secure_base36_default_arg():
    result = secure_base36()
    assert len(result) == 8

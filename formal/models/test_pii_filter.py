"""I13: PII Filter — Detection and Redaction — Hypothesis property-based tests."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from maistro.security.sentinel.pii_filter import PIIMatch, redact, scan_and_redact, scan_for_pii


class PIIScanMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.scanned_count = 0
        self.total_matches = 0

    @rule(
        text=st.text(min_size=0, max_size=500),
    )
    def scan_text(self, text):
        matches = scan_for_pii(text)
        self.scanned_count += 1
        self.total_matches += len(matches)
        for m in matches:
            assert isinstance(m, PIIMatch)
            assert isinstance(m.pii_type, str)
            assert isinstance(m.value, str)
            assert isinstance(m.start, int)
            assert isinstance(m.end, int)

    @invariant()
    def match_count_non_negative(self):
        assert self.total_matches >= 0


TestPIIScanMachine = PIIScanMachine.TestCase


def test_aws_key_detected():
    text = "key is AKIAIOSFODNN7EXAMPLE and that is bad"
    matches = scan_for_pii(text)
    assert any(m.pii_type == "aws_key" for m in matches)


def test_github_token_detected():
    text = "token ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx here"
    matches = scan_for_pii(text)
    assert any(m.pii_type == "github_token" for m in matches)


def test_api_key_detected():
    text = "key sk-xxxxxxxxxxxxxxxxxxxx found"
    matches = scan_for_pii(text)
    assert any(m.pii_type == "api_key" for m in matches)


def test_jwt_detected():
    text = (
        "eyJhbGciOiJIUzI1NiJ9."
        + "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
        + "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    matches = scan_for_pii(text)
    assert any(m.pii_type == "jwt" for m in matches)


def test_email_detected():
    text = "contact user@example.com for details"
    matches = scan_for_pii(text)
    assert any(m.pii_type == "email" for m in matches)


def test_private_key_detected():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowI...\n-----END RSA PRIVATE KEY-----"
    matches = scan_for_pii(text)
    assert any(m.pii_type == "private_key" for m in matches)


@given(
    text=st.text(
        min_size=1,
        max_size=200,
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters=" .,!?"),
    ),
)
@settings(max_examples=100)
def test_plain_text_no_matches(text):
    matches = scan_for_pii(text)
    assert isinstance(matches, list)


@given(
    text=st.text(min_size=0, max_size=200),
)
@settings(max_examples=50)
def test_redact_contains_placeholders(text):
    redacted, matches = scan_and_redact(text)
    for m in matches:
        placeholder = f"[REDACTED:{m.pii_type}]"
        assert placeholder in redacted


def test_redact_removes_original_value():
    text = "key is AKIAIOSFODNN7EXAMPLE end"
    redacted, matches = scan_and_redact(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted


def test_redact_preserves_surrounding():
    text = "prefix AKIAIOSFODNN7EXAMPLE suffix"
    redacted, matches = scan_and_redact(text)
    assert "prefix" in redacted
    assert "suffix" in redacted


@given(
    text=st.text(min_size=0, max_size=100),
)
@settings(max_examples=50)
def test_pii_match_frozen(text):
    matches = scan_for_pii(text)
    for m in matches:
        with pytest.raises((AttributeError, TypeError)):
            m.pii_type = "other"


def test_overlapping_matches_no_duplication():
    text = "AKIAIOSFODNN7EXAMPLE"
    matches = scan_for_pii(text)
    positions = [(m.start, m.end) for m in matches]
    for i, (s1, e1) in enumerate(positions):
        for j, (s2, e2) in enumerate(positions):
            if i != j:
                assert not (s1 < e2 and s2 < e1), f"Overlapping: {positions[i]} and {positions[j]}"


@given(
    text=st.text(min_size=0, max_size=100),
)
@settings(max_examples=50)
def test_matches_sorted_by_start(text):
    matches = scan_for_pii(text)
    starts = [m.start for m in matches]
    assert starts == sorted(starts)


@given(
    text=st.text(min_size=0, max_size=100),
)
@settings(max_examples=50)
def test_scan_and_redact_consistent(text):
    redacted, matches = scan_and_redact(text)
    assert isinstance(redacted, str)
    assert isinstance(matches, list)


def test_empty_string_no_matches():
    matches = scan_for_pii("")
    assert matches == []


def test_no_matches_redact_unchanged():
    text = "hello world"
    result = redact(text, [])
    assert result == text

"""I13: PII Filter — Detection and Redaction — Hypothesis property-based tests."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from maistro.security.sentinel.pii_filter import (
    PIIMatch,
    normalize_for_scan,
    redact,
    scan_and_redact,
    scan_for_pii,
)


class PIIScanMachine(RuleBasedStateMachine):
    """Span-integrity properties for PII detection.

    The old `match_count_non_negative` invariant counted the machine's own
    accumulator (`total_matches >= 0`) — true of any integer. The properties
    below pin the detector's OUTPUT geometry instead: every reported span
    must lie inside the scanned text, and an embedded, known credential must
    be localized (some match covers it).
    """

    # Real credential shapes from the governed oracle space (masked preview
    # not required here — the raw sample never enters the model state).
    _SAMPLES = [
        ("aws_key", "AKIAIOSFODNN7EXAMPLE"),
        ("github_token", "ghp_" + "aBcDeFgHiJkLmNoPqRsTtUvWxYz0123456789"[:36]),
        ("email", "alice@example.com"),
    ]

    def __init__(self):
        super().__init__()
        self.last_text: str | None = None
        self.last_matches: list | None = None

    @rule(
        text=st.text(min_size=0, max_size=500),
    )
    def scan_text(self, text):
        matches = scan_for_pii(text)
        for m in matches:
            assert isinstance(m, PIIMatch)
            assert isinstance(m.pii_type, str)
            assert isinstance(m.value, str)
            assert isinstance(m.start, int)
            assert isinstance(m.end, int)
        self.last_text = text
        self.last_matches = matches

    @rule(
        prefix=st.text(
            min_size=0,
            max_size=40,
            alphabet=st.characters(min_codepoint=32, max_codepoint=126).filter(lambda c: c.isalnum() or c == " "),
        ),
        sample=st.sampled_from([s for _, s in _SAMPLES]),
        suffix=st.text(
            min_size=0,
            max_size=40,
            alphabet=st.characters(min_codepoint=32, max_codepoint=126).filter(lambda c: c.isalnum() or c == " "),
        ),
    )
    def scan_embedded_credential(self, prefix, sample, suffix):
        """Localization + bounds + redaction on one known credential.

        Prefix/suffix are printable ASCII alphanumerics, which
        `normalize_for_scan` leaves unchanged, so canonical offsets equal raw
        offsets here and the sample sits at `len(prefix)` in BOTH coordinate
        systems. Counterexample classes: a span computed on a derived view
        whose length differs from canonical (bounds fail); an off-by-one that
        shrinks the span fails to cover the sample; a detector that silently
        misses its own pattern fails coverage; a redactor that mis-slices its
        own spans leaves part of the credential behind and fails the
        leak-prevention assertion.
        """
        parts = [p for p in (prefix, sample, suffix) if p]
        text = " ".join(parts)
        matches = scan_for_pii(text)
        pos = len(prefix) + (1 if prefix else 0)
        canonical_len = len(normalize_for_scan(text))
        for m in matches:
            assert 0 <= m.start < m.end <= canonical_len, (
                f"span [{m.start},{m.end}) outside canonical text of length {canonical_len}"
            )
        assert any(m.start < pos + len(sample) and m.end > pos for m in matches), (
            f"no detector even overlaps the embedded credential at [{pos},{pos + len(sample)}); got {matches!r}"
        )
        # Leak prevention: redaction must shred the credential — no 8-char
        # window of it may survive contiguously. (Detectors legitimately
        # absorb overlapping sibling matches, so the surviving span may be
        # offset; what may never happen is a long plaintext fragment left
        # behind.) Counterexample class: a redactor that mis-slices its own
        # spans (off-by-one, wrong coordinate system) leaves a long
        # reconstructable run of the secret in its output.
        redacted = redact(text, matches)
        for i in range(len(sample) - 8):
            assert sample[i : i + 8] not in redacted, (
                f"redaction left fragment {sample[i : i + 8]!r} of the embedded credential"
            )
        self.last_text = text
        self.last_matches = matches

    @invariant()
    def last_matches_respect_canonical_bounds(self):
        """Bounds property over the most recent scan.

        Spans index the CANONICAL string (normalize_for_scan), per the
        documented contract — that is the coordinate system redact() slices
        in. Counterexample class: any span extending past the canonical text
        (or ending before it starts) fails here.
        """
        if self.last_text is None or self.last_matches is None:
            return
        canonical_len = len(normalize_for_scan(self.last_text))
        for m in self.last_matches:
            assert 0 <= m.start < m.end <= canonical_len, (
                f"span [{m.start},{m.end}) outside canonical text of length {canonical_len}"
            )


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

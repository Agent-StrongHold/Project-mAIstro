# ruff: noqa: RUF001 — confusable Unicode literals are test fixtures

"""Acceptance coverage for normalized PII/secret detection on product paths."""

from __future__ import annotations

import base64
import unicodedata
from urllib.parse import quote, quote_plus

import pytest

from maistro.agents.strategies.direct import DirectStrategy
from maistro.agents.strategies.react import ReactStrategy
from maistro.security._types import AuthContext, WardenVerdict
from maistro.security.sentinel.pii_filter import scan_and_redact, scan_for_pii
from maistro.security.sentinel.policy import Sentinel
from maistro.testing.faux_provider import FauxProvider, FauxResponse


class _CleanWarden:
    async def scan(self, text: str, boundary: str) -> WardenVerdict:
        return WardenVerdict(clean=True)


@pytest.mark.ac("SPEC-082126-3c9d/AC-1")
def test_canonical_normalization_catches_compatibility_and_zero_width_evasion() -> None:
    fullwidth = "ＡＫＩＡＩＯＳＦＯＤＮＮ７ＥＸＡＭＰＬＥ"
    zero_width = "AKIA\u200bIOSF\u200bODNN\u200b7EXAMPLE"

    for value in (fullwidth, zero_width):
        redacted, matches = scan_and_redact(f"key={value}")
        assert any(match.pii_type == "aws_key" for match in matches)
        assert "[REDACTED:aws_key]" in redacted
        assert "AKIAIOSFODNN7EXAMPLE" not in redacted


@pytest.mark.ac("SPEC-082126-3c9d/AC-2")
def test_homoglyph_percent_and_base64_evasions_are_detected() -> None:
    secret = "AKIAIOSFODNN7EXAMPLE"
    homoglyph = "АKIAIOSFODNN7EXAMPLE"  # first character is Cyrillic U+0410
    percent_email = "someone%40example.com"
    encoded_secret = base64.urlsafe_b64encode(secret.encode()).decode().rstrip("=")

    cases = [
        (homoglyph, "aws_key"),
        (percent_email, "email"),
        (encoded_secret, "aws_key"),
    ]
    for payload, expected_type in cases:
        redacted, matches = scan_and_redact(f"value={payload}")
        assert any(match.pii_type == expected_type for match in matches), payload
        assert payload not in redacted
        assert f"[REDACTED:{expected_type}]" in redacted


@pytest.mark.ac("SPEC-082126-3c9d/AC-3")
def test_detection_views_preserve_false_positive_controls_and_deterministic_redaction() -> None:
    ordinary_non_latin = "Привет κόσμε"
    harmless_encoded = base64.urlsafe_b64encode(b"ordinary status message").decode().rstrip("=")
    luhn_invalid = "1234 5678 9012 3456"

    assert scan_for_pii(ordinary_non_latin) == []
    assert scan_for_pii(harmless_encoded) == []
    assert scan_for_pii(luhn_invalid) == []
    assert scan_and_redact(ordinary_non_latin)[0] == unicodedata.normalize(
        "NFKD", ordinary_non_latin
    )

    secret = base64.urlsafe_b64encode(b"AKIAIOSFODNN7EXAMPLE").decode().rstrip("=")
    once, _ = scan_and_redact(f"payload={secret}")
    twice, _ = scan_and_redact(once)
    assert once == twice


@pytest.mark.ac("SPEC-082126-3c9d/AC-4")
async def test_normalized_filter_is_used_on_direct_react_and_sentinel_post_call_paths() -> None:
    secret = "AKIAIOSFODNN7EXAMPLE"
    encoded_secret = base64.urlsafe_b64encode(secret.encode()).decode().rstrip("=")

    direct = DirectStrategy()
    provider = FauxProvider(default_response=FauxResponse(content=f"result {encoded_secret}"))
    direct_result = await direct.reason([{"role": "user", "content": "x"}], "test", provider)
    assert direct_result.response is not None
    assert encoded_secret not in direct_result.response
    assert "[REDACTED:aws_key]" in direct_result.response

    react_result = await ReactStrategy()._sanitize_tool_result(
        "tool",
        "contact someone%40example.com",
        sentinel=None,
        auth=None,
        warden=None,
    )
    assert "someone%40example.com" not in react_result
    assert "[REDACTED:email]" in react_result

    sentinel = Sentinel(warden=_CleanWarden(), permission_table={})
    post_call_result = await sentinel.post_call(
        "tool",
        "key АKIAIOSFODNN7EXAMPLE",
        AuthContext(user_id="u1", roles=frozenset()),
    )
    assert "АKIAIOSFODNN7EXAMPLE" not in post_call_result
    assert "[REDACTED:aws_key]" in post_call_result


def test_the_homoglyph_fold_is_index_for_index_with_its_input() -> None:
    """The confusable view is scanned but never returned. A hit found in it is
    redacted out of the canonical string at the *same* offsets, so the fold has
    to preserve length — a single entry mapping to two characters would shift
    every span after it and leak the tail of a secret. `str.translate` allows
    multi-character targets, so this is a property of the map, not of the call."""
    from maistro.security.normalize import _HOMOGLYPHS, fold_homoglyphs

    assert _HOMOGLYPHS, "an empty map would make this test vacuous"
    for source, target in _HOMOGLYPHS.items():
        assert isinstance(target, str) and len(target) == 1, (
            f"U+{source:04X} folds to {target!r}, which is not one character"
        )

    sample = "".join(chr(c) for c in _HOMOGLYPHS)
    assert len(fold_homoglyphs(sample)) == len(sample)


# ── the Codex review on #126: four ways an encoding still got through ──


@pytest.mark.ac("SPEC-082126-3c9d/AC-2")
def test_a_base64_encoded_ssn_is_short_enough_to_have_been_excluded() -> None:
    """The candidate floor was sixteen characters. An SSN is eleven, which
    Base64-encodes to fifteen before padding — so *every* encoded SSN sat below
    the threshold, in a filter whose stated purpose was catching encoded PII."""
    encoded = base64.b64encode(b"219-09-9999").decode()
    assert len(encoded.rstrip("=")) == 15, "the length that used to be excluded"

    redacted, matches = scan_and_redact(f"note {encoded}")

    assert [match.pii_type for match in matches] == ["ssn"]
    assert encoded not in redacted


@pytest.mark.ac("SPEC-082126-3c9d/AC-2")
def test_a_percent_encoded_connection_string_is_not_split_into_fragments() -> None:
    """`quote` leaves `/` literal by default. A candidate class that stopped at
    it cut the value into pieces, none of which could satisfy the
    connection-string detector — so the whole credential passed through."""
    encoded = quote("postgres://u:p@localhost/db")
    assert "/" in encoded and "%3A" in encoded, "the shape that used to split"

    redacted, matches = scan_and_redact(encoded)

    assert [match.pii_type for match in matches] == ["connection_string"]
    assert "localhost" not in redacted


@pytest.mark.ac("SPEC-082126-3c9d/AC-2")
def test_form_encoded_plus_signs_are_decoded_as_spaces() -> None:
    """`+` is ambiguous and the encoder does not say which it meant. Decoding it
    only as a literal turned `%2B1+415+555+2671` into `+1+415+555+2671`, whose
    separators the phone detector rejects."""
    encoded = quote_plus("+1 415 555 2671")
    assert encoded == "%2B1+415+555+2671"

    redacted, matches = scan_and_redact(encoded)

    assert [match.pii_type for match in matches] == ["phone"]
    assert "415" not in redacted


@pytest.mark.ac("SPEC-082126-3c9d/AC-3")
def test_an_encoded_candidate_overlapping_a_hit_absorbs_it_rather_than_vanishing() -> None:
    """One bug, two symptoms. The encoded candidate spanned both the visible AWS
    key and an encoded phone; overlapping the key's span, it was dropped whole,
    so the phone stayed in the output — and a second pass then redacted it,
    breaking idempotence. Both are the same discard."""
    text = "AKIAIOSFODNN7EXAMPLE%2B1%20415%20555%202671"

    once, matches = scan_and_redact(text)
    twice, _ = scan_and_redact(once)

    assert "415" not in once, "the phone must not survive the first pass"
    assert "AKIAIOSFODNN7EXAMPLE" not in once
    assert twice == once, "a second pass must find nothing left to do"
    assert len(matches) == 1, "the wider span replaces the one it contains"


def test_partial_overlap_is_still_refused() -> None:
    """Absorption is only for containment. Two spans that cross without one
    containing the other have no correct merge — widening to their union would
    redact text neither detector claimed — so the later one is still dropped."""
    from maistro.security.sentinel.pii_filter import _append_match

    matches: list = []
    seen: list[tuple[int, int]] = []
    canonical = "x" * 40
    _append_match(matches, seen, pii_type="aws_key", canonical=canonical, start=0, end=20)
    _append_match(
        matches,
        seen,
        pii_type="phone",
        canonical=canonical,
        start=10,
        end=30,
        may_absorb=True,
    )

    assert [(m.start, m.end) for m in matches] == [(0, 20)]

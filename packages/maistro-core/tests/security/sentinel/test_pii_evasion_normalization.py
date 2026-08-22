# ruff: noqa: RUF001, RUF002, RUF003 — confusable Unicode literals are test fixtures

"""Acceptance coverage for normalized PII/secret detection on product paths."""

from __future__ import annotations

import base64
import unicodedata

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
    assert scan_and_redact(ordinary_non_latin)[0] == unicodedata.normalize("NFKD", ordinary_non_latin)

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

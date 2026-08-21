"""Tests for ambient (free, per-call) reconciliation signal parsers.

Every provider-specific parser defaults to `via_litellm=True`, reading the
`llm_provider-`-prefixed passthrough headers -- per LiteLLM's own docs, the
*unprefixed* `x-ratelimit-*` headers reflect LiteLLM's own configured
rate-limit tier for the calling key whenever one is set, not the real
provider's capacity, so they are not a safe default to read from.
"""

from __future__ import annotations

import httpx

from maistro.quota.ambient import (
    LLM_PROVIDER_HEADER_PREFIX,
    AmbientSignalParser,
    CerebrasHeaderParser,
    GeminiHeaderParser,
    GroqHeaderParser,
    LiteLLMOwnBudgetHeaderParser,
    MistralHeaderParser,
    SambaNovaHeaderParser,
)
from maistro.quota.rate_profile import LimitUnit


def _response(headers: dict[str, str]) -> httpx.Response:
    return httpx.Response(200, headers=headers, request=httpx.Request("GET", "https://example.com"))


def _prefixed(headers: dict[str, str]) -> dict[str, str]:
    return {LLM_PROVIDER_HEADER_PREFIX + k: v for k, v in headers.items()}


def test_groq_parser_satisfies_protocol() -> None:
    assert isinstance(GroqHeaderParser(), AmbientSignalParser)


def test_groq_parses_both_dimensions_via_litellm_prefix_by_default() -> None:
    response = _response(
        _prefixed({"x-ratelimit-remaining-requests": "950", "x-ratelimit-remaining-tokens": "4500"})
    )
    snapshots = GroqHeaderParser().parse("groq:kimi-k2", response)

    by_unit = {s.unit: s.remaining for s in snapshots}
    assert by_unit[LimitUnit.REQUESTS] == 950.0
    assert by_unit[LimitUnit.TOTAL_TOKENS] == 4500.0
    assert all(s.scope_key == "groq:kimi-k2" for s in snapshots)


def test_groq_ignores_unprefixed_headers_by_default() -> None:
    """The unprefixed headers are LiteLLM's own budget tier, not Groq's real
    capacity -- the default (via_litellm=True) must not read them."""
    response = _response(
        {"x-ratelimit-remaining-requests": "950", "x-ratelimit-remaining-tokens": "4500"}
    )
    assert GroqHeaderParser().parse("groq:kimi-k2", response) == []


def test_groq_direct_mode_reads_unprefixed_headers() -> None:
    response = _response({"x-ratelimit-remaining-requests": "10"})
    snapshots = GroqHeaderParser(via_litellm=False).parse("groq:kimi-k2", response)
    assert len(snapshots) == 1
    assert snapshots[0].unit == LimitUnit.REQUESTS
    assert snapshots[0].remaining == 10.0


def test_groq_parses_partial_headers() -> None:
    response = _response(_prefixed({"x-ratelimit-remaining-requests": "10"}))
    snapshots = GroqHeaderParser().parse("groq:kimi-k2", response)
    assert len(snapshots) == 1
    assert snapshots[0].unit == LimitUnit.REQUESTS


def test_groq_returns_empty_list_when_headers_absent() -> None:
    response = _response({})
    assert GroqHeaderParser().parse("groq:kimi-k2", response) == []


def test_groq_ignores_unparseable_header_value() -> None:
    response = _response(_prefixed({"x-ratelimit-remaining-requests": "not-a-number"}))
    assert GroqHeaderParser().parse("groq:kimi-k2", response) == []


def test_sambanova_parses_requests_only() -> None:
    response = _response(_prefixed({"x-ratelimit-remaining-requests": "18"}))
    snapshots = SambaNovaHeaderParser().parse("sambanova:deepseek-r1", response)
    assert len(snapshots) == 1
    assert snapshots[0].unit == LimitUnit.REQUESTS
    assert snapshots[0].remaining == 18.0


def test_sambanova_empty_when_absent() -> None:
    assert SambaNovaHeaderParser().parse("sambanova:deepseek-r1", _response({})) == []


def test_mistral_parses_generic_header() -> None:
    response = _response(_prefixed({"X-RateLimit-Remaining": "42"}))
    snapshots = MistralHeaderParser().parse("mistral:mistral-small", response)
    assert len(snapshots) == 1
    assert snapshots[0].unit == LimitUnit.REQUESTS
    assert snapshots[0].remaining == 42.0


def test_cerebras_parses_both_dimensions() -> None:
    response = _response(
        _prefixed(
            {
                "x-ratelimit-remaining-requests-day": "25",
                "x-ratelimit-remaining-tokens-minute": "55000",
            }
        )
    )
    snapshots = CerebrasHeaderParser().parse("cerebras:qwen3-235b", response)
    by_unit = {s.unit: s.remaining for s in snapshots}
    assert by_unit[LimitUnit.REQUESTS] == 25.0
    assert by_unit[LimitUnit.TOTAL_TOKENS] == 55000.0


def test_gemini_parses_generic_remaining() -> None:
    response = _response(_prefixed({"x-ratelimit-remaining": "12"}))
    snapshots = GeminiHeaderParser().parse("gemini:gemini-2-5-flash", response)
    assert len(snapshots) == 1
    assert snapshots[0].unit == LimitUnit.REQUESTS
    assert snapshots[0].remaining == 12.0


def test_all_parsers_satisfy_protocol() -> None:
    for parser in (
        GroqHeaderParser(),
        SambaNovaHeaderParser(),
        MistralHeaderParser(),
        CerebrasHeaderParser(),
        GeminiHeaderParser(),
        LiteLLMOwnBudgetHeaderParser(),
    ):
        assert isinstance(parser, AmbientSignalParser)


class TestLiteLLMOwnBudgetHeaderParser:
    """This parser reads LiteLLM's *own* configured rate-limit tier for the
    calling key -- not the real provider's capacity. Distinct, legitimate use
    case (tracking your own proxy-side budget), but must never be confused
    with "how much room does the provider actually have left"."""

    def test_reads_unprefixed_headers_directly(self) -> None:
        response = _response(
            {"x-ratelimit-remaining-requests": "1200", "x-ratelimit-remaining-tokens": "88000"}
        )
        snapshots = LiteLLMOwnBudgetHeaderParser().parse("team-a", response)

        by_unit = {s.unit: s.remaining for s in snapshots}
        assert by_unit[LimitUnit.REQUESTS] == 1200.0
        assert by_unit[LimitUnit.TOTAL_TOKENS] == 88000.0

    def test_does_not_read_the_llm_provider_prefixed_headers(self) -> None:
        """Those are the real backend's signal -- a different question."""
        response = _response(_prefixed({"x-ratelimit-remaining-requests": "5"}))
        assert LiteLLMOwnBudgetHeaderParser().parse("team-a", response) == []

    def test_empty_when_headers_absent(self) -> None:
        """Matches LiteLLM's own documented gap: these headers are dropped on
        streaming responses -- an absent header must be a no-op, not a crash."""
        assert LiteLLMOwnBudgetHeaderParser().parse("team-a", _response({})) == []

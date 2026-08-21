"""Ambient reconciliation signals — parsed for free from a response already
in hand, no extra network call.

**Correction (verified against LiteLLM's own docs):** the *unprefixed*
`x-ratelimit-remaining-{requests,tokens}` headers are only conditionally the
real upstream provider's signal. Per LiteLLM: if the calling API key has any
rate limit configured *in LiteLLM itself*, these headers report LiteLLM's own
internal budget/tier tracking for that key — a number this codebase has no
way to know is (or isn't) kept in sync with the real provider's actual
capacity. Only when the key has *no* LiteLLM-side limit configured do they
fall back to the (still-normalized) backend signal. That's not something
`ambient.py` can detect from a response alone, so it isn't a safe default.

**The `llm_provider-`-prefixed headers are unconditionally reliable** — per
LiteLLM's docs, these are the original upstream response headers, passed
through *unmodified*. That also means they are **not** normalized into one
shape: each provider's own raw, native header names survive under the
prefix. So the five provider-specific parsers below (`GroqHeaderParser`
etc.) — reading `llm_provider-{that provider's own header name}` by default
via `via_litellm=True` — are the right tool for `maistro_llm_call` traffic,
not a hypothetical unused path. Pass `via_litellm=False` only for a call path
that talks to a provider directly, bypassing LiteLLM's prefix entirely.

A response can carry more than one simultaneous dimension (both requests and
tokens remaining at once), so `parse` returns a list, not a single snapshot.

Cohere is deliberately not here at all: its response body carries
`meta.billed_units` — what *this call* cost, not what's *remaining* — which
is a usage report to record directly (see `recorder.py`), not a balance to
reconcile against.
"""

from __future__ import annotations

import time
from typing import Protocol, runtime_checkable

import httpx

from maistro.quota.rate_profile import LimitUnit
from maistro.quota.reconciliation import ProviderQuotaSnapshot

# Per LiteLLM's docs: the original, unmodified upstream response headers are
# passed through under this prefix — unconditionally reliable, unlike the
# unprefixed x-ratelimit-* headers (which reflect LiteLLM's own configured
# rate-limit tier for the calling key whenever one is set).
LLM_PROVIDER_HEADER_PREFIX = "llm_provider-"


@runtime_checkable
class AmbientSignalParser(Protocol):
    """Extracts whatever remaining-capacity snapshots a real response
    carries. Returns an empty list if the response has none (malformed,
    missing headers, wrong endpoint) — never raises for a merely-absent
    signal, since ambient parsing is opportunistic by nature."""

    def parse(self, scope_key: str, response: httpx.Response) -> list[ProviderQuotaSnapshot]: ...


def _snapshot_from_header(
    scope_key: str, response: httpx.Response, header: str, unit: LimitUnit
) -> ProviderQuotaSnapshot | None:
    raw = response.headers.get(header)
    if raw is None:
        return None
    try:
        remaining = float(raw)
    except ValueError:
        return None
    return ProviderQuotaSnapshot(
        scope_key=scope_key,
        unit=unit,
        remaining=remaining,
        checked_at=time.time(),
    )


def _parse_pairs(
    scope_key: str,
    response: httpx.Response,
    prefix: str,
    header_units: tuple[tuple[str, LimitUnit], ...],
) -> list[ProviderQuotaSnapshot]:
    snapshots = []
    for header, unit in header_units:
        snap = _snapshot_from_header(scope_key, response, prefix + header, unit)
        if snap is not None:
            snapshots.append(snap)
    return snapshots


class GroqHeaderParser:
    """Per Groq's own docs: `x-ratelimit-remaining-requests` is always RPD
    (not RPM, despite the generic-looking name); `x-ratelimit-remaining-tokens`
    is always TPM.

    `via_litellm=True` (default) reads these under LiteLLM's `llm_provider-`
    passthrough prefix — the correct choice for `maistro_llm_call` traffic.
    Set `via_litellm=False` only for a hypothetical path calling Groq directly.
    """

    _HEADERS: tuple[tuple[str, LimitUnit], ...] = (
        ("x-ratelimit-remaining-requests", LimitUnit.REQUESTS),
        ("x-ratelimit-remaining-tokens", LimitUnit.TOTAL_TOKENS),
    )

    def __init__(self, *, via_litellm: bool = True) -> None:
        self._prefix = LLM_PROVIDER_HEADER_PREFIX if via_litellm else ""

    def parse(self, scope_key: str, response: httpx.Response) -> list[ProviderQuotaSnapshot]:
        return _parse_pairs(scope_key, response, self._prefix, self._HEADERS)


class SambaNovaHeaderParser:
    """Per-minute request headroom only — SambaNova's per-model RPD/TPD
    credit-style limits aren't exposed in response headers. See
    `GroqHeaderParser` for the `via_litellm` prefix rationale.
    """

    _HEADERS: tuple[tuple[str, LimitUnit], ...] = (
        ("x-ratelimit-remaining-requests", LimitUnit.REQUESTS),
    )

    def __init__(self, *, via_litellm: bool = True) -> None:
        self._prefix = LLM_PROVIDER_HEADER_PREFIX if via_litellm else ""

    def parse(self, scope_key: str, response: httpx.Response) -> list[ProviderQuotaSnapshot]:
        return _parse_pairs(scope_key, response, self._prefix, self._HEADERS)


class MistralHeaderParser:
    """A single generic `X-RateLimit-Remaining` header — Mistral's docs don't
    split it by requests vs. tokens, so this is read as REQUESTS (the more
    literal reading of an undifferentiated "rate limit" figure). See
    `GroqHeaderParser` for the `via_litellm` prefix rationale.
    """

    _HEADERS: tuple[tuple[str, LimitUnit], ...] = (("X-RateLimit-Remaining", LimitUnit.REQUESTS),)

    def __init__(self, *, via_litellm: bool = True) -> None:
        self._prefix = LLM_PROVIDER_HEADER_PREFIX if via_litellm else ""

    def parse(self, scope_key: str, response: httpx.Response) -> list[ProviderQuotaSnapshot]:
        return _parse_pairs(scope_key, response, self._prefix, self._HEADERS)


class CerebrasHeaderParser:
    """Confirmed against Cerebras's own docs ("we inject several custom
    headers into every API response" to monitor usage in real time):
    `x-ratelimit-remaining-requests-day` (RPD — daily, not per-minute, despite
    the generic-looking name) and `x-ratelimit-remaining-tokens-minute`
    (TPM). Unlike Groq, the two dimensions use *different* windows — day for
    requests, minute for tokens — so don't assume they're a matched pair.
    See `GroqHeaderParser` for the `via_litellm` prefix rationale.
    """

    _HEADERS: tuple[tuple[str, LimitUnit], ...] = (
        ("x-ratelimit-remaining-requests-day", LimitUnit.REQUESTS),
        ("x-ratelimit-remaining-tokens-minute", LimitUnit.TOTAL_TOKENS),
    )

    def __init__(self, *, via_litellm: bool = True) -> None:
        self._prefix = LLM_PROVIDER_HEADER_PREFIX if via_litellm else ""

    def parse(self, scope_key: str, response: httpx.Response) -> list[ProviderQuotaSnapshot]:
        return _parse_pairs(scope_key, response, self._prefix, self._HEADERS)


class GeminiHeaderParser:
    """`x-ratelimit-remaining` — a single figure per response, not split by
    dimension in the header name itself. Read as REQUESTS; Gemini also has a
    TPM and (for image models) IPM dimension this header doesn't distinguish,
    so a caller relying solely on this signal is only getting the RPM/RPD
    picture, not the full multi-dimension one `rate_profile.py` can model.
    See `GroqHeaderParser` for the `via_litellm` prefix rationale.
    """

    _HEADERS: tuple[tuple[str, LimitUnit], ...] = (("x-ratelimit-remaining", LimitUnit.REQUESTS),)

    def __init__(self, *, via_litellm: bool = True) -> None:
        self._prefix = LLM_PROVIDER_HEADER_PREFIX if via_litellm else ""

    def parse(self, scope_key: str, response: httpx.Response) -> list[ProviderQuotaSnapshot]:
        return _parse_pairs(scope_key, response, self._prefix, self._HEADERS)


class LiteLLMOwnBudgetHeaderParser:
    """Reads LiteLLM's *own* internal rate-limit-tier headers (unprefixed
    `x-ratelimit-remaining-{requests,tokens}`) — its configured budget for the
    calling API key/team, not the upstream provider's real capacity. Useful
    only if you specifically want to track the proxy-side budget itself
    (e.g. to alert when a team is approaching its configured allowance);
    do not use this to answer "how much room does the provider actually have
    left" — that's what the `via_litellm=True` provider-specific parsers are
    for, since LiteLLM's own tier and the real provider quota are tracked
    completely independently and nothing keeps them in sync automatically.
    """

    def parse(self, scope_key: str, response: httpx.Response) -> list[ProviderQuotaSnapshot]:
        return _parse_pairs(
            scope_key,
            response,
            "",
            (
                ("x-ratelimit-remaining-requests", LimitUnit.REQUESTS),
                ("x-ratelimit-remaining-tokens", LimitUnit.TOTAL_TOKENS),
            ),
        )

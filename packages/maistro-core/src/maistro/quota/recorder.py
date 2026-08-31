"""Wires real per-call usage into the local quota cache (`InMemoryUsageLog`).

The one thing guaranteed present and correct in every LiteLLM (OpenAI-
compatible) response is the standard `usage.prompt_tokens` /
`usage.completion_tokens` pair — that's part of the compatibility contract
itself, so it's populated the same way regardless of which upstream provider
actually served the call. This is therefore the *primary* recording path.

Provider-specific extras (raw rate-limit headers, Cohere's `meta.billed_units`)
are not guaranteed to survive LiteLLM's response normalization the way the
standard `usage` object is — a proxy whose whole job is presenting one common
shape has no obligation to forward provider-native metadata untouched. Ambient
header parsing (`ambient.py`) is wired in here too, but strictly as a
best-effort bonus signal: if the expected headers didn't survive the proxy
hop, the parser already returns an empty list and nothing happens — the
primary `usage`-based recording is what a caller should actually rely on.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from maistro.quota.ambient import AmbientSignalParser
from maistro.quota.rate_profile import LimitUnit
from maistro.quota.reconciliation import (
    AdaptiveReconciliationPolicy,
    ReconciliationOutcome,
    ReconciliationState,
    reconcile_ambient,
)
from maistro.quota.usage_log import InMemoryUsageLog
from maistro.quota.usage_report import extract_usage


def record_llm_usage(
    log: InMemoryUsageLog,
    scope_key: str,
    response_json: dict[str, Any],
    *,
    now: float | None = None,
) -> tuple[int, int]:
    """Record one real call's actual token usage. Returns what was recorded
    so callers (tests, logging) can see it without re-deriving it."""
    input_tokens, output_tokens = extract_usage(response_json)
    log.record(scope_key, input_tokens=input_tokens, output_tokens=output_tokens, now=now)
    return input_tokens, output_tokens


@dataclass
class ScopedReconciliationRegistry:
    """One `ReconciliationState` per (scope_key, unit).

    Ambient signals from different dimensions of the same model track
    independently — Groq's RPD-remaining and TPM-remaining are different
    quantities entirely and must not share one delta-comparison state.
    """

    _states: dict[tuple[str, LimitUnit], ReconciliationState] = field(default_factory=dict)

    def get_or_create(self, scope_key: str, unit: LimitUnit) -> ReconciliationState:
        key = (scope_key, unit)
        if key not in self._states:
            self._states[key] = ReconciliationState(policy=AdaptiveReconciliationPolicy())
        return self._states[key]


def record_ambient_signals(
    registry: ScopedReconciliationRegistry,
    log: InMemoryUsageLog,
    scope_key: str,
    response: httpx.Response,
    parser: AmbientSignalParser,
    *,
    now: float | None = None,
) -> list[ReconciliationOutcome]:
    """Best-effort: reconcile against whatever ambient snapshots `parser`
    extracts from `response`. Empty list in, empty list out — a proxy that
    stripped the expected headers just means no ambient signal this call,
    not a failure."""
    outcomes = []
    for snapshot in parser.parse(scope_key, response):
        state = registry.get_or_create(scope_key, snapshot.unit)
        outcomes.append(reconcile_ambient(state, scope_key, log, snapshot, now=now))
    return outcomes


def build_quota_recording_hook(
    log: InMemoryUsageLog,
    scope_key: str,
    *,
    ambient_parser: AmbientSignalParser | None = None,
    registry: ScopedReconciliationRegistry | None = None,
) -> Callable[[dict[str, Any], httpx.Response], None]:
    """Build an `on_response` callback for `maistro_llm_call` (or any
    `(response_json, response) -> None` callback site) that wires both
    recording paths in one line:

        hook = build_quota_recording_hook(log, "cerebras:qwen3-235b", ambient_parser=CerebrasHeaderParser())
        await maistro_llm_call(messages, model="cerebras-qwen-3-235b", on_response=hook)

    Pick the provider-specific parser matching whichever backend the model
    routes to (`ambient.py`), with its default `via_litellm=True` — LiteLLM's
    own *unprefixed* `x-ratelimit-*` headers reflect its internal budget
    tracking for the calling key whenever one is configured, not the real
    provider's capacity, so the reliable signal is always the `llm_provider-`
    -prefixed passthrough these parsers read by default. There's no single
    generic parser that works for every provider here, since the prefixed
    headers preserve each backend's own raw, unnormalized header names.

    `registry` defaults to a fresh one per hook — pass a shared instance if
    several hooks (e.g. one per model) should share ambient reconciliation
    state, which they should whenever they're really the same scope_key.
    """
    registry = registry if registry is not None else ScopedReconciliationRegistry()

    def hook(response_json: dict[str, Any], response: httpx.Response) -> None:
        record_llm_usage(log, scope_key, response_json)
        if ambient_parser is not None:
            record_ambient_signals(registry, log, scope_key, response, ambient_parser)

    return hook

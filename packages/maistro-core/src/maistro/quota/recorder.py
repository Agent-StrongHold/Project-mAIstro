"""Record provider evidence for canonical model Invocations.

The live path is :class:`CanonicalInvocationUsageRecorder`, installed once at
Invocation terminalization by ``CapabilityEffectContext``. It records provider,
cycle, usage evidence and Invocation identity exactly once, including an
explicit unreported marker when a provider omits usage. A second live entry
point covers the one call class that crosses no canonical authority: the
conductor's raw-gateway fallback (``agents/conductor.py``) records its usage
evidence on the process default usage log with explicit provenance and, when
the Container composition root registered a process default quota ledger, on
that ledger too — reported tokens as usage, a missing report as an unreported
marker — so an ungoverned composition can neither be silently invisible nor
present complete quota percentages while omitting the call. The raw
``on_response`` hook below is a compatibility adapter for older raw-HTTP call
sites; after the #718 cutover no shipped production call site supplies it, and
ambient/header reconciliation with it is explicitly not a wired production
path — the canonical Invocation recorder is the only Invocation-keyed
recording mechanism.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

import httpx

from maistro.capabilities.invocation import Invocation
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


class CanonicalInvocationUsageRecorder:
    """Record completed model Invocations exactly once on the quota ledger.

    Canonical model effects use this hook from Invocation terminalization, so
    retries and deduplicated effects cannot charge twice. Missing usage is
    recorded as unreported evidence, never as a measured zero.
    """

    def __init__(
        self,
        log: InMemoryUsageLog,
        quota_tracker: Any | None = None,
        *,
        billing_cycle: str = "monthly",
    ) -> None:
        self._log = log
        self._quota_tracker = quota_tracker
        self._billing_cycle = billing_cycle
        self._recorded: set[str] = set()

    async def record(self, invocation: Invocation) -> None:
        """Record one completed physical effect, keyed by Invocation identity.

        At-least-once: the Invocation is marked recorded only after every
        write succeeds, so a transient ledger failure raised here leaves the
        effect unmarked and the next ``record`` attempt (a terminalization
        retry, or a deduplicated effect hand-out re-confirming evidence)
        repairs the ledger instead of permanently omitting it. Charging stays
        at-most-once: durable trackers are idempotent on Invocation identity
        (``record_invocation``), and this in-process guard plus the tracker's
        own dedupe keep retries charge-free.
        """
        if invocation.invocation_id in self._recorded:
            return
        provider = invocation.binding.provider_name
        usage = invocation.usage
        input_tokens = usage.input_units if usage is not None else 0
        output_tokens = usage.output_units if usage is not None else 0
        # Durable ledger first: it is the authoritative sink and is idempotent
        # on Invocation identity, so a failure here records nothing rather
        # than half the evidence. The usage-log append that follows cannot
        # fail in practice, and only after both succeed is the Invocation
        # marked recorded.
        if self._quota_tracker is not None:
            record_invocation = getattr(self._quota_tracker, "record_invocation", None)
            if record_invocation is not None:
                await record_invocation(
                    invocation.invocation_id,
                    provider,
                    self._billing_cycle,
                    input_tokens,
                    output_tokens,
                    usage is not None,
                )
            elif usage is not None:
                # Compatibility for external trackers predating canonical
                # evidence. Not identity-keyed, so it charges on the first
                # successful attempt only — the mark below plus this guard
                # make retries no-ops in-process.
                await self._quota_tracker.record_usage(
                    provider, self._billing_cycle, input_tokens, output_tokens
                )
            else:
                record_unreported = getattr(self._quota_tracker, "record_unreported", None)
                if record_unreported is not None:
                    # Not on the QuotaTracker protocol; a tracker that tracks
                    # unreported evidence still exposes this async hook.
                    await cast("Callable[[str, str], Awaitable[None]]", record_unreported)(
                        provider, self._billing_cycle
                    )
        self._log.record(
            provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=((usage.cost_cents or 0.0) / 100.0) if usage is not None else 0.0,
            invocation_id=invocation.invocation_id,
            provider=provider,
            billing_cycle=self._billing_cycle,
            usage_reported=usage is not None,
        )
        self._recorded.add(invocation.invocation_id)


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
    """Build a compatibility `on_response` callback for legacy raw HTTP sites.

    Canonical model calls do not supply this callback: their Invocation
    terminalization invokes ``CanonicalInvocationUsageRecorder`` once. After
    the #718 cutover no shipped production entry point passes this hook —
    ambient/header reconciliation through it is retained for compatibility
    callers and tests only, not as a wired production recording path (the
    explicit-verifier wiring is recorded as owed in
    ``quality/reachability-dispositions.json``, id ``quota-verification``).

    For older `(response_json, response) -> None` callback sites this still
    wires both recording paths in one line:

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

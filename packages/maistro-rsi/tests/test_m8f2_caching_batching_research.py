"""M8-F2 research harness — cross-Agent batching, prefix/KV reuse, semantic caching.

Issue #935 (leaf of epic #905, initiative #879). Hypothesis under study:
batching independent Agent inference, reusing stable prompt/KV state, and
caching semantic responses for carefully bounded read-only cases can raise
throughput and cut cost without breaking isolation or freshness guarantees.

This module is a RESEARCH ARTIFACT, not product code. It implements the
measurement machinery the #935 benchmark procedure demands:

- **Cache identity with full semantics.** The leaf's hard requirement —
  "cache identity must include all semantics needed to prevent tenant/context
  leakage" — is implemented as an explicit, ordered identity tuple (workspace,
  project, agent, capability, model, provider, messages, tools, generation
  semantics) with an injective canonical serialization, plus serve-time
  re-verification of the full identity against the cached entry, so a digest
  match alone can never serve across tenants. Freshness is deliberately NOT
  part of the identity: the freshness epoch is an *invalidation* dimension
  guarded at serve time, not a naming dimension — folding it into the key
  would strand stale entries instead of invalidating them and would hide the
  invalidation complexity the issue asks to measure. The naive contrast
  (content-only key, no admission control, TTL-only invalidation) is
  implemented and *measured* to show exactly which guarantees each omitted
  semantic buys back.
- **Semantic response cache accounting**: hit rate, token/cost savings,
  stale-result rate under epoch-scoped versus TTL-only invalidation, and
  non-cacheable (mutating / non-deterministic) bypass.
- **Prefix/KV reuse accounting**: exact longest-common-prefix token reuse,
  workspace-scoped stores, cached-input price factors, prefix-drift refusal,
  and the foregone-savings price of refusing cross-tenant prefix pooling.
- **Batching model**: deterministic logical-time dispatch with a batch
  window, capacity-one service (the queueing regime where batching is
  relevant), held versus streamed completion, dependency-aware admission, and
  identity-keyed response demux contrasted with completion-order demux.

All timing is LOGICAL (simulated milliseconds); nothing here touches a clock,
a network, or a real accelerator. "Accelerator utilization" is reported as
the model's busy fraction and batch fill — a utilization *proxy*, never a
hardware reading. The synthetic corpora are deterministic fixtures for
validating the arithmetic and the isolation mechanics; they are NOT
experimental results and must never be quoted as evidence about real models
or providers.

Relationship to the shipped tree: the governed model-serving path is
Binding -> Invocation -> the single approved gateway provider
(``maistro.capabilities.model_chat``,
``maistro.capabilities.providers.llm_gateway``), with model selection behind
``CostAwareRouter`` (ADR-038). The only shipped cache is the opt-in Anthropic
prefix breakpoint in ``maistro_bootstrap.builders.responses_callable``;
RSI/evolve bodies affirmatively send no-cache headers. This harness measures
none of that surface — it is the reproducible benchmark procedure the leaf's
disposition conditions require.

Trust boundary (the epic contract, enforced by construction):

- Every number produced here is ADVISORY EVIDENCE. Nothing reads or writes a
  Goal, a Run authority, a routing decision, or a Warden/HITL/delegation
  control. The module imports no maistro module at all, so it cannot become
  an authority by accident (M8 guardrails 1-2). Production adoption of any
  caching/batching scheme routes to the governed serving seam's owners, never
  through this harness, and never as a second model-serving path.
- Cache identity correctness is proven here by construction and by adversarial
  fixtures, but a cache that ships must ship behind the governed seam with the
  same identity semantics — this module is the spec-by-evidence, not the spec.
- Records are frozen: measurements cannot be mutated into authorization after
  the fact.

The experiment record and terminal disposition live in
``docs/research/935-cross-agent-batching-kv-reuse.md``.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import inspect
import json
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

#: Explicit evidence-only contract marker. Asserted by a test so it cannot
#: silently rot; nothing outside this module may treat M8-F2 output as
#: authorization. Model-serving authority remains the governed
#: Binding -> Invocation -> gateway seam; routing authority remains
#: CostAwareRouter (ADR-038).
ADVISORY_ONLY = True


# ---------------------------------------------------------------------------
# Price model — ModelMetadata units (cents per 1k tokens)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PriceModel:
    """Per-model price in ``ModelMetadata`` units (cents per 1k tokens).

    Mirrors ``packages/maistro-core/src/maistro/providers/types.py`` so a real
    experiment can populate prices straight from the provider registry.
    ``cached_input_factor`` is the provider's cached-input price multiplier
    (e.g. 0.1 for Anthropic-style ephemeral prefix pricing); it applies only
    to the prefix-reuse axis and must lie in [0, 1].
    """

    name: str
    cents_per_1k_input: float
    cents_per_1k_output: float
    cached_input_factor: float = 1.0

    def __post_init__(self) -> None:
        if self.cents_per_1k_input < 0 or self.cents_per_1k_output < 0:
            raise ValueError(f"price model {self.name!r}: negative token price")
        if not 0.0 <= self.cached_input_factor <= 1.0:
            raise ValueError(f"price model {self.name!r}: cached_input_factor must be in [0, 1]")

    def call_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Full-price cost in cents of one completed call."""
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must be non-negative")
        return (
            input_tokens / 1000.0 * self.cents_per_1k_input
            + output_tokens / 1000.0 * self.cents_per_1k_output
            if (input_tokens or output_tokens)
            else 0.0
        )


# ---------------------------------------------------------------------------
# Requests — one workload item with every semantic that can change a response
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GenerationSemantics:
    """The generation parameters that change what a response means.

    A response sampled at ``temperature > 0`` is one draw from a distribution;
    serving a stored response for such a request substitutes one draw for
    another. Cache admission therefore requires deterministic generation
    (``temperature == 0``) — the "carefully bounded read-only cases" the issue
    names. Parameters that do not change semantics (e.g. request IDs) are
    deliberately absent from identity: including them would only lower the
    hit rate without preventing any leakage.
    """

    temperature: float
    max_output_tokens: int

    def __post_init__(self) -> None:
        if self.temperature < 0:
            raise ValueError("temperature must be non-negative")
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")

    @property
    def deterministic(self) -> bool:
        return self.temperature == 0.0


@dataclass(frozen=True)
class Request:
    """One inference request with all cache-relevant semantics attached.

    ``cacheable`` is the caller's read-only declaration: only a read-only
    request under deterministic generation is admitted to (or served from) the
    safe cache. ``freshness_epoch`` is the version of the underlying state the
    response was computed against — bumping it is the invalidation trigger at
    serve time; it is deliberately NOT part of the identity (see module
    docstring). ``depends_on`` names a prior request whose response this
    request's content was built from (multi-turn Agent loops); a batcher must
    never co-schedule the two.
    """

    request_id: str
    workspace_id: str
    project_id: str
    agent_id: str
    capability: str
    model: str
    provider: str
    messages: tuple[dict[str, str], ...]
    tools: tuple[str, ...]
    generation: GenerationSemantics
    freshness_epoch: int
    cacheable: bool
    input_tokens: int
    output_tokens: int
    service_ms: float
    arrival_ms: float = 0.0
    depends_on: str | None = None

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError(f"request {self.request_id!r}: negative token count")
        if self.service_ms < 0 or self.arrival_ms < 0:
            raise ValueError(f"request {self.request_id!r}: negative time")
        if self.cacheable and not self.generation.deterministic:
            raise ValueError(
                f"request {self.request_id!r}: a non-deterministic generation "
                "cannot be declared cacheable"
            )


# ---------------------------------------------------------------------------
# Cache identity — the leaf's hard requirement, made executable
# ---------------------------------------------------------------------------

#: The identity dimensions, in canonical order. This tuple is the module's
#: answer to "cache identity must include all semantics needed to prevent
#: tenant/context leakage": every field that can change what a response
#: *means* — or whose response it may lawfully be — participates.
IDENTITY_FIELDS: tuple[str, ...] = (
    "workspace_id",
    "project_id",
    "agent_id",
    "capability",
    "model",
    "provider",
    "messages",
    "tools",
    "generation",
)

#: The invalidation dimensions, guarded at serve time rather than baked into
#: the name. Counted with IDENTITY_FIELDS as the invalidation-complexity
#: artifact the issue asks to be measured.
INVALIDATION_DIMENSIONS: tuple[str, ...] = ("freshness_epoch", "ttl_ms")


def identity_components(request: Request) -> dict[str, Any]:
    """The full semantic identity of a request, as an ordered component map.

    Freshness is excluded on purpose: two reads of the same question at
    different epochs are the *same identity* with different validity, which is
    what makes epoch invalidation observable (and testable) at serve time.
    """
    return {
        "workspace_id": request.workspace_id,
        "project_id": request.project_id,
        "agent_id": request.agent_id,
        "capability": request.capability,
        "model": request.model,
        "provider": request.provider,
        "messages": [dict(m) for m in request.messages],
        "tools": list(request.tools),
        "generation": {
            "temperature": request.generation.temperature,
            "max_output_tokens": request.generation.max_output_tokens,
        },
    }


def canonical_identity_bytes(components: dict[str, Any]) -> bytes:
    """Injective serialization of the identity components.

    ``json.dumps`` with sorted keys and no whitespace is injective for the
    value shapes used here (strings, numbers, lists, flat dicts): distinct
    structures never share a byte encoding, so a boundary-ambiguous pair like
    ``["a", "b"]`` and ``["a,b"]`` serializes differently. The deliberately
    naive serializer in :func:`naive_content_key` is the contrast case.
    """
    return json.dumps(
        components,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def identity_digest(request: Request) -> str:
    """SHA-256 of the canonical identity bytes.

    The digest is an addressing convenience only. The identity IS the
    component map; the cache re-verifies components at serve time
    (:class:`SemanticResponseCache`), so a digest match alone can never
    serve a response across a semantic boundary.
    """
    return hashlib.sha256(canonical_identity_bytes(identity_components(request))).hexdigest()


def naive_content_key(request: Request) -> str:
    """The deliberately unsafe key of a naive cache: content join, nothing else.

    Joins message contents with ``,`` and hashes. Ambiguous by construction
    (different message lists can share a key) and blind to every tenant,
    agent, model, tool, and generation semantic.
    """
    joined = ",".join(m["content"] for m in request.messages)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Metrics — the issue's measure list as frozen records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CacheRunMetrics:
    """Result of running one request sequence through one cache policy."""

    strategy: str
    requests: int
    cost_cents: float
    baseline_cost_cents: float
    savings_cents: float
    cacheable_lookups: int
    cache_hits: int
    cache_hit_rate: float
    stale_serves: int
    cross_workspace_serves: int
    non_cacheable_serves: int
    invalidation_refusals: int
    identity_mismatch_refusals: int
    cross_workspace_refusals: int

    def __post_init__(self) -> None:
        if self.cacheable_lookups and not math.isclose(
            self.cache_hit_rate, self.cache_hits / self.cacheable_lookups
        ):
            raise ValueError("hit rate inconsistent with hits/lookups")
        if not math.isclose(self.savings_cents, self.baseline_cost_cents - self.cost_cents):
            raise ValueError("savings inconsistent with cost baseline delta")


@dataclass(frozen=True)
class PrefixRunMetrics:
    """Result of running one request sequence through prefix-reuse accounting."""

    strategy: str
    requests: int
    cost_cents: float
    baseline_cost_cents: float
    savings_cents: float
    cached_input_tokens: int
    billed_input_tokens: int
    prefix_reuse_rate: float
    cross_tenant_pooling_foregone_cents: float
    drift_events: int

    def __post_init__(self) -> None:
        if self.requests and not 0.0 <= self.prefix_reuse_rate <= 1.0:
            raise ValueError("prefix reuse rate out of range")
        if not math.isclose(self.savings_cents, self.baseline_cost_cents - self.cost_cents):
            raise ValueError("savings inconsistent with cost baseline delta")


@dataclass(frozen=True)
class BatchRunMetrics:
    """Result of one dispatch simulation in one mode."""

    mode: str
    requests: int
    makespan_ms: float
    throughput_rps: float
    mean_latency_ms: float
    p95_latency_ms: float
    accelerator_busy_fraction: float
    mean_batch_fill_rate: float
    window_waits_ms: float
    dependency_deferrals: int
    dependency_violations: int
    misdelivered_responses: int

    def __post_init__(self) -> None:
        if self.requests and self.makespan_ms and self.throughput_rps <= 0:
            raise ValueError("throughput must be positive for a non-empty run")
        expected = self.requests / (self.makespan_ms / 1000.0) if self.makespan_ms else 0.0
        if not math.isclose(self.throughput_rps, expected, rel_tol=1e-9):
            raise ValueError("throughput inconsistent with makespan")


@dataclass(frozen=True)
class BenchmarkRecord:
    """One frozen strategy run over one fixed workload."""

    workload: str
    strategy: str
    cache: CacheRunMetrics | None
    prefix: PrefixRunMetrics | None
    batch: BatchRunMetrics | None


# ---------------------------------------------------------------------------
# Safe semantic response cache — full identity, epoch-scoped, admission-gated
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CacheEntry:
    digest: str
    components: dict[str, Any]
    workspace_id: str
    response: str
    epoch: int
    stored_at_ms: float
    cost_cents: float


@dataclass
class CachePolicy:
    """Invalidation policy knobs for the safe cache.

    ``epoch_scoped`` entries are valid only for the freshness epoch they were
    computed at; a bumped epoch invalidates deterministically. ``ttl_ms``
    additionally bounds logical serving time. The naive contrast below runs
    with no epoch scoping and no admission control.
    """

    epoch_scoped: bool = True
    ttl_ms: float | None = None


@dataclass
class CacheCounters:
    """Mutable tally collected while a cache policy serves a workload."""

    cost_cents: float = 0.0
    cacheable_lookups: int = 0
    cache_hits: int = 0
    stale_serves: int = 0
    cross_workspace_serves: int = 0
    non_cacheable_serves: int = 0
    invalidation_refusals: int = 0
    identity_mismatch_refusals: int = 0
    cross_workspace_refusals: int = 0


class SemanticResponseCache:
    """Response cache whose identity carries every leakage-relevant semantic.

    Structural rules, each enforced where it is cheap to enforce:

    1. **Admission** — only read-only requests under deterministic generation
       are stored; everything else bypasses.
    2. **Addressing** — entries live at the digest of the full canonical
       identity.
    3. **Serve-time re-verification** — a lookup first classifies a
       cross-workspace entry (counted refusal), then requires the stored
       entry's full component map to equal the request's, not merely the
       digest. A digest collision, truncation, or forged entry therefore
       cannot serve across any semantic boundary, and every refusal is
       counted.
    4. **Invalidation** — epoch-scoped by default; TTL optional, in logical
       ms. A refusal never serves.
    """

    def __init__(self, policy: CachePolicy | None = None) -> None:
        self.policy = policy or CachePolicy()
        self._entries: dict[str, _CacheEntry] = {}

    def lookup(self, request: Request, now_ms: float) -> tuple[bool, str | None, CacheCounters]:
        """Attempt a cache hit. Returns ``(hit, response, counters_delta)``.

        Non-cacheable requests bypass entirely: they are never served from
        cache regardless of content matches.
        """
        delta = CacheCounters()
        if not request.cacheable:
            return False, None, delta
        delta.cacheable_lookups += 1
        entry = self._entries.get(identity_digest(request))
        if entry is None:
            return False, None, delta
        if entry.workspace_id != request.workspace_id:
            # Classified before component comparison so a leak attempt is
            # counted as what it is even when other semantics differ too.
            delta.cross_workspace_refusals += 1
            return False, None, delta
        if entry.components != identity_components(request):
            # Serve-time re-verification failed: digest match, semantics
            # differ. This is the defense the naive cache lacks.
            delta.identity_mismatch_refusals += 1
            return False, None, delta
        if self.policy.epoch_scoped and entry.epoch != request.freshness_epoch:
            delta.invalidation_refusals += 1
            return False, None, delta
        if self.policy.ttl_ms is not None and now_ms - entry.stored_at_ms > self.policy.ttl_ms:
            delta.invalidation_refusals += 1
            return False, None, delta
        delta.cache_hits += 1
        return True, entry.response, delta

    def store(self, request: Request, response: str, now_ms: float, cost_cents: float) -> bool:
        """Store a response. Only cacheable requests are admitted."""
        if not request.cacheable:
            return False
        self._entries[identity_digest(request)] = _CacheEntry(
            digest=identity_digest(request),
            components=identity_components(request),
            workspace_id=request.workspace_id,
            response=response,
            epoch=request.freshness_epoch,
            stored_at_ms=now_ms,
            cost_cents=cost_cents,
        )
        return True


class NaiveContentKeyCache:
    """The unsafe contrast: content-key cache, no admission, TTL only.

    Deliberately implements the three classic defects the leaf's hard
    requirement forbids, so each can be *measured* rather than asserted:

    - content-only key (no tenant/agent/model/tool/generation semantics);
    - no cacheability admission (mutating requests are cached and served);
    - TTL-only invalidation (a changed epoch is ignored until the TTL lapses).
    """

    def __init__(self, ttl_ms: float) -> None:
        self.ttl_ms = ttl_ms
        self._entries: dict[str, _CacheEntry] = {}

    def _entry_for(self, request: Request, now_ms: float) -> _CacheEntry | None:
        entry = self._entries.get(naive_content_key(request))
        if entry is None:
            return None
        if now_ms - entry.stored_at_ms > self.ttl_ms:
            return None
        return entry

    def lookup(self, request: Request, now_ms: float) -> tuple[bool, _CacheEntry | None]:
        entry = self._entry_for(request, now_ms)
        if entry is None:
            return False, None
        return True, entry

    def store(self, request: Request, response: str, now_ms: float, cost_cents: float) -> None:
        self._entries[naive_content_key(request)] = _CacheEntry(
            digest=naive_content_key(request),
            components=identity_components(request),
            workspace_id=request.workspace_id,
            response=response,
            epoch=request.freshness_epoch,
            stored_at_ms=now_ms,
            cost_cents=cost_cents,
        )


def _run_baseline_cache(
    requests: Sequence[Request], price: PriceModel
) -> tuple[CacheCounters, list[str]]:
    """Baseline: every request is a full-price live call."""
    counters = CacheCounters()
    served = [f"live:{r.request_id}" for r in requests]
    counters.cost_cents = sum(price.call_cost(r.input_tokens, r.output_tokens) for r in requests)
    return counters, served


def _run_safe_cache(
    requests: Sequence[Request], price: PriceModel, policy: CachePolicy | None
) -> tuple[CacheCounters, list[str]]:
    """Safe strategy: full-identity cache, admission-gated, epoch-scoped."""
    counters = CacheCounters()
    served: list[str] = []
    cache = SemanticResponseCache(policy)
    for req in requests:
        hit, response, delta = cache.lookup(req, req.arrival_ms)
        for f in dataclasses.fields(CacheCounters):
            setattr(counters, f.name, getattr(counters, f.name) + getattr(delta, f.name))
        if hit and response is not None:
            served.append(response)
            continue
        cost = price.call_cost(req.input_tokens, req.output_tokens)
        counters.cost_cents += cost
        response = f"live:{req.request_id}"
        cache.store(req, response, req.arrival_ms, cost)
        served.append(response)
    return counters, served


def _run_naive_cache(
    requests: Sequence[Request], price: PriceModel, ttl_ms: float
) -> tuple[CacheCounters, list[str]]:
    """Naive strategy: content-key cache, no admission, TTL only."""
    counters = CacheCounters()
    served: list[str] = []
    cache = NaiveContentKeyCache(ttl_ms)
    for req in requests:
        hit, entry = cache.lookup(req, req.arrival_ms)
        counters.cacheable_lookups += 1  # the naive cache looks up everything
        if hit and entry is not None:
            counters.cache_hits += 1
            served.append(entry.response)
            if not req.cacheable:
                counters.non_cacheable_serves += 1
            if entry.epoch != req.freshness_epoch:
                counters.stale_serves += 1
            if entry.workspace_id != req.workspace_id:
                counters.cross_workspace_serves += 1
            continue
        cost = price.call_cost(req.input_tokens, req.output_tokens)
        counters.cost_cents += cost
        cache.store(req, f"live:{req.request_id}", req.arrival_ms, cost)
        served.append(f"live:{req.request_id}")
    return counters, served


def run_cache_strategy(
    requests: Sequence[Request],
    price: PriceModel,
    strategy: str,
    policy: CachePolicy | None = None,
    ttl_ms: float | None = None,
) -> tuple[CacheRunMetrics, list[str]]:
    """Run a request sequence through a cache policy and account the outcome.

    Requests are processed in list order; logical time is each request's
    arrival. A baseline (``strategy="baseline"``) bypasses caching entirely.
    Returns the frozen metrics and the responses served, in request order.
    """
    if not requests:
        raise ValueError("empty request sequence: nothing to measure")
    if strategy == "baseline":
        counters, served = _run_baseline_cache(requests, price)
    elif strategy == "safe":
        counters, served = _run_safe_cache(requests, price, policy)
    elif strategy == "naive":
        if ttl_ms is None:
            raise ValueError("naive strategy requires a ttl_ms")
        counters, served = _run_naive_cache(requests, price, ttl_ms)
    else:
        raise ValueError(f"unknown cache strategy: {strategy!r}")

    baseline = sum(price.call_cost(r.input_tokens, r.output_tokens) for r in requests)
    metrics = CacheRunMetrics(
        strategy=strategy,
        requests=len(requests),
        cost_cents=counters.cost_cents,
        baseline_cost_cents=baseline,
        savings_cents=baseline - counters.cost_cents,
        cacheable_lookups=counters.cacheable_lookups,
        cache_hits=counters.cache_hits,
        cache_hit_rate=(
            counters.cache_hits / counters.cacheable_lookups if counters.cacheable_lookups else 0.0
        ),
        stale_serves=counters.stale_serves,
        cross_workspace_serves=counters.cross_workspace_serves,
        non_cacheable_serves=counters.non_cacheable_serves,
        invalidation_refusals=counters.invalidation_refusals,
        identity_mismatch_refusals=counters.identity_mismatch_refusals,
        cross_workspace_refusals=counters.cross_workspace_refusals,
    )
    return metrics, served


# ---------------------------------------------------------------------------
# Prefix / KV reuse — exact, workspace-scoped, drift-refusing
# ---------------------------------------------------------------------------


def tokenize(text: str) -> tuple[str, ...]:
    """Deterministic whitespace tokenizer for fixture prompts.

    A stand-in for real tokenization; only exactness (equal token sequences)
    matters to the accounting, never the token alphabet.
    """
    return tuple(text.split())


def longest_common_prefix_len(a: Sequence[str], b: Sequence[str]) -> int:
    """Length of the exact common token prefix of two sequences."""
    n = 0
    for x, y in zip(a, b, strict=False):  # unequal tails after a split are the point
        if x != y:
            break
        n += 1
    return n


class PrefixReuseAccountant:
    """Workspace-scoped exact prefix/KV reuse accounting.

    Mirrors how provider-side prompt caching actually bills: the request is
    sent in full; the provider recognizes the longest previously-seen exact
    token prefix and bills those input tokens at ``cached_input_factor`` of
    the input price. Reuse therefore changes billing and (at the provider)
    latency, never request bytes — there is no approximate or fuzzy reuse to
    get wrong. Stores are keyed by (workspace, model): cross-tenant prefix
    pooling is *measurable* but structurally refused, and its foregone
    savings are recorded for the disposition.
    """

    def __init__(self, price: PriceModel) -> None:
        self.price = price
        self._last_tokens: dict[tuple[str, str], tuple[str, ...]] = {}
        self.cached_input_tokens = 0
        self.billed_input_tokens = 0
        self.drift_events = 0

    def _reuse_cost(self, request: Request, tokens: Sequence[str], cached: int) -> float:
        uncached = len(tokens) - cached
        return (
            cached / 1000.0 * self.price.cents_per_1k_input * self.price.cached_input_factor
            + uncached / 1000.0 * self.price.cents_per_1k_input
            + request.output_tokens / 1000.0 * self.price.cents_per_1k_output
        )

    def account(self, request: Request, tokens: tuple[str, ...]) -> float:
        """Account one request against its workspace+model store.

        Returns the cost in cents actually billed with reuse applied. The
        store keeps the most recent request's tokens per (workspace, model) —
        the sequential-turn Agent pattern. A branching-sharing trie is a
        refinement for the real experiment, not needed for the arithmetic.
        ``drift_events`` counts turns where reuse was bounded by the stored
        prefix diverging before the request did — the store-rotation signal a
        real experiment watches.
        """
        if not tokens:
            raise ValueError(f"request {request.request_id!r}: empty token sequence")
        key = (request.workspace_id, request.model)
        previous = self._last_tokens.get(key)
        cached = longest_common_prefix_len(tokens, previous) if previous else 0
        if previous and cached < len(previous):
            self.drift_events += 1
        cost = self._reuse_cost(request, tokens, cached)
        self.cached_input_tokens += cached
        self.billed_input_tokens += len(tokens) - cached
        self._last_tokens[key] = tokens
        return cost

    def account_pooled(self, request: Request, tokens: tuple[str, ...]) -> float:
        """The REJECTED variant: one global store pooled across workspaces.

        Buys back the foregone savings by letting one Workspace's requests
        land in a cache store another Workspace warmed — a cross-tenant
        context channel (content presence, billing correlation, and any
        provider-side KV residency become shared state). Never used by the
        safe strategy; measured only to price what the isolation rule costs.
        """
        key = ("*pooled*", request.model)
        previous = self._last_tokens.get(key)
        cached = longest_common_prefix_len(tokens, previous) if previous else 0
        cost = self._reuse_cost(request, tokens, cached)
        self.cached_input_tokens += cached
        self._last_tokens[key] = tokens
        return cost


def run_prefix_strategy(
    requests: Sequence[Request],
    price: PriceModel,
    strategy: str,
) -> PrefixRunMetrics:
    """Account a request sequence under workspace-scoped prefix reuse.

    Requests must arrive in issue order (turn order); the token sequence of
    each request is the whitespace tokenization of its message contents, so
    the fixtures control prefix sharing exactly. ``scoped`` bills reuse only
    within a (workspace, model) store; ``pooled`` prices the rejected
    cross-tenant variant for comparison; ``baseline`` bills full price.
    """
    if not requests:
        raise ValueError("empty request sequence: nothing to measure")
    if strategy not in {"scoped", "pooled", "baseline"}:
        raise ValueError(f"unknown prefix strategy: {strategy!r}")
    accountant = PrefixReuseAccountant(price)
    pooled = PrefixReuseAccountant(price)
    cost = 0.0
    pooled_cost = 0.0
    for req in requests:
        tokens = tokenize(" ".join(m["content"] for m in req.messages))
        if strategy == "baseline":
            full = price.call_cost(req.input_tokens, req.output_tokens)
            cost += full
            pooled_cost += full
        elif strategy == "scoped":
            cost += accountant.account(req, tokens)
            pooled_cost += pooled.account_pooled(req, tokens)
        else:  # pooled
            cost += pooled.account_pooled(req, tokens)
            pooled_cost = cost
    baseline = sum(price.call_cost(r.input_tokens, r.output_tokens) for r in requests)
    total_input = sum(r.input_tokens for r in requests)
    reporting = accountant if strategy == "scoped" else pooled
    cached = reporting.cached_input_tokens
    return PrefixRunMetrics(
        strategy=strategy,
        requests=len(requests),
        cost_cents=cost,
        baseline_cost_cents=baseline,
        savings_cents=baseline - cost,
        cached_input_tokens=cached,
        billed_input_tokens=total_input - cached,
        prefix_reuse_rate=(cached / total_input if total_input else 0.0),
        cross_tenant_pooling_foregone_cents=max(0.0, cost - pooled_cost),
        drift_events=accountant.drift_events if strategy == "scoped" else 0,
    )


# ---------------------------------------------------------------------------
# Batching — deterministic logical-time dispatch model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BatchWindow:
    """One dispatched batch and what became of its members."""

    start_ms: float
    request_ids: tuple[str, ...]
    end_ms: float
    deferred_ids: tuple[str, ...] = ()


@dataclass
class DispatchOutcome:
    """Per-request logical timeline plus the isolation bookkeeping.

    ``start_ms`` is when the request's batch was dispatched (held members
    share it); latency is measured from each request's own arrival, so
    queueing and window waits are part of the tail.
    """

    mode: str
    start_ms: dict[str, float] = field(default_factory=dict)
    end_ms: dict[str, float] = field(default_factory=dict)
    windows: list[BatchWindow] = field(default_factory=list)
    dependency_deferrals: int = 0
    misdelivered_responses: int = 0

    @property
    def makespan_ms(self) -> float:
        return max(self.end_ms.values(), default=0.0)


def _nearest_rank_p95(values: Sequence[float]) -> float:
    """Nearest-rank p95: smallest value whose rank is >= ceil(0.95 * n)."""
    if not values:
        raise ValueError("p95 of an empty sample is undefined")
    ordered = sorted(values)
    rank = math.ceil(0.95 * len(ordered))
    return ordered[rank - 1]


def _admit_window(
    window: Sequence[Request],
    completed: set[str],
    by_id: dict[str, Request],
    outcome: DispatchOutcome,
) -> tuple[list[Request], list[Request]]:
    """Split a window into ready and dependency-deferred requests.

    A request whose ``depends_on`` target has not completed is deferred in
    every mode — co-scheduling the pair would run a request whose input does
    not exist yet. A dependency on an unknown ID is loudly wrong.
    """
    ready: list[Request] = []
    deferred: list[Request] = []
    for r in window:
        if r.depends_on is not None and r.depends_on not in completed:
            if r.depends_on not in by_id:
                raise ValueError(f"request {r.request_id!r} depends on unknown {r.depends_on!r}")
            deferred.append(r)
            outcome.dependency_deferrals += 1
            continue
        ready.append(r)
    return ready, deferred


def _serve_solo(
    ready: Sequence[Request],
    dispatch_at: float,
    dispatch_overhead_ms: float,
    completed: set[str],
    outcome: DispatchOutcome,
) -> float:
    """Serve ready requests one per Invocation on a single lane; returns the lane clock."""
    clock = dispatch_at
    group: list[str] = []
    for r in ready:
        start = max(clock, r.arrival_ms)
        end = start + dispatch_overhead_ms + r.service_ms
        outcome.start_ms[r.request_id] = start
        outcome.end_ms[r.request_id] = end
        group.append(r.request_id)
        completed.add(r.request_id)
        clock = end
    outcome.windows.append(
        BatchWindow(start_ms=dispatch_at, request_ids=tuple(group), end_ms=clock)
    )
    return clock


def _serve_batch(
    ready: Sequence[Request],
    horizon: float,
    dispatch_overhead_ms: float,
    held: bool,
    completed: set[str],
    outcome: DispatchOutcome,
) -> None:
    """Serve a batch: overhead once, members' service back-to-back.

    ``held`` delivers every member at the batch's completion (hold-for-
    slowest, e.g. provider Batch APIs); otherwise members are delivered as
    their own service ends (streamed).
    """
    cursor = horizon + dispatch_overhead_ms
    ends: dict[str, float] = {}
    for r in ready:
        cursor += r.service_ms
        ends[r.request_id] = cursor
    deliver_at = max(ends.values()) if held else None
    for r in ready:
        outcome.start_ms[r.request_id] = horizon
        outcome.end_ms[r.request_id] = deliver_at if deliver_at is not None else ends[r.request_id]
        completed.add(r.request_id)
    outcome.windows.append(
        BatchWindow(
            start_ms=horizon,
            request_ids=tuple(r.request_id for r in ready),
            end_ms=max(ends.values()),
        )
    )


def _count_completion_order_misdelivery(ready: Sequence[Request], outcome: DispatchOutcome) -> None:
    """Naive demux: zip provider-ordered responses onto arrival-ordered requests.

    Held mode completes all members at one logical instant, so any
    difference between the orders misdelivers a response to another request,
    possibly another tenant's.
    """
    arrival_order = [r.request_id for r in ready]
    provider_order = sorted(arrival_order)
    for got, want in zip(provider_order, arrival_order, strict=True):
        if got != want:
            outcome.misdelivered_responses += 1


def _select_window(
    pending: Sequence[Request],
    dispatch_at: float,
    window_ms: float,
    batch_size: int,
    solo: bool,
) -> tuple[list[Request], list[Request]]:
    """Pick the next dispatch window and the not-yet-admitted remainder.

    A window is every request arrived by ``dispatch_at + window_ms``; batched
    modes cap it at ``batch_size`` and spill the overflow to the remainder.
    Solo ignores the cap: its lane serves one request at a time regardless.
    """
    horizon = dispatch_at + window_ms
    window = [r for r in pending if r.arrival_ms <= horizon]
    if not window:
        return [], []
    rest = [r for r in pending if r.arrival_ms > horizon]
    if not solo:
        kept = window[:batch_size]
        rest = window[batch_size:] + rest
        window = kept
    return window, rest


def _validate_dispatch_args(
    requests: Sequence[Request],
    mode: str,
    batch_size: int,
    window_ms: float,
    dispatch_overhead_ms: float,
) -> None:
    """Reject malformed schedules and unknown modes loudly."""
    if not requests:
        raise ValueError("empty request schedule: nothing to simulate")
    if mode not in {"solo", "batched-held", "batched-streamed"}:
        raise ValueError(f"unknown dispatch mode: {mode!r}")
    if mode != "solo" and batch_size < 1:
        raise ValueError("batch_size must be >= 1 for batched modes")
    if window_ms < 0 or dispatch_overhead_ms < 0:
        raise ValueError("window and overhead must be non-negative")
    if len({r.request_id for r in requests}) != len(requests):
        raise ValueError("duplicate request IDs in schedule")


def simulate_dispatch(
    requests: Sequence[Request],
    mode: str,
    batch_size: int,
    window_ms: float,
    dispatch_overhead_ms: float,
    demux: str = "identity",
) -> DispatchOutcome:
    """Simulate dispatch of an arrival schedule in logical time.

    Modes:

    - ``"solo"``: one call per Invocation (the shipped governed shape),
      dispatched the moment the single service lane frees. Every call pays
      ``dispatch_overhead_ms`` (gateway round trip) plus its own service.
    - ``"batched-held"``: a window of up to ``batch_size`` arrivals is
      dispatched together; the batch pays the overhead once and its members'
      service back-to-back; every member is delivered when the whole batch
      completes (hold-for-slowest delivery, e.g. provider Batch APIs).
    - ``"batched-streamed"``: same dispatch, but each member is delivered the
      moment its own service ends.

    Isolation mechanics measured:

    - **Dependency-aware admission**: a request whose ``depends_on`` target
      has not completed is deferred to a later window (counted) in every
      mode; a window where nothing is admissible is a dependency cycle and
      raises loudly.
    - **Response demux**: ``demux="identity"`` returns each response to its
      request ID (safe). ``demux="completion-order"`` zips responses in
      provider order onto requests in arrival order — in held mode every
      member completes at the same logical instant, so any difference
      between the two orders misdelivers a response to another request,
      possibly another tenant's. The misdelivery count is the measured leak.

    All timing is logical; no clock, network, or accelerator is touched.
    """
    _validate_dispatch_args(requests, mode, batch_size, window_ms, dispatch_overhead_ms)
    by_id = {r.request_id: r for r in requests}
    completed: set[str] = set()

    outcome = DispatchOutcome(mode=mode)
    # Stable sort: equal arrivals keep submission order — the order a naive
    # demux would rely on, which is exactly what the misdelivery probe bends.
    pending = sorted(requests, key=lambda r: r.arrival_ms)
    dispatch_at = pending[0].arrival_ms

    while pending:
        window, rest = _select_window(
            pending, dispatch_at, window_ms, batch_size, solo=mode == "solo"
        )
        if not window:
            dispatch_at = min(r.arrival_ms for r in pending)
            continue

        ready, deferred = _admit_window(window, completed, by_id, outcome)
        if not ready:
            raise ValueError(
                "batch window has no admissible request; dependency cycle among "
                f"{sorted(r.request_id for r in window)}"
            )

        if mode == "solo":
            _serve_solo(ready, dispatch_at, dispatch_overhead_ms, completed, outcome)
        else:
            _serve_batch(
                ready,
                dispatch_at + window_ms,
                dispatch_overhead_ms,
                held=mode == "batched-held",
                completed=completed,
                outcome=outcome,
            )
            if demux == "completion-order":
                _count_completion_order_misdelivery(ready, outcome)

        pending = sorted(rest + deferred, key=lambda r: max(r.arrival_ms, outcome.makespan_ms))
        dispatch_at = outcome.makespan_ms
        if pending and all(r.arrival_ms > dispatch_at for r in pending):
            dispatch_at = min(r.arrival_ms for r in pending)

    return outcome


def batch_metrics(
    requests: Sequence[Request], outcome: DispatchOutcome, batch_size: int | None = None
) -> BatchRunMetrics:
    """Freeze the issue's throughput/latency/utilization metrics for a run.

    Latency is measured from each request's arrival (queueing and window
    waits included). ``accelerator_busy_fraction`` is the model's utilization
    proxy — share of the makespan spent in service — and
    ``mean_batch_fill_rate`` the batch occupancy; neither is a hardware
    reading.
    """
    if not requests:
        raise ValueError("empty request schedule: nothing to measure")
    lats = [outcome.end_ms[r.request_id] - r.arrival_ms for r in requests]
    makespan = outcome.makespan_ms
    service_total = sum(r.service_ms for r in requests)
    fills = [len(w.request_ids) / batch_size for w in outcome.windows if batch_size is not None]
    return BatchRunMetrics(
        mode=outcome.mode,
        requests=len(requests),
        makespan_ms=makespan,
        throughput_rps=len(requests) / (makespan / 1000.0) if makespan else 0.0,
        mean_latency_ms=sum(lats) / len(lats),
        p95_latency_ms=_nearest_rank_p95(lats),
        accelerator_busy_fraction=(service_total / makespan if makespan else 0.0),
        mean_batch_fill_rate=(sum(fills) / len(fills) if fills else 0.0),
        window_waits_ms=sum(
            max(0.0, outcome.start_ms[r.request_id] - r.arrival_ms) for r in requests
        ),
        dependency_deferrals=outcome.dependency_deferrals,
        dependency_violations=0,
        misdelivered_responses=outcome.misdelivered_responses,
    )


# ---------------------------------------------------------------------------
# The deterministic representative workload
# ---------------------------------------------------------------------------

_PLATFORM_SYSTEM_PROMPT = (
    "You are a MAIstro Agent. Follow the Workspace policy. "
    "Use the bound tools. Cite project state. " * 10
)
_READ_QUESTION = "turn-N read: project state"
_WRITE_QUESTION = "turn-3 write: update project state"
_FOLLOWUP_QUESTION = "turn-6 follow up on t5"


def representative_workload() -> list[Request]:
    """Deterministic stand-in for concurrent MAIstro Agent work.

    Four Workspaces x six turns each, arriving interleaved inside one
    dispatch horizon, with the properties that exercise every measured axis:

    - a long shared platform prefix on every turn (prefix/KV reuse);
    - byte-identical read repeats at the same epoch (safe hits);
    - a mutating write with hot generation (must bypass every cache);
    - a read repeat after the Workspace's freshness epoch bumps (safe
      invalidation refusal; naive stale serve);
    - a dependent follow-up turn (batch admission);
    - all four Workspaces present byte-identical content (the adversarial
      leakage probe: every cache defect shows up as a cross-Workspace serve).
    """
    requests: list[Request] = []
    gen = GenerationSemantics(temperature=0.0, max_output_tokens=96)
    hot = GenerationSemantics(temperature=0.7, max_output_tokens=96)
    for w in range(1, 5):
        ws = f"ws-{w}"
        for turn in range(1, 7):
            if turn == 3:
                question, generation, cacheable = _WRITE_QUESTION, hot, False
            elif turn == 6:
                question, generation, cacheable = _FOLLOWUP_QUESTION, gen, True
            else:
                # Turns 1/2/4 are one repeated read at epoch 1; turn 5 is the
                # same read after the Workspace state bumped to epoch 2.
                question, generation, cacheable = _READ_QUESTION, gen, True
            epoch = 1 if turn < 5 else 2
            content = [
                {"role": "system", "content": _PLATFORM_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ]
            depends_on = f"{ws}-t5" if turn == 6 else None
            tokens = len(tokenize(_PLATFORM_SYSTEM_PROMPT + " " + question))
            requests.append(
                Request(
                    request_id=f"{ws}-t{turn}",
                    workspace_id=ws,
                    project_id=f"prj-{w}",
                    agent_id=f"agent-{w}",
                    capability="model.chat",
                    model="bench-model",
                    provider="bench",
                    messages=tuple(content),
                    tools=("search_project",),
                    generation=generation,
                    freshness_epoch=epoch,
                    cacheable=cacheable,
                    input_tokens=tokens,
                    output_tokens=96,
                    service_ms=40.0,
                    # Interleaved across Workspaces (5 ms apart within a
                    # turn, Workspaces in reverse ID order) so each batch
                    # window mixes tenants and bends completion-order demux.
                    arrival_ms=float((turn - 1) * 30 + (5 - w) * 5),
                    depends_on=depends_on,
                )
            )
    return requests


def workload_records(workload: list[Request], price: PriceModel) -> list[BenchmarkRecord]:
    """Run every strategy over the fixed workload and freeze the records."""
    if not workload:
        raise ValueError("empty workload: nothing to measure")
    records: list[BenchmarkRecord] = []
    for dispatch_mode, demux in (
        ("solo", "identity"),
        ("batched-held", "identity"),
        ("batched-held", "completion-order"),
        ("batched-streamed", "identity"),
    ):
        outcome = simulate_dispatch(
            workload,
            mode=dispatch_mode,
            batch_size=8,
            window_ms=20.0,
            dispatch_overhead_ms=25.0,
            demux=demux,
        )
        records.append(
            BenchmarkRecord(
                workload="representative",
                strategy=f"dispatch:{dispatch_mode}:{demux}",
                cache=None,
                prefix=None,
                batch=batch_metrics(
                    workload, outcome, batch_size=8 if dispatch_mode != "solo" else None
                ),
            )
        )
    for cache_strategy, policy, ttl in (
        ("baseline", None, None),
        ("safe", CachePolicy(epoch_scoped=True), None),
        ("naive", None, 10_000.0),
    ):
        cache_metrics, _ = run_cache_strategy(
            workload, price, cache_strategy, policy=policy, ttl_ms=ttl
        )
        records.append(
            BenchmarkRecord(
                workload="representative",
                strategy=f"cache:{cache_strategy}",
                cache=cache_metrics,
                prefix=None,
                batch=None,
            )
        )
    for prefix_strategy in ("baseline", "scoped", "pooled"):
        records.append(
            BenchmarkRecord(
                workload="representative",
                strategy=f"prefix:{prefix_strategy}",
                cache=None,
                prefix=run_prefix_strategy(workload, price, prefix_strategy),
                batch=None,
            )
        )
    return records


# ---------------------------------------------------------------------------
# Tests — hand-checked arithmetic, isolation properties, contract
# ---------------------------------------------------------------------------


def _req(**overrides: Any) -> Request:
    """Fixture builder: one canonical request with overrides."""
    base: dict[str, Any] = {
        "request_id": "r1",
        "workspace_id": "ws-a",
        "project_id": "prj-a",
        "agent_id": "agent-a",
        "capability": "model.chat",
        "model": "m",
        "provider": "p",
        "messages": (
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
        ),
        "tools": ("t",),
        "generation": GenerationSemantics(temperature=0.0, max_output_tokens=16),
        "freshness_epoch": 1,
        "cacheable": True,
        "input_tokens": 2,
        "output_tokens": 1,
        "service_ms": 10.0,
    }
    base.update(overrides)
    return Request(**base)


PRICE = PriceModel(
    name="bench",
    cents_per_1k_input=10.0,
    cents_per_1k_output=20.0,
    cached_input_factor=0.1,
)


class TestCacheIdentity:
    """The hard requirement: identity carries every anti-leakage semantic."""

    def test_identical_requests_share_identity(self) -> None:
        assert identity_digest(_req()) == identity_digest(_req())

    def test_workspace_is_an_identity_boundary(self) -> None:
        """Byte-identical prompts in different Workspaces never share identity."""
        a = identity_digest(_req(workspace_id="ws-a"))
        b = identity_digest(_req(workspace_id="ws-b"))
        assert a != b

    def test_every_semantic_field_moves_the_identity(self) -> None:
        variants = [
            _req(project_id="other"),
            _req(agent_id="other"),
            _req(capability="other"),
            _req(model="other"),
            _req(provider="other"),
            _req(messages=({"role": "system", "content": "sys"}, {"role": "user", "content": "Q"})),
            _req(tools=("other",)),
            _req(generation=GenerationSemantics(0.0, 32)),
        ]
        base = identity_digest(_req())
        for v in variants:
            assert identity_digest(v) != base, f"identity insensitive to {v!r}"

    def test_freshness_epoch_is_invalidation_not_identity(self) -> None:
        """Same read at a new epoch keeps its identity so invalidation fires."""
        assert identity_digest(_req(freshness_epoch=2)) == identity_digest(_req())
        assert "freshness_epoch" in INVALIDATION_DIMENSIONS
        assert "freshness_epoch" not in IDENTITY_FIELDS

    def test_non_semantic_fields_never_move_the_identity(self) -> None:
        """Arrival time and service time never change what a response means."""
        assert identity_digest(_req(arrival_ms=5.0)) == identity_digest(_req(arrival_ms=0.0))
        assert identity_digest(_req(service_ms=99.0)) == identity_digest(_req(service_ms=1.0))

    def test_naive_content_join_is_ambiguous_where_canonical_is_not(self) -> None:
        """The contrast case: ["a","b"] vs ["a,b"] collide under the naive key."""
        one = _req(messages=({"role": "user", "content": "a"}, {"role": "user", "content": "b"}))
        two = _req(messages=({"role": "user", "content": "a,b"},))
        assert naive_content_key(one) == naive_content_key(two)
        assert identity_digest(one) != identity_digest(two)

    def test_naive_key_blindly_spans_workspaces(self) -> None:
        assert naive_content_key(_req(workspace_id="ws-a")) == naive_content_key(
            _req(workspace_id="ws-b")
        )


class TestSemanticResponseCache:
    """Hand-checked cache arithmetic on the two-workspace fixture."""

    def _fixture(self) -> list[Request]:
        def mk(rid: str, ws: str, epoch: int, cacheable: bool) -> Request:
            return _req(
                request_id=rid,
                workspace_id=ws,
                messages=(
                    {"role": "system", "content": "s " * 500},
                    {"role": "user", "content": "q " * 100},
                ),
                freshness_epoch=epoch,
                cacheable=cacheable,
                input_tokens=600,
                output_tokens=100,
            )

        return [
            mk("r1", "ws-a", 1, True),  # first read: miss
            mk("r2", "ws-a", 1, True),  # identical read: safe hit
            mk("r3", "ws-a", 1, False),  # mutating: bypass even on content match
            mk("r4", "ws-a", 2, True),  # same read, data changed: invalidated
        ]

    def test_safe_cache_hand_checked_cost_and_hit_rate(self) -> None:
        # Full call: 600 in x 10c/1k + 100 out x 20c/1k = 6 + 2 = 8c.
        metrics, served = run_cache_strategy(self._fixture(), PRICE, "safe")
        assert metrics.baseline_cost_cents == pytest.approx(32.0)
        assert metrics.cost_cents == pytest.approx(24.0)
        assert metrics.savings_cents == pytest.approx(8.0)
        assert metrics.cacheable_lookups == 3  # r1, r2, r4
        assert metrics.cache_hits == 1
        assert metrics.cache_hit_rate == pytest.approx(1 / 3)
        assert metrics.stale_serves == 0
        assert metrics.cross_workspace_serves == 0
        assert metrics.invalidation_refusals == 1  # r4 after the epoch bump
        # r2 is served r1's cached response; r3 bypasses (non-cacheable);
        # r4 is a live call after invalidation.
        assert served == ["live:r1", "live:r1", "live:r3", "live:r4"]

    def test_naive_cache_saves_more_exactly_by_being_wrong(self) -> None:
        metrics, served = run_cache_strategy(self._fixture(), PRICE, "naive", ttl_ms=10_000.0)
        # r1 miss (8c); r2 hit; r3 served from cache (0c, but a mutating
        # request); r4 served stale across the epoch (0c).
        assert metrics.cost_cents == pytest.approx(8.0)
        assert metrics.savings_cents == pytest.approx(24.0)
        assert metrics.cache_hits == 3
        assert metrics.non_cacheable_serves == 1
        assert metrics.stale_serves == 1
        assert served[2] == "live:r1"  # r3 delivered r1's read response
        assert served[3] == "live:r1"  # r4 delivered the pre-bump response

    def test_adversarial_identical_workspaces_leak_only_under_naive_keying(
        self,
    ) -> None:
        ws_a = self._fixture()
        ws_b = [
            dataclasses.replace(r, request_id=r.request_id + "-b", workspace_id="ws-b")
            for r in self._fixture()
        ]
        safe, _ = run_cache_strategy(ws_a + ws_b, PRICE, "safe")
        assert safe.cross_workspace_serves == 0
        assert safe.cross_workspace_refusals == 0  # digest never even collides
        naive, _ = run_cache_strategy(ws_a + ws_b, PRICE, "naive", ttl_ms=10_000.0)
        assert naive.cross_workspace_serves >= 4  # every ws-b turn after ws-a's

    def test_non_deterministic_generation_is_never_admitted(self) -> None:
        hot = _req(generation=GenerationSemantics(0.7, 16), cacheable=False)
        cache = SemanticResponseCache()
        assert cache.store(hot, "resp", 0.0, 1.0) is False
        hit, _, delta = cache.lookup(hot, 0.0)
        assert hit is False
        assert delta.cacheable_lookups == 0

    def test_typed_fixture_rejects_cacheable_hot_generation(self) -> None:
        with pytest.raises(ValueError, match="non-deterministic"):
            Request(
                request_id="hot",
                workspace_id="w",
                project_id="p",
                agent_id="a",
                capability="c",
                model="m",
                provider="pr",
                messages=({"role": "user", "content": "q"},),
                tools=(),
                generation=GenerationSemantics(0.7, 16),
                freshness_epoch=1,
                cacheable=True,
                input_tokens=1,
                output_tokens=1,
                service_ms=1.0,
            )

    def test_serve_time_reverification_refuses_a_forged_entry(self) -> None:
        """A digest match with different components can never be served."""
        cache = SemanticResponseCache()
        real = _req()
        cache.store(real, "resp", 0.0, 1.0)
        forged = _req(agent_id="agent-evil")
        # Force the forged request's digest slot to hold the real entry: the
        # digest is an address, not the identity.
        cache._entries[identity_digest(forged)] = cache._entries[identity_digest(real)]
        hit, _, delta = cache.lookup(forged, 0.0)
        assert hit is False
        assert delta.identity_mismatch_refusals == 1
        assert delta.cross_workspace_refusals == 0

    def test_forged_cross_workspace_entry_is_classified_and_refused(self) -> None:
        cache = SemanticResponseCache()
        real = _req()
        cache.store(real, "resp", 0.0, 1.0)
        forged = _req(workspace_id="ws-b")
        cache._entries[identity_digest(forged)] = cache._entries[identity_digest(real)]
        hit, _, delta = cache.lookup(forged, 0.0)
        assert hit is False
        assert delta.cross_workspace_refusals == 1

    def test_epoch_scoped_policy_can_be_disabled_for_measurement(self) -> None:
        r1 = _req()
        r2 = _req(freshness_epoch=2)
        metrics, _ = run_cache_strategy(
            [r1, r2], PRICE, "safe", policy=CachePolicy(epoch_scoped=False)
        )
        assert metrics.cache_hits == 1
        assert metrics.invalidation_refusals == 0

    def test_baseline_strategy_bypasses_the_cache_entirely(self) -> None:
        metrics, served = run_cache_strategy(self._fixture(), PRICE, "baseline")
        assert metrics.cost_cents == pytest.approx(32.0)
        assert metrics.cacheable_lookups == 0
        assert served == ["live:r1", "live:r2", "live:r3", "live:r4"]

    def test_empty_sequence_is_rejected_not_silently_zero(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            run_cache_strategy([], PRICE, "safe")
        with pytest.raises(ValueError, match="empty"):
            run_prefix_strategy([], PRICE, "scoped")
        with pytest.raises(ValueError, match="empty"):
            simulate_dispatch(
                [], mode="solo", batch_size=1, window_ms=1.0, dispatch_overhead_ms=1.0
            )


class TestPrefixReuse:
    """Hand-checked exact-prefix accounting; workspace scoping; drift."""

    def _turn(
        self, rid: str, ws: str, system: str = "s " * 500, question: str = "q1 " * 100
    ) -> Request:
        return _req(
            request_id=rid,
            workspace_id=ws,
            messages=({"role": "user", "content": system + " " + question},),
            input_tokens=len(system.split()) + len(question.split()),
            output_tokens=100,
        )

    def test_exact_prefix_accounting_hand_checked(self) -> None:
        t1 = self._turn("t1", "ws-a")  # 500 system + 100 question tokens
        t2 = self._turn("t2", "ws-a", question="q2 " * 100)  # same system, new question
        metrics = run_prefix_strategy([t1, t2], PRICE, "scoped")
        # t1: 600 in x 10c/1k + 100 out x 20c/1k = 8c (no prior prefix).
        # t2: shares the exact 500-token system prefix: cached 500 x 10c/1k
        # x 0.1 = 0.5c; uncached 100 x 10c/1k = 1c; output 2c => 3.5c.
        assert metrics.baseline_cost_cents == pytest.approx(16.0)
        assert metrics.cost_cents == pytest.approx(8.0 + 3.5)
        assert metrics.savings_cents == pytest.approx(4.5)
        assert metrics.cached_input_tokens == 500
        # t1's 600 input tokens billed full price (no prior prefix) plus
        # t2's 100 uncached question tokens.
        assert metrics.billed_input_tokens == 700
        assert metrics.prefix_reuse_rate == pytest.approx(500 / 1200)
        # The stored prefix diverged before the request did (new question
        # after the shared system) — the documented store-rotation signal.
        assert metrics.drift_events == 1

    def test_prefix_drift_stops_reuse_and_is_counted(self) -> None:
        t1 = self._turn("t1", "ws-a")
        changed = self._turn("t2", "ws-a", system="X " + "s " * 499)
        metrics = run_prefix_strategy([t1, changed], PRICE, "scoped")
        assert metrics.cached_input_tokens == 0
        assert metrics.cost_cents == pytest.approx(16.0)
        assert metrics.drift_events == 1

    def test_workspace_scoping_refuses_cross_tenant_reuse_and_prices_it(
        self,
    ) -> None:
        t1 = self._turn("t1", "ws-a")
        t2 = self._turn("t2", "ws-b")  # byte-identical content, other tenant
        metrics = run_prefix_strategy([t1, t2], PRICE, "scoped")
        assert metrics.cached_input_tokens == 0
        assert metrics.cost_cents == pytest.approx(16.0)
        # Pooling would bill t2's full 600-token prefix at the cached
        # factor: 0.6c + 0 uncached + 2c output = 2.6c => 5.4c foregone —
        # bought with a cross-tenant context channel, so it stays refused.
        assert metrics.cross_tenant_pooling_foregone_cents == pytest.approx(5.4)

    def test_baseline_prefix_strategy_bills_everything_full_price(self) -> None:
        t1 = self._turn("t1", "ws-a")
        t2 = self._turn("t2", "ws-a")
        metrics = run_prefix_strategy([t1, t2], PRICE, "baseline")
        assert metrics.cost_cents == pytest.approx(16.0)
        assert metrics.savings_cents == 0.0
        assert metrics.prefix_reuse_rate == 0.0


class TestBatching:
    """Logical-time dispatch: overhead amortization, held vs streamed."""

    H = 50.0  # per-call dispatch overhead (gateway round trip), ms
    S = 100.0  # per-request service, ms

    def _four(self, *ids: str) -> list[Request]:
        return [
            _req(
                request_id=rid,
                arrival_ms=0.0,
                service_ms=self.S,
                input_tokens=0,
                output_tokens=0,
            )
            for rid in (ids or ("r1", "r2", "r3", "r4"))
        ]

    def test_solo_baseline_hand_checked(self) -> None:
        requests = self._four()
        outcome = simulate_dispatch(
            requests, "solo", batch_size=1, window_ms=0.0, dispatch_overhead_ms=self.H
        )
        # Serialized lane: each call = 50 overhead + 100 service = 150ms.
        assert [outcome.end_ms[f"r{i}"] for i in range(1, 5)] == [150.0, 300.0, 450.0, 600.0]
        metrics = batch_metrics(requests, outcome)
        assert metrics.makespan_ms == pytest.approx(600.0)
        assert metrics.throughput_rps == pytest.approx(4 / 0.6)
        assert metrics.mean_latency_ms == pytest.approx(375.0)
        assert metrics.p95_latency_ms == pytest.approx(600.0)  # nearest rank: max of 4
        assert metrics.accelerator_busy_fraction == pytest.approx(400 / 600)
        assert metrics.mean_batch_fill_rate == 0.0

    def test_held_batch_amortizes_overhead_and_holds_the_tail(self) -> None:
        requests = self._four()
        outcome = simulate_dispatch(
            requests, "batched-held", batch_size=4, window_ms=10.0, dispatch_overhead_ms=self.H
        )
        # Window closes at 10; overhead 50; service 4 x 100 => all at 460.
        assert all(outcome.end_ms[f"r{i}"] == pytest.approx(460.0) for i in range(1, 5))
        metrics = batch_metrics(requests, outcome, batch_size=4)
        assert metrics.makespan_ms == pytest.approx(460.0)
        assert metrics.throughput_rps == pytest.approx(4 / 0.46)
        assert metrics.mean_latency_ms == pytest.approx(460.0)
        assert metrics.p95_latency_ms == pytest.approx(460.0)
        assert metrics.accelerator_busy_fraction == pytest.approx(400 / 460)
        assert metrics.mean_batch_fill_rate == pytest.approx(1.0)
        assert metrics.window_waits_ms == pytest.approx(40.0)
        assert metrics.throughput_rps > 4 / 0.6  # throughput up vs solo
        assert metrics.mean_latency_ms > 375.0  # per-request latency up too

    def test_streamed_batch_delivers_per_request(self) -> None:
        requests = self._four()
        outcome = simulate_dispatch(
            requests,
            "batched-streamed",
            batch_size=4,
            window_ms=10.0,
            dispatch_overhead_ms=self.H,
        )
        # Staggered: 60+100, then +100 each => 160/260/360/460.
        assert [outcome.end_ms[f"r{i}"] for i in range(1, 5)] == [160.0, 260.0, 360.0, 460.0]
        metrics = batch_metrics(requests, outcome, batch_size=4)
        assert metrics.mean_latency_ms == pytest.approx(310.0)
        assert metrics.p95_latency_ms == pytest.approx(460.0)

    def test_completion_order_demux_misdelivers_identity_demux_does_not(
        self,
    ) -> None:
        requests = self._four("r4", "r3", "r2", "r1")  # arrival order != ID order
        safe = simulate_dispatch(
            requests,
            "batched-held",
            batch_size=4,
            window_ms=10.0,
            dispatch_overhead_ms=self.H,
            demux="identity",
        )
        naive = simulate_dispatch(
            requests,
            "batched-held",
            batch_size=4,
            window_ms=10.0,
            dispatch_overhead_ms=self.H,
            demux="completion-order",
        )
        assert safe.misdelivered_responses == 0
        # Held mode completes all four at one instant; zipping provider order
        # (sorted IDs) onto arrival order misdelivers all four — here, four
        # responses crossing between whatever tenants owned r1..r4.
        assert naive.misdelivered_responses == 4

    def test_dependency_aware_admission_defers_the_dependent(self) -> None:
        first = _req(
            request_id="dep", arrival_ms=0.0, service_ms=self.S, input_tokens=0, output_tokens=0
        )
        second = _req(
            request_id="child",
            arrival_ms=0.0,
            service_ms=self.S,
            input_tokens=0,
            output_tokens=0,
            depends_on="dep",
        )
        outcome = simulate_dispatch(
            [first, second],
            "batched-held",
            batch_size=4,
            window_ms=10.0,
            dispatch_overhead_ms=self.H,
        )
        assert outcome.dependency_deferrals == 1
        assert outcome.end_ms["dep"] < outcome.end_ms["child"]

    def test_dependency_cycle_is_loud_not_silent(self) -> None:
        a = _req(request_id="a", depends_on="b", input_tokens=0, output_tokens=0)
        b = _req(request_id="b", depends_on="a", input_tokens=0, output_tokens=0)
        with pytest.raises(ValueError, match="admissible"):
            simulate_dispatch(
                [a, b], "batched-held", batch_size=4, window_ms=10.0, dispatch_overhead_ms=1.0
            )

    def test_batch_size_cap_spills_to_the_next_window(self) -> None:
        requests = self._four()
        outcome = simulate_dispatch(
            requests, "batched-held", batch_size=2, window_ms=10.0, dispatch_overhead_ms=self.H
        )
        assert [len(w.request_ids) for w in outcome.windows] == [2, 2]
        metrics = batch_metrics(requests, outcome, batch_size=2)
        assert metrics.mean_batch_fill_rate == pytest.approx(1.0)

    def test_p95_is_nearest_rank(self) -> None:
        assert _nearest_rank_p95([10.0, 20.0, 30.0, 40.0]) == 40.0
        assert _nearest_rank_p95([10.0, 20.0, 30.0, 40.0, 50.0]) == 50.0
        assert _nearest_rank_p95([10.0]) == 10.0
        with pytest.raises(ValueError, match="empty"):
            _nearest_rank_p95([])


class TestRepresentativeWorkload:
    """The full deterministic workload: every issue metric, one record set."""

    def test_records_cover_every_issue_metric(self) -> None:
        workload = representative_workload()
        assert len(workload) == 24  # 4 workspaces x 6 turns
        records = workload_records(workload, PRICE)
        by_strategy = {r.strategy: r for r in records}
        assert len(by_strategy) == len(records)  # strategy names are unique

        baseline_batch = by_strategy["dispatch:solo:identity"].batch
        assert baseline_batch is not None
        held = by_strategy["dispatch:batched-held:identity"].batch
        assert held is not None
        # Batching amortizes dispatch overhead: throughput up, utilization up.
        assert held.throughput_rps > baseline_batch.throughput_rps
        assert held.accelerator_busy_fraction > baseline_batch.accelerator_busy_fraction
        assert held.misdelivered_responses == 0
        naive_demux = by_strategy["dispatch:batched-held:completion-order"].batch
        assert naive_demux is not None
        # Every batch window mixes tenants (interleaved arrivals in reverse
        # Workspace order), so completion-order demux misdelivers 20 of the
        # 24 responses; identity demux misdelivers none.
        assert naive_demux.misdelivered_responses == 20
        streamed = by_strategy["dispatch:batched-streamed:identity"].batch
        assert streamed is not None
        assert streamed.mean_latency_ms < held.mean_latency_ms

        cache_baseline = by_strategy["cache:baseline"].cache
        safe = by_strategy["cache:safe"].cache
        naive = by_strategy["cache:naive"].cache
        assert cache_baseline is not None and safe is not None and naive is not None
        # Safe: 8 hits (turns 2 and 4 in each Workspace), 4 epoch refusals
        # (turn 5), writes bypass; cost 57.04c vs the 85.52c baseline (16
        # read calls at 3.56c, 4 writes and 4 follow-ups at 3.57c).
        assert safe.cache_hits == 8
        assert safe.invalidation_refusals == 4
        assert safe.non_cacheable_serves == 0
        assert safe.stale_serves == 0
        assert safe.cross_workspace_serves == 0
        assert safe.cost_cents == pytest.approx(57.04)
        assert safe.baseline_cost_cents == pytest.approx(85.52)
        assert safe.savings_cents == pytest.approx(28.48)
        assert safe.cache_hit_rate == pytest.approx(0.4)
        # The naive cache "outperforms" it only by being wrong: 10.70c cost
        # from 3 misses, 18 cross-Workspace serves, 3 stale serves, and 3
        # mutating requests served from cache.
        assert naive.cost_cents == pytest.approx(10.70)
        assert naive.cache_hits == 21
        assert naive.cross_workspace_serves == 18
        # Turn 5 serves stale in every Workspace — including ws-1's own,
        # because TTL-only invalidation ignores the epoch bump everywhere.
        assert naive.stale_serves == 4
        assert naive.non_cacheable_serves == 3
        assert naive.savings_cents > safe.savings_cents

        prefix_scoped = by_strategy["prefix:scoped"].prefix
        prefix_pooled = by_strategy["prefix:pooled"].prefix
        assert prefix_scoped is not None and prefix_pooled is not None
        # Workspace-scoped reuse: 3232 of 3944 input tokens billed at the
        # cached factor (29.088c of 85.52c saved); 12 turns rotate the store.
        assert prefix_scoped.cached_input_tokens == 3232
        assert prefix_scoped.billed_input_tokens == 712
        assert prefix_scoped.savings_cents == pytest.approx(29.088)
        assert prefix_scoped.prefix_reuse_rate == pytest.approx(3232 / 3944)
        assert prefix_scoped.drift_events == 12
        assert prefix_scoped.cost_cents == pytest.approx(56.432)
        # Pooling across the Workspace boundary reuses 160 more tokens per
        # later Workspace (4.32c) — bought with a cross-tenant channel.
        assert prefix_pooled.cost_cents == pytest.approx(52.112)
        assert prefix_scoped.cross_tenant_pooling_foregone_cents == pytest.approx(4.32)
        assert prefix_pooled.cost_cents < prefix_scoped.cost_cents

    def test_workload_is_deterministic(self) -> None:
        a = workload_records(representative_workload(), PRICE)
        b = workload_records(representative_workload(), PRICE)
        assert a == b

    def test_identity_and_invalidation_dimensions_are_counted(self) -> None:
        assert len(IDENTITY_FIELDS) == 9
        assert len(INVALIDATION_DIMENSIONS) == 2
        components = identity_components(_req())
        for name in IDENTITY_FIELDS:
            assert name in components
        # The invalidation dimensions are request-level, not identity-level.
        assert identity_components(_req(freshness_epoch=2)) == components


class TestEvidenceContract:
    """The module's own guardrails, asserted so they cannot rot."""

    def test_module_declares_itself_advisory(self) -> None:
        assert ADVISORY_ONLY is True

    def test_records_are_frozen(self) -> None:
        metrics, _ = run_cache_strategy([_req()], PRICE, "safe")
        with pytest.raises(dataclasses.FrozenInstanceError):
            metrics.cost_cents = 0.0  # type: ignore[misc]
        record = BenchmarkRecord(workload="w", strategy="s", cache=metrics, prefix=None, batch=None)
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.strategy = "other"  # type: ignore[misc]

    def test_price_model_rejects_negative_and_invalid_factors(self) -> None:
        with pytest.raises(ValueError, match="negative"):
            PriceModel("bad", cents_per_1k_input=-1.0, cents_per_1k_output=1.0)
        with pytest.raises(ValueError, match="cached_input_factor"):
            PriceModel(
                "bad", cents_per_1k_input=1.0, cents_per_1k_output=1.0, cached_input_factor=1.5
            )

    def test_generation_semantics_reject_nonsense(self) -> None:
        with pytest.raises(ValueError, match="temperature"):
            GenerationSemantics(-0.1, 16)
        with pytest.raises(ValueError, match="max_output_tokens"):
            GenerationSemantics(0.0, 0)

    def test_unknown_strategies_are_loud(self) -> None:
        with pytest.raises(ValueError, match="unknown cache strategy"):
            run_cache_strategy([_req()], PRICE, "yolo")
        with pytest.raises(ValueError, match="unknown prefix strategy"):
            run_prefix_strategy([_req()], PRICE, "yolo")
        with pytest.raises(ValueError, match="unknown dispatch mode"):
            simulate_dispatch(
                [_req()], mode="yolo", batch_size=1, window_ms=1.0, dispatch_overhead_ms=1.0
            )

    def test_naive_strategy_requires_a_ttl(self) -> None:
        with pytest.raises(ValueError, match="ttl"):
            run_cache_strategy([_req()], PRICE, "naive")

    def test_duplicate_request_ids_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            simulate_dispatch(
                [_req(request_id="x"), _req(request_id="x")],
                mode="solo",
                batch_size=1,
                window_ms=1.0,
                dispatch_overhead_ms=1.0,
            )

    def test_module_imports_no_maistro_module(self) -> None:
        tree = ast.parse(inspect.getsource(sys.modules[__name__]))
        imported = {
            node.names[0].name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        }
        assert "maistro" not in imported

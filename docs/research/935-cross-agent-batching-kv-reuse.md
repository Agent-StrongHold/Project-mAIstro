# M8-F2 research note — cross-Agent batching, prefix/KV reuse, and semantic caching

Leaf: #935. Epic: #905. Initiative: #879.

## Hypothesis

Batching independent Agent inference, reusing stable prefix or KV state, and caching semantic responses for bounded read-only cases could raise throughput and cut cost without breaking isolation or freshness.

## Canonical seam

The governed model-serving path is one seam, but it is not the only shipped one. `CostAwareRouter` in `packages/maistro-core/src/maistro/providers/router.py` selects a model when the request does not name one; a Binding pin or request-named alias outranks it. `packages/maistro-core/src/maistro/capabilities/model_chat.py` admits the call as Binding, then Invocation, then the single approved gateway provider in `packages/maistro-core/src/maistro/capabilities/providers/llm_gateway.py`. That provider is the module allowed to hold the HTTP client for governed model egress. The governed path does not share a batch, a prefix cache, or a response cache across Agents.

It is also not the only shipped egress: `quality/model-egress.json` records multiple direct model callers still awaiting governed migration, including `maistro.agents.conductor`, `maistro.events.handlers`, and `maistro_bootstrap.builders.responses_callable`. The server-backed conductor reaches `maistro.agents.conductor._call_gateway`, which posts directly to `/chat/completions` without CostAwareRouter, Binding, or Invocation. Those callers share none of the governed path's caches either.

## Cache identity — the leaf's hard requirement, made executable

The issue requires that "cache identity must include all semantics needed to prevent tenant/context leakage". The harness implements this as an explicit, ordered identity tuple — workspace, project, agent, capability, model, provider, messages, tools, generation semantics — with an injective canonical JSON serialization (sorted keys, no whitespace), plus **serve-time re-verification**: a cached entry stores the full component map and a lookup requires component equality, not merely digest equality, so a digest collision, truncation, or forged entry can never serve across a semantic boundary. Cross-workspace entries are classified and refused before component comparison, so a leak attempt is counted as what it is even when other semantics also differ.

Two design decisions are recorded because a future implementer will be tempted to reverse them:

- **Freshness is invalidation, not identity.** The freshness epoch is deliberately excluded from the identity tuple and guarded at serve time instead. Folding it into the key would strand stale entries under old keys (unbounded growth, no observable invalidation) and would hide the invalidation complexity this leaf is asked to measure. The invalidation dimensions are the epoch and the TTL.
- **Admission is separate from identity.** Only read-only requests under deterministic generation (`temperature == 0`) are ever stored or served; mutating requests bypass entirely, and a non-deterministic request cannot even declare itself cacheable (the type rejects it).

The naive contrast — content-only key, no admission control, TTL-only invalidation — is implemented so each omitted semantic can be *measured*, not asserted.

## Record

This note still reports no real-provider experiment: the deterministic CI environment holds no credentials, and the governed seam ships no cache, batch, or cross-Agent prefix reuse to measure. Implementing any of the three on that seam now would be a second model-serving path. Caveat (reassessed per review): production traffic is not confined to the governed seam — the direct egress callers recorded in `quality/model-egress.json` still post outside CostAwareRouter/Binding/Invocation, so any future batching / KV-reuse work must either cover those paths as well or scope itself explicitly to the governed seam and treat the direct callers as remaining migration debt.

What this change adds is the reproducible measurement machinery the benchmark procedure needs, as a separated research artifact:
`packages/maistro-rsi/tests/test_m8f2_caching_batching_research.py` (test suite only; it imports no maistro module, so it cannot become an authority by accident — M8 guardrails 1-2; 40 checks, all passing at this head). It implements the issue's full measure list — throughput, an accelerator-utilization *proxy* (busy fraction and batch fill; never a hardware reading), p95 latency, cache hit rate, token/cost savings in `ModelMetadata` units, stale-result rate, cross-Workspace isolation risk, and invalidation complexity (the 9 identity dimensions + 2 invalidation dimensions, counted) — over deterministic logical-time fixtures.

What the fixtures demonstrate (synthetic arithmetic and isolation mechanics, **not** evidence about real models or providers):

- **The identity requirement is load-bearing, not ceremonial.** On a 24-request adversarial workload where all four Workspaces present byte-identical content, the safe cache (full identity, epoch-scoped, admission-gated) costs 57.04¢ against an 85.52¢ full-price baseline (−33.3%; hit rate 0.400) with **zero** stale serves, **zero** cross-Workspace serves, and **zero** mutating requests served. The naive cache "saves" more — 10.70¢, a 0.875 hit rate — and pays for it with **18 cross-Workspace serves, 4 stale serves (including a Workspace's own stale read — TTL-only invalidation ignores epoch bumps everywhere), and 3 mutating requests served from cache**. Every cent of the naive cache's extra "savings" is a correctness violation the identity semantics forbid.
- **Freshness scoping is what makes invalidation observable**: the epoch bump produces exactly 4 refusals (one per Workspace) on the safe cache and exactly 4 stale serves on the naive one — the same traffic, the difference is the invalidation policy.
- **Prefix/KV reuse**: exact longest-common-prefix accounting bills 3232 of 3944 input tokens at the 0.1 cached-input factor (29.088¢ saved, 81.9% reuse rate) with Workspace-scoped stores; 12 turns rotate a store (reuse bounded by divergence, the drift signal a real experiment watches). Pooling one store across the Workspace boundary is measurably cheaper — 52.112¢, 94.1% reuse — **because it leaks**: 160 tokens per later Workspace ride a cross-tenant context channel. The 4.32¢ difference is the recorded price of the isolation rule, and it is rejected.
- **Batching**: with a 25 ms per-call dispatch overhead, 40 ms service, a 20 ms window, and batch size 8 over the interleaved 24-request schedule, held batching cuts the makespan 1565 → 1145 ms (15.34 → 20.96 req/s, utilization proxy 0.613 → 0.838, batch fill 0.75) — dispatch-overhead amortization is real but bounded by the overhead's share of a call. Held delivery raises mean latency for early members and completion-order demux **misdelivers 20 of 24 responses** (responses crossed between tenants) where identity-keyed demux misdelivers none; streamed delivery keeps the throughput win and lowers mean latency (530 ms vs held 643 ms vs solo 730 ms). Dependency-aware admission deferred the 4 dependent follow-ups out of their dependency's window under solo dispatch — the guard that stops a batch from running a request whose input does not exist yet — and a dependency cycle raises loudly rather than deadlocking.

Executed probe record (head 34795962548, 2026-10-08):
`uv run pytest packages/maistro-rsi/tests/test_m8f2_caching_batching_research.py -q` → 40 passed;
`uv run pytest packages/maistro-rsi/tests -q` → 1273 passed, 3 skipped;
`uv run ruff check` and `uv run ruff format --check` clean;
`uv run python scripts/check-suite-inventory.py` → 17 suites match (delta +40 recorded in `docs/testing/inventory-notes/935-cross-agent-batching-kv-reuse.md`).

## Benchmark procedure (what a real experiment must do)

1. Ride the governed seam only: Instrument the Binding → Invocation → gateway path (and state explicitly which of the `quality/model-egress.json` direct callers are in or out of scope). Per the epic measurement contract, throughput and latency numbers come from canonical Invocation records, never side logs.
2. Reproduce the identity semantics of the harness behind the governed seam as a *measurement* layer first (key construction + hit/stale/refusal counters), with no serving behavior change, and confirm the isolation probes (byte-identical cross-Workspace content, epoch bumps, forged identities) are refused in production shape.
3. Enable provider-side prefix caching (the shipped opt-in Anthropic breakpoint pattern) for a Workspace-scoped cohort and measure real cached-input billing and latency deltas against the same cohort without it.
4. Batch only where the provider offers a batch surface behind the same seam; measure throughput, p95/p99 latency (held-mode tail drag included), and cost per Invocation. Dependency-aware admission and identity-keyed demux are preconditions, not options.
5. For semantic caching, admit only read-only + deterministic-generation Invocations, epoch-scope them per Workspace, and report stale-result rate and cross-Workspace serve count as first-class metrics — both must be identically zero for an INCUBATE recommendation.
6. Update the disposition here with real numbers; the synthetic fixtures above are arithmetic validation only and must never be quoted as provider evidence.

## Disposition

**WATCH** — unchanged from the merged disposition, now with the machinery that makes the experiment runnable and the identity semantics specified by evidence. Move to **INCUBATE** when a real experiment on the governed seam (procedure above) shows a material cost or throughput win at zero cross-Workspace serves, zero stale serves, and bounded p95 regression, with the direct-egress callers covered or explicitly scoped out. **REJECT** if real runs show stale serves or cross-Workspace serves under the full-identity cache (the identity construction has failed and must not ship), or if the batching/caching win does not survive honest accounting (held-mode tail latency and invalidation complexity included).

No adoption is authorized by this note; this change adds no product code, no flag, no cache, and no second model-serving path.

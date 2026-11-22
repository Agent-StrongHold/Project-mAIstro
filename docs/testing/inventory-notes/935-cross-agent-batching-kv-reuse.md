---
inventory-delta:
  packages/maistro-rsi/tests: +40
---
# 935 M8-F2: cross-Agent batching / prefix-KV reuse / semantic caching harness (+40)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #935 (epic M8-F #905, initiative #879) asked for an evaluation of cross-Agent
batching, prefix/KV reuse, and semantic response caching, with a hard requirement:
cache identity must include all semantics needed to prevent tenant/context leakage.
No provider or gateway experiment exists (the deterministic CI holds no credentials,
and the governed seam has no cache to measure), so the research record
(`docs/research/935-cross-agent-batching-kv-reuse.md`) keeps its WATCH disposition and
this change adds the reproducible benchmark machinery the issue's measure list
demands, as one self-contained test module in `packages/maistro-rsi/tests/`
(`test_m8f2_caching_batching_research.py`, +40 node IDs).

The module is deliberately test-side and imports no maistro module (asserted via AST
in-suite): it is research evidence, not product code (M8 guardrails 1-2), so no
vulture/reachability identity changes. The 40 cases validate, on deterministic
hand-checked fixtures: the cache identity construction (every semantic field —
workspace, project, agent, capability, model, provider, messages, tools, generation —
moves the digest while arrival/service timing provably does not; the naive
content-join key demonstrably collides on `["a","b"]` vs `["a,b"]` and spans
workspaces), the freshness epoch as an invalidation dimension rather than an identity
one, serve-time re-verification refusing forged entries classified as identity-
mismatch or cross-workspace refusals, safe-cache arithmetic (8¢ calls, 1/3 hit rate,
0 stale) against the naive cache saving more *exactly by being wrong* (serving a
mutating request, a stale post-epoch read, and cross-Workspace serves), exact
longest-common-prefix reuse arithmetic (500 cached tokens at a 0.1 factor = 4.5¢
saved) with workspace scoping refusing cross-tenant reuse and pricing the foregone
savings, prefix drift stopping reuse and being counted, the batching model's
hand-checked timeline (solo 150/300/450/600 ms vs held 460 ms: throughput up,
mean latency up, utilization 2/3 → 0.87), completion-order demux misdelivering all
four responses where identity demux misdelivers none, dependency-aware admission
deferring dependents and raising on cycles, and the full 24-request adversarial
workload where all four Workspaces present byte-identical content — the safe
configuration posts 0 stale / 0 cross-Workspace serves while the naive one posts 18
cross-Workspace serves, 4 stale serves, and 3 mutating requests served from cache,
and pooled prefix reuse is measurably cheaper (52.112¢ vs 56.432¢) exactly because
it leaks. Plus the evidence-only contract itself: advisory marker, frozen records,
loud rejections of empty/duplicate/unknown inputs, and the no-maistro-imports AST
check.

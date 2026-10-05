# M8-B4 research note — speculative parallel model calls with early stopping or verifier selection

Leaf: #917. Epic: #900. Initiative: #879.

## Hypothesis

For high-value/latency-sensitive tasks, launching multiple heterogeneous model
candidates in parallel and stopping/selecting early may reduce tail latency or
improve success enough to justify extra token spend.

## Canonical seam

The experiment runs on the one governed model seam, not beside it: every
candidate call crosses `ModelChatEgress` (`packages/maistro-core/src/maistro/capabilities/model_chat.py`)
— Binding pin → Invocation → the approved gateway Provider
(`capabilities/providers/llm_gateway.py`) — with `CostAwareRouter`
(`packages/maistro-core/src/maistro/providers/router.py`) supplying the
canonical low-latency-first fallback chain (ADR-079) that the serial baseline
escalates through. Each candidate is its own governed Invocation with its own
effect key: duplicate physical calls are measured, never hidden or merged, and
the harness's ledger audit (`count_invocations`) fails the run if any physical
call does not resolve to exactly one Invocation — a cancelled candidate
surfaces as an `UNKNOWN` Invocation, exactly as production cancellation would.

Nothing canonical changed: no Invocation semantics, no router policy, no
product path, no flag. The harness is `scripts/bench_speculative_parallel.py`
(offline, deterministic) and the recorded numbers live in
`docs/benchmarks/speculative-parallel-baseline.json`.

## Method

Four candidate-delivery strategies over a fixed 120-task workload, judged on
identical physics per (task, model) via a seeded pure outcome schedule
(common random numbers):

- **serial-fallback** — canonical baseline: `CostAwareRouter.fallback_chain`
  tried one call at a time, escalating on the first unacceptable answer
  (quick-8b → balanced-70b → strong-405b);
- **single-strong** — always pin strong-405b, once;
- **parallel-early-stop** — launch all three, deliver the first acceptable
  completion, cancel the rest (billed input + output accrued to the cancel);
- **parallel-verifier** — launch all three, wait for all, select by an
  independent verifier whose score is truth ±0.1 noise (width 0.2).

Simulated provider physics (clearly not production traffic): catalog latencies
900/2400/5200 ms × jitter ±40%, 2% independent transient failures, and a
correlated outage — one task in seven loses one provider for the whole task.
Two topologies: **diverse** (one provider per model) and **same** (all models
behind one provider), the control for the provider-diversity question.
Metrics per the issue: p50/p95 latency, tokens/cost, success quality,
correlated-failure survival, cancellation waste, provider-diversity benefit,
and verifier-selection error. Reported latencies are simulated model
milliseconds; real wall-clock only exercises the governed path.

## Record (seed 917, 120 tasks, 2% transient failure, outage every 7th task)

| topology | strategy | p50 | p95 | success | score | cost | waste | outage succ. | verifier err. |
|---|---|---|---|---|---|---|---|---|---|
| diverse | serial-fallback | 1047 ms | 4054 ms | 100% | 0.748 | 92.1¢ | 14.1¢ | 100% | — |
| diverse | single-strong | 5132 ms | 6939 ms | 88.3% | 0.818 | 450.0¢ | 36.6¢ | 61.1% | — |
| diverse | parallel-early-stop | 1047 ms | 3003 ms | 100% | 0.748 | 434.9¢ | 356.8¢ | 100% | — |
| diverse | parallel-verifier | 5132 ms | 6939 ms | 100% | 0.908 | 610.0¢ | 254.7¢ | 100% | 13.3% |
| same | serial-fallback | 1077 ms | 9399 ms | 85.0% | 0.629 | 116.8¢ | 57.0¢ | 0% | — |
| same | single-strong | 5132 ms | 6939 ms | 79.2% | 0.732 | 426.0¢ | 55.5¢ | 0% | — |
| same | parallel-early-stop | 1077 ms | 6247 ms | 85.0% | 0.629 | 412.6¢ | 352.7¢ | 0% | — |
| same | parallel-verifier | 5132 ms | 6939 ms | 85.0% | 0.776 | 577.4¢ | 267.4¢ | 0% | 10.8% |

Findings:

1. **Early stopping's latency win is real but narrow.** Against the serial
   cascade it only moves the tail (p95 4054 → 3003 ms, −26%); p50 is
   identical because the first acceptable completion is usually the same
   quick-8b answer the cascade would have stopped at. Success and delivered
   quality are unchanged (100%, 0.748).
2. **The spend is brutal.** Early stop costs 4.7× the serial baseline
   (434.9¢ vs 92.1¢), and 356.8¢ — 82% of it — is waste: tokens billed to
   cancelled or non-delivering candidates (217,994 units cancelled
   mid-flight of 360 physical calls). Verifier selection costs 6.6×.
3. **Verifier selection buys quality, not latency.** Delivered score rises to
   0.908 (vs 0.748) but latency is the worst of all strategies (it waits for
   the slowest candidate; p95 6939 ms), and the noisy verifier picks a
   strictly worse answer than the best available on 13.3% of tasks.
4. **Single-strong is dominated.** No retry on failure (88.3% success),
   strong-model latency, and 450¢ — roughly early-stop's cost for worse
   availability.
5. **Provider diversity is load-bearing for parallelism.** With all candidates
   behind one provider, every correlated outage kills the whole fan-out
   (outage-task success 0% across strategies) and early-stop's p95 degrades
   3003 → 6247 ms; the diverse topology survives every outage by completing
   on another provider. Heterogeneous *providers*, not just heterogeneous
   models, are what speculative parallelism monetizes.
6. **Ledger honesty held.** 157/360/360/120 physical calls map 1:1 to
   governed Invocations per run; the 212 `UNKNOWN` rows in the early-stop run
   are the cancelled candidates — visible, billed, and never merged.

## Threats to validity

The physics is a deterministic simulation, not production traffic: latency
bands, failure rates, quality curves, and the 0.2 verifier-noise width are
assumptions, and one synthetic task shape stands in for workload mix. The
acceptability oracle shared by the cascade and early-stop is ground truth —
generous to both, since production callers must actually evaluate answers
before escalating or stopping. No cross-provider rate limits, pricing
variance, or gateway queueing are modeled, all of which erode parallel fan-out
further. Real-traffic replay against the governed seam would be the next
measurement step, and it belongs to the model-routing/evaluation owner.

## Disposition

**WATCH.** The simulation shows a real but narrow tail-latency win (−26% p95
at equal quality) bought with a 4.7× token multiple and 82% waste, a
quality win from verifier selection that costs the worst latency and carries a
13.3% selection error, and a hard dependency on provider diversity that
single-gateway deployments do not have. Nothing here justifies changing
canonical Invocation semantics or making speculative fan-out a production
path. Graduate triggers to re-open: (a) a measured workload where tail latency
is the binding SLO and the token multiple is acceptable to its owner, (b) a
deployment with genuine multi-provider egress behind the governed seam, and
(c) a verifier whose selection error is bounded on real traffic. Production
adoption, if any, routes to the existing model-routing/evaluation owner per
the epic exit contract.

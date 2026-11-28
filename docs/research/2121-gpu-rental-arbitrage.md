# M8-F3 research note — opportunistic GPU-rental arbitrage and capability-aware fleet routing

Leaf: #2121. Epic: #905. Initiative: #879. Sibling leaves: #934 (M8-F1,
heterogeneous fleet benchmark), #935 (M8-F2, batching/KV reuse — dispositioned
in their own notes).

## Hypothesis

A 22–24 h/day autonomous software factory can buy inference capacity from
opportunistic marketplace GPU rentals (Vast/Salad/Prime-Intellect-class hosts)
at a lower **expected accepted-task cost** than fixed hardware or on-demand
cloud **if — and only if — selection is capability-aware**: offers are priced
at their *availability* (advertised prices are leads, not guarantees), and a
(GPU, quantization, stack, context, task) combination with no verified
compatibility record is ineligible rather than guessed. The null hypothesis
the epic guards against: any arbitrage "win" whose mechanism requires
provisioning infrastructure on trust of unverified listings, or widening the
model-egress authority path.

This is a research/experiment issue, **not** authorization to provision
infrastructure, rent hardware, spend money, or change production routing.

## Canonical seam

The experiment touches no shipped seam and opens no egress:

- **Model selection** remains `CostAwareRouter.select(task, budget, scope)`
  (`packages/maistro-core/src/maistro/providers/router.py`, ADR-038 fallback
  semantics, ADR-079 metadata) — untouched. This bench does not route model
  calls at all; it prices *infrastructure* offers. Marketplace discovery here
  grants no model egress: `quality/model-egress.json` is not read and not
  written by the harness, and the script imports no network module (pinned by
  AST in `tests/test_bench_gpu_rental_arbitrage.py`, so the proof cannot rot).
- **No provisioning path exists.** The harness reads a synthetic feed, ranks
  it, and reports. Every "rental" in the replay is arithmetic; the billing cap
  fails closed; nothing outside the process is touched.

Three structural facts frame the question (all pinned by tests):

1. **Sticker price is not expected cost.** The feed's cheapest listed offer is
   an unverified $0.02/h RTX 3060 lead. Priced at its modeled availability
   (10%), its risk-adjusted hourly cost ($0.57/GPU-h) exceeds every verified
   offer's. The issue's rule "treat advertised prices as unverified leads,
   never availability guarantees" becomes arithmetic, not a warning label.
2. **Capability is the binding constraint, not price.** Of 15 feed offers, 8
   are rejected at ingestion (stale, false price, unapproved host, dead
   capacity, sub-floor reliability, wrong schema) and the leads lose on
   availability; of the survivors, only entries with a *verified* capability
   cell can serve a workload at all. The registry is deliberately sparse: most
   (GPU, quant, stack/version, context, concurrency, task-class) cells are
   absent, and absent means INELIGIBLE. An anomalous $0.06/h A40 lead would
   still be ineligible on its host's trust status even if its price were real.
3. **Fixed-hardware commitment is a coverage bet.** Pinning the RTX 3090
   serves the four light workload classes and fails closed on the two heavy
   ones (no verified 70B-class cell on 24 GB) — the route a price-blind
   operator cannot take at any price.

## Method

`scripts/bench_gpu_rental_arbitrage.py` is the offline/replay evaluator
(recorded run in `docs/benchmarks/gpu-rental-arbitrage-baseline.json`,
runnable via the manual `gpu-rental-arbitrage-bench.yml` workflow;
deterministic and offline, blake2b seeds — same seed, byte-identical report,
including no wall-clock field):

- **Offer schema (versioned, `1`)** — price/hour, attached CPU rate, monthly
  storage, egress $/GB, reliability claim, min duration, preemption flag,
  provisioning start time, capacity, region, host, price basis
  (`advertised` = unverified lead, `verified` = audited history), capture
  timestamp, TTL. Freshness is `captured_at + ttl_seconds > now`, **re-checked
  at execution time**, so an offer fresh at ranking but stale at rental is
  refused. Eligibility is contract-ordered: schema version → price validity
  (finite, positive; CPU rate finite, non-negative) → freshness → host trust
  (`APPROVED_HOSTS`) → reliability floor → capacity → known GPU → capability
  cell present **and** compatible → VRAM fit. The first failing rule names the
  rejection; a rejected offer is never ranked.
- **Capability registry** — keyed by (GPU, quantization, serving stack +
  version, context bucket, concurrency, task class) → decode throughput,
  modeled acceptance, warmup seconds, provenance. Every record in the fixture
  is `synthetic-fixture`; **zero cells are hardware-measured**, and the report
  prints that count as 0. Unknown compatibility is ineligible, never guessed;
  the published hardware facts (e.g. the P40's lack of a weight-only int4
  path) reject before any registry guess could.
- **Ranking on expected accepted-task cost** — risk-adjusted GPU-hour (full
  hourly cost incl. amortized storage/egress ÷ modeled availability) ×
  max(modeled session seconds — warmup + provisioning start + decode —,
  minimum-rental window) ÷ 3600 ÷ `SESSION_TASKS` ÷ acceptance (retries
  priced as attempts-per-accepted-task) × preemption redo multiplier. The
  rental minimum is honored at session level, before amortization: a session
  shorter than the minimum still pays the whole minimum billable window. The
  redo multiplier is geometric, `1 + 0.5·p/(1−p)` at `PREEMPTION_RATE = p`:
  the replay executor retries a preempted task until completion with a fresh
  preemption draw per attempt, so the expected number of preemptions before
  completion is p/(1−p), each repeating the post-checkpoint half. Secondary
  diagnostics: risk-adjusted $/GPU-hour and $/million accepted output
  tokens.
- **Routes** — `fixed-gpu` (pinned RTX 3090, cheapest eligible listing for it),
  `cheapest-listed` (the naive price sort), `cheapest-eligible` (full
  eligibility + expected-cost minimum), `quality-adjusted` (cheapest-eligible
  constrained to the `QUALITY_FLOOR` acceptance floor).
- **Failure-injection replay** — eight modes over a chat batch under
  idempotent execution: every task carries an idempotency key; a preempted
  attempt bills only its post-checkpoint tail and requeues under the SAME key;
  a completed key is never executed or billed twice; the billing cap refuses
  further spend rather than exceeding it.
- **Annual sensitivity** — `always-rented`, `owned-16GB-plus-cloud` (capex
  amortized 3 yr + power + 40% cloud overflow), and `heavy-model-on-demand`
  (owned base + 25% of hours at a 2× heavy premium), each at 22 and 24 h/day
  over 365 days, under lead/mid/high price bases. The lead base exists only to
  show what the anomalous prices would be worth IF TRUE.

## Record

All numbers below are **simulation** — authored model over a synthetic feed,
with zero hardware measurements (per-file `data_class: simulation` markers in
the baseline JSON).

Route selection per workload class (expected accepted-task cost in USD,
authored model):

| workload        | fixed-gpu (3090)  | cheapest-listed        | cheapest-eligible | exp. ¢/task | $/M-acc-tok |
|-----------------|-------------------|------------------------|-------------------|------------:|------------:|
| chat            | vast-3090-021     | lead-3060-002 (trap)   | vast-3090-021     | 0.1554      | 7.97        |
| classification  | vast-3090-021     | lead-3060-002 (trap)   | vast-3090-021     | 0.1523      | 133.52      |
| extraction      | vast-3090-021     | lead-3060-002 (trap)   | vast-3090-021     | 0.1621      | 3.43        |
| summarization   | vast-3090-021     | lead-3060-002 (trap)   | vast-3090-021     | 0.1675      | 2.47        |
| code_repair     | FAILS (mismatch)  | lead-3060-002 (trap)   | vast-a40-048      | 0.6298      | 15.09       |
| planning        | FAILS (mismatch)  | lead-3060-002 (trap)   | vast-a40-048      | 1.6359      | 17.38       |

- **The naive route loses everywhere.** `cheapest-listed` selects the
  $0.02/h lead for every class; priced at its availability it is the most
  expensive option in the feed per reliable GPU-hour ($0.5694 risk-adjusted,
  vs $0.2599 for the verified vast 3090 that wins chat). Even the advertised
  4090 lead — which has a capability cell and passes VRAM — loses on expected
  cost to a verified offer with a *higher sticker price*. That is the
  arbitrage question's actual answer at the mechanism level: **arbitrage
  is real only after verification; before it, the cheap listing is the most
  expensive route.**
- **The rental minimum is priced, not ignored.** Every feed offer carries a
  1-hour minimum; honoring it at session level means a chat task decoding in
  seconds still bills the full minimum window amortized over `SESSION_TASKS`,
  so expected ¢/task tracks the risk-adjusted hourly rate and the cheapest
  verified 3090 wins every light class (the premium salad 4090 loses on its
  hourly once both pay the same window). The same amortization is why the
  tiny classification workload shows the highest $/M-acc-tok (133.5): its
  few output tokens spread over a fixed billable window. Fixed-gpu and
  cheapest-listed rows carry finite expected costs wherever the pick can
  serve the workload; null is reserved for picks that cannot serve it at all.
- **Capability beats price, and fixed hardware under-covers.** The heavy
  classes (70B) have verified cells only on the A40 48 GB — every 24 GB route
  fails closed for them regardless of price. The fixed-3090 operator saves
  nothing on the work it cannot serve at all.
- **Quality-adjusted never has to leave the eligible set** — the fixture's
  verified cells all clear the 0.85 acceptance floor, so the route's cost is
  the constraint expression, exercised by tests rather than by the record.

Failure injection (40-task chat batch, authored billing model; "keys" =
distinct completed idempotency keys):

| mode             | accepted | billed (model $) | keys | behavior pinned |
|------------------|---------:|-----------------:|-----:|-----------------|
| benign           | 40       | 0.006216         | 40   | baseline spend |
| preemption       | 40       | 0.006993         | 40   | checkpoint/requeue; redo tail billed; **no key completes twice, no accepted task billed twice** |
| billing_cap      | 3        | 0.000466         | 3    | cap refuses the rest, fail-closed |
| stale_offer      | 0        | 0                | —    | execution-time re-validation refuses the fresh-at-ranking offer |
| host_unavailable | 0        | 0                | —    | drained offer dropped; SAME selection path re-ranks the rest (failover target found) |
| oom              | 0        | 0                | —    | 70B on a verified 24 GB cell rejected at pre-flight, before any rental |
| model_mismatch   | 0        | 0                | —    | unregistered (gpu, quant, stack, context, class) cell ineligible, not guessed |
| invalid_price    | 0        | 0                | —    | NaN/negative prices never enter ranking |

Annual sensitivity (USD/year, simulation; "lead" = anomalous prices IF TRUE):

| hours/day | basis | always-rented | owned-16GB+cloud | heavy-on-demand |
|----------:|------ |--------------:|-----------------:|----------------:|
| 22        | lead  | 2,810.50      | 1,461.71         | 1,742.76        |
| 22        | mid   | 4,416.50      | 2,104.11         | 2,545.76        |
| 22        | high  | 8,833.00      | 3,870.71         | 4,754.01        |
| 24        | lead  | 3,066.00      | 1,577.92         | 1,884.52        |
| 24        | mid   | 4,818.00      | 2,278.72         | 2,760.52        |
| 24        | high  | 9,636.00      | 4,205.92         | 5,169.52        |

- **Ownership dominates renting at every basis in the model.** The owned-16GB
  strategy is ~2.1–2.3× cheaper than always-rented at mid basis; the delta is
  arithmetic (capex amortization + power vs 24/7 rental rates), not evidence.
- **The 22→24 h/day step is a ~9.1% always-rented cost step** (7,880 → 8,760
  GPU-hours/year) — the marginal hour is never free, and the issue's demand
  for separating 22 and 24 h/day is exactly this line.
- **Acceptance measured on this round: none.** There is no accepted-task
  outcome/$ figure, no supervising-hour figure, and no confidence interval,
  because there are no observed tasks. Any such number in this round would be
  invented. AC5's observable half (simulation-vs-observed separation) is met
  by the absence itself plus the `data_class` markers; the substantive half
  awaits the real-hardware run below.

### Access limitations (AC3's second branch)

**No GPU was benchmarked.** This round executed its deterministic offline
harness against a synthetic feed only. Renting — even one hour of one RTX
3060 — is a spending action no research note can authorize, and no operator
approval, budget, or marketplace account exists for this lane. Per the issue's
own AC3 branch, this is the documented-access-limitations outcome: **no
measured results are claimed**, and none of the numbers above may be cited as
hardware evidence. The three distinct GPU classes requirement is satisfied
structurally (3090/A40/4090 fixture cells plus the eight-SKU hardware matrix
in the report's `gpu_catalog`), not empirically.

## What a real experiment must do

1. Obtain explicit operator approval and a capped budget for a **pinned
   rubric** replay first (the harness's schema/registry/cost model are the
   reusable part — swap `offer_feed` for a live feed only after approval).
2. Rent ≥3 distinct GPU classes for a fixed budget from a host whose price
   basis is `verified` (audited billing history, not advertisement); record
   exact SKU, driver/runtime, model/quantization, region, start time,
   preemptions, and every charge (storage, egress, CPU, deposit terms).
3. Replay recorded Invocations (real tokens/duration from `InvocationUsage`)
   with independently scored acceptance (`RunStatus` + `RunEvalScore`, never
   the serving path's own judgment); collect TTFT, p50/p95, prefill/decode
   throughput, cache hits, GPU utilization via the
   `maistro.capabilities.slots.infra` probe surface.
4. Inject every failure mode above on the live host (stop the host, revoke a
   credential, preempt); confirm the idempotency and cap behavior transfers.
5. Only then re-price the annual sensitivity with observed availability and
   update this disposition. Any production change routes through the canonical
   routing seam and its owners (epic exit), never through this bench.

## Trust boundary

The harness reads no Goal, writes no Run/Invocation, opens no socket, reads no
credential, holds no deposit path, and grants no model-egress authority — the
AST test pins the no-network property structurally, the feed carries the
unapproved-host and reliability fixtures so the trust controls are exercised
rather than asserted, and the billing cap fails closed. Sensitive repo data on
unapproved hosts is prevented *by this design* only in the sense that no data
path exists; a future operator wiring must keep it that way (approved-host
allow-list first, minimal credentials, isolated workloads, explicit approval
before any rental, no unattended top-up).

## Disposition

**WATCH** (new leaf; no prior disposition to move). Go/no-go: **NO-GO** for
any rental, deposit, spending, or production adoption. The mechanism work is
done and pinned — versioned offers, availability-priced leads, unknown-
capability ineligibility, idempotent capped execution — but every magnitude is
simulator-dependent and zero cells are hardware-measured.

**#934 stays WATCH; it cannot move to INCUBATE on this round.** #934's own
INCUBATE trigger requires a replayed-Invocation run on real infrastructure
with hardware-utilization numbers; this round produced no hardware evidence
and therefore does not satisfy it. The one thing this leaf adds toward that
trigger is the *offer-side* half of the future experiment (schema, trust
gates, risk-adjusted ranking, capped idempotent execution) that #934's
benchmark procedure did not cover. INCUBATE for either leaf becomes honest
only after the real-hardware run described above, at a fixed quality budget,
on ≥3 GPU classes, with observed acceptance. **REJECT** this leaf if real
marketplace availability at verified price bases never approaches the modeled
levels, or if deposit/billing risk proves unpriceable. No adoption is
authorized by this note.

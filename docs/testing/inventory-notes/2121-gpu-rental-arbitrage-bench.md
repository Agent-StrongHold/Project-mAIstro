---
inventory-delta:
  tests/: +68
---

# 2121 opportunistic GPU-rental arbitrage research bench

Implements the #2121 (RESEARCH M8-F) deliverable: an offline, deterministic
evaluator for opportunistic GPU-rental arbitrage — a versioned marketplace-offer
schema with contract-ordered freshness/eligibility rules, a deliberately sparse
synthetic capability registry where unknown (GPU, quantization, stack/version,
context, concurrency, task-class) compatibility is ineligible rather than
guessed, four routes (fixed-gpu, cheapest-listed, cheapest-eligible,
quality-adjusted) ranked on expected accepted-task cost with advertised leads
risk-adjusted by modeled availability, eight injected failure modes replayed
under idempotent checkpoint/resume execution with a hard billing cap, and three
ownership strategies priced at 22 and 24 h/day over 365 days under
lead/mid/high price bases. The research record, the access-limitations
statement (no hardware was benchmarked; no measured results are claimed), and
the no-go/WATCH disposition are in
`docs/research/2121-gpu-rental-arbitrage.md`, with the recorded run in
`docs/benchmarks/gpu-rental-arbitrage-baseline.json` and the manual
`gpu-rental-arbitrage-bench.yml` workflow. No product code changes.

All additions, no removals:

- `scripts/bench_gpu_rental_arbitrage.py` — the bench itself (measured root:
  the root `tests/` suite is the `--source=scripts` coverage producer, and the
  reachability gate roots the script at the workflow step that executes it).
  Pure stdlib, offline: it imports no network module, reads no quality ledger,
  provisions nothing, spends nothing, and emits no wall-clock field — the
  report is byte-identical across reruns.
- `tests/test_bench_gpu_rental_arbitrage.py` — **+68 tests** in the root
  `tests/` suite (+66 in the initial bench round; +2 in the salvage round
  that priced the rental minimum into `expected_accepted_task_cost`: the
  minimum binds on sessions shorter than the billable window, and is inert
  once the session outgrows it; the redo-multiplier pin moved from the
  single-preemption 1 + 0.5·p to the geometric 1 + 0.5·p/(1−p) that the
  replay executor's retry-until-completion loop actually implies): the
  versioned offer schema (valid offer eligible; wrong
  schema version, non-finite/negative/zero prices, negative CPU rate,
  expired TTL with the boundary pinned exclusive, unapproved host, sub-floor
  reliability, zero capacity, unknown GPU each rejected by a stable reason;
  rejection order deterministic; every broken feed fixture rejected by name
  while the approved-host lead passes the schema gate on purpose); the
  capability registry (sparse by design, synthetic provenance only, unknown
  cell ineligible-not-guessed, recorded-incompatible cell ineligible, the P40
  int4 hardware fact enforced from published specs, 70B-on-24GB classified OOM
  after a compatible cell, all eight research-matrix SKUs present); expected
  cost (leads priced at availability — the $0.02/h lead risk-adjusts above
  every verified offer, division-not-annotation pinned to 1e-9, 1/acceptance
  retry pricing exact to 1e-12, redo multiplier only on preemptible offers,
  zero-acceptance never viable, $/Mtok diagnostic consistent with the task
  cost); the four routes (cheapest-listed picks the trap lead,
  cheapest-eligible never picks an ineligible or advertised offer, the
  capability-eligible 4090 lead still loses on expected cost, the quality
  floor constrains, fixed-gpu fails closed on heavy classes and falls through
  stale listings, empty feeds fail closed with named reasons, route shape and
  simulation data-class labels); failure injection (all eight modes report
  payloads; preemption completes every key exactly once with redo spend
  visible; billing cap refuses with the refusal events recorded; stale offers
  refused at execution time; OOM/mismatch/invalid-price never rent;
  failover re-enters the same selection path; a forced selection failure
  reports route failures rather than fake success); annual sensitivity (24h
  exceeds 22h by exactly 24/22 on rented strategies, owned dominates,
  heavy-on-demand premium ordering, lead basis annotated unverified, owned
  power scales with hours, both-hours default); determinism (byte-identical
  reports, seed sensitivity, no generated-at/date-shaped/epoch values in the
  report, CLI output/stdout/arg-validation); and the trust boundary
  (AST-structural: the script imports no network, time, datetime, random,
  uuid, or subprocess module and references no effect-call attribute; the
  disposition is explicit no-go with #934 held at WATCH and named INCUBATE
  preconditions; the report carries the trust-control block).
- `.github/workflows/gpu-rental-arbitrage-bench.yml` — MANUAL_DIAGNOSTIC
  workflow executing the bench on demand (also the reachability root for the
  script), dispositioned in `quality/workflow-inventory.json`.
- `quality/workflow-inventory.json` — one reviewed MANUAL_DIAGNOSTIC row.
- `docs/research/README.md` — one disposition-table row (M8-F3, WATCH).
- `docs/benchmarks/gpu-rental-arbitrage-baseline.json` — the recorded
  deterministic run (byte-identical rerun verified).

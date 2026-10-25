---
inventory-delta:
  tests/: +48
---

# 934 heterogeneous fleet-routing research bench

Implements the #934 (RESEARCH M8-F1) deliverable: an offline, deterministic
benchmark comparing fleet-composition policies — hosted-only, local-only, the
shipped `CostAwareRouter` over the whole fleet, and a difficulty-aware
local-first candidate — over one shared task corpus, one shared
policy-independent outcome table, and one shared seed-independent
provider-pressure schedule, across four scenarios (benign, local outage,
hosted-provider outage, hosted capacity pressure). The research record and
the GRADUATE/INCUBATE/REJECT/WATCH disposition are in
`docs/research/934-heterogeneous-fleet-benchmark.md`, with the recorded
run in `docs/benchmarks/fleet-routing-baseline.json` and the manual
`fleet-routing-bench.yml` workflow. No product code changes.

All additions, no removals:

- `scripts/bench_fleet_routing.py` — the bench itself (measured root: the
  root `tests/` suite is the `--source=scripts` coverage producer, and the
  reachability gate roots the script at the workflow step that executes it).
  Every selection is a real `CostAwareRouter.select(task, budget, scope)`
  call over the real `InMemoryProviderRegistry`; outages ride
  `mark_unavailable` (ADR-038's circuit-break seam); failover re-enters the
  same router with attempted models excluded from `scope`; cost is
  `compute_cost_cents`. Outcomes come from a stated deterministic simulator
  (no per-task routing telemetry exists to replay), with provider pressure
  keyed to a constant seed so it models observable egress conditions — the
  split that lets the leakage audit decide for escalating policies.
- `tests/test_bench_fleet_routing.py` — **+48 tests** in the root `tests/`
  suite: catalog invariants (heterogeneous fleet, free local / priced hosted,
  resolvable fallback chains); corpus determinism and jitter-twin shape;
  provider-pressure locality (local never rate-limits; fires only in the
  pressure scenario; run-seed independence); attempt-model physics (capacity
  bound is registry arithmetic, rate-limited attempts bill nothing but pay
  fast-reject latency); scenario fail-closed on unknown names and outage
  marking scoped to the right providers; the structural claims (scoped fleets
  never cross the provider boundary; the shipped router over the whole fleet
  absorbs zero local work and is fit-blind; local-first routes easy work to
  local and reasoning to reasoning-capable entries); escalation mechanics
  pinned at the stubbed-simulator level (quality failures never escalate;
  observable failures escalate to models not yet attempted); accounting
  hygiene (local attempts cost exactly zero, observable failures bill
  nothing, shares sum to 1, utilization bounded, a fully-collapsed fleet
  reports zero throughput rather than a 1 ms-floor artifact, route failures
  priced at the worst outcome); single-attempt policies never beat the
  oracle; the pressure scenario degrades the incumbent and escalates the
  candidate; full-report determinism; all-scenarios mode shape; zero
  leakage violations for outcome-blind policies with the oracle positive
  control proven able to fire; static fleets never flip under jitter; and
  the model-egress ledger audit (frozen set intact, fail-closed when the
  ledger is missing, tolerant of module-object rows) plus the CLI payloads.

- `scripts/check-ratchet-provenance.py` — one reviewed `CANDIDATE_AUTHORED`
  entry: the bench reads `quality/model-egress.json` from the candidate tree
  as portability *evidence* (row count plus the approved provider's
  presence, written to the report, gating nothing), which is exactly the
  "documented exception" branch that provenance policy requires for any
  script touching a ledger; the blocking two-way ratchet stays owned by
  `check-model-egress.py`.

The bench is deterministic (seeded blake2b draws, no wall-clock assertions,
no network), so every property above is pinned exactly, and the test scale
is deliberately small (36-task corpora) to respect the root suite's
`--timeout=30` producer budget.

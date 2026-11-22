# M8-F1 research note — benchmarking heterogeneous local + cloud model fleets behind canonical routing

Leaf: #934. Epic: #905. Initiative: #879. Sibling leaf: #935 (M8-F2, batching/KV
reuse — dispositioned in its own note).

## Hypothesis

A heterogeneous fleet that combines local/open models with hosted/provisioned
models can lower cost and improve resilience while preserving quality **if
routing respects task difficulty and provider capabilities**. The null
hypothesis the epic guards against: any cost or resilience win whose mechanism
requires coupling canonical execution to one vendor, one engine, or one
accelerator fleet.

## Canonical seam

The experiment routes through the shipped fleet seam and nothing else:

- **Selection**: `CostAwareRouter.select(task, budget, scope)`
  (`packages/maistro-core/src/maistro/providers/router.py`, ADR-038 fallback
  semantics, ADR-079 metadata) over an `InMemoryProviderRegistry` — the exact
  selection path `maistro.capabilities.model_chat` uses for governed egress.
- **Outage injection**: `InMemoryProviderRegistry.mark_unavailable` — the
  availability set is the shipped circuit-break point (ADR-038); a Binding pin
  would refuse rather than fall back (fallback cannot widen authorization,
  ADR-081226-6b46), and every policy here is the unpinned path.
- **Failover**: re-entering the same router with the attempted models excluded
  from `scope` — a per-call narrowing. The shipped router already walks
  declared `fallback_to` chains; `scope` is how a policy composes a fleet
  without opening a second selection path.
- **Cost**: `compute_cost_cents` over `ModelMetadata` (cents per 1k tokens).
- **Portability**: the fleet catalog's free-form `provider` field, plus
  `quality/model-egress.json` — the bench reads the ledger and reports zero
  new direct callers; a technique that forced a 21st module to hold an HTTP
  client for model egress would fail the seam rule outright
  (`scripts/check-model-egress.py` ratchets both ways).

Three structural facts about the seam frame the whole question (all pinned by
tests):

1. **The shipped router is provider-blind.** It filters by budget, sorts by
   `latency_p50_ms`, and walks chains; "provider" is metadata it never reads.
   Adding local entries to the registry and changing nothing else therefore
   absorbs **zero** work onto local capacity: the hosted fast tier wins every
   latency race (`mixed-shipped` ≡ `hosted-only`, exactly, in the benign
   scenario — model HHI 1.000, 100% of tasks on `gpt-3.5-turbo`). Local
   capacity is operator-opted-in, as the epic note observed; the bench makes
   that observation exact.
2. **The production call shape is capacity-blind** (#914's finding, replayed
   on the fleet question). Nothing in `RouterBudget` or the bare call shape
   reads `max_tokens`, so the shipped router sends 60k-token summarizations to
   a 4k-window model and 50.5% of the corpus ends in an observable capacity
   failure — on the *incumbent* deployment, not just on experimental ones.
3. **Fleet composition is expressible today through scope/budget/availability
   alone.** A difficulty-aware local-first candidate — easy tasks scoped to
   capacity-fitting local entries, hard classes to capable hosted tiers,
   reasoning-flagged tasks to reasoning-adequate entries, escalating on
   *observable* failures only (capacity, rate limit; never on quality, which
   is only knowable post-hoc — that is leaf #915's territory) — requires no
   new production mechanism. It is a candidate policy over the existing seam,
   not a wiring proposal.

## Method

`scripts/bench_fleet_routing.py` is the offline/replay evaluator (results in
`docs/benchmarks/fleet-routing-baseline.json`, runnable via the manual
`fleet-routing-bench.yml` workflow; deterministic, offline, blake2b seeds —
same seed, same numbers):

- **Corpus** — identical classes, bands, and hashing to
  `scripts/bench_model_routing.py` (#914): 2,400 tasks over six capability
  classes with observable features and a HIDDEN per-task difficulty only the
  outcome model sees. Keeping the corpus identical makes the two routing
  benches comparable.
- **Fleet catalog** — the provider-test fixture catalog
  (`packages/maistro-core/tests/providers/fixtures_models.py`), extended the
  way the heterogeneous question requires: `mistral-large` (a second hosted
  provider, so a single-provider outage is survivable without local capacity)
  and `local-qwen-14b` (a second, reasoning-capable local entry, so the local
  fleet has internal selection). Two hosted providers and one local host,
  declared once in the registry — the operator's fleet declaration, unchanged.
- **Outcome table** — one fixed deterministic simulator over (task, model)
  pairs built once per scenario BEFORE any policy runs, so cross-policy
  comparisons are exact. Same escalation shape as #914 (tier comfort zones,
  difficulty cliffs, reasoning/tool penalties), extended with provider
  physics: capacity failures (registry `max_tokens` arithmetic) and
  scenario-driven hosted rate limits. A 429 bills nothing but pays fast-reject
  latency. Provider pressure is keyed to a constant seed, NOT the run seed: a
  rate limit is an *observable egress condition*, so failover may react to it
  without leaking hidden outcome data — that split is what makes the leakage
  audit decidable for escalating policies.
- **Policies** — `hosted-only` (the incumbent deployment; real router scoped
  to hosted names, production call shape), `local-only` (the all-in local
  counterfactual), `mixed-shipped` (the shipped router, unconstrained, over
  the whole fleet — what an operator gets today by adding local entries),
  `mixed-local-first` (the difficulty-aware candidate above; NOT production
  code), and `oracle` (per-task utility argmax — the regret baseline and the
  leakage positive control; single-attempt, so the failover candidate may
  legitimately exceed it and its delta is reported unsigned).
- **Scenarios** — `all-available`, `local-outage` (both local entries
  circuit-broken), `hosted-outage` (anthropic down — the provider that owns
  the fleet's hosted reasoning capability), `capacity-pressure` (everything
  up; hosted attempts inside a deterministic pressure window rate-limit at
  35%; local unaffected). Pressure is a property of the scenario timeline,
  identical for every policy: the bench measures pressure *avoidance*, not
  demand relief — an honest scope limit.
- **Measured** (the issue's list, each mapped to its source):
  - *success quality* — final-attempt success rate over the shared table;
  - *cost* — `compute_cost_cents` totals, per task and per success; observable
    failures bill zero (sunk latency only), the escalation-composition rule;
  - *p50/p95 latency* — realized final-attempt latencies per policy;
  - *throughput* — a stated makespan model: local attempts serialize on one
    executor (`LOCAL_CONCURRENCY = 1`), hosted attempts run 16-wide; tasks
    and successes per second of makespan;
  - *failover behavior* — escalation rate, attempts per task, residual
    observable-failure rate, route failures, per scenario;
  - *hardware utilization* — local-executor busy fraction, hosted-fleet
    utilization, and the counted artifact "local executors needed to finish
    the local work inside the hosted makespan";
  - *operational complexity* — counted: registry entries, providers, extra
    local processes (+1 inference server), observed failure-mode classes;
  - *portability* — provider shares/HHI (movement only through the registry's
    `provider` field) plus the model-egress ledger audit (20 rows, approved
    gateway present, zero new direct callers).

## Record

All-available fleet (2,400 tasks; costs in cents; hosted-only is the baseline
per the epic's fleet-experiment contract):

| policy            | success | ¢/task | p50 ms | p95 ms | miss  | t/s   | prov. HHI |
|-------------------|--------:|-------:|-------:|-------:|------:|------:|----------:|
| hosted-only       | 0.372   | 0.0011 | 400    | 512    | 0.000 | 39.36 | 1.00      |
| local-only        | 0.490   | 0.0000 | 2500   | 3315   | 0.299 | 0.39  | 1.00      |
| mixed-shipped     | 0.372   | 0.0011 | 400    | 512    | 0.000 | 39.36 | 1.00      |
| mixed-local-first | 0.821   | 0.4243 | 2016   | 6840   | 0.372 | 0.54  | 0.41      |
| oracle            | 0.998   | 0.4073 | 613    | 1381   | 0.000 | 23.24 | 0.61      |

- **Local capacity without a policy is dead capacity.** `mixed-shipped` and
  `hosted-only` are numerically identical in every benign-scenario metric:
  the shipped latency-first selection keeps 100% of tasks on the hosted
  fast tier. The heterogeneous-fleet question is a *policy* question before
  it is a capacity question.
- **The incumbent's 37.2% success is not a price story** — 50.5% of tasks end
  in an observable capacity failure because the production call shape never
  reads `max_tokens` (fact 2). Any fleet policy that scopes by capacity beats
  it before difficulty-awareness enters.
- **Difficulty-aware local-first buys quality and provider diversity, and
  pays in hardware.** +44.9pp success over the incumbent, provider HHI
  1.00 → 0.41, at 0.42¢/task (the incumbent's bill is near-zero only because
  it mostly fails). The cost is the local host pinned at 100% busy:
  throughput falls 39.4 → 0.54 tasks/s, p95 rises to 6.8 s with a 37.2%
  deadline-miss rate, and the counted operational artifact says **89 local
  executors** are needed to finish the local share inside the hosted
  makespan. On one workstation GPU, "local-first" is a cost/resilience play,
  not a throughput play — scaling it is a hardware purchase the bench can
  count.

Degraded and pressured fleets:

| scenario / policy             | success | t/s   | failover behavior |
|-------------------------------|--------:|------:|-------------------|
| local-outage / local-only     | 0.000   | 0.000 | all 2,400 tasks route-fail; the all-in local fleet is a total-loss configuration |
| local-outage / mixed-local-first | 0.830 | 25.86 | easy work falls to the hosted stage; **zero route failures**, p95 1.1 s |
| hosted-outage / hosted-only   | 0.372   | 39.36 | unchanged — it never used the dead provider (concentration cuts both ways); the fleet-wide 200k-token window died with it, and 84 tasks now fit no remaining model |
| hosted-outage / mixed-local-first | 0.773 | 0.28 | reasoning work rides `local-qwen-14b`; local host saturates (**521 executors** to match hosted makespan); zero route failures |
| capacity-pressure / hosted-only | 0.235 | 45.71 | 430 tasks end rate-limited (residual observable failure 0.685); no defense |
| capacity-pressure / mixed-local-first | 0.722 | 0.54 | escalates on 11.4% of tasks (1.11 attempts/task); only 33 of 2,400 tasks end rate-limited (1.4%, vs 430 for the pressured incumbent); pressure avoidance converts directly to +48.7pp success |

- **Resilience is the heterogeneous fleet's cleanest win.** Under a local
  outage the mixed fleet keeps every task routed (the all-in local fleet
  route-fails everything); under a hosted-provider outage it keeps a
  reasoning-capable route (the reasoning-capable hosted entry was the one
  that died) and absorbs the window-capacity loss onto local; under hosted
  capacity pressure its escalation — which conditions only on observable
  errors — cuts the rate-limited final rate from 17.9% (430 of 2,400) to
  1.4% (33) while raising success 0.235 → 0.722 over the pressured
  incumbent.
- **Throughput is the symmetric loss.** Every scenario where the local host
  carries real work pins it at 100% busy and drops completed-tasks/sec by
  1–2 orders of magnitude against elastic hosted concurrency. The epic's
  hardware-utilization metric is the binding constraint on the hypothesis,
  and it is a hardware count, not a software fix.
- **Portability holds.** Provider concentration moves only through the
  registry's `provider` field (HHI 1.00 → 0.41 under local-first); the
  model-egress ledger is unchanged (20 rows, approved gateway present, zero
  new direct callers). The experiment required no new egress, no new
  authority, and no vendor coupling.

**Honest scope limit:** the repository records no per-task routing telemetry,
so the corpus and outcomes are simulated (the same limitation the #914 note
records). The experiment measures fleet-policy *structure* against a stated
outcome model and the shipped seam's real levers; it does not measure
production traffic. Every magnitude above is simulator-dependent; the
structural facts are not. This is why the disposition is not GRADUATE.

Executed probe record (head 3479596254, 2026-10-08):
`uv run python scripts/bench_fleet_routing.py --tasks-per-class 400 --seed
fleet-bench-v1 --scenario all --output docs/benchmarks/fleet-routing-baseline.json`
→ 4 scenarios, 5 policies each, ~7.6 s wall; `uv run pytest
tests/test_bench_fleet_routing.py -q` → 46 passed; `uv run ruff check` and
`uv run ruff format --check` clean.

Post-merge re-validation (merge head d6f36de02, 2026-10-08): after syncing
origin/develop (conformance suites, calibration research, workflow updates;
`docs/research/README.md` table conflict resolved keeping both rows), the
same probe command was re-run to a temp output and reproduced
`docs/benchmarks/fleet-routing-baseline.json` exactly (semantic diff empty);
`uv run pytest tests/test_bench_fleet_routing.py -q` → 48 passed (the two
tests added after the original probe are what the +48 inventory delta
records); `uv run ruff check .`, `uv run ruff format --check .`,
`scripts/check-suite-inventory.py`, `scripts/check-workflow-inventory.py`,
`scripts/check-ratchet-provenance.py`, `scripts/check-model-egress.py`, and
`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` all clean; CI's single-process battery
(`pytest tests/ packages/hive-conductor/backend/tests
packages/maistro-design/tests -q --timeout=60`) → 9,064 passed, 149 skipped.

Second develop-sync re-validation (merge head 88f459145, 2026-10-09): merged
origin/develop again (adds research leaves #923/#929/#930 and the #929
graph-pattern-reuse workflow to the same two registry rows this leaf owns;
conflicts resolved keeping both sides). The probe command re-run to a temp
output reproduced `docs/benchmarks/fleet-routing-baseline.json` exactly
(byte-identical excluding `generated_at`); `uv run pytest
tests/test_bench_fleet_routing.py -q` → 48 passed; `uv run ruff check .`
and `uv run ruff format --check .` clean; `scripts/check-suite-inventory.py`
(17 suites match), `scripts/check-workflow-inventory.py` (28 workflows
dispositioned), `scripts/check-ratchet-provenance.py`,
`scripts/check-model-egress.py` (20 rows, zero new direct callers),
`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` (1,323 reviewed identities match),
`scripts/check-doc-links.py`, and `scripts/check-reachability.py` all exit 0
at this merge head.

## Threats to validity

- The outcome model is authored, not observed: tier comfort zones, the
  difficulty cliff, and the 35% pressure rate are stated modeling choices.
  What no plausible re-parameterization changes: a 4k-window model cannot
  hold a 60k-token document (arithmetic), an unavailable registry entry is
  not selected (mechanism), and a policy scoped to hosted names cannot elect
  a local model (scope is a constraint).
- Local throughput is modeled as one serial executor — the pessimistic
  corner of the hardware space. N local executors scale the local numbers
  linearly until another resource binds; the counted
  `local_executors_to_match_hosted` artifact (89–521 across scenarios) is
  the number an operator would actually act on.
- The pressure window is policy-independent by construction, so the bench
  measures pressure avoidance, not demand relief; a fleet that routes away
  from a saturating provider would also *relieve* it, and that second-order
  benefit is not counted here.
- The oracle assumes perfect per-task foreknowledge over capacity-adequate
  models; it is a ceiling, not a proposal.

## Benchmark procedure (what a real experiment must do)

1. Replay recorded Invocations — real model, tokens, cost, and duration per
   task — through this evaluator instead of the simulator
   (`InvocationUsage` already persists model/cost; per-task realized latency
   and terminal outcome capture is the missing telemetry, the same gap the
   #914 note names).
2. Pin the rubric/eval corpus BEFORE the run; score quality from terminal
   `RunStatus` + `RunEvalScore`, never from the serving path's own judgment.
3. Run the four scenarios against a real gateway with a real local engine
   (Ollama rides the OpenAI-compatible seam today); inject outages by
   stopping the local host and revoking a provider credential — the same two
   injection points the registry availability set models.
4. Report per-model-entry cost/latency/success (never gateway aggregates),
   failover counts from the resilience classifier's categories, and
   accelerator utilization collected via the `maistro.capabilities.slots.infra`
   probe surface with the collection procedure recorded in the leaf.
5. Update this disposition. Any GRADUATE routes to the model-routing owner
   and must accept or explicitly waive ADR-079 first (it is still Proposed
   while `CostAwareRouter` ships as its implementation).

## Trust boundary

Every policy here is evidence, not authority: the harness reads no Goal,
writes no Run/Invocation, makes no routing decision, and opens no egress —
`quality/model-egress.json` is read to prove the last point, not written.
Escalation conditions only on egress-observable failures; hidden outcome
data never reaches a decision (the leakage audit is a test-pinned gate, with
the oracle as its positive control). A fleet policy that survives a real
experiment reaches production only as a change to the canonical routing seam
owned by the routing owner (epic exit), subject to ADR-038 fallback
semantics and the Binding-pin refusal rule; this bench never becomes a
second selection path, and its outputs are frozen measurements, not actions.

## Disposition

**WATCH.** The structural case is real and verified in code: fleet
composition is expressible through the shipped seam's existing levers; the
shipped router absorbs zero local work without a policy; the incumbent's
quality floor is a capacity-blindness artifact; and the difficulty-aware
candidate dominates on success, cost-at-quality, failover, and provider
diversity across all three disruption scenarios. But no real fleet experiment
exists — outcomes are simulated and no accelerator was measured — so the
hypothesis is unevidenced on MAIstro workloads. Move to **INCUBATE** when a
replayed-Invocation run (procedure above) on representative workloads
confirms a material cost or resilience gain at a fixed quality budget, with
hardware-utilization numbers collected on real infrastructure. **REJECT** if
real runs show the local executor's throughput ceiling dominating the savings
at realistic fleet sizes, or if failover behavior under real gateway outages
diverges from the availability-seam model. No adoption is authorized by this
note; the epic's seam rule is both the thing tested and the boundary the
result must respect.

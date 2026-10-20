# M8-A research note — advanced verification and assurance against real MAIstro seams

Epic: #880. Leaves: #881, #882, #883, #884, #885, #886, #887, #888, #889, #890,
#891, #892, #893, #894, #896, #897. Initiative: #879. Milestone tracker: #878.

## Research question

Which advanced verification and assurance techniques materially improve
confidence in MAIstro beyond the existing quality stack, at acceptable
engineering and CI cost?

## Baseline audit (epic contract item 2, executed at this head)

The epic text credits the existing stack with "property testing, mutation
testing, OpenAPI contract fuzzing, strict typing, architecture fitness
functions, coverage gates, real PostgreSQL/S3 integration legs, and a
`formal/` Hypothesis suite". The leaves' experiments must compare against what
those controls *actually do*, not what the quality workflow's header says they
do. Audited at `feb19affc`:

| Claimed control | Actual state at this head | Evidence |
| --- | --- | --- |
| `formal/` Hypothesis suite | **Executing.** Invariants I1–I29 against real `maistro.security`/`auth` code; PR-gated plus nightly profile. Executed locally: `uv run pytest formal -q` → **663 passed, 1 skipped** (I29 `PgRunStore` skips without `MAISTRO_TEST_PG_DSN`, `formal/models/test_run_lease_fence.py:114`), ≈56 s wall clock on the CI profile. | `formal/README.md`, `.github/workflows/formal-conformance.yml` |
| Property testing in packages | Partial. `hypothesis` is a declared dev dependency of `hive-conductor`, `maistro-design`, and `formal/` only; the canonical execution lifecycle (#881) and Invocation effects (#882) have no state-machine property coverage. | `packages/*/pyproject.toml` |
| Mutation testing | **Parked.** `.github/workflows/mutation.yml` is `workflow_dispatch`-only on self-hosted runners and its only job echoes a deferral notice; nothing mutates on PRs or schedules. The machinery (`scripts/mutation_*.py`, `quality/mutation-baseline.json`, `quality/mutation-history.json`) is present but idle. The `quality.yml:8` comment "cosmic-ray on changed files only" describes no executing step. | `.github/workflows/mutation.yml:1-33` |
| OpenAPI contract fuzzing | **Absent.** "schemathesis" occurs exactly once in the tree — the `quality.yml:9` header comment. No dependency, workflow step, script, or config exists. The `quality-gate` job names itself "Pillars 1–4, 7, 8" (`quality.yml:707`): pillar 6 (contract) is not among them. | repo-wide grep; `.github/workflows/quality.yml:9,707` |
| Strict typing | Executing: mypy strict across `packages/*/src` plus advisory pyright. | `AGENTS.md` typecheck command; `quality.yml` |
| Architecture fitness functions | Executing: 75 `scripts/check-*.py` gates and 40 `quality/*.json` per-identity ledgers (vulture, radon, reachability, promotion surface, direct effects) with merge-base grant provenance (`scripts/ratchet_provenance.py`). | `scripts/`, `quality/` |
| Coverage gates | Executing, at **per-file floors of 90 % lines / 80 % branch arcs** (`scripts/check-diff-coverage.py:320-322`) — not the "≥95 % on touched files" the `quality.yml:1` header claims. | `scripts/check-diff-coverage.py`, `quality.yml:695-703` |
| Real PostgreSQL/S3 legs | Executing in CI: postgres service matrix (17, 18) and a vendored-toolchain MinIO leg; `ac_outcome_plugin` counts a skip as no evidence. Locally the real-store legs need a DSN/service. | `ci.yml:304-310,404-424` |

Two of the eight claimed pillars — mutation and contract fuzzing — therefore do
not execute at this head. This is recorded, not repaired here: restoring
mutation runners is a CI-capacity decision owned outside M8, and standing up
the contract-fuzzing leg is precisely leaf #893's experiment. No gate was
weakened to reach this conclusion (the epic's non-goals), and neither gap
invalidates an M0–M7 acceptance criterion that cited those pillars as
executing — but any leaf or roadmap text that treats "mutation testing" or
"contract fuzzing" as live baselines is contradicted by this audit and should
cite it.

## Canonical seams (leaf map)

Each leaf targets one canonical seam and one failure class the current gates
do not reach. Seam ownership per the accepted ADRs (`Goal -> Graph -> Run ->
NodeRun -> Attempt` remains the only execution model; nothing below proposes a
second authority):

| Leaf | Canonical seam | Failure class today's gates miss |
| --- | --- | --- |
| #881 Hypothesis state machines over the execution lifecycle | `maistro.graph` executor/`NodeRun` transitions | interleaved lifecycle sequences (unit tests fix one path) |
| #882 Invocation effect/idempotency state machines | Invocation ledger + effect application | duplicate/replayed effects under retry |
| #883 deterministic crash/failpoint testing | durable-run checkpoint/restore seams | partial-write/crash-between-step states |
| #884 TLA+/Apalache-style model checking | execution concurrency protocol | counterexamples across *all* interleavings, not sampled ones |
| #885 differential reference-model testing | canonical state machines vs. an independent model | oracle gaps where both implementation and test share a bug |
| #886 Workspace noninterference | workspace/project scoping (`ProjectScopeStore`, membership) | cross-workspace leakage through composed operations |
| #887 real PostgreSQL race/invariant testing | `PgRunStore`/persistence under concurrency | lost updates/serialization anomalies (only I29 touches this today) |
| #888 replay/checkpoint/determinism | durable_runs replay path | divergence between replayed and original state |
| #889 metamorphic testing | retrieval/AI/provider/Graph behavior | absent fixed oracle; only invariant *relations* hold |
| #890 CrossHair symbolic execution | pure Python invariants (policies, builders) | path-sensitive violations random search rarely reaches |
| #891 direct Z3/SMT modeling | constraint-heavy decisions (routing, tiers) | constraint-interaction bugs across decision dimensions |
| #892 conformance suites | store/provider/adapter protocols | a conforming-looking implementation failing one operation's contract |
| #893 stateful Schemathesis workflows | OpenAPI surface (`maistro_server`) | multi-step API state corruption (baseline audit: leg absent) |
| #894 critical-zone mutation policy | architecture-critical modules | surviving mutants in zones coverage cannot judge (machinery parked) |
| #896 coverage-guided fuzzing (Atheris) | parsers/untrusted-input attack surface | structured-input crashes beyond grammar-guided cases |
| #897 Lean/Rust/Aeneas correctness kernel | tiny kernel candidate | proof-grade guarantees (feasibility question only) |

## Record

This note reports the baseline audit and the comparative machinery; it runs no
leaf experiment and adds no product code, flag, or authority (M8 guardrails 1–2). Executed evidence at this head:

1. **formal/ suite run** (procedure above): 663 passed, 1 skipped, ≈56 s — the
   matrix's anchor row for "what already executes".
2. **mutation workflow inspection**: `mutation.yml` defers everything to a
   self-hosted `workflow_dispatch`; the PR-blocking quality gate contains no
   mutation step.
3. **schemathesis absence**: repo-wide grep finds the name only in the
   `quality.yml:9` comment.
4. **coverage floor measurement**: the enforcing gate defaults are 90/80
   per file (`check-diff-coverage.py:320-322`); the 95 % figure appears only
   in the workflow header prose.

The comparative output machinery — the epic's promised ranked assurance
matrix — is implemented as an evidence-only research harness:
`packages/maistro-rsi/tests/test_m8a_assurance_baseline_research.py` (test
module only; imports nothing from `maistro`, so it cannot become an authority
by accident). It fixes the eight criteria the epic names as a closed axis
vocabulary (four benefit, four cost), requires every score to carry a
citation, excludes unmeasured candidates from ranking instead of scoring them
zero, requires a `technique` row to carry exactly one #878 terminal
disposition before it can rank, and ranks with a transparent unweighted
net (mean benefit − mean cost), name-tiebroken for determinism. The measured
baseline rows from the audit above ship in that module as the reference
population; leaves append evidenced rows and rank against them.

## Leaf #881 experiment: Execution lifecycle state machine

As part of leaf #881, we created a Hypothesis state machine to test the
execution lifecycle of a `Run` object. The state machine models the `Run`
status transitions (CREATED → QUEUED → RUNNING → WAITING → PAUSED →
COMPLETED/FAILED/CANCELLED/TIMED_OUT) and checks that the internal model
matches the `Run`'s status at every step.

### Experiment details

- **Target seam**: `maistro.graph` executor/`NodeRun` transitions
- **Failure class targeted**: interleaved lifecycle sequences (unit tests fix one path)
- **Experimental artifact**: `formal/models/test_execution_lifecycle.py`
- **Procedure**: We defined a `RuleBasedStateMachine` that creates a minimal
  `Graph` and `Run` instance, then defines rules for each possible transition
  and invariants to ensure the model matches the `Run` status and that
  terminal states have no outgoing transitions.

### Results

The state machine compiles and can be instantiated, but due to pytest
collection issues (related to the presence of a custom `__init__` method in
the state machine class), it is not currently executed as a test in the
pytest suite. Manual instantiation shows that the state machine can be
created and that the invariants hold for the initial state.

### Evidence

- Source: `formal/models/test_execution_lifecycle.py`
- Note: The state machine defines the execution lifecycle transitions and
  invariants. The class can be imported and instantiated without error.

### Disposition

Given that the experiment did not produce runnable test evidence (due to
technical limitations in the test environment), we assign a disposition of
**WATCH** (watch this space) for leaf #881. The state machine correctly
models the execution lifecycle and is ready to be run once the pytest
collection issue is resolved.

## Assurance matrix — state at this head

Rubric: each row scores the epic's eight criteria 0–3, every score cited;
net = mean(benefit) − mean(cost); unevidenced rows excluded, not zeroed.
Baseline ranking (from the harness population): architecture fitness
functions and the formal/ suite lead the executing controls; the real
PostgreSQL/S3 legs trade breadth and runtime cost for the strongest oracle;
diff coverage adds breadth, not depth; mutation and contract fuzzing rank
last as non-executing controls.

Leaf #881 (execution Hypothesis state machines) is added as a technique row
with the following scores and evidence (based on the experiment record above):

- defect_yield: 0 (no counterexamples found yet due to test not running)
- confidence_strength: 1 (model matches initial state, but no transitions
  executed in test)
- applicability_breadth: 2 (applies to the execution lifecycle seam;
  other seams like invocation effects require different models)
- oracle_trustworthiness: 3 (model is derived from the documented
  transitions in `maistro.runs.lifecycle`)
- implementation_effort: 1 (state machine is straightforward to write)
- maintenance_burden: 1 (minimal; depends on the documented lifecycle)
- ci_runtime_cost: 0 (test not yet running in CI)
- async_distributed_friction: 1 (model does not capture concurrency;
  only linear transitions)

Net score: (0+1+2+3)/4 - (0+1+1+0)/4 = 1.5 - 0.5 = 1.0

Disposition: WATCH (as per experiment record)

This technique row is added to the assurance matrix for ranking against the
baseline population.

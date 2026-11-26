# M8-A research note — advanced verification and assurance against real MAIstro seams

Epic: #880. Leaves: #881, #882, #883, #884, #885, #886, #887, #888, #889, #890,
#891, #892, #893, #894, #896, #897. Initiative: #879. Milestone tracker: #878.

## Scope and freshness

This is a **partial epic artifact**, not completion evidence for all 16 leaves.
The baseline audit and its six harness rows are historical observations at
`feb19affc`, not live probes of the current tree. Citation strings and numerical
scores are review judgments, not independently verified measurements. In
particular, mutation and Schemathesis are no longer absent: develop now has
`scripts/mutation_pr_gate.py` wired in `mutation.yml` and generated API workflow
tests in `packages/maistro-server/tests/api/test_stateful_workflow_api.py`.
Their current defect yield and CI cost have **not** been remeasured here.

The linear helper prototype below predates the richer PostgreSQL experiment in
[leaf #881's own note](881-execution-lifecycle-state-machines.md). Do not read
its narrow assurance-matrix row as a ranking of that entire leaf. Fresh local
validation and the remaining epic acceptance gaps are recorded at the end.

## Research question

Which advanced verification and assurance techniques materially improve
confidence in MAIstro beyond the existing quality stack, at acceptable
engineering and CI cost?

## Historical baseline audit (epic contract item 2, at feb19affc)

The epic text credits the existing stack with "property testing, mutation
testing, OpenAPI contract fuzzing, strict typing, architecture fitness
functions, coverage gates, real PostgreSQL/S3 integration legs, and a
`formal/` Hypothesis suite". The leaves' experiments must compare against what
those controls *actually do*, not what the quality workflow's header says they
do. Audited at `feb19affc`:

| Claimed control | State at the audited revision | Evidence |
| --- | --- | --- |
| `formal/` Hypothesis suite | **Executing.** Invariants I1–I29 against real `maistro.security`/`auth` code; PR-gated plus nightly profile. Executed locally: `uv run pytest formal -q` → **663 passed, 1 skipped** (I29 `PgRunStore` skips without `MAISTRO_TEST_PG_DSN`, `formal/models/test_run_lease_fence.py:114`), ≈56 s wall clock on the CI profile. | `formal/README.md`, `.github/workflows/formal-conformance.yml` |
| Property testing in packages | Partial. `hypothesis` is a declared dev dependency of `hive-conductor`, `maistro-design`, and `formal/` only; leaf #881 now ships a collected `Run` lifecycle state machine, while Invocation effects (#882) still have none. | `packages/*/pyproject.toml`, `formal/models/test_execution_lifecycle.py` |
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

## Historical audit record

The initial artifact reported only the baseline audit and comparative machinery;
it ran no leaf experiment and added no product code, flag, or authority (M8
guardrails 1–2). Evidence recorded at feb19affc (not revalidated as current):

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

## Historical #881 precursor: linear Run helper state machine

As part of leaf #881, we created a Hypothesis state machine to test the
execution lifecycle of a `Run` object. The state machine models the `Run`
status transitions (CREATED → QUEUED → RUNNING → WAITING → PAUSED →
COMPLETED/FAILED/CANCELLED/TIMED_OUT) and checks that the internal model
matches the `Run`'s status at every step.

### Experiment details

- **Target seam**: in-memory `maistro.runs.lifecycle.transition_run`
- **Failure class targeted**: sequential helper enforcement diverging from its
  transition table (not concurrent, persisted, NodeRun or Attempt behavior)
- **Experimental artifact**: `formal/models/test_execution_lifecycle.py`
- **Procedure**: We defined a `RuleBasedStateMachine` that creates a minimal
  `Graph` and `Run` instance, then defines rules for each possible transition
  and invariants to ensure the model matches the `Run` status and that
  terminal states have no outgoing transitions.

### Results

The state machine is now collected and executed by pytest via the
`TestExecutionLifecycleMachine = ExecutionLifecycleMachine.TestCase`
assignment at module scope (the same pattern the other formal models use), so
it runs in the formal-conformance leg instead of sitting uncollected. Each
step calls the production `transition_run` helper from
`maistro.runs.lifecycle` rather than mirroring the status by hand, so a
divergence between the documented `RUN_TRANSITIONS` table and the helper's
enforcement surfaces as a failed property. The invariants (model matches the
Run status, terminal statuses have no outgoing transitions, and the in-memory
status is in the table's domain) hold across the CI profile's example budget;
no counterexample has been found so far. Both oracle and implementation read
`RUN_TRANSITIONS`, so a wrong table entry can pass both. These properties do
not establish oracle independence or the full execution contract.

### Evidence

- Source: `formal/models/test_execution_lifecycle.py`
- Executed in this round: `uv run pytest formal -x -q` (with core/evolve/rsi
  source paths) includes the collected machine. The module's second test is an
  empty placeholder, not additional behavioral evidence.

### Disposition

The collection blocker is resolved and the state machine now runs as a real
property test, so leaf #881 moves from **WATCH** to **INCUBATE**: the
technique is runnable and exercises production transition logic, but it
still covers only the linear `Run` lifecycle (not `NodeRun`/`Attempt`, and
no concurrency or crash interleaving). It should graduate only after those
seams are modeled and a defect-finding yield is observed.

## Assurance matrix — historical baseline plus linear precursor

Rubric: each row scores the epic's eight criteria 0–3, every score cited;
net = mean(benefit) − mean(cost); unevidenced rows excluded, not zeroed.
Baseline ranking (from the harness population): architecture fitness
functions and the formal/ suite lead the executing controls; the real
PostgreSQL/S3 legs trade breadth and runtime cost for the strongest oracle;
diff coverage adds breadth, not depth; mutation and contract fuzzing rank
last as non-executing controls.

The `linear Run transition helper (#881 precursor)` row has these advisory
scores, matching the harness (not a measurement of the PostgreSQL leaf):

- defect_yield: 0 (no counterexamples observed)
- confidence_strength: 2 (collected machine calls the production helper)
- applicability_breadth: 1 (only Run helper transitions)
- oracle_trustworthiness: 1 (shared production table, not an independent oracle)
- implementation_effort: 1 (small existing machine)
- maintenance_burden: 1 (depends on lifecycle table and Run construction)
- ci_runtime_cost: 1 (runs in the existing formal suite)
- async_distributed_friction: 1 (only sequential, in-memory transitions)

Net score: (0+2+1+1)/4 - (1+1+1+1)/4 = 0.0.
Disposition: INCUBATE. This row cannot support a current, all-leaf ranking.

## Independent repair and acceptance check (2026-11-26)

Frozen develop base: `7926d9ab4dda6a699a80536c6d03a59eab205725`.
The preserved merge conflict was completed without dropping either side's
unique conflicting changelog entries, then that base was merged. No quality
ledger or grant differs from that base.

A concrete defect in the epic's comparative machinery was reproduced: frozen
`AssuranceCandidate` objects retained mutable score/evidence dictionaries.
Clearing a caller-owned dictionary could remove an already-recorded row from
ranking; assignment through a candidate could rewrite scores or citations.
Four regression cases failed against the old harness and now pass after
copying both inputs into read-only snapshots. This is a **research artifact
defect**, owned and repaired in #880, not a live M0–M7 product defect. It was
found by inspection plus deterministic witnesses, not by the #881 state machine.
No false positive was observed in these four cases; this is not a measured
false-positive rate for any technique. Maintenance cost is two mapping copies
and four cases in the existing test module, with no new dependency or CI job.

Executed validation (job `ad341667e2e24753b26f0486edd200d6`; logs named
`check-*.log` in that job directory):

- `uv sync --locked --extra dev` succeeded.
- `uv run ruff check .` and `uv run ruff format --check .` passed (3678 files).
- With `PYTHONPATH=packages/maistro-evolve/src:packages/maistro-rsi/src`,
  `uv run pytest packages/maistro-rsi/tests -x -q` passed: **1819 passed,
  4 skipped**, 101.82 s, including all 26 matrix tests.
- With core/evolve/rsi source paths, `uv run pytest formal -x -q` passed:
  **668 passed, 4 skipped**, 56.37 s. The PostgreSQL lifecycle and lease/fence
  tests skipped without a DSN; they are **not acceptance evidence** in this run.
- Standalone matrix run: `uv run pytest
  packages/maistro-rsi/tests/test_m8a_assurance_baseline_research.py -x -q`
  passed **26 tests**, 0.06 s (local pytest time, not a CI latency estimate).
  `check-test-duplicates.py` also passed: 1844 unique files, no duplicates.
- Suite inventory matched **1823 RSI / 672 formal** collected nodes, including
  the new `packages/maistro-rsi/tests: +4` delta.
- Formal-oracle-independence against the frozen base, execution-lifecycles
  (19 classified vocabularies), and release-consistency gates passed.

| Epic acceptance requirement | Evidence / remaining gap |
| --- | --- |
| Real MAIstro target | Linear precursor calls production `transition_run`; persisted execution and other leaf seams not reverified here. |
| Current baseline | Historical audit preserved and explicitly dated; formal and RSI suites freshly executed. Current all-control cost/yield comparison **UNVERIFIED**. |
| Bounded prototype | Existing test-only matrix and collected helper machine remain; four cases repair the matrix's evidence snapshot boundary. No production rewrite. |
| Defects, false positives, CI cost, complexity, maintenance | Snapshot defect, red/green cases and suite costs above. Per-leaf measurement completeness **UNVERIFIED**. |
| Additional failure class | Helper/table enforcement mismatch and evidence mutation documented; neither is a proof of distributed execution semantics. |
| Terminal disposition per leaf | Precursor remains INCUBATE; other leaves' dispositions and their supporting evidence **UNVERIFIED** in this round. |
| Route live defects to M0–M7 owner | No live product defect established here; research-only snapshot defect repaired in #880. No GitHub mutations. |
| Ranked matrix across eight criteria when leaves complete | Scorer exercises all eight axes; population is six historical baseline rows plus one precursor, **not** a completed all-leaf comparative output. |

Accepted ADRs `ADR-081226-a66b` and `ADR-081426-1f7c` retain canonical domain
lifecycle ownership; `ADR-083126-5e62` separates evidence from the trusted
judge. Reconciliation: M8 scores and dispositions are advisory only, never
execution, authorization, event or quality-gate authority. A shared-table
model is not called independent, and randomized passing runs are not proofs.
The epic still needs a separately validated, current all-leaf synthesis;
this repair is a partial handoff, not integration approval or issue closure.

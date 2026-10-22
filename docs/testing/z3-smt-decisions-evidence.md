# Direct Z3/SMT modeling of a constraint-heavy decision: experiment record (#891, M8-A11)

Parent epic: #880 (advanced verification techniques). Deliverable per the
issue: one representative solver-backed experiment — satisfiability and
counterexample questions against a real constraint-heavy decision, compared
with the current procedural logic and tests — plus a
GRADUATE / INCUBATE / REJECT / WATCH disposition. Per the issue's non-goal,
no solver runtime dependency enters production; `z3-solver` is a dev-only
dependency and a source-scan test enforces that boundary.

## Target and baseline

One representative decision: **the schedule fire/skip core** of
`maistro.scheduling.engine.evaluate` — overlap policy × active-run ×
max_runs exhaustion over a due-occurrence vector. It is the constraint-heavy
decision the epic's scheduling bullet names, it is a pure function of its
arguments (no clock, no store), and its semantics are *documented* (the
`OverlapPolicy` docstrings, the `SkipReason.BUFFERED` contract, the
exhaustion rule on `ScheduleEvaluation.exhausted`) — so a contract encoding
can be written from the documentation and then differentially checked
against the code.

Baseline before this experiment: `tests/scheduling/test_engine.py` — 21
hand-written unit/property tests, two of them property-shaped (every due
occurrence accounted; fires never exceed the remaining budget, Hypothesis
over `runs_so_far × max_runs`). They check *samples*. None of them can ask
"does any input in this entire bounded space have a different answer?"

## Prototype

`packages/maistro-core/tests/scheduling/_z3_fire_contract.py` (machinery) +
`test_engine_z3_conformance.py` (13 node IDs):

- **Contract encoding** (`FireContractModel`): per evaluation cell, SMT
  constraints over decision variables — which due occurrence fires, the skip
  reason per occurrence, the cancellation request, the exhaustion flag —
  transcribed from the documented rules, not from the code paths.
- **Whole-grid differential**: 336 cells (due 0–5 × 4 policies × active-run ×
  budgets {unbounded, 1–6}). Per cell, the production function runs on a real
  `Schedule` and the solver answers two questions:
  *conforms* (sat) — production's decision satisfies the contract; and
  *unique-beyond* (unsat) — no other contract-satisfying decision exists.
  Together: production is **the unique function satisfying the documented
  contract on the entire bounded grid** — a completeness claim sampled and
  Hypothesis tests cannot make.
- **Teeth guards**: deliberately drifted encodings (SKIP encoded as ALLOW;
  the budget cap dropped) must turn the uniqueness query satisfiable with a
  witness — measured, so the differential is known not to be vacuous.
- **Counterexample/explainability queries** (`impossible_fire_core`):
  requesting a forbidden decision (fire under SKIP/BUFFER_ONE with an active
  Run; a non-exhausted evaluation with a spent budget) returns unsat, and the
  **unsat core names the blocking rule family** — `policy` for the overlap
  holds, `exhaustion` for the spent budget — matching the procedural reason
  codes.
- **Bounded closed-loop starvation model** (`BufferedStarvationModel`): four
  ticks of BUFFER_ONE with per-tick arrivals, the single held occurrence
  carried across evaluations, a symbolic run length (1–3 ticks or
  never-ending), and a fire budget. Every run length inside the bound is
  explored in one query: no tick ever idles with a held occurrence and
  remaining budget without firing; a run that ends within the horizon always
  drains the buffer; the budget is never exceeded. The one hold that never
  drains — a Run that never ends — is **satisfiable as a witness**,
  distinguishing declared hold semantics from starvation.
- **Short-circuit and horizon pins**: zero remaining budget and disabled
  schedules short-circuit before the core (excluded from the grid, pinned
  directly); occurrences behind the catch-up horizon are out of the
  enumeration walk entirely (see findings).
- **Boundary guard**: a source scan asserting no `packages/*/src` module
  references z3, plus a manifest scan asserting no shipped package or
  extension manifest declares the solver as a requirement in any group —
  the research non-goal cannot drift in through a static import *or* a
  dynamic load backed by an undeclared-at-source dependency.

## Findings

**No production defect found.** Every query that should be unsat was; every
counterexample-shaped question about production returned a proof rather than
a witness. Nothing to route to an M0–M7 owner. Two observations about the
*system*, not defects:

1. **The horizon is out-of-scope, not a skip.** `evaluate` never emits
   `OUTSIDE_CATCHUP` on this path: the walk starts at `enumeration_start`
   (never before the horizon), so occurrences older than the window are
   neither fired nor skipped — the caller learns the range from
   `enumeration_start` (#1059), and `window_clamped` documents the same
   shape for clamped hosts. An encoding that assumed a staleness axis
   (as an early draft of this experiment did) models semantics the engine
   does not have; the committed machinery records this in its module note
   and a test pins the behavior.
2. **The specification is functional, and that caps SMT's marginal value
   here.** Every documented rule pins exact outcomes, so "does a
   contract-satisfying decision different from production exist" reduces to
   "does production satisfy the contract". The uniqueness half of the
   differential is only non-trivial as a check that the encoding is *total*
   (under-constrained rules would leave cells satisfiable and name exactly
   where the written semantics underspecify the code). For decisions whose
   constraint systems admit many valid answers — assignment, exclusivity,
   allocation — this reduction does not happen and the solver's
   satisfiability/counterexample power is the point; this target is the
   degenerate case. That is a measured result, not a conjecture: the
   encoding effort (below) bought a certificate, not a discovery.

**False positives.** Three, all in the experiment's own machinery during
development, each caught by the differential exactly as designed: the
BUFFER_ONE hold was encoded as an override fighting the overlap tail (two
variants of the same transcription slip), and the witness extraction mapped
fire positions instead of occurrence indices. A `conforms` unsat or a
`unique_beyond` sat is a *divergence signal* that cannot tell spec-drift
from a production defect — a human reads the cell either way. That is the
maintenance cost of the technique stated precisely.

## Measurements

| Quantity | Value |
|---|---|
| Bounded cells certified | 336 (whole grid, no sampling) |
| Conformance walk (production run + encode + check per cell) | 0.60 s |
| Uniqueness walk | 0.60 s |
| Explainability queries (unsat cores) | 3 queries, each unsat with a 2-family core (blocking rule + request) |
| Closed-loop starvation queries | 12 queries (3 budgets × 4 properties), 0.07 s total |
| Teeth guards | 2 mutations, both detected with witnesses |
| Suite cost | +13 node IDs, ~3 s wall clock in `packages/maistro-core/tests` |
| Solver | z3-solver 5.1.0.0, per-query timeout 10 s (never approached), dev dependency only |
| Modeling effort | ~330 lines of machinery + ~230 lines of tests; the transcription bugs above were found and fixed by the differential within the first grid walks |

Solver performance and explainability are not the bottleneck: every query is
milliseconds and the cores name exactly the rule family a maintainer would
want. The costs are the encoding effort, the drift risk between docstrings
and encoding, and a dev-only but real dependency — all paid indefinitely if
the machinery is kept.

## What failure class does this catch that existing gates do not?

Honest answer for this target: **specification drift with complete
coverage**. Existing unit and property tests verify samples; mutation
testing verifies the tests. Neither can state "the code is the unique
function the written semantics allow on this whole bounded space". A policy
docstring that stops matching the code (or an encoding that under-states
the rules) is caught as a whole-space property, with an unsat core naming
the disagreeing rule. For *multi-solution* constraint decisions the same
machinery would additionally answer satisfiability/counterexample questions
that sampling cannot frame. The existing gates cover this target's sampled
behavior well — which is why the experiment found nothing.

## Disposition: WATCH

Not GRADUATE: no defect found, the duplication with the procedural logic is
nearly total for this functional target, and the cost side (encoding effort,
drift maintenance, a solver dependency in CI) is permanent.

Not REJECT: the technique produced the only whole-space certificate in the
repo's inventory, millisecond queries, and two-family unsat-core
explanations that read like the reason codes a maintainer would write. The
machinery is small, inert (test-tree only, source-scanned), and its teeth
are measured.

WATCH, with a concrete re-engagement trigger: apply this pattern to a
constraint-heavy decision whose valid-answer space is *not* a single point —
the issue's own examples that this leaf did not take up: agent/capability
assignment under eligibility and policy combinations, ownership exclusivity
("can two owners exist under the declared constraints"), or
graph/delegation legality. There the solver answers questions the
procedural tests cannot ask, and INCUBATE becomes a live option. Re-run the
measurement table on that target before deciding.

## Provenance

An earlier exploratory draft (two demo scripts modeling scheduling
admission and workspace authorization outside the test tree) was superseded
by this experiment: its solver calls re-wrapped procedural boolean checks
rather than encoding constraints, it did not run against the z3 API, and
root-level `examples/` sit outside the monorepo layout. The superseded
drafts are preserved with the attempt's records, not committed here. Per
the epic's non-goals, no competing `formal/` authority is established — the
machinery lives in the maistro-core test tree beside the target's suite.

## Review-findings disposition

Independent review of the experiment raised three findings; all three are
resolved on this branch:

1. **Starvation by replacement was invisible (addressed).** The closed-loop
   model stored only a 0/1 buffer count, so firing a *newer* occurrence
   while the held one stayed queued was indistinguishable from draining it.
   The model now carries occurrence IDs (`held[t]`/`fired[t]`), the
   starvation queries assert the *specific* held ID fires, and a
   `bypass-held` drift mutation proves the identity-blind encoding accepts
   what the ID-aware queries flag (the
   `test_starvation_queries_hold_occurrence_identity_not_just_a_count`
   teeth guard, the +13th node ID).
2. **The boundary guard scanned source only (addressed).** A manifest that
   declared `z3-solver` without any static import would ship the solver
   past a source-only scan. The guard now also parses every
   `packages/*` and `extensions/*` `pyproject.toml` (`tomllib`, fail-closed
   on unparsable input) and rejects the solver as a requirement in any
   dependency group; the root manifest's dev lists remain its only
   legitimate home.
3. **Run-length decrement phase in the closed loop (assessed; no change).**
   The observation: a run fired at tick t sets `run_left[t+1] = run_length`,
   so the busy period starts the tick *after* the fire, while the initial
   run is already in flight at tick 0. Measured against the
   fire-tick-counts variant (`run_left[t+1] = run_length − 1` on fire):
   both encodings give a fired run exactly `run_length` occupied ticks (the
   phase shifts, the duration does not — the "lasts one tick longer" reading
   does not hold), and every query verdict is identical under both —
   starvation, drain, budget, never-ending, and both mutation teeth, across
   budgets 1–3, faithful and mutated. The choice never flips an answer this
   experiment reports, so the committed encoding stays; if the model is
   ever re-anchored to production tick accounting, the phase convention
   should be decided then, not now.

# M8-A research note — direct Z3/SMT modeling of the schedule fire/skip decision

Epic: #880. Leaf: #891 (M8-A11). Initiative: #879.

Full experiment record with the measured tables, false-positive log, and the
review-findings disposition:
[`docs/testing/z3-smt-decisions-evidence.md`](../testing/z3-smt-decisions-evidence.md).
Committed machinery: `packages/maistro-core/tests/scheduling/_z3_fire_contract.py`
(encoding and closed-loop model) and `test_engine_z3_conformance.py` (13 node
IDs). This note is the M8-indexed summary; the evidence record stays beside
the suite it certifies.

## Hypothesis (from the issue)

Direct SMT modeling is valuable where MAIstro asks satisfiability/assignment
questions rather than executing arbitrary application code.

## Canonical target

One representative constraint-heavy decision: the **schedule fire/skip core**
of `maistro.scheduling.engine.evaluate` — overlap policy × active-run ×
max_runs exhaustion over a due-occurrence vector (the issue's
scheduling/resource-allocation candidate class). It is pure, documented
(`OverlapPolicy` docstrings, the `SkipReason.BUFFERED` contract, the
exhaustion rule on `ScheduleEvaluation.exhausted`), and already under test,
so an encoding written from the documentation can be differentially checked
against the code.

## Baseline

`packages/maistro-core/tests/scheduling/test_engine.py`: 21 hand-written
unit/property tests, two of them property-shaped (Hypothesis over
`runs_so_far × max_runs`). They check *samples*; none can ask whether any
input in an entire bounded space has a different answer.

## Method (bounded prototype, test tree only)

- **Contract encoding** (`FireContractModel`): per-cell SMT constraints over
  the decision variables (which occurrence fires, the skip reason per
  occurrence, cancellation, exhaustion), transcribed from the documented
  semantics, not the code paths.
- **Whole-grid differential**: 336 cells (due 0–5 × 4 policies × active-run ×
  budgets {unbounded, 1–6}). Per cell the production `evaluate` runs on a real
  `Schedule` and the solver answers *conforms* (sat) and *unique-beyond*
  (unsat): production is the unique function satisfying the documented
  contract on the entire bounded grid.
- **Teeth guards**: deliberately drifted encodings (SKIP encoded as ALLOW;
  the budget cap dropped) must turn uniqueness satisfiable with a witness.
- **Explainability**: forbidden-fire requests return unsat with a two-family
  unsat core (`policy` for overlap holds, `exhaustion` for the spent budget),
  matching the procedural reason codes.
- **Closed-loop starvation model** (`BufferedStarvationModel`): four BUFFER_ONE
  ticks with per-tick arrivals, the held occurrence carried *by ID*, symbolic
  run lengths, and a fire budget; every run length inside the bound explored
  in one query. The never-ending Run is satisfiable as the witness that holds
  forever — declared semantics, not starvation.
- **Boundary guard**: source scan (`packages/*/src`) plus manifest scan
  (`packages/*`, `extensions/*` `pyproject.toml`, all dependency groups)
  keep `z3-solver` a dev-only dependency — the issue's non-goal.

## Findings

- **No production defect found** — nothing to route to an M0–M7 owner.
- The horizon is out-of-scope, not a skip: `evaluate` never emits
  `OUTSIDE_CATCHUP` on this path (pinned by a test).
- The target is the degenerate case for SMT: the documented specification is
  functional (every rule pins exact outcomes), so the uniqueness query reduces
  to conformance. The certificate is real (whole-space, not sampled) but the
  duplication with procedural logic is nearly total. For multi-solution
  constraint decisions — assignment, exclusivity, allocation — the reduction
  does not happen, and the solver's satisfiability/counterexample power is the
  point.
- Three false positives during development, all in the experiment's own
  machinery, each caught by the differential; a divergence signal cannot tell
  spec-drift from a production defect without a human reading the cell.

## Measurements (summary)

| Quantity | Value |
|---|---|
| Bounded cells certified | 336 (whole grid, no sampling) |
| Conformance + uniqueness walks | 0.60 s each |
| Explainability queries | 3, each unsat with a 2-family core |
| Starvation queries | 12 (3 budgets × 4 properties), 0.07 s |
| Teeth guards | 2 mutations, both detected with witnesses |
| Suite cost | +13 node IDs, ~3 s wall clock |
| Modeling effort | ~330 lines machinery + ~230 lines tests |

## What failure class does this catch that existing gates do not?

For this target: **specification drift with complete coverage** — a policy
docstring that stops matching the code is caught as a whole-space property
with an unsat core naming the disagreeing rule. Sampled unit/property tests
and mutation testing cannot state "the code is the unique function the written
semantics allow on this whole bounded space".

## Disposition: WATCH

Not GRADUATE: no defect found, duplication is nearly total for this
functional target, and the costs (encoding effort, drift maintenance, a
dev-only solver dependency in CI) are permanent. Not REJECT: the technique
produced the repo's only whole-space certificate, millisecond queries, and
two-family unsat-core explanations; the machinery is small, inert, and its
teeth are measured.

Re-engagement trigger: apply the pattern to a constraint-heavy decision whose
valid-answer space is *not* a single point — the issue's own unclaimed
examples: agent/capability assignment under eligibility and policy
combinations, ownership exclusivity ("can two owners exist under the declared
constraints"), or graph/delegation legality. There INCUBATE becomes a live
option; re-run the measurement table on that target before deciding.

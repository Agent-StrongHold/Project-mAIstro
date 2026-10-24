# M8-A5 research note — differential reference-model testing for canonical state machines

Issue #885. Epic: #880. Initiative: #879. Milestone: M8. Status at this head:
**the experiment ran** — the prescribed prototype exists, works offline, and
produced a measured defect-yield comparison against an ordinary-assertion
control group. Terminal disposition: **INCUBATE**. No implementation defect
was found at this head, so nothing routes to an M0–M7 owner; the measured
synthetic-drift yield and the harness costs are recorded below.

## Research question

Can a deliberately simple reference model serve as an independent oracle for
complex production state machines and expose semantic drift that ordinary
assertions miss — and at what maintenance cost?

## Canonical seams (verified at this head)

The issue lists five candidate targets. One was prototyped; the others are
recorded with the reason each was not:

- **Run/NodeRun/Attempt lifecycle — prototyped.** The execution spine of the
  canonical model, one identity per work, gated by
  `scripts/check-execution-lifecycles.py`. The machine is pure and
  synchronous (`packages/maistro-core/src/maistro/runs/lifecycle.py`):
  transition tables plus earned completion (#43/#241), acceptance
  projection and supersession (#48, ADR-082426-a47f), the durable-Run fence
  (#1335), and lease reclaim (ADR-082426-e3ff/f170). No I/O, no database, no
  async — the exact shape the issue's experiment prescription asks for.
- **Invocation histories, event replay/checkpoints** — not prototyped: the
  durable stores behind them (SQLite/Postgres projections,
  `durable_runs/`) are I/O-bound; a no-I/O reference model would need a
  second seam (an in-memory store conformance target) before the differential
  comparison means anything. INCUBATE's first extension point.
- **Goal ownership/delegation** — not prototyped: the canonical Goal store
  does not exist at this head (#458); there is nothing to differentially test.
- **Registries/authorization state** — not prototyped: authorization is
  admission-time and ledger-owned; an independent oracle risks becoming a
  competing authorization path, which the campaign forbids. Out of scope by
  construction.

## Record

**Prototype** (this head):
`packages/maistro-core/tests/runs/test_m8a5_differential_reference_model_research.py`,
one test-side module (+31 node IDs, see
`docs/testing/inventory-notes/885-m8a5-differential-harness.md`). It contains:

- a `ReferenceModel` — ~330 lines of plain dataclasses and dicts whose
  transition tables, stamping, cascade, acceptance, completion, and lease
  rules were transcribed from the contract prose (lifecycle docstrings,
  ADR-082426-a47f/e3ff/f170, #43/#48/#230/#233/#241/#1335). An AST-pinned
  contract test keeps it free of `maistro` imports, so it cannot drift into
  a re-import of the thing it oracles;
- an `Executor` that drives the real functions (`transition_run`,
  `transition_node_run`, `transition_attempt`, `settle_open_node_run`,
  `check_completion_is_earned`, `refuse_completion_under_terminal_run`, the
  lease/reclaim helpers) over the same operation stream;
- `run_stream`, the differential driver: every op is applied to both sides;
  agreement is (both accept **and** full normalized state matches) or (both
  refuse **with the same category**); one operation kind (`tick`) advances a
  driver-owned logical clock and re-compares the observable state, because
  lease-expiry predicates are functions of time, not stored fields;
- ten hand-written semantic mutants (`Drift*` Executor subclasses), each
  emulating one plausible implementation drift, each proven non-vacuous by a
  minimal probe stream that is clean on the real implementation;
- a 12-assertion ordinary-assertion control group, matched to the coverage
  the existing lifecycle suite actually has at this head (first-start
  stamping, one refusal edge, acceptance requirement, supersession,
  earned-completion refusals, cascade/reclaim error text, lease expiry after
  the fact, wrong-token renewal) — with a guard test that the control group
  is green on the real implementation.

**Real drift found at this head: zero.** The differential property holds
over 150 generated streams per CI run, a one-off deep sweep of 1,000 streams
(~6,500 operations, seed-recorded in the job evidence), and a frozen
32-stream / 576-op corpus (243 driver-applicable ops). This is the answer to
"how often does the reference model reveal implementation drift?" for a
green implementation: not once in ~7,000 driven operations — which is the
expected result on a machine guarded by the existing suite plus mutation
testing, and is itself evidence that the oracle is not tuning out the
implementation (the same harness catches all ten injected drifts below).

**Defect-yield comparison** (the issue's deliverable). Ten semantic mutants;
detection = at least one failure. Ordinary assertions detected **6/10**; the
differential harness detected **10/10**:

| Injected drift                                                | Ordinary | Differential |
| ------------------------------------------------------------- | -------- | ------------ |
| M1 terminal states lose absorbing edges                        | yes      | yes          |
| M2 completion accepted without evidence                        | yes      | yes          |
| M3 superseded acceptance survives resumption                   | yes      | yes          |
| M4 completion consults the oldest NodeRun per node             | **no**   | yes          |
| M5 a paused human wait no longer blocks completion             | yes      | yes          |
| M6 lease expiry compares `<` instead of `<=` at the boundary   | **no**   | yes          |
| M7 an expired lease can be renewed with its old token          | **no**   | yes          |
| M8 `started_at` re-stamped on every RUNNING re-entry           | **no**   | yes          |
| M9 reclaim error anonymized (holder no longer named)           | yes      | yes          |
| M10 cascade error anonymized (Run outcome no longer named)     | yes      | yes          |

The four differential-only rows are exactly the "semantic drift that
ordinary assertions miss" the issue hypothesizes: M4 is a *which-record*
error invisible when a node has one NodeRun; M6 and M7 are *boundary*
errors invisible to after-the-fact assertions; M8 is a *preservation* error
invisible to set-once assertions. Honest caveats: these are injected
mutants, not historical defects — synthetic-drift yield bounds, not proves,
real-drift yield; the ordinary control group is a 12-assertion sample of the
real suite's coverage, so its 6/10 is a lower bound on the real suite's
yield; and the differential harness's detection surface includes the
hand-written probes, not only the generated corpus — the generated corpus
alone does not reach M3's eight-operation precondition chain or M4's
re-execution-then-complete pattern within 32 seeds, which is itself a
finding: **differential power is bounded by stream reachability**, and rare
contract paths need targeted probes even under model-based generation.

**Hypothesis shrinking.** Useful, with one asymmetry. For drifts whose
precondition chain random search can reach (M10: `add_node → queued →
settle`), `hypothesis.find` shrank a realistic 20-op counterexample to a
≤4-op minimal trace, byte-stable across reruns under `derandomize=True, database=None`
— quotable directly in a defect report. For chain-shaped drifts (M3's
acceptance-supersession chain) random search does not reach the divergence
in a 300-example budget over even a one-node alphabet; those drifts are
covered by hand-written probes instead. So: shrinking works when generation
reaches the defect; reachability, not shrinking, is the bottleneck.

**Transcription judgment calls** (the "how difficult is it to keep the model
independent" answer, itemized — this is the maintenance-cost evidence):

1. `reclaim_attempt`'s docstring says it settles "one Attempt whose lease
   lapsed", but the function does not itself check expiry — the recovery
   sweeps check before calling. The model encodes the *enforceable*
   contract (transition legality only). Encoding the prose-intent as a
   hard refusal would have produced a false positive on the first corpus
   run; deciding what the contract *is* is oracle-writer work no
   transcription can avoid.
2. A WAITING/PAUSED acceptance pins its NodeRun: moving to the other wait
   status is table-legal but unrepresentable (status ≠ accepted
   logical_status), and the implementation refuses it with a raw
   pydantic `ValidationError` rather than `InvalidLifecycleTransition`.
   The model normalizes both to a refusal *category* ("unrepresentable" vs
   "illegal") and compares categories — which is how the harness surfaced
   the distinction in the first place.
3. A newly supplied acceptance wins over supersession-clearing
   (implementation precedence); the model mirrors it. Written the other
   way, the harness would have flagged a real-looking divergence during
   bring-up.
4. Driver preconditions (an `AcceptedNodeOutcome` can only be constructed
   from a physically completed Attempt; acceptance only names acceptable
   logical statuses) are evaluated on the model and are construction
   constraints, not lifecycle rules — smuggled rules here would have made
   the oracle agree by construction.

**Normalization boundaries required** (the issue's question, answered):

- the logical clock is driver-owned and injected into every transition, so
  timestamps compare exactly; with a wall clock, only invariants
  (presence/ordering) would survive;
- statuses compare as strings; acceptance records compare by projection
  (`logical_status`/`result`/`error`), not identity;
- constructor-side stamps (`created_at`, `issued_at`, `accepted_at`)
  compare by presence only;
- the legacy completed→completed hydration path is excluded from the op
  vocabulary (a migration compatibility shim, not a lifecycle rule);
- refusal comparison is two-level: agreed refusal + agreed category, so a
  drift that merely changes *which rule* fires is still visible.

**Costs.** The oracle is ~330 lines against the implementation's ~560; the
suite runs in ~2s. Contract evolution surfaces as loud harness failures, not
silent passes: any added or removed lifecycle edge, stamping rule, or
refusal category diverges on generated streams that exercise it. The
recurring cost is the transcription judgment list above, which grows with
semantic (not syntactic) contract change.

## Trust boundary

This module **imports `maistro`** — a deliberate departure from the other
M8 harnesses, reconciled here against M8 guardrails 1–2. A differential
oracle that never touches the implementation under test is vacuous; driving
the real `maistro.runs.lifecycle` is the experiment. The guardrails' intent
(no research artifact may become an authority or ship as product code) is
preserved by construction: the module lives entirely under `tests/`, is
imported by no product module, computes nothing any authority reads, adds
no work-state vocabulary (the execution-lifecycles ledger gate polices that
independently), and its only outputs are assertions inside the file. The
oracle half is additionally AST-pinned to stay `maistro`-free. Run/NodeRun/
Attempt remains the one execution identity.

## Disposition

- **#885 (differential reference-model testing): INCUBATE** — the prototype
  is real, offline, cheap (~2s CI), and demonstrated a 4-mutant detection
  advantage over a faithful ordinary-assertion control group on the
  canonical execution spine; adoption as a standing gate is a product
  decision for the Run/NodeRun/Attempt owners, not something this note
  authorizes.
- Move to **GRADUATE** when the harness catches a real (non-injected)
  implementation drift on a production seam, or when the runs owners adopt
  the differential property as a standing CI gate with an explicit
  maintenance grant for the oracle.
- Move to **REJECT** if, over a real evolution window, oracle transcription
  breaks on contract changes that the ordinary suite plus mutation testing
  already catch — i.e., if the maintenance column dominates a yield column
  that stays at zero real finds.

Extension order if incubated: invocation histories and event replay next
(they need an in-memory conformance seam first), then registries. Goal
ownership remains untestable until #458 lands. No adoption is authorized by
this note.

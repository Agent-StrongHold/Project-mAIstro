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
one test-side module (+32 node IDs, see
`docs/testing/inventory-notes/885-m8a5-differential-harness.md`). It contains:

- a `ReferenceModel` — ~330 lines of plain dataclasses and dicts whose
  transition tables, stamping, cascade, acceptance, completion, and lease
  rules were transcribed from the contract prose (lifecycle docstrings,
  ADR-082426-a47f/e3ff/f170, #43/#48/#230/#233/#241/#1335). An AST-pinned
  contract test keeps it free of `maistro` imports *and* of references to
  the production symbols the driver imports, so it cannot drift into
  delegating to the thing it oracles;
- an `Executor` that drives the real functions (`transition_run`,
  `transition_node_run`, `transition_attempt`, `settle_open_node_run`,
  `check_completion_is_earned`, `refuse_completion_under_terminal_run`, the
  lease/reclaim helpers) over the same operation stream;
- `run_stream`, the differential driver: every op is applied to both sides;
  agreement is (both accept **and** full normalized state matches) or (both
  refuse with the same category **and** the post-refusal state still
  matches — a refusal is expected to be atomic); one operation kind (`tick`)
  advances a driver-owned logical clock and re-compares the observable
  state, because lease-expiry predicates are functions of time, not stored
  fields; lease renewals present the *model's* fencing token, so token
  rotation or mis-derivation on the real side cannot renew against its own
  drift;
- ten hand-written semantic mutants (`Drift*` Executor subclasses), each
  emulating one plausible implementation drift, each proven non-vacuous by a
  minimal probe stream that is clean on the real implementation;
- a 13-assertion ordinary-assertion control group, matched to the coverage
  the existing lifecycle suite actually has at this head (first-start
  stamping, one refusal edge, acceptance requirement, supersession,
  earned-completion refusals, the retried-node newest-wins rule, cascade/
  reclaim error text, lease expiry after the fact, wrong-token renewal) —
  with a guard test that the control group is green on the real
  implementation.

**Real drift found at this head: zero.** The differential property holds
over 150 generated streams per CI run, a reproducible deep sweep of 1,000
seeded streams (18,000 generated / 5,764 driven operations — replayed by
`test_deep_sweep_replays_one_thousand_seeded_streams`, which regenerates
`corpus_stream(seed)` for seeds 0–999 deterministically), and a frozen
32-stream / 576-op corpus (243 driver-applicable ops). This is the answer to
"how often does the reference model reveal implementation drift?" for a
green implementation: not once in ~24,000 driven operations — which is the
expected result on a machine guarded by the existing suite plus mutation
testing, and is itself evidence that the oracle is not tuning out the
implementation (the same harness catches all ten injected drifts below).

**Defect-yield comparison** (the issue's deliverable). Ten semantic mutants;
detection = at least one failure. Scored on **matched scenarios**: the
ordinary control group and the differential harness both face every mutant
with the same shared material (13 fixed assertions; the same 32-stream
corpus for every mutant), and each mutant's own hand-written probe is
reported as a **separate column** — a probe is written from its mutant, so
it proves non-vacuity and bounds targeted-harness power, but folding it into
the comparison column would make detection true by construction. Ordinary
assertions detected **7/10**; the differential harness on the shared
generated corpus alone detected **4/10**; with the mutant's targeted probe
added, the harness detected **10/10**:

| Injected drift                                                | Ordinary | Differential (shared corpus) | Differential (+ own probe) |
| ------------------------------------------------------------- | -------- | ---------------------------- | -------------------------- |
| M1 terminal states lose absorbing edges                        | yes      | yes                          | yes                        |
| M2 completion accepted without evidence                        | yes      | yes                          | yes                        |
| M3 superseded acceptance survives resumption                   | yes      | **no**                       | yes                        |
| M4 completion consults the oldest NodeRun per node             | yes      | **no**                       | yes                        |
| M5 a paused human wait no longer blocks completion             | yes      | **no**                       | yes                        |
| M6 lease expiry compares `<` instead of `<=` at the boundary   | **no**   | **no**                       | yes                        |
| M7 an expired lease can be renewed with its old token          | **no**   | **no**                       | yes                        |
| M8 `started_at` re-stamped on every RUNNING re-entry           | **no**   | **no**                       | yes                        |
| M9 reclaim error anonymized (holder no longer named)           | yes      | yes                          | yes                        |
| M10 cascade error anonymized (Run outcome no longer named)     | yes      | yes                          | yes                        |

Read honestly, the table records **two** findings, not one:

- The probe-completed harness detects everything the ordinary suite detects
  and three rows only it catches. M6 and M7 are *boundary* errors invisible
to after-the-fact assertions; M8 is a *preservation* error invisible to
set-once assertions. M4 is *not* one of them: the control group deliberately
matches the existing suite's coverage, and the real suite already covers the
retried-node case
(`test_spine_conformance.py::_assert_a_retried_node_does_not_condemn_its_run`),
so an ordinary assertion mirroring it detects M4 — claiming otherwise would
have understated the ordinary suite by construction.
- On the shared generated corpus alone the differential harness detects
  **fewer** mutants than the ordinary suite (4/10 vs 7/10). Model-based
generation does not replace targeted scenarios; it extends *coverage width*
(every step's full state compared) while remaining bounded by stream
reachability — the generated corpus alone does not reach M3's
acceptance-supersession chain, M4's re-execution-then-complete pattern, or
the M6–M8 timing/preservation boundaries within 32 seeds. **Differential
power is bounded by stream reachability**, and rare contract paths need
targeted probes even under model-based generation. That is the honest cost
line for the runs owners, not a detraction: the oracle's marginal value over
a good point-assertion suite is the three boundary/preservation rows plus
whole-state observation, and both of those required targeted material to
measure.

Honest caveats: these are injected mutants, not historical defects —
synthetic-drift yield bounds, not proves, real-drift yield; the ordinary
control group is a 13-assertion sample of the real suite's coverage, so its
7/10 is a lower bound on the real suite's yield.

**Hypothesis shrinking.** Useful, with two recorded asymmetries. First, the
recorded long counterexample itself (18 operations of realistic traffic
around an M10 divergence) fed through a deterministic delta-debug pass
(chunk halving down to unit removals, committed as
`TestShrinkingEvidence._delta_debug`) shrinks to a **2-operation** minimal
divergence (`add_node n0` → `settle_open n0 failed`), byte-stable by
construction — quotable directly in a defect report. Second,
`hypothesis.find` run independently in a deliberately reduced one-node
alphabet (the reduction a human debugger performs) both reaches and shrinks
an M10 divergence to a ≤4-operation trace, byte-stable across reruns under
`derandomize=True, database=None`. That reduced space cannot express the
recorded trace — the two results are separate measurements, not one. For
chain-shaped drifts (M3's acceptance-supersession chain) random search does
not reach the divergence in a 300-example budget over even a one-node
alphabet; those drifts are covered by hand-written probes instead. So:
shrinking works when generation reaches the defect; reachability, not
shrinking, is the bottleneck.

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
- lease identity compares in full — holder, fencing token, and expiry — not
  just the expiry; renewal presents the oracle's token (one shared token
  source), so a real side that rotated tokens on renew, reused a stale
  token, or drifted the holder diverges either at the refusal or in the
  snapshot;
- constructor-side stamps (`created_at`, `issued_at`, `accepted_at`)
  compare by presence only;
- the legacy completed→completed hydration path is excluded from the op
  vocabulary (a migration compatibility shim, not a lifecycle rule);
- refusal comparison is three-level: agreed refusal, agreed category, and
  agreed post-refusal state — so a drift that changes *which rule* fires, or
  one that mutates a record before refusing (breaking refusal atomicity),
  is still visible.

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
  is real, offline, cheap (~2s CI), and demonstrated a 3-mutant detection
  advantage over a faithful ordinary-assertion control group on the
  canonical execution spine (boundary/preservation drifts only an
  always-on oracle sees), alongside an honestly recorded weakness: on the
  shared generated corpus alone it under-detects a good point-assertion
  suite (4/10 vs 7/10), so its value is whole-state observation plus
  targeted probes, not blind generation. Adoption as a standing gate is a
  product decision for the Run/NodeRun/Attempt owners, not something this
  note authorizes.
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

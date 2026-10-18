# Deterministic crash/failpoint testing: experiment record (#883, M8-A3)

Parent epic: #880 (advanced verification techniques). Deliverable per the
issue: a bounded prototype, recorded evidence, and a
GRADUATE / INCUBATE / REJECT / WATCH disposition. Production fixes belong to
the affected M0-M7 owner; this record routes findings, it does not change
production semantics.

## Prototype

`packages/maistro-core/tests/failpoints/` — a test-tree failpoint lab
(`_failpoints.py`) plus two deterministic matrices:

- execution spine: `tasks/execution.py` — 10 cells;
- external effects: `capabilities/invocation.py` — 7 cells;
- machinery guards: 5 cells (inertness, fire-once, source scan).

22 node IDs total, deterministic (fixed inputs, one forced crash per cell, no
randomness, no wall-clock assertions — recovery is driven at
`now + 1h` so lease expiry is structural, not timed).

## Targets and baseline

The issue's candidate targets, and what already covered them before this
experiment:

| Target | Prior evidence | What this prototype adds |
|---|---|---|
| TaskRunner / Attempt execution | `tests/runs/test_crash_window_invariants.py` (5 spine windows), `tests/runs/test_recovery_evidence_pack.py` | a generated matrix over the *task* dispatch path (`TaskAttemptExecutor`), including receipt reconciliation (#849) and the queued-vs-WAITING resume split |
| Invocation provider dispatch | `tests/capabilities/test_invocation_reconciliation.py` (one hand-written crash-after-effect case) | the full seam × mode × recovery cross-product with an exactly-once oracle |
| Durable event/checkpoint stores | recovery events pipeline tests | not extended here (bounded scope; see disposition) |
| Reactor/recovery paths | `Container.recover_abandoned_attempts` coverage | driven as-is — the matrix deliberately uses the canonical recovery halves, never a second authority |

## Instrumentation design

A crash is a forced interleaving, not sleep-and-hope: `CrashPoint` wraps any
store and raises a `BaseException` (`CrashSimulated`) at one named write —
before it commits (crash-before) or after it lands (crash-after). This is the
same forced-interleaving discipline the existing kill-recovery suites use,
generalized so one wrapper carries any store's seams. `StatusJournal` records
every status observation a scenario makes and reports any entity observed
non-terminal after having been terminal (the "terminal state cannot regress"
property, checked over the whole timeline, not just the endpoint).
`EffectLedger` is the modeled remote system, written before the provider
returns so crash-after-effect leaves it holding an effect the engine ledger
may not know about.

The machinery lives entirely under `tests/`. It cannot ship enabled because it
cannot ship at all — `test_no_production_module_imports_the_failpoint_lab`
holds that boundary executable. This was also the only ledger-safe placement:
new `src/` symbols used only by tests would mint vulture identities that
cannot be banked in the same change (two-merge rule), and the reachability
gate would see a never-wired production module.

## Matrix cells and recorded dispositions

Execution spine (each cell: one crash, then the canonical recovery halves —
`reclaim_expired_attempts` + `AttemptLifecycleReconciler`, exactly what
`Container.recover_abandoned_attempts` runs — then re-drive):

| Seam | Mode | Recorded disposition |
|---|---|---|
| `claim` | before | Run stays QUEUED; boot recovery rehydrates it into the restarted queue; a worker pass completes it; receipt written by the queue that owns it |
| `claim` | after | the atomic claim (#1114) leaves RUNNING + NodeRun + leased Attempt with zero work done; the lease sweep reclaims, the reconciler parks WAITING, the dispatch seam's retry path finishes; exactly one NodeRun, ordinals [1,2] |
| work, effect-before | — | attempt reclaimed, retry applies the effect once |
| work, effect-after | — | **the effect is applied twice** — see findings |
| attempt terminal commit | before | same at-least-once boundary as work-effect-after |
| attempt terminal commit | after | durable Attempt holds the result; redispatch is refused (`completed Attempt awaits domain acceptance`); the reconciler replays acceptance and the Run completes **without re-running the work** |
| Run terminal commit | before | NodeRun accepted, Run RUNNING; reconciler settles from evidence; no re-run |
| Run terminal commit | after | Run COMPLETED; receipt reconciled by recovery (#849); no re-run |

Invocation boundary (each cell: at most one physical provider call, ever):

| Seam | Mode | Recorded disposition |
|---|---|---|
| admission | before | nothing recorded; retry admits fresh and dispatches once |
| admission | after | CREATED row blocks retry (`UnsafeEffectRetry`); discovery lists it (`dispatch_active` false — crash-before-effect); NOT_APPLIED evidence frees the effect; retry dispatches once |
| running persistence | after | RUNNING + `dispatch_active` blocks retry; discovery distinguishes it from a CREATED row; NOT_APPLIED frees it; one dispatch |
| terminal commit | before | effect applied remotely; RUNNING row blocks a second call; a provider-adapter report settles APPLIED from the remote ledger; replay never re-calls |
| terminal commit | after | terminal row landed; retries are pure replays of the same invocation id |
| control (no crash) | — | ordinary exactly-once replay |

## Findings

1. **No new production defect at the tested seams.** Every recorded
   disposition above matches the contract the module docstrings and prior
   evidence claim: the atomic claim leaves no stranded RUNNING Run; refusal
   plus evidence replay prevents a duplicate effect where the result is
   durable; the Invocation ledger keeps provider calls at most once across
   every tested crash point and recovery. The prototype's counterexample
   search found nothing to route to an M0-M7 owner from these seams.
2. **The layering boundary is the finding worth keeping.** Work whose result
   was lost with the process is re-run: the execution spine is at-least-once
   for *work*, and exactly-once for *external effects* is entirely the
   Invocation effect-key ledger's job (`crash work-after-effect` applies the
   modeled effect twice; the invocation matrix proves the ledger prevents the
   same ordering at the effect boundary). A task executor that performs an
   unguarded external call inside its work is exactly where the issue's
   "no duplicate external effect" property would fail — the matrix makes the
   boundary explicit instead of letting it stay folklore.
3. **One in-memory-tier receipt gap, documented not fixed.** A Run parked
   WAITING by attempt recovery resumes through the dispatch seam's retry
   path; on the in-memory tier the receipt lived in the dead process, so a
   cold restarted queue has no receipt until the Run terminalizes and
   recovery reconciles it. Durable tiers repair this at recovery time
   (#849, `test_receipt_durability.py`). Existing known behavior; the matrix
   pins it per cell so a future change that regresses the durable path fails
   a named cell.
4. **False positives: none.** The `when` predicate shape means a seam armed at
   a multi-write method (e.g. `save`, `transition_run`) only fires on the
   named write; `test_a_predicate_rejecting_call_does_not_spend_the_failpoint`
   pins that a rejected call does not spend the armed failpoint — the failure
   mode that would make a matrix cell pass for the wrong reason.

## Cost

- Runtime: ~1.5 s wall for all 22 cells (deterministic; no sleeps, no
  resource contention — lease windows are asserted at a pinned `now`).
- CI cost: one extra directory in an existing collected suite; no new job, no
  services, no Docker. The inventory delta is recorded
  (`docs/testing/inventory-notes/883-crash-failpoint-matrix.md`, +22).
- Complexity/maintenance: the reusable core is ~230 lines; adding a seam to an
  existing matrix is one `Failpoint` entry plus one parametrize value. Adding
  a new *boundary* needs a wiring helper per boundary (the two matrices carry
  ~100 lines each of scenario scaffolding), which is the main scaling cost.

## What failure class this catches that existing gates do not

Property and mutation testing explore *inputs* against code that is allowed to
run to completion; the existing crash-window suite explores *named two-write
seams* on one spine. Neither generates the cross-product of operation × crash
point × recovery strategy with a whole-timeline oracle (terminal-no-regression)
and a remote ground truth (duplicate-effect detection). The class is
"durable-state machines observed across process death at arbitrary commit
boundaries" — ambiguities that only exist when a write lands without its
successor. The invocation matrix's discovery-eligibility assertions, for
example, fail if anyone weakens `dispatch_active` bookkeeping, which
input-level testing cannot see.

## Disposition: INCUBATE

Reasons:

- The technique found no new defect here, but the spine it found nothing in is
  the one crash-window testing already hardened; the invocation matrix and the
  receipt/queued-vs-WAITING splits are new surface, and the cells pin contracts
  (discovery eligibility, evidence-replay-not-rerun, receipt reconciliation)
  that nothing else asserts as a cross-product.
- Cost is small and the machinery is reusable across stores (any object with
  async write methods), so extending to the checkpoint store and reactor seams
  (the two candidate targets not covered) is incremental.
- Not GRADUATE: promotion into `maistro.testing` (for cross-package reuse) is
  blocked on the vulture/reachability banking path — a grant would have to
  land first, then the move (two-merge rule), and the reachability ratchet
  would need the module wired from a declared entry point. That decision
  belongs to the M8 comparative output once sibling leaves (#881, #882, #888)
  report whether they want the same lab.
- Not WATCH/REJECT: the prototype is already load-bearing regression coverage
  for #1114/#849/#1194 contracts in matrix form; deleting it would lose
  assertions nothing else makes.

Next steps if incubated: extend the same lab to the checkpoint store
(`tasks/checkpoint.py`) and shutdown settlement (`TaskRunner.stop` /
`_settle_cancelled`); consider the `maistro.testing` promotion decision
together with the sibling M8 leaves.

# M8-A research note — stress Invocation effect/idempotency semantics with stateful property testing

Epic: #880. Leaf: #882 (M8-A2). Initiative: #879.

## Hypothesis (from the issue)

The canonical Invocation/effect boundary is a high-value target for generated
histories because correctness depends on prior outcomes, retries, cancellation,
and stable logical effect identity rather than isolated inputs.

## Canonical target

`maistro.capabilities.invocation` — `InvocationExecutionService` over
`InMemoryInvocationStore`, plus the store's atomic `claim`
(ADR-081226-6b46). The governed wrapper and the durable SQLite/PostgreSQL
stores sit above/below the same lifecycle and are recorded as follow-up, not
prototype scope.

## Baseline (what existed before this leaf)

- Four conformance files exercise the lifecycle directly:
  `test_invocation_reconciliation.py`, `test_binding_invocation.py`,
  `test_invocation_store.py`, `test_effect_replica_conformance.py` —
  63 tests, all passing at base `28614700b` (3.6s). The full
  `packages/maistro-core/tests/capabilities` directory is 708 tests.
- All of them are hand-written scenarios. No stateful generator explored
  outcome-dependent retry/ambiguity orderings at this seam;
  `formal/` (the Hypothesis stateful suite, #410 evidence rules) had no
  Invocation model.

## Prototype

`formal/models/test_invocation_effect_idempotency.py` (new): a Hypothesis
`RuleBasedStateMachine` driving the real service, plus two minimal-sequence
`@given` properties. It generates histories across
CREATED/RUNNING/COMPLETED/FAILED/UNKNOWN with retries under fresh Attempt
IDs, provider `EffectNotApplied`, generic exceptions, cancellation, operator
reconciliation (APPLIED / NOT_APPLIED / INDETERMINATE), NodeRun switches, and
duplicate concurrent logical effects raced by two workers sharing one ledger.
The issue's six candidate invariants — COMPLETED logical effects never
dispatch twice; UNKNOWN/RUNNING/CREATED block automatic repetition; only
proven-not-applied FAILED effects are retryable; logical effect identity is
stable across physical Attempts; terminal records always carry terminal
timestamps; concurrent same-effect attempts cannot cause duplicate provider
execution — are asserted against an independent per-identity outcome model;
the provider executor is the only place a dispatch is ever counted.
Registered as counted invariants I31 in
`formal/INVARIANTS.md` per the #410 evidence rules.

## Results

**Zero production counterexamples.** 100 CI-profile examples per run
(derandomized) and a 1000-example run found no input where the
implementation violated any of the six candidate invariants. Every failure
observed during development was a defect in the model, not the
implementation — three false positives, all instructive:

1. **Race-key reuse (harness bug).** The race rule recycled an
   already-completed effect key and demanded one new dispatch; a completed
   effect correctly replays with zero dispatches. Fixed by generating a
   fresh key per race.
2. **Scope confusion (oracle bug).** A post-APPLIED replay omitted
   `logical_effect=True`, so the oracle assumed Run-scoped replay while
   invoking a NodeRun-scoped new effect — which correctly re-dispatched.
   Fixed in the oracle.
3. **UNKNOWN terminal-timestamp confusion (contract subtlety).** After
   INDETERMINATE evidence the model asserted `finished_at is None`, but an
   UNKNOWN row was already lifecycle-terminal when the ambiguity was
   recorded; reconciliation leaves that record intact. Fixed in the oracle;
   the distinction (UNKNOWN blocks retries *and* carries a terminal
   timestamp) is exactly the kind of double-vocabulary hazard that motivated
   the issue.

**Unique yield beyond the conformance suite: 2 of 5 mutants.** A five-mutant
battery against `invocation.py` (in-tree edit, `/tmp` backup, `cp` restore;
SHA-256 verified byte-identical after the run):

| Mutant | Defect class | 63 conformance tests | 708 capabilities tests | Formal model |
|---|---|---|---|---|
| M1 | foreign non-terminal admission guard dropped (`_settled_by_another_admission`) | survive | survive | **caught** |
| M2 | UNKNOWN made retryable in *both* guard layers (`_prior_effect` + admission guard) | caught | caught | caught |
| M3 | terminal timestamp dropped (`_terminalize`) | caught | caught | caught |
| M4 | #1194 logical-effect admission widening narrowed | caught | caught | caught |
| M5 | ordinary effects over-widened to Run scope | survive | survive | **caught** |

M1 removes the only guard that refuses a second dispatch when a worker's
claim returns *another worker's non-terminal row* — a state reachable only
when two services share a ledger and the loser's history read precedes the
winner's claim. No hand-written test constructs that interleaving; the
generated race does, every run. M5 silently deduplicates *ordinary*
capability effects across NodeRuns (the opposite of M4) — a plausible
over-generalization of the #1194 widening that nothing pins today.

**Defense-in-depth finding (WATCH-class).** M2 restricted to a *single*
guard layer survives every suite, including the new model: retry blocking
holds if either layer refuses, and the refusal is not attributable to a
layer (both raise `UnsafeEffectRetry`). The duplication is therefore
load-bearing but unverifiable one layer at a time; a refactor that removes
one layer's UNKNOWN handling ships green. Recorded for the canonical
Invocation owner; per the epic, defects/gaps route to M0-M7 owners rather
than being "fixed" in M8.

**Harness-vacuity finding.** With non-yielding resolver/executor stubs, the
race rule collapsed to one atomic admission per worker and M1/M4 survived:
the interleaving window the guards exist to close never opened. A stateful
model of concurrent seams must yield where production awaits I/O, and
mutant verification is what exposed the vacuity — a green generated suite
proved nothing until the battery ran.

**Runtime/CI cost.** CI profile: 3 collected tests, ~4.8s (100 machine
examples x up to 50 steps + 40 property examples). 1000-example run: 44.3s,
linear. The suite already runs on every PR via `formal-conformance.yml`
(with PostgreSQL for I29), so the marginal CI cost of registering this model
is ~5s. Shrink quality: each dev-time failure minimized to a 2-4 step
sequence automatically.

**Developer complexity / maintenance.** One file following the existing
formal-model conventions (shared conftest profiles, documented
counterexample classes, demonstrated mutants). The oracle encodes the
documented admission-identity contract (#1194, module docstring); if that
contract changes legitimately, the model updates with it — same maintenance
class as I29's import-the-store's-table rule.

## What failure class existing gates do not catch

Outcome-dependent *interleavings*: states that only exist between two
workers' admissions on a shared ledger (M1), and scope-widening in the
unprofitable direction (M5). Scenario tests enumerate histories someone
thought of; the generator explores the ordering space where those two
defects live. Mutation testing (parked per the #880 baseline audit) would
find these mutants only if a harness ran this file against them — the model
is the missing half.

## Disposition

**GRADUATE** — for this seam, at this scope. The model is registered as
standing evidence (I31 in `formal/INVARIANTS.md`), runs in the already-required
formal-conformance job, costs ~5s, and demonstrated unique protection
(2/5 guard-erosion mutants invisible to 708 conformance tests) with zero
production false positives across 1000+ generated histories.

INCUBATE follow-ups (not done here, deliberately bounded prototype):
- a durable-store leg (SQLite/PostgreSQL `claim` semantics under real
  connection races, alongside I29's PostgreSQL pattern);
- the governed wrapper's policy/approval paths;
- observability: wire `formal/models` invocation-mutant runs into the parked
  mutation-testing policy (#894 owner).

## Trust boundary

The prototype imports only `maistro.capabilities.binding` and
`maistro.capabilities.invocation` through their public seam as a consumer.
It writes no Goal, no Run, no routing decision, and no
Warden/HITL/delegation control, and cannot become an authority: it is test
code in `formal/models/`. No live production defect was found, so nothing
needed routing to a canonical owner; the single-layer-M2 coverage gap above
is recorded for them instead.

# M8-A research note — stateful generated workflows across multi-step APIs

Epic: #880. Leaf: #893 (M8-A13). Initiative: #879.

## Hypothesis (from the issue)

MAIstro's API testing gains substantially more value from exploring legal and
adversarial multi-step *workflows* — creation chains, cross-principal access,
idempotent retries, stale identifiers — than from independent (stateless)
OpenAPI requests. The deliverable is one representative stateful API workflow
suite plus a terminal disposition, without duplicating existing endpoint tests
unless the workflow adds a new state/relation failure class.

## Canonical target

The `maistro-server` HTTP surface: `POST /tasks` (admission with
`Idempotency-Key`), `GET/DELETE /tasks/{id}`, `GET /runs/{id}`,
`POST /runs/{id}/cancel`, `GET /runs/{id}/node-runs`, `POST /workspaces`, and
the workspace project tree — driven in-process over the same in-memory
canonical Run spine (`wire_execution_spine`) the production lifespan wires for
a no-database deployment. Candidate workflows from the issue map as follows:
Workspace → Project → task/Run → cancel/query/retry (modeled; the Goal seam is
not HTTP-exposed on this surface, recorded below), resource as principal A →
access as principal B (modeled), idempotency-key repeat/retry (modeled),
create/delete/query stale identifiers (modeled), schedule/cancel/recreate (not
representable — no HTTP schedule route on this surface; recorded below).

## Baseline (what existed before this leaf)

- **Stateless endpoint tests.** At the leaf base (`af7996883`) `packages/maistro-server/tests`
  alone collected 538 tests; with `packages/maistro-core/tests/tasks` the stateless battery was
  996-998 tests (25 skipped without a DSN). At the develop-sync head (`e20e9f52` merged) the
  same battery collects 1104: server 581 (573 passed / 8 skipped) plus core tasks 523
  (506 passed / 17 skipped). They pin single-request contracts
  thoroughly: 202/409/422 idempotency shapes, owner-scoped reads, cancel
  semantics, cross-caller key scoping.
- **Stateless schemathesis CLI against the live dev server** (ad-hoc run left
  by an earlier #893 attempt, `.schemathesis/default/cache/crashes/`, not a
  committed gate): 300 crash fingerprints over 275 distinct operations, of
  which 273 first-responses were **429** (rate limiter), 25 were 404, one 200.
  The dominant yield of full-surface stateless fuzzing was undocumented-429
  conformance noise — a real spec gap, but not workflow signal, and unusable
  as a PR gate because it needs a running stack.
- **Native Schemathesis stateful testing** (`schema.as_state_machine()`)
  cannot run against this surface at all: it requires OpenAPI response
  `links`, and the served spec declares none (now pinned by a committed
  contract probe). The leaf therefore evaluates the issue's explicitly allowed
  alternative: *equivalent generated workflow testing* — a Hypothesis
  `RuleBasedStateMachine` whose request bodies are still schema-generated from
  the served OpenAPI document via schemathesis positive-mode strategies.

## Prototype

`packages/maistro-server/tests/api/test_stateful_workflow_api.py` (committed,
runs in the standard server test job). A state machine drives the real routers
through ASGI with two switchable authenticated principals. Schemathesis
supplies per-request bodies from the served OpenAPI schema; the workflow layer
supplies transitions, bundles, and oracles. Fourteen rules plus one global
invariant pin relations, not endpoints:

- admission under explicit keys with a collision-prone pool: replay of the
  same payload reconciles to the original receipt and Run; a different
  payload under the same key is a 409 that mints nothing; a second principal
  sharing a textual key admits its own run;
- keyless admission: byte-identical retries reconcile by derived key inside
  the 24h window; per-scenario salts keep scenarios from reconciling across
  examples;
- retry of a **terminal** admission answers with the original identity and the
  terminal status — never a fresh run over finished work;
- task-route cancel terminalizes receipt and Run together, a repeat cancel is
  the pinned 400; run-route cancel does the same from the other direction — it
  terminalizes the canonical Run *and* projects that truth onto the receipt
  inside the same request, after which the receipt route refuses the repeat
  (400) and the run route stays idempotent. **This oracle changed shape at the
  develop sync:** the leaf base left the receipt `queued` until a worker
  reconciled it, the run-cancel receipt projection closed that asymmetry, and
  the suite went red on the merge naming the exact route pair (*Develop sync*
  below);
- cross-principal probes of tasks, runs, node-runs, workspaces, and the
  project tree are 404 without existence leaks, leave state untouched, and
  listings never show another principal's receipt;
- fabricated identifiers are 404s on both surfaces for any principal; the
  workspace-scope header without the Hive HMAC proof is a 403 that mints
  nothing; oversized keys are 422.

## Results

**Zero production counterexamples.** PR profile (25 examples × ≤12 steps,
derandomized): green 5/5 consecutive runs, ~7s at the leaf base and 8.0s at
the develop-sync head. Deeper randomized profile
(100 examples × 20 steps, fresh seeds): green 3/3 at 41-63s during
development, green 2/2 at 35.4s and 43.0s at the sync head. Two failures during development were harness bugs the stateful
form caught immediately — a principal switch that did not reach the auth
dependency (every request ran as one principal, so every cross-principal
assertion failed) and a cross-request rule that carried a workspace id
without its owning principal (404 on the follow-up request). Both are
exactly the "authority travels with the identifier" relation the suite now
pins.

**Independent re-validation sharpened this — in the suite's favor.** A
re-validation round on a second machine re-ran the deep profile and hit
two intermittent failures in ~11 runs (the derandomized PR profile never
failed). Both were **model defects, not production defects** — production
behavior matched its source on every one:

1. the listing invariant checked only the first page (`limit=200`), but
   examples share one in-memory store, so a deep run pushes a principal
   past one page and the oldest-first truncation dropped the fresh
   receipts the model still expected — fixed by walking `next_cursor` to
   exhaustion (which also pins no-duplicate-ids and full-store
   cross-principal non-leak);
2. the model kept one `(owner, task)` per textual key, but the admission
   scope is per-(principal, workspace, action, key): both principals can
   hold the same textual key, and when the second owner reused a key their
   own principal already held with a different body, production correctly
   409'd where the model demanded 202 — fixed by tracking claims
   per-owner.

This is the experiment's own thesis working: the derandomized PR profile
was byte-stable because it is shallow; the nightly-depth knob is what
generates the interleavings that exposed both defects, and each failure
shrank to a single rule plus its draws.

**Unique yield beyond the stateless battery: 2 of 4 mutants.** In-tree edits
with `/tmp` backup and byte-verified restore, measured at the leaf base
(`af7996883`, stateless battery 996-998):

| Mutant | Defect class | 996-998 stateless tests | Workflow suite |
|---|---|---|---|
| M1 | terminal-replay re-admission: a cancelled admission's live receipt no longer short-circuits replay, so a retry of finished work can answer `queued` | survive (998 pass) | **caught** |
| M2 | payload fingerprint narrowed to `description` only: same description + changed constraints under one key silently replays | caught (core unit test on the fingerprint body) | **caught** (409 relation at HTTP) |
| M3 | `list_tasks` owner scoping dropped | caught (core unit test) | **caught** (cross-principal listing invariant) |
| M4 | run-cancel idempotence dropped: cancelling an already-terminal Run refuses instead of answering the canonical state | survive (997 pass) | **caught** |

M1 and M4 are reachable only through *sequences*: a retry of a cancelled
admission, or a second cancellation arriving through the other route after the
first one terminalized the pair. No single-request test constructs either; the
generator reaches both because the workflow keeps the relation graph in play.
M2/M3 show the division of labor honestly: where a unit test pins the
mechanism directly, the workflow suite adds defense in depth at the HTTP
relation level, not unique yield.

The matrix is labeled historical evidence, not a claim about this head. M4's
*shape* moved when the receipt projection landed: the in-request projection and
the repeated-cancel 200 are now also pinned statelessly by
`packages/maistro-server/tests/api/test_runs_api.py`
(`test_run_cancel_uses_the_canonical_lifecycle`,
`test_cancel_without_a_task_correlation_keeps_local_receipts_unchanged`), so
what stays unique here is the cross-route pair — run-route cancel followed by
the receipt route's 400, with both surfaces agreeing to every later rule — and
terminal replay after a run-route cancel. Re-running the four mutants at this
head was out of scope for the sync round; the table carries the commit it was
measured at rather than being quietly re-dated.

**Develop sync: the suite caught a production semantic change at merge time.**
The leaf was cut at `af7996883`, where `POST /runs/{id}/cancel` terminalized
the Run and left the receipt `queued` for a worker to reconcile — an asymmetry
this suite pinned as observed behavior. Develop has since landed the run-cancel
receipt projection (`maistro_server.api.runs.cancel_run` →
`TaskQueue.update_status` + `TaskQueue.settle_terminal_receipt`), so the receipt
reads `cancelled` inside the cancelling request. Against develop the committed
oracle failed with a one-line, correctly-located red:

```
assert 400 == 200   # DELETE /tasks/{id} after POST /runs/{id}/cancel
test_stateful_workflow_api.py:450 in owner_cancels_through_the_run
Falsifying example: submit_with_key → owner_cancels_through_the_run (2 steps)
```

The rule was repaired to the new semantics (the projection lands in-request; the
receipt route refuses the repeat with 400; the run route stays idempotent) and
the repair was checked in both directions:

- against the merged head: green — PR profile 8.0s, deep 100×20 randomized
  green 2/2 at 35.4s and 43.0s, full server suite 573 passed / 8 skipped;
- against leaf-base production code with the *repaired* file copied in (scratch
  worktree, `PYTHONPATH` shadow): red with
  `AssertionError: assert 'queued' == 'cancelled'` at line 469 — so the new
  assertion is not vacuous; it pins exactly the projection that landed.

Two oracles, two heads, each red against the other's production behavior. A
stateless endpoint test written at the leaf base would have kept passing on
both heads while asserting nothing about the route pair.

**Stateless-vs-stateful comparison, per the issue's evidence ask:**

- *Unique failures*: 2/4 mutants unique to the workflow suite; zero failures
  the stateless battery found that the workflow missed; two further failures
  the deep profile found were in the workflow's *own oracle*, not production
  (above) — the stateless battery has no analogous mechanism to even
  express that mistake; and one real production semantic change (the run-cancel
  receipt projection) caught at the develop sync, where the stateless battery
  on both heads stayed green because the change landed with its own new
  stateless tests and nothing pinned the route *pair*.
- *Setup complexity*: one file, reusing the existing in-memory spine wiring
  (`test_tasks_idempotency.py` pattern); no live service, no containers.
  Adding a new relation is one rule; adding a new stateless scenario is a new
  hand-written test.
- *Runtime*: ~8s PR profile at the sync head (comparable to the 44s stateless
  in-memory idempotency file); nightly depth is an env knob, not a code change.
- *Flake rate*: after the two oracle fixes, PR profile green 3/3 (6.9-10.5s)
  and deep randomized profile green 4/4 (36-54s, fresh seeds) on the
  re-validation machine, on top of the earlier development-machine runs;
  at the develop-sync head, PR profile green (8.0s) and deep randomized
  profile green 2/2 (35.4s, 43.0s) after the cancel-oracle repair.
  derandomized PR runs are byte-stable, nightly opts out for fresh
  orderings. Before the fixes the deep profile failed intermittently and
  the PR profile never did — the honest reading is that PR-depth stability
  is proven, deeper depth is exercising genuinely new interleavings.
- *Shrink/reproduction quality*: every observed failure minimized to a 2-4
  step rule sequence with draws shown (both dev-time harness bugs above
  shrank to a single rule plus one draw; both re-validation model defects
  shrank to one rule each). This is materially better than a stateless
  429-noise crash file, which reproduces one request and explains nothing
  about ordering.
- *PR vs nightly*: PR-suitable as committed (deterministic, seconds,
  hermetic). The stateless CLI baseline is nightly-shaped at best (needs a
  running stack, 300-crash noise floor).

**Recorded constraints (not defects):** the Goal seam and schedule flows are
not HTTP-exposed on this surface, so two candidate workflows from the issue
are unrepresentable here; the served OpenAPI carries no response links, so
native Schemathesis stateful testing needs a links/inference evaluation before
it can replace the hand-written transition layer.

## What failure class existing gates do not catch

Relation-level orderings: a retry answering differently *after* the work went
terminal, and two cancellation routes that must agree about the same receipt.
The mutants were hypothetical regressions and shipped behavior held, but the
develop sync showed the class is live rather than hypothetical: the run-cancel
receipt projection changed what a *sequence* of two routes must answer, its own
new stateless tests pinned the mechanism in-request, and only this suite went
red on the pair. Cross-route terminal agreement is a semantic a well-meaning
"fix" can still silently break in either direction, and it is the shape this
suite now watches on every PR.

## Disposition

**GRADUATE** — for this seam, at this scope. The suite is committed standing
evidence in the server test job (already required CI), costs ~8s per PR,
demonstrated unique protection (2/4 relation mutants invisible to ~1000
stateless tests, measured at the leaf base), caught a real production semantic
change at the develop sync that no stateless test on either head expressed,
produced zero production false positives across 11 recorded runs, and shrank
every observed failure to a minimal reproducible workflow. The production
follow-up this graduates into is ordinary maintenance of the committed suite
plus the extensions below; no architecture decision changes — the suite is
test code over the canonical Run spine and introduces no second execution
authority.

INCUBATE-style follow-ups (deliberately not done in this bounded prototype):

- durable legs: the same machine against the SQLite/PostgreSQL spine tier
  (the stateless durable idempotency legs already show the shapes);
- the workspace-scope HMAC flow and delegation (`X-Maistro-Delegation`)
  variants as first-class rules;
- revisit native Schemathesis stateful if the spec grows response links or an
  inference layer — the committed contract probe is the tripwire;
- a Goal/schedule HTTP surface, if one ships, joins the machine.

## Trust boundary

The prototype imports `maistro_server` and `maistro` public seams as a
consumer, wires only the stores production wires for a no-database deployment,
and writes no Goal, no routing decision, and no authorization policy of its
own: it is test code under `packages/maistro-server/tests/`. One dev
dependency is declared (`schemathesis>=4.29`, MIT) because a fresh
`uv sync` prunes undeclared packages and the suite must not run green having
verified nothing.

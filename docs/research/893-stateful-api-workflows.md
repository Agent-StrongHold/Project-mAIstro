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

- **Stateless endpoint tests.** `packages/maistro-server/tests` alone collects
  538 tests; with `packages/maistro-core/tests/tasks` the stateless battery is
  996-998 tests (25 skipped without a DSN). They pin single-request contracts
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
  the pinned 400; run-route cancel terminalizes the Run while the receipt may
  stay `queued` until a worker reconciles it (observed production asymmetry,
  pinned rather than guessed), after which the receipt route completes the
  projection;
- cross-principal probes of tasks, runs, node-runs, workspaces, and the
  project tree are 404 without existence leaks, leave state untouched, and
  listings never show another principal's receipt;
- fabricated identifiers are 404s on both surfaces for any principal; the
  workspace-scope header without the Hive HMAC proof is a 403 that mints
  nothing; oversized keys are 422.

## Results

**Zero production counterexamples.** PR profile (25 examples × ≤12 steps,
derandomized): green 5/5 consecutive runs, ~7s. Deeper randomized profile
(100 examples × 20 steps, fresh seeds): green 3/3 at 41-63s. Two failures
during development were harness bugs the stateful form caught immediately —
a principal switch that did not reach the auth dependency (every request ran
as one principal, so every cross-principal assertion failed) and a
cross-request rule that carried a workspace id without its owning principal
(404 on the follow-up request). Both are exactly the "authority travels with
the identifier" relation the suite now pins.

**Unique yield beyond the stateless battery: 2 of 4 mutants.** In-tree edits
with `/tmp` backup and byte-verified restore:

| Mutant | Defect class | 996-998 stateless tests | Workflow suite |
|---|---|---|---|
| M1 | terminal-replay re-admission: a cancelled admission's live receipt no longer short-circuits replay, so a retry of finished work can answer `queued` | survive (998 pass) | **caught** |
| M2 | payload fingerprint narrowed to `description` only: same description + changed constraints under one key silently replays | caught (core unit test on the fingerprint body) | **caught** (409 relation at HTTP) |
| M3 | `list_tasks` owner scoping dropped | caught (core unit test) | **caught** (cross-principal listing invariant) |
| M4 | run-cancel idempotence dropped: cancelling an already-terminal Run refuses, so the receipt-route completion of a run-cancelled task strands `queued` | survive (997 pass) | **caught** |

M1 and M4 are reachable only through *sequences*: a retry of a cancelled
admission, or a receipt-route cancel following a run-route cancel. No
single-request test constructs either; the generator reaches both because the
workflow keeps the relation graph in play. M2/M3 show the division of labor
honestly: where a unit test pins the mechanism directly, the workflow suite
adds defense in depth at the HTTP relation level, not unique yield.

**Stateless-vs-stateful comparison, per the issue's evidence ask:**

- *Unique failures*: 2/4 mutants unique to the workflow suite; zero failures
  the stateless battery found that the workflow missed.
- *Setup complexity*: one file, reusing the existing in-memory spine wiring
  (`test_tasks_idempotency.py` pattern); no live service, no containers.
  Adding a new relation is one rule; adding a new stateless scenario is a new
  hand-written test.
- *Runtime*: ~7s PR profile (comparable to the 44s stateless in-memory
  idempotency file); nightly depth is an env knob, not a code change.
- *Flake rate*: 0 failures in 8 runs across profiles and seeds; derandomized
  PR runs are byte-stable, nightly opts out for fresh orderings.
- *Shrink/reproduction quality*: every dev-time failure minimized to a 2-4
  step rule sequence with draws shown (both harness bugs above shrank to a
  single rule plus one draw); this is materially better than a stateless
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
terminal, and a receipt projection stranded by a *cross-route* cancellation
path. Both shipped behavior held — the mutants were hypothetical regressions —
but nothing except a generated workflow could have watched those seams, and
the production asymmetry (run terminal ≠ receipt terminal immediately) was
until now an untested semantic that a well-meaning "fix" could silently break
in either direction.

## Disposition

**GRADUATE** — for this seam, at this scope. The suite is committed standing
evidence in the server test job (already required CI), costs ~7s per PR,
demonstrated unique protection (2/4 relation mutants invisible to ~1000
stateless tests), zero production false positives across 8 runs, and shrank
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

---
inventory-delta: {}
---
# auto-42 independent verification (L42 verify, head d646cee4)

Read-only acceptance verification of PR 1326 against issue #42 at head
d646cee4772f2b87fc35ed4c63583846dac2fa0c. No product code changed by this note.

Executed locally at this head (all pass): driver check logs 0-7 (uv sync, ruff
check/format, 171 core+server tests, 4 conductor tests, 3 suite-inventory
gates); 113 tests across chat Attempt lease/reclaim recovery, execution
fencing, runtime/task cancellation, durable executor, harness replay dedupe,
delegate child-run claim and binding Invocations; 20 tests across event
correlation and the Conductor cancel route + subprocess-kill E2E; 103 tests
across Attempt result acceptance/reconciliation/repair and chat execution.

Independently reproduced the prior double-dispatch finding scenario: an unkeyed
EFFECT_KEY node now fails closed (one visit, Run failed); a keyed node whose
provider fails ambiguously performs exactly one physical dispatch and later
visits raise UnsafeEffectRetry (outcome UNKNOWN); only a proven
EffectNotApplied authorizes a second dispatch. Each retry produces a new
chronological NodeRun + Attempt.

Blocking findings (repair required, none addressed by this note):

- Issue #1169 and issue #1194 are OPEN upstream; #42 acceptance requires
  #1169/#1170/#1194 closed before #42 is complete. Only #1170 is CLOSED.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` fails at this head: 6 NEW unauthorized
  identities from this branch (graph/nodes/agent_delegate_remote.py:463
  `_create_child_run` — genuinely dead, docstring-only references;
  runs/store.py:344,808 / sqlite_store.py:317 / pg_store.py:468
  `find_child_run_by_effect` — test-only callers; server api/a2a.py:62
  `create_a2a_task` — live route, unbanked) plus 2 stale ledger entries to
  prune (tools/reversibility.py `idempotency_key`, durable_runs/executor.py
  `_replace_node_run`).
- PR 1326 is draft with red CI (integration-scope, exact-debt-ledger, CI test,
  coverage (MinIO), object storage (MinIO), quality gate).

---

## Post-merge addendum (L42 repair, head a5788b422 + follow-up commits)

This addendum supersedes the blocking-finding list above where facts changed.

Executed at the merged head (develop ba2f1f077 merged into auto-42, then
reconciled): ruff check/format clean; mypy (all six package src trees) clean;
pytest core runs+graph+capabilities+a2a+runtime+tasks = 2903 passed; events +
integration + persistence + builders = 974 passed; maistro-server = 363
passed; hive-conductor backend = 2481 passed; tests/migrations = 14 passed
after re-threading the duplicated `034` revision; check-execution-lifecycles
PASS (19 classified, 0 violations); check-lifecycle-provenance PASS.

Upstream state re-checked live: #1169 CLOSED, #1170 CLOSED, #1194 still OPEN,
#42 OPEN, PR 1326 still draft and CONFLICTING (the local merge here resolves
the conflicting content; the PR itself was not touched per lane rules).

Debt-ledger: the merge plus dead-code removal reduced the unauthorized vulture
identities to exactly one: `create_a2a_task`
(packages/maistro-server/src/maistro_server/api/a2a.py) — a live route handler
that must be banked via a reviewed grant, which lane rules prohibit this
worker from making. `scripts/check-vulture-baseline.py` therefore still exits
1 pending that grant.

---

## L42 repair re-validation (head 607453bc0, driver job fdc969865d78)

Independent re-check at the lane head (the prior driver run died on a provider
error before executing any check, so nothing above was trusted). Everything
below was executed fresh in this session:

- `uv run ruff check .` clean; `uv run ruff format --check .` clean (2495
  files); mypy over all six package src trees clean (711 files).
- pytest: graph/durable_runs + graph/nodes = 712 passed; capabilities + runs =
  1138 passed; a2a + runtime + tasks = 454 passed; server = 363 passed;
  tests/migrations = 14 passed; chat lease + capabilities = 313 passed;
  container chat/runs + run service + event authority = 88 passed;
  hive-conductor cancel routes = 9 passed.
- Gates: `check-execution-lifecycles` PASS (19 classified, 0 violations);
  `check-lifecycle-provenance` PASS; `check-vulture-baseline` still exits 1 on
  exactly the one unbanked `create_a2a_task` identity (grant outside lane
  authority, unchanged).
- **Independent reproduction of the prior ambiguous-replay finding** (scratch
  script, not committed): an EFFECT_KEY node dispatching an external effect
  whose provider dies with a generic exception, under `max_attempts: 3`, now
  yields exactly **1 physical dispatch** (was 2 pre-fix): visit 1 dispatches
  and the Invocation lands UNKNOWN; visits 2-3 raise `UnsafeEffectRetry`
  ("manual/reconciliation evidence is required before retry") because the
  effect identity `(run_id, effect_scope, binding, effect_key)` is stable
  across NodeRun visits. History stays chronological: NodeRun ordinals 1,2,3,
  one completed (physically tried) Attempt each, NodeRuns/Run FAILED. This
  confirms the `effect_scope` contract end to end on the in-memory store; the
  SQLite and pg durable stores scope `list_effect` identically (pg INSERT
  binding covered by 607453bc0).
- Upstream re-checked live read-only: #1169 CLOSED, #1170 CLOSED, **#1194
  still OPEN**, #42 OPEN. #1194's enforcement implementation is present and
  proven in-branch; only the issue-closure action remains, which lane rules
  assign to the orchestrator.
- Residual risk recorded (no evidence of a reachable duplicate on canonical
  paths): the durable Invocation stores' partial unique index
  `uq_capability_invocation_active_effect` keys on `(run_id, node_run_id,
  binding_id, effect_key)`, so the *database-level* hard guarantee does not
  span NodeRun visits; cross-visit dedupe relies on the scoped `list_effect`
  check inside `InvocationExecutionService.invoke` plus Attempt fencing/run
  ownership. A scope-keyed partial index would make the DB guarantee match the
  logical contract; left for the integrator to weigh.
- Verdict at this head: branch code needs no further repair; #42 acceptance
  cannot be fully signed off from this lane because #1194 closure and the
  `create_a2a_task` ledger grant are external actions (NEEDS-DEEP-REVIEW
  handoff).

## L42 re-validation at e0d8d9a9d (second pass, 2026-09-25)

Fresh validation battery executed in this lane (no driver check logs were
provided: `manifest.json` carries `checks: []`, so all evidence below is
self-executed):

- `ruff check .` PASS; `ruff format --check .` PASS (2496 files); mypy over
  the six src trees PASS (711 files).
- pytest: durable_runs+nodes **712 passed**; durable_runs full dir **431
  passed** (includes the new guard test); capabilities+runs **1138 passed**;
  core a2a+runtime+tasks **454 passed**; maistro-server **363 passed**
  (includes the `/a2a/tasks/create` endpoint test); chat-lease recovery +
  runtime execution **31 passed** (10 cancel/deadline tests among them);
  migrations **14 passed**; conductor cancel routes **9 passed**.
- Gates: `check-execution-lifecycles` PASS (19 classified, 0 violations);
  `check-lifecycle-provenance` PASS (0 violations); `check-suite-inventory`
  exit 0 (pre-existing non-fatal format warning on
  `auto-42-develop-merge-reconciliation.md`, untouched).

Findings re-verification at this head:

- `create_a2a_task` vulture identity re-confirmed as the **only** branch-caused
  scan delta: scanning the pristine merge-base tree (ba2f1f077, extracted via
  `git archive`) yields 1426 findings vs 1427 at HEAD, and the set difference
  is exactly `packages/maistro-server/src/maistro_server/api/a2a.py:: unused
  function 'create_a2a_task'`. The ~1400 other deltas of a bare
  `check-vulture-baseline.py` run are base-inherent (the merge-base ledger is
  stale relative to its own tree: 0 recorded pytest-discovered entries vs 437
  scanned), affecting any branch off ba2f1f077 and not caused by auto-42.
  Banking the route handler still requires a develop-side reviewed grant
  (authorizations are read from the base revision), outside lane authority.
  The endpoint itself is live product surface (`app.include_router(a2a.router)`
  at `main.py:492`, canonical `claim_run_by_effect` admission) and is covered
  by `packages/maistro-server/tests/api/test_a2a_api.py`.
- The `effect_scope` contract is now regression-locked in-tree:
  `packages/maistro-core/tests/graph/durable_runs/test_ambiguous_effect_replay_guard.py`
  drives the durable graph retry through `InvocationExecutionService` and
  asserts exactly 1 physical dispatch, visits 2-3 refused with
  `UnsafeEffectRetry`, three chronological NodeRuns (one physically complete
  Attempt each), Run FAILED, and the UNKNOWN Invocation retaining the first
  visit's identities. Mutation-checked: dropping the stable `effect_scope`
  makes the test fail with three dispatches. See
  `auto-42-ambiguous-effect-guard-test.md`.
- Upstream unchanged: #1169 CLOSED, #1170 CLOSED, **#1194 still OPEN**, #42
  OPEN. Verdict stands at NEEDS-DEEP-REVIEW: no in-tree defect found; the
  remaining acceptance item (dependent-issue closure) and the ledger grant
  are orchestrator actions.

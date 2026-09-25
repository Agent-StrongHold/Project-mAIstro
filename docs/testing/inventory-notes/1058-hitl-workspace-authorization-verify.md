---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
---

# Issue 1058 — independent verification record (head 2e2275e1ec93)

Documentation-only verifier note. No production or test code changed.

## Executed at this head

- `uv run pytest packages/maistro-core/tests/graph/durable_runs/` — 472 passed / 21 skipped.
- Full backend suite `uv run pytest packages/hive-conductor/backend/tests` —
  **2660 passed / 1 skipped / 0 failed**. This closes the prior finding:
  `test_registered_dag_recovery.py` no longer raises the
  `submit_hitl_answer() missing keyword-only 'authorization'` TypeError; the
  repair commit 2e2275e1e supplies typed `HitlAuthorization` evidence and is
  test-only (no production change).
- `uv run ruff check .` — clean. `check-suite-inventory` — ok (13 suites).
  `check-radon-baseline` — exit 0. `check-vulture-baseline` with the CI
  contract (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`)
  — exit 0, 1415 → 1415, no new debt. The default-scope vulture invocation
  remains red, matching the pre-existing trunk drift documented in
  `auto-1058-vulture-invocation.md` (red at the develop base as well).
- `mypy packages/maistro-core/src/maistro/graph/durable_runs/` — clean (17
  files). Repo-wide mypy on `packages/maistro-core/src` reports only 5
  `import-not-found` errors for `maistro_bootstrap` (bootstrap extra not
  installed in this environment; unrelated to this diff).
- `check-doc-links`, `check-ac-state`, `check-retired-guidance` — exit 0.
- Individual acceptance tests re-run green: two-Workspace scoped
  list/inspect/answer/cancel (`test_hitl_routes_are_scoped_to_the_callers_workspaces`
  incl. 50 foreign records and forged `_pause`), expiry scope + late race
  (`test_expiry_endpoint_cannot_timeout_a_foreign_workspace`),
  library-side two-Workspace late race, foreign-authorization refusals on
  canonical/in-memory stores, delegation evidence validation/consumption,
  dags.write 403 arm, unknown-run 404, and the membership-predicate pins
  (`test_hitl_membership_predicate_guards_mutation`,
  `test_hitl_mutation_rechecks_membership_at_the_store_boundary`,
  `test_pending_rechecks_membership_before_disclosing_payload`).

## Residual notes

- No closure keywords (`fixes/closes/resolves #…`) in any commit message or
  the PR body; only `Refs #1058`.
- CI status for PR 1392 was not observed; the local suite above is the only
  green claim made here.

## Re-validation at 3723f188 (verify lane, mutation probe re-executed)

- Lane suites re-run: 48 backend HITL/authority/recovery tests passed; 166
  core durable-runs tests passed; `ruff check .` clean; both suite
  inventory gates ok; prior TypeError finding passes in isolation.
- Literal membership-predicate mutation re-executed without tree edits via a
  pytest plugin patching `HitlAuthorization.permits -> True`:
  `test_hitl_mutation_rechecks_membership_at_the_store_boundary`,
  `test_sqlite_rejects_revoked_membership_inside_settlement`,
  `test_settlement_waits_for_membership_revocation_then_refuses`, and
  `test_two_workspace_late_race_cannot_settle_foreign_pause` all FAILED as
  required (4 failed / 1 passed). The surviving pin is the route-level
  `is_member` denial test, which is killed by removing the route predicate
  instead — both authorization layers are pinned. Worktree left clean.

## Independent re-validation at 034cfc4dd (verify lane, post-merge) — NEEDS-REPAIR

- Worktree clean at 034cfc4dd (merge of develop 1dea30dfe into auto-1058).
- Full backend suite: **2667 passed / 1 skipped / 0 failed**; ruff check and
  format clean; both suite-inventory gates ok; the previously repaired
  `test_registered_dag_recovery.py` passes in isolation (backend HITL
  quartet 48 passed).
- **New un-reconciled develop caller found:**
  `uv run pytest packages/maistro-core/tests` — **1 failed, 10162 passed**:
  `test_pause_reason_wakers.py:912::test_hitl_expiry_settles_exactly_its_declared_statuses`
  raises `TypeError: expire_hitl_pauses() missing 1 required keyword-only
  argument: 'authorization'`. The test arrived with develop #1552
  (750edd84d) and calls the pre-cutover signature; the merge into auto-1058
  did not reconcile it — the same failure class the 2e2275e1e repair fixed
  for `test_registered_dag_recovery.py`. The driver's deterministic checks
  missed it because `check-suite-inventory` compares *collection counts*
  only, and the targeted pytest lanes did not include this file.
- Mutation probes re-executed at this head without tree edits via /tmp
  pytest plugins: patching `HitlAuthorization.permits -> True` fails the 4
  store-level guard tests; patching `routes.hitl.is_member -> True` fails
  `test_hitl_routes_are_scoped_to_the_callers_workspaces` (foreign inspect
  returns 200 — real leak). Both predicates are load-bearing; worktree left
  untouched.

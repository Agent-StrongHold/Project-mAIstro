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

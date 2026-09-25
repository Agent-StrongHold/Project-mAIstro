---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# auto-48-hitl-workspace-auth-merge

Salvage-and-complete record for the interrupted merge of develop's HITL
workspace-authorization work (`60862b6c5eb1`, "[M2-A][#364] Enforce Workspace
object authorization on HITL list/answer/cancel routes") into `auto-48`, found
in progress with one unresolved conflict. No new tests were added by this
lane; the +26 settlement-suite and +4 door-suite test functions arrive from
the incoming side, which ships its own inventory notes (`1058-*`,
`auto-1058-*`).

## Merge conflict resolutions

- `packages/maistro-core/tests/graph/durable_runs/test_hitl_settlement.py` —
  the import block was the single textual conflict (HEAD's `GraphContinuation`
  vs incoming's `HitlAuthorization`/`HitlAuthorizationRequired`/
  `HitlDelegationEvidence`). Resolved as the union; every union symbol is used
  by the auto-merged body.
- Same file, semantic conflict: HEAD's crash-repair tests
  (`test_reconcile_repairs_crash_after_answer_before_run_mirror`,
  `test_resume_repair_falls_back_to_the_bounded_sweep_on_legacy_stores`) call
  `submit_hitl_answer` without the store-level `authorization` the incoming
  protocol now requires. Fixed by passing `authorization=_test_authorization()`
  and adding the two tests' Workspaces (`ws-hitl-answer-reconcile`,
  `ws-hitl-legacy-sweep`) to the helper's authorized set — crash coverage and
  the authorization gate are both preserved.
- `packages/hive-conductor/backend/tests/test_hitl_door.py` — the incoming
  `test_hitl_mutation_rechecks_membership_at_the_store_boundary` ends each
  loop iteration with `monkeypatch.undo()`, which on this branch also tears
  down the autouse binding of `get_canonical_run_store` (this branch's door
  fails closed with 503 without it), so the cancel leg got 503 instead of the
  store's 404. Dropped the blanket `undo()`; each iteration re-patches
  `routes.hitl.is_member`, so the revocation-must-win scenario is unchanged
  (404, Run stays PAUSED, exactly two membership checks).

## Independent validation at 87f71178d (merge 678c16316 + the settlement/door fix, 2026-09-25)

- `uv run pytest packages/maistro-core/tests/graph/durable_runs -q` — 515
  passed, 21 skipped (the skips are the `MAISTRO_TEST_PG_DSN` legs); the
  full `packages/maistro-core/tests/graph` tree — 1400 passed, 79 skipped.
- **Postgres legs executed** on a throwaway `pgvector/pgvector:pg18`
  container (`alembic upgrade head` from empty, then `MAISTRO_TEST_PG_DSN`
  set): full `durable_runs/` suite — **536 passed, 0 skipped**. The incoming
  workspace-authorization store changes therefore hold on the Postgres
  backend, not only on SQLite. Throwaway container removed afterwards.
- Full `packages/hive-conductor/backend/tests -q` — **2670 passed,
  1 skipped** (up from 2663 at 17ec79e7: the incoming side adds tests, all
  green).
- Targeted hive suites (`test_hitl_door`, `test_hitl_timeout_cancel`,
  `test_workspace_authority`, `test_registered_dag_recovery`,
  `test_dag_agents`) — 64 passed, including the previously failing
  membership-recheck test (subsumed by the full-suite run above).
- `uv run ruff check .` / `uv run ruff format --check .` — clean (2533
  files); six-package mypy battery — clean (713 files).
- `scripts/check-vulture-baseline.py` — PASS with the CI invocation
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`,
  1415 reviewed identities -> 1414 findings). Note for future passes: the
  script's *default* args scan test trees the ledger was never banked for and
  fails en masse; the ledger oracle is the merge base, which only advances to
  the incoming tip once the merge is committed.
- Also green at this head: `check-ac-state`, `check-doc-links`,
  `check-wiring-reads`, `check-radon-baseline`, `check-ratchet-provenance`,
  `check-shipped-surface-truth`, `check-convergence-matrix`,
  `check-execution-lifecycles`, `check-agent-store-writes`,
  `check-durable-table-inventory`, `check-contract-markers`,
  `check-reachability`, `check-cross-package-imports`,
  `check-owned-store-access`, `check-public-routes`,
  `check-m1-convergence-freeze --base 03c8ba83a`.

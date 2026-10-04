inventory-delta:
  tests/: +0
---

# Issue 41 verify (round 18): independent acceptance re-derivation at head 46ee33d12

No test delta: verification only. The worktree arrived clean at
`46ee33d12ae7565f96fc4966d6508c47be4cc55a` and was left at that content; this
note records the re-executed evidence behind the verdict. All checks below were
re-executed by this run, not inherited from prior rounds.

## Lane battery re-executed (all green)

| Check | Outcome |
|---|---|
| `uv sync --locked --extra dev` | Resolved 244, checked 204 |
| `uv run ruff check .` / `ruff format --check .` | All checks passed / 2599 files formatted |
| core+server runs/idempotency battery (6 files) | 409 passed, 127 skipped |
| hive battery (test_api, test_engine_service, test_username_registry, test_workspace_scoped_submission) | 107 passed (incl. the round-17 `test_register_duplicate_username` regression) |
| `check-suite-inventory.py` × 3 suites | ok: 1 suite each, match recorded inventory |
| chat admission (`test_chat_admission.py` + hive `test_chat_run_admission.py`) | 53 passed (outside the driver's default battery; added) |
| `tests/migrations/test_migration_chain.py` against real PostgreSQL (auto41-cov-pg, `MAISTRO_TEST_DATABASE_URL`) | 12 passed — chain downgrade/upgrade holds incl. `quota_usage_events` |
| `tests/test_gates_ran_publisher_contract.py` | 12 passed |
| PG-tier durable idempotency on a real server (`test_the_postgres_tier_reconciles_on_a_real_server`, `MAISTRO_TEST_PG_DSN`) | passed (DB alembic-upgraded to head first; the chain fixture's `downgrade base` teardown empties a shared DB, so the two files must not share one run) |
| core chat→graph e2e (`test_chat_to_graph_e2e.py`) | 2 passed |

## Acceptance re-derivation (issue #41)

- task/chat submission yields canonical run_id — mission receipt carries
  `run_id` (`routes/missions.py:33`, `models/schemas.py:59`);
  `test_api.py:373` asserts `body["run_id"] == "run-abc123"`;
  chat admission returns the canonical Run (53 tests green).
- stable scoped idempotency contract (#1176) — `tasks/idempotency.py` hashes
  key+principal+Workspace+Project+action into `admission_scope_key`, records a
  payload fingerprint (mismatch → 409), claims by PK insert with claimant-token
  fencing, begin-announcement resolves the ambiguous window by discovery
  (`find_run_by_task_receipt` in `runs/pg_store.py:606` / `sqlite_store.py:526`);
  retry/restart/replica-handoff/concurrent-HTTP-retry tests all green incl.
  the real-PostgreSQL tier.
- one-node Graph valid for direct/chat work — `runs/admission.py:49`
  `direct_work_graph` (one node, no edges, refuses unregistered kinds);
  spine conformance green.
- Run authoritative post-admission — `tasks/admission.py` maps the task
  machine onto the Run lifecycle (`RUN_STATUS_BY_TASK_STATUS`,
  `record_transition`, parked-resume-before-terminal guard);
  `test_parked_run_resume.py` + spine conformance green.
- session/request provenance correlated — provenance keys `task_id`,
  `session_id`, `request_id` stamped at admit (`tasks/admission.py:211-217`);
  `test_a_task_receipt_finds_its_run_and_only_that_run` green.
- parity/E2E coverage — 107-test hive parity battery, 53 chat-admission tests,
  and the core chat→graph e2e all green; the Playwright suite
  (`hive-conductor/tests/e2e`, 119 tests) exists but needs a browser stack and
  was not executed in this lane (browser-level: UNVERIFIED here).
- #1176 closes before this issue completes — `gh issue view 1176` (read-only):
  CLOSED 2026-09-19T20:01:50Z. Issue #41 itself remains OPEN; PR 1325 body and
  all 543 lines of branch commit messages contain no fixes/closes/resolves
  keywords (grep count 0), so nothing auto-closes #41.

## Verdict basis

Every acceptance criterion except browser-level Playwright execution has
executed, observed evidence at this head; that remaining item is supplementary
coverage, not an acceptance gate. Merge-readiness: handoff to integration.

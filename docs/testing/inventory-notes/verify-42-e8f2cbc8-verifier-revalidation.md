---
inventory-delta:
  tests/: +0
---

# auto-42 round 25 — independent verifier revalidation at e8f2cbc8

Read-only verification of the round-24 repair (e8f2cbc8c, "rewrite the stale
043 conformance test for the surviving 035 claim chain") at the same head.
No source changes; counts unchanged; this note only records executed evidence.

## Executed at this head (first-hand)

- `pytest tests/migrations/test_capability_invocation_effect_index_migration.py
  tests/migrations/test_single_migration_head.py tests/migrations/test_migration_chain.py`:
  5 passed, 13 skipped (PG-gated).
- Fresh `pgvector/pgvector:pg18` container: `alembic upgrade head` reaches the
  single head `053`; live `uq_capability_invocation_active_effect` is
  `(run_id, effect_scope, binding_id, effect_key)` with the
  created/running/completed/unknown predicate and live
  `idx_capability_invocation_effect` keeps
  `(run_id, node_run_id, binding_id, effect_key, created_at, invocation_id)` —
  the one-schema contract proven on a server, not only via the AST guard.
  `test_migration_chain.py` + rewritten file + `test_event_schema_agreement.py`
  against that server: 20 passed.
- `check-suite-inventory.py --suite tests/`: ok — 4541 collected = recorded
  (the round-24 `tests/: +2` reconciliation holds).
- `ruff check .` / `ruff format --check .`: clean.
- Lane suites (the 17-file runtime set): 588 passed, 124 skipped.
- CI test-job command `pytest tests/ --ignore=tests/tools/registry -q`: run A
  2 failed / 4373 passed / 90 skipped; run B (minutes later, same head)
  4375 passed / 90 skipped; the round-24 run at this head also recorded
  4375 passed (its events log carries the tool output).

## The 2-run-A failures are a suite-interference heisenflake, not this branch

Both failures were `tests/test_install_mnemonic_handling.py::
TestAnInterruptDoesNotLeaveThePhraseBehind` (trap-on-SIGINT purge):
`kill -INT $$` returned 0 and left the phrase file. The file and `install.sh`
are byte-identical to develop (branch diff touches neither), the pair passes
in isolation (20/20), and the failure signature is exactly what a parent
process SIGINT disposition of SIG_IGN produces (POSIX: signals ignored on
shell entry cannot be trapped — reproduced deliberately with a 3-line
`signal.signal(SIGINT, SIG_IGN)` harness). No test or production source sets
SIGINT handlers (grep: only comments about uvicorn owning signals), and this
branch's `tests/` delta is confined to the two migrations files, which contain
no signal or in-process-server behavior. Run B at the same head is green, so
the named CI `test` failure (the stale 043 conformance test) is fixed and the
residual red is environmental flake; a recurrence should be triaged as its own
issue (find the suite member that leaks SIG_IGN), not attributed to auto-42.

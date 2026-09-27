---
inventory-delta:
  packages/maistro-core/tests: +0
---

No new tests; the existing chain suite was re-proven live against an empty
pgvector:pg18 after the renumber.

# auto-72 verifier repair 2 (develop sync + alembic collision)

Repair round on top of the origin/develop sync. No production store behavior
changed; the fixes are the collision the sync created, the retention-ledger
omission the durable table left behind, and the preserved merge conflict.

- **Develop sync resolved.** The worktree held a preserved in-progress merge of
  `a71fc2e43` with one conflict in
  `packages/maistro-server/tests/api/test_main.py`
  (`test_the_lifespan_says_which_run_store_is_live`): develop's side mocked a
  container whose `run_store.list_by_status` feeds startup recovery (#41);
  this branch's side mocked `flush_usage_log`/`aclose` for the shutdown
  write-behind contract (#72/#1204). Resolution keeps one mocked container
  providing both. `origin/develop` had since moved to `031bd0746`; that merge
  applied clean on top.
- **Elevation migration renumbered 039 -> 043.** develop added
  `039_canvas_job_admission_key` (revision `"039"`, parent `"038"`), colliding
  with this branch's elevation-grants migration on the same id and parent, so
  `alembic history` failed with "042 overlaps with other requested revisions
  039" and `alembic heads` warned "Revision 039 is present more than once".
  The elevation migration now attaches after the develop chain tip `042` as
  revision `043` — one head, linear chain. Proven live: chain applied,
  round-tripped, and downgraded against an empty `pgvector:pg18`
  (`tests/migrations/test_migration_chain.py`, 11 passed; the suite's
  `EXPECTED_TABLES` equality already pins `elevation_grants`, so the rename
  is behaviorally covered without new tests).
- **`elevation_grants` registered in `quality/durable-table-retention.json`.**
  `scripts/check-durable-table-inventory.py` failed (also at the prior head —
  pre-existing) because the table this branch introduced had no entry. Added
  the honest one: `security_evidence`, backends postgres+sqlite, retention
  `undecided` (#72) — validity is TTL-filtered at read time and no DELETE
  exists, so expired rows accumulate; a driven expiry sweep is the open owner
  decision. Gate now reports 64 tables, all declared.

Validation this round: ruff check/format clean; targeted battery
(schema concurrency + fork-based cross-process upgrade, sqlite usage log,
elevation durable, container wiring, server health/main/strike health)
107 passed; persistence+quota+security suites re-run against a live
migrated pgvector:pg18 (chain 001 -> 043 applied via DATABASE_URL,
MAISTRO_TEST_PG_DSN): 2071 passed / 19 skipped / 1 known failure — and
setting MAISTRO_TEST_DATABASE_URL un-skips the strike-tracker PostgreSQL
leg: test_strike_tracker_conformance.py + test_elevation_durable.py
42 passed, 0 skipped (the 19 prior-round skips are gone). Vulture
baseline gate clean (no ledger amendment needed); suite inventories
(core 11172, server 391) match.

Known pre-existing, out-of-scope (unchanged verdict from
auto-72-verifier-repair.md): `security/test_log_redaction.py::
test_install_is_idempotent` fails under pytest 9 (the runner attaches its own
capture handlers to the non-propagating fixture logger, so the second install
counts them). Re-proven identical at starting head 7193e640 in a throwaway
worktree before any of this round's changes; unrelated to the #72 durable-state
criteria and owned by a CI-repair lane.

---
inventory-delta:
  packages/maistro-core/tests: +5
  packages/maistro-server/tests: +3
---

# auto-72 CI repair: wiring-reads regression + diff-coverage floor

Three CI jobs failed at head 0b89f4c3c on one root cause plus one hidden
second defect; this round fixes both, with evidence, not scanner appeasement.

- **Wiring-reads ratchet (Quality gate + `test` job + Coverage-gate job's
  combined suite).** `Container.stores_memory_backed` was read only through a
  `getattr` string in `health.py`, which the AST ratchet cannot see, so the
  field counted as newly-unread (11 -> 12). Repair gives the field a genuine
  read — `container is not None and bool(container.stores_memory_backed)` —
  and completes the ad-hoc container stubs in `test_health.py` /
  `test_strike_tracker_health.py` so they mirror the real Container dataclass,
  which always carries the field. Ratchet re-proven: 11 -> 11, exit 0;
  `tests/test_check_wiring_reads.py` 36 passed.
- **Diff-coverage gate (never reached in CI; reproduced locally).** The
  coverage-gate job died at the wiring-reads test before its own arithmetic,
  so the per-file floor failure underneath was invisible: `PgElevationStore`
  had no PostgreSQL leg anywhere (the coverage-postgres producer's suite list
  did not name the security suite), `health.py`'s write-behind reporting
  branch had no test, and `main.py`'s shutdown-flush failure path had no test.
  Repairs:
  - `quality.yml` names
    `packages/maistro-core/tests/security/test_elevation_durable.py` in the
    coverage-postgres producer, per that list's own rule ("a new PostgreSQL
    store means an edit here, every time").
  - `tests/security/test_elevation_durable.py` gains the PostgreSQL legs
    (restart round-trip, expired/wrong-scope rejection, canonical-pool backend
    selection) that skip on a laptop and raise under
    `MAISTRO_REQUIRE_PG_LEGS`, plus a legacy naive-timestamp read for the
    `_grant_from_row` UTC normalization.
  - `test_health.py` gains the write-behind usage-log diagnostic test
    (persistence backend, mode, durable) — the mixed-persistence reporting the
    #72 contract asks for.
  - `test_main.py` gains the shutdown-flush failure test (logged as
    `usage_log_flush_failed`, `aclose` still awaited) and the cleared-container
    shutdown test (the defensive `getattr` read is a real contract).
  - `tests/conftest.py` truncates `elevation_grants` in the pg_pool fixture so
    deterministic principals cannot read a previous run's grant.
- Proven live against pgvector:pg18 (DSN on port 18790): migration chain
  001 -> 044 applied on an empty database (`039_quota_usage_event_identity ->
  044`), `tests/migrations/test_migration_chain.py` 11 passed, and the
  producer suite list including the security file 4266 passed / 8 skipped;
  `scripts/check-diff-coverage.py --base 8bfd35903` exits 0 over the four
  changed production files.

Known pre-existing, out of scope: `packages/maistro-server/tests/api/
test_tasks.py::TestGetTaskResult::test_task_with_result_returns_result_body`
fails only when `MAISTRO_TEST_PG_DSN`/`DB_*` are exported while running the
server suite — `TaskQueue.set_result` then takes the write-behind persistence
path (`tasks/queue.py` `_persist` -> `asyncio.create_task`) outside an event
loop. Both files are byte-identical to the develop base (`git diff 8bfd35903
-- <paths>` empty) and no CI job sets those variables for the server suite, so
this is a latent develop bug owned by a CI-repair lane, not a #72 regression.

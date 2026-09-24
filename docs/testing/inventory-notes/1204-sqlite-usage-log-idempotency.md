---
inventory-delta:
  packages/maistro-core/tests: +10
---
# #1204 SQLite usage-log idempotency

Four new cases in `packages/maistro-core/tests/quota/test_sqlite_usage_log.py` cover
legacy-schema identity backfill, same-timestamp event identity, forced
overlapping snapshots, and a commit that succeeds before its result is reported
as failed. Each restores the durable log and asserts exact request/token totals,
proving that retries and concurrent flushes cannot inflate quota usage. Two additional persistence cases exercise the shared quota tracker protocol: memory, SQLite, and PostgreSQL all deduplicate a repeated event identity and reject identity reuse with different usage.

## Merge resolution against trunk's serialized schema upgrades (#1461)

Trunk landed `serialized_schema_upgrade` (per-connection lock + `BEGIN
IMMEDIATE`) on top of the pre-#1204 watermark implementation, so the merge
conflicted in both `ensure_schema` methods. Resolution combines both:
`SqliteUsageLog.ensure_schema` runs the event-id column backfill and unique
identity index inside the shared discipline, nested under the instance
operation lock so the migration excludes `snapshot`/`restore` on the same
connection; `SqliteQuotaTracker.ensure_schema` creates `quota_usage` and
`quota_usage_events` inside the shared discipline. Trunk's `SqliteUsageLog`
watermark and per-scope timestamp dedup are fully replaced by the event
identity semantics this issue owns. Verified live against a pgvector:pg18
container: the legacy timestamp-only table upgrades and backfills
`legacy:<rowid>` identities, three overlapping snapshots restore exactly once
(2 requests / 25 total tokens for a 15-token backfilled row plus a 10-token
event), and a repeated `record_usage(event_id=...)` keeps `request_count=1`.

## Develop-merge resolution (60862b6c5)

Merging develop's 60862b6c5 into the lane conflicted in
`docs/architecture/CONVERGENCE-MATRIX.md` only: develop's #1470 rewrote the
Credentials row around the retired `credential_store_v2`, which this same merge
applies, so its row text was taken; but its Quota share of `most` was rejected
because `check-convergence-matrix.py` recomputes the merged tree's unreachable
quota share as `some` (7 of 14 modules) — the branch's wired quota backends are
part of that arithmetic. No quota/persistence source file conflicted: develop
did not touch the #1204 surfaces, and the migration chain re-verified as a
single linear head (`039_quota_usage_event_identity`) applying cleanly from
empty PostgreSQL.

## Retention and chain-tip repairs

Two durable-bookkeeping repairs from the validation round: `quota_usage_events`
needed an entry in `quality/durable-table-retention.json` (recorded honestly as
`undecided` against #325, which owns retention — this issue creates the ledger,
it does not decide its lifetime), and the `usage_events` entry's note no longer
claims `SqliteUsageLog` is unwired. The migration's parent also moved from
`038` to the develop chain tip `036_audit_log_org_scope` after develop's
`039`/`040` re-forked the chain; `test_audit_scope_migration`'s head pin
follows the new tip, the same reconciliation its own comment narrates for
#1531 and #1079.

## Migration chain linearization

The branch's migration previously shared trunk's renumbered 033-035 space and
sat as a second alembic head, which fails CI's `alembic upgrade head`. It is
renamed to `039_quota_usage_event_identity`; after develop's
`039_canvas_job_admission_key` and `040` merged, its parent moved again — from
`038` to the develop chain tip `036_audit_log_org_scope` — because the old
parent re-forked the chain into two heads. `tests/migrations/test_migration_chain.py`
applies the full chain to an empty PostgreSQL database, and the
downgrade/upgrade cycle recreates `quota_usage_events` — both run green
against the live server.

## Pinned-revision store suite follows its own convention

`tests/migrations/test_quota_and_session_stores.py` pins the revision the
durable stores run against; `PgQuotaTracker` now touches `quota_usage_events`,
which the old pin (023) predates. The pin moves *within* the existing suite,
so that suite's collected count does not change — hence no delta for it above. Per the suite's documented drift procedure
(the #327 move), the pin moves to `039_quota_usage_event_identity`; the
fixture's plain upgrade-from-empty already exercised the `vector`-dependent
001, so no new image coupling is introduced. All 11 cases pass against the
migrated scratch database.

## Independent verification (lane L1204, head bb42cd1a6)

Re-executed by the independent verifier against the exact head; no source files
changed. Lane paths: 95 passed / 22 skipped (matches the recorded driver run).
With `MAISTRO_TEST_PG_DSN` pointed at the lane pgvector:pg18 container: the full
`packages/maistro-core/tests/persistence/` + quota usage-log + container + RSI
selection runs 661 passed with zero skips, including
`test_retrying_one_event_does_not_double_count[memory|sqlite|postgres]` — the
PostgreSQL leg ran against a real server, not the mock. `tests/migrations`
passes 96/96 with `MAISTRO_TEST_DATABASE_URL` set (note: that suite's
`empty_database` fixture deliberately `downgrade base`s the database the URL
names — point it at a sacrificial database, and do not also export
`DATABASE_URL`, which overrides the scratch-DB `DB_*` env the qs-suite builds
and silently redirects its alembic run at the wrong database). Full
`packages/maistro-core/tests`: 10172 passed, 655 skipped, 1 xfailed.
`ruff check` / `ruff format --check`, both `check-suite-inventory` gates,
`check-durable-table-inventory`, `check-convergence-matrix`, and
`check-reachability` all pass. `alembic upgrade head` from an empty database
applies the chain to the single head `039_quota_usage_event_identity`; the four
pivotal quota tests (legacy backfill, same-timestamp identities, forced
overlapping snapshots, commit-result-lost retry) and the three-backend
conformance test were re-run by name and pass. PR body and branch commits
carry no closure keywords; PR 1462 remains a draft.

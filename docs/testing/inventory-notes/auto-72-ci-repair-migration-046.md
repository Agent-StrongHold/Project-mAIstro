---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  tests/: +0
---

No new tests this round: a CI-repair round for the merge-queue evaluation at
the develop sync `f8adf13f8` (merge of `origin/develop` tip `bc1182f9c` into
auto-72). Existing suites re-proven green; node counts unchanged in every
gated suite (full `check-suite-inventory.py` run: 14/14 ok, `tests/` = 4117).

# auto-72 CI repair — migration renumber to 046 + PG learnings scope coercion

## What failed (named gates at f8adf13f8)

- `coverage (PostgreSQL)` — quality.yml producer
- `lint-and-type-check` — ci.yml mypy step
- `Quality gate (Pillars 1–4, 7, 8)` — downstream of the missing
  `coverage-postgres` artifact
- `gates-ran` — aggregate of the above

## Root cause 1: alembic revision-id collision after the develop sync

Develop landed `045_capability_invocation_logical_effect` (#1194, parent
`043`) while this branch carried `045_durable_elevation_grants` (#72, parent
`044`). After the merge the chain had two heads named `045`, breaking every
`upgrade head` consumer, and the bare `op.create_table` DDL failed the
stamp-back re-application walk (`DuplicateTable`) — the same shape that broke
#1194's own coverage (PostgreSQL) leg.

Repair (per the chain's stated convention, see the 046 docstring):

- `alembic/versions/045_durable_elevation_grants.py` renamed (git mv) to
  `046_durable_elevation_grants.py`; `revision = "046"`,
  `down_revision = "045"` — the chain is linear again with exactly one head:
  `042 → 039_quota_usage_event_identity → 044 → 043 → 045 → 046`.
- DDL is now idempotent (`CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT
  EXISTS`) so a database that already carries `elevation_grants` is adopted
  untouched by the chain-level re-application test
  (`test_reapplying_the_chain_over_an_already_migrated_schema_is_adopted`).
- `quality/durable-table-retention.json` elevation_grants note now cites
  alembic 046; the head assertion in
  `tests/migrations/test_capability_invocation_effect_index_migration.py`
  follows to `["046"]`.

## Root cause 2: mypy arg-type in pg_learnings (from develop's #1156 fix)

Develop's `1e8b27a84` added `scope=row.get("scope") or "agent"` in
`_row_to_learning`, passing `Any | str` where `Learning.scope` is
`MemoryScope` — `Success: no issues found in 847 source files` became
1 error. The SQLite twin (`sqlite_learnings.py:397`) already coerces with
`MemoryScope(...)`. The repair mirrors the twin exactly:
`scope=MemoryScope(row.get("scope") or "agent")` (pg_learnings.py:538).
Runtime behavior for store-written rows is unchanged (scopes are valid
`MemoryScope` values by construction; a StrEnum equals its string), and a
corrupted scope value now fails visibly at row-mapping on both backends —
twin parity per #1156.

## Evidence (all commands run in this worktree)

- `uv run ruff check .` / `uv run ruff format --check .` — clean (2616 files).
- Migration suites on an **unmigrated** pgvector:pg18 database
  (`MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_DATABASE_URL=…:5472/maistro_test`):
  `uv run pytest tests/migrations -q` → **100 passed**.
- `uv run alembic upgrade head` → walks `…→ 043 → 045 → 046`, single head.
- Schema-dependent PG legs (chain applied):
  `uv run pytest packages/maistro-core/tests/persistence
  packages/maistro-core/tests/test_container_postgres.py
  packages/maistro-core/tests/security/test_elevation_durable.py -q` →
  **686 passed**.
- Learnings twins after the coercion fix:
  `pytest …/test_pg_learnings.py …/test_learning_contract.py
  …/test_sqlite_learnings.py …/test_sqlite_learnings_scope.py
  …/test_record_provenance.py -q` (PG DSN set) → **94 passed**;
  SQLite-only `test_elevation_durable.py` → 3 passed, 3 PG skips.
- `uv run mypy <9 package src trees>` → **Success: no issues found in 847
  source files** (was 1 error before the fix).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → 1402/1402, 0
  unclassified (no ledger amendment needed; the fix eliminated no
  identities and added none).
- `uv run python scripts/check-durable-table-inventory.py` → ok, 70 tables.
- `uv run python scripts/check-suite-inventory.py` → ok, 14 suites match.

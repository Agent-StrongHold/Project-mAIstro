---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

No new tests this round; the work is (a) repairing this ledger's own
front-matter format and (b) the develop sync. Existing suites re-proven green
in full (maistro-core 10680 passed / 733 skipped / 1 xfailed;
maistro-server 413 passed) plus the #72 targeted battery (106 passed).

# auto-72 verifier repair 5 — inventory-note schema repair + develop sync 151bcfe2e

## What failed before (prior finding, reproduced)

`uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`
exited 2 at head 88604f872 with

    error: docs/testing/inventory-notes/auto-72-verifier-repair4.md:
    cannot read `added: []` as `<suite>: <±count>` under `inventory-delta:`

The repair4 note used an `added: []/removed: []/modified:` shape the ledger
parser cannot read (DELTA_LINE_RE accepts only indented `<suite>: <±count>`
lines). Rewritten as `packages/maistro-core/tests: +0` with the fixture
rationale moved into the note body.

## Develop sync

`origin/develop` advanced to 151bcfe2e (#1628, effect-door ratchet
authorizations: `quality/ratchet-authorizations.json` +
`maistro_rsi/sensitive_paths.py`). Merged into auto-72 with no conflicts;
no #72-owned file overlaps.

## Gates re-proven at merge head (e9fcedf7b + merge)

- `uv run ruff check .` — pass; `uv run ruff format --check .` — 2603 files ok.
- `uv run python scripts/check-suite-inventory.py` (full, no args, CI shape) —
  **ok: 14 suite(s) match the recorded inventory** (maistro-core 11414,
  maistro-server 413, …).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — 1403↔1403 vs base
  151bcfe2e3d2, unclassified 0, never_allowlist 0. No ledger edit needed.
- `check-durable-table-inventory.py` — ok: 70 durable tables, each with a
  declared retention.
- `check-promotion-surface.py`, `check-merge-markers.py` — ok.
- Live PostgreSQL (pgvector:pg18, container `auto-718-repair-pg`, port
  18718), `MAISTRO_TEST_DATABASE_URL` set:
  - `uv run pytest tests/migrations/ -q` — **96 passed** (2m34s); the
    chain incl. `045_durable_elevation_grants` applies on the empty-database
    path with the order-independent fixture from 9cb36bcd6.
  - `uv run pytest packages/maistro-core/tests/security/test_strike_tracker_conformance.py
    packages/maistro-core/tests/events/ -q` — **422 passed** on the same
    shared DB, re-proving the #1172 PG strike conformance and the
    fixture's cross-suite ordering fix.

## Spot checks of #72 durable-state acceptance surfaces (source-level)

- Health truthfulness: `container.py:1773` computes `stores_memory_backed`
  from the actual `database_url` (`:memory:` check), and
  `maistro_server/api/health.py:87-121` reports per-family
  `{backend, durable}` (Pg/Sqlite/memory distinction, `usage_log`
  persistence backend) — not only Foundation State.
- #1204 idempotency: `maistro/quota/sqlite_usage_log.py:51,100,133`
  (`event_id TEXT NOT NULL UNIQUE`, unique index, `ON CONFLICT (event_id) DO
  NOTHING`); 14 tests in `tests/quota/test_sqlite_usage_log.py`.
- #1157: `tests/persistence/test_sqlite_schema_concurrency.py` passed.
- #1156: 1e8b27a84 NULL category/scope coercion; learnings suites green in
  the full core run.
- #1172: `alembic/versions/045_durable_elevation_grants.py` present;
  strike/health suites green.

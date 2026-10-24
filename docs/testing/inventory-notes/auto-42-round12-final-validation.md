---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---
# auto-42 round 12: fresh full core-path validation at 581286c782dd

No production or test code changed in this repair round. The mandatory
CI-repair Vulture ratchet found no unbanked identities, so the permitted
`quality/vulture-baseline.json` amendment was neither needed nor made.

## Executed evidence

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` passed: 1,402 reviewed
  identities, with `unclassified: 0` and `never_allowlist: 0`.
- `uv run pytest packages/maistro-core/tests/graph/durable_runs
  packages/maistro-core/tests/tasks packages/maistro-core/tests/runtime
  packages/maistro-core/tests/runs
  packages/maistro-core/tests/observability/test_execution_correlation.py
  -x -q` passed: **2021 passed, 285 skipped**. The six emitted
  `PytestUnhandledThreadExceptionWarning` warnings are from `aiosqlite`
  worker cleanup after SQLite tests; no test failed.
- `uv run ruff check .`, `uv run ruff format --check .`,
  `scripts/check-execution-lifecycles.py`, `scripts/check-lifecycle-provenance.py`,
  `scripts/check-durable-table-inventory.py`, and
  `scripts/check-suite-inventory.py --suite packages/maistro-core/tests` all
  passed.
- A fresh disposable PostgreSQL 18 database was migrated from the current
  Alembic base through revision `046`, then
  `MAISTRO_TEST_PG_DSN=... MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest
  packages/maistro-core/tests/runs -x -q` passed: **1241 passed, 3 skipped**.
  The temporary database and role were dropped after the run. The same four
  pre-existing SQLite cleanup warnings occurred.

## External acceptance blocker

Read-only `gh issue view` queries at this head report #1169 and #1170 CLOSED,
but **#1194 OPEN** (`closedAt: null`). Issue #42 explicitly requires all three
to close before it can be complete. This lane cannot close a GitHub issue and
no local repair can satisfy that external dependency.

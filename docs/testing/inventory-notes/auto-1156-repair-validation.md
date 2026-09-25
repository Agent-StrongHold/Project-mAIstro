---
inventory-delta:
  packages/maistro-core/tests: +0
---
# auto-1156 repair validation evidence

Validation re-executed from a clean head for the #1156 repair lane; no new
test nodes, this note records the executed evidence and the disposition of
the prior run's findings.

Executed against a dedicated pgvector:pg18 container migrated with
`uv run alembic upgrade head` (chain is linear, tip `036_audit_log_org_scope`):

- `packages/maistro-core/tests/persistence` + `memory/learnings` +
  `agents/test_base.py` + `agents/test_context_builder.py`: all green with
  `MAISTRO_TEST_PG_DSN` set — the conformance learning nodes (round-trip of
  every declared field, org/team/user scope on `find_relevant` and
  `get_promoted`) passed the memory, SQLite **and** PostgreSQL
  parameterizations, plus both real-server `find_similar` scope-axis tests.
- `packages/maistro-core/tests` (full package) with the DSN: 10685 passed,
  116 skipped, 1 xfailed.
- `scripts/check-diff-coverage.py coverage.xml --base 3e9f7525` over a
  branch-collected maistro-core run: every learning-scope source file clears
  the 90%/80% per-file floor (the earlier 82.8% `pg_learnings.py` failure is
  gone; the real-DSN producer covers lines 128 and 283-289). Residual FAIL
  entries are outside this issue: `events/pg_stores.py` and
  `protocols/auth.py` were changed by merged #1163/#1472 work, and the
  canvas/bootstrap/design/evolve/scripts phases need the full CI matrix.
- `check-doc-links.py`, `check-adr-index.py`, `check-cross-package-imports.py`,
  `check-suite-inventory.py`, `verify-monorepo-layout.sh`: all ok.
- `ruff check .` / `ruff format --check .`: clean after formatting the
  lane's reproduction script.

Disposition of the prior run's `_text` finding
(`sqlite_learnings.py::_text` maps NULL to `""`): this is the documented
disposition, not a defect. The `Learning` dataclass declares `team_id` and
`source_query` as non-optional `str`, so a read has no NULL shape to return;
the PostgreSQL twin maps identically (`row.get("team_id") or ""`), and the
storage layer keeps legacy columns NULL — asserted by the migration test in
`test_sqlite_learnings_scope.py` (`SELECT source_query, team_id ... ==
(None, None)`), which also proves a legacy row stays withheld from other orgs.
No scope or provenance is fabricated at rest; only the read shape coerces,
identically on both twins.

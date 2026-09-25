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

## Round 2 — CI quality-gate repair (radon CC ratchet)

CI at `417f6660a` failed `quality.yml`'s Quality gate in the radon CC ratchet
(`scripts/check-radon-baseline.py`): the #1156 scope work had grown
`InMemoryLearningStore.store` to C(11), `PgLearningStore.store` to C(12) and
`SqliteLearningStore.store` to C(12) — unbaselined complexity — and left one
stale entry (`InMemoryLearningStore.find_relevant`, refactored below C by the
shared `learning_scope_predicate` extraction) that the ratchet requires to be
pruned.

Repair: code motion only, no baseline growth. The dedup probe of each `store`
was extracted verbatim into a helper on its own class
(`InMemoryLearningStore._find_dedup_match`, `PgLearningStore._bump_dedup_hit`,
`SqliteLearningStore._bump_dedup_hit`), returning every `store` to grade A/B
(A(4)/B(6)/B(6) measured); the stale `find_relevant` entry was removed from
`quality/radon-baseline.json`. A first cut of the pg helper typed its
connection as `asyncpg.Connection`, which pyright flagged (22 vs baseline 21,
`PoolConnectionProxy` is the actual `pool.acquire()` product); retyped to
`asyncpg.pool.PoolConnectionProxy` — pyright back at the 21 baseline.

Re-executed evidence (pgvector:pg18 container on :5599, migrated to
`036_audit_log_org_scope`):

- `check-radon-baseline.py`: exit 0 — new 0, regressed 0, improved 0,
  candidate-stale 0; the ratchet tightened 69 -> 68 reviewed blocks.
- `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`: exit 0, 1415 reviewed identities -> 1415.
- `mypy --strict packages/maistro-core/src`: clean (631 files), with the
  `bootstrap` extra installed as CI's `--all-extras` does.
- `pyright`: 21 errors = `PYRIGHT_BASELINE` 21.
- `pytest packages/maistro-core/tests` with `MAISTRO_TEST_PG_DSN`:
  10804 passed, 116 skipped, 1 xfailed — including the PostgreSQL
  parameterizations of the round-trip and scope conformance nodes that
  exercise the refactored `PgLearningStore.store` dedup path.
- `check-diff-coverage.py coverage.xml --base 55c5ad892e68bdd015db00ebe034ea6818a8c1f5`
  over a branch-collected core run: ok — every measured touched file ≥ 90%
  lines / 80% branch arcs (`reproduction.py` remains outside any measured
  root, as recorded in round 1).
- `xenon` (baseline 77): 0 violations. `interrogate -f 46 .../maistro`:
  54.4%. `formal/` hypothesis pillar: 421 passed, 1 skipped (after
  `uv pip install -e packages/maistro-evolve`, as CI installs it).
  `check-execution-lifecycles.py`, `check-model-egress.py`: ok.
- `ruff check .` / `ruff format --check .`: clean.

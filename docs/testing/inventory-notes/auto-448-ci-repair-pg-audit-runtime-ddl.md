---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-448-ci-repair-pg-audit-runtime-ddl

Lane L448 (issue #448) CI repair at 34379a166. The merge-queue evaluation at
that head reported ten red checks; `gh api .../actions/jobs/<id>/logs` gives the
per-job evidence, and it splits into exactly two causes — one authored here and
one inherited from develop.

## Cause 1 (authored here, repaired): `PgAuditLog.ensure_schema` took over DDL

34379a166 made `ensure_schema` issue `CREATE TABLE IF NOT EXISTS audit_log`
(the table, its four named indexes and the eight `ix_audit_page_*` cursor
indexes) behind a transaction-scoped advisory lock. Four CI jobs died on it,
all on the same assertion in the fake-pool suite:

- `postgres (pg17)` (job 118633528887) and `postgres (pg18)`
  (118633528819): `test_ensure_schema_adds_proof_columns_idempotently` →
  `AttributeError: 'FakeConnection' object has no attribute 'transaction'`.
- `coverage (no services)` (118633347128): the same failure plus
  `test_container_wiring.py::test_audit_log_wiring_prefers_postgres_and_upgrades_its_schema`
  → `'_AuditFakeConnection' object has no attribute 'transaction'`.
- `coverage (PostgreSQL)` (118633347094): same test,
  `1 failed, 6285 passed`.

The change was also wrong on the durability contract, proven against
`pgvector/pgvector:pg17` in this worktree:

- the table it fabricates gives `org_id` **no server default**, while migration
  `036_audit_log_org_scope` declares `server_default=sa.text("''")` — the shape
  `test_real_postgres_two_org_scope_and_schema` pins;
- it makes the canonical chain un-replayable: `PgAuditLog.ensure_schema()` on an
  empty database followed by `alembic upgrade head` dies with
  `sqlalchemy.exc.ProgrammingError: (psycopg.errors.DuplicateTable) relation
  "audit_log" already exists` in revision `005`, whose `create_table` is
  unconditional.

So the repair restores the contract the sibling PostgreSQL stores already keep
(`container.py`: "an idempotent ALTER that adds the scope column its queries
name"): `ensure_schema` is the `ADD COLUMN IF NOT EXISTS` half only, and a
database that was never migrated fails loudly with `UndefinedTable` instead of
being self-repaired into a second schema authority. The alembic chain (005,
036, 062) stays the only owner of the table, its defaults and its indexes.

## packages/maistro-core/tests (+1)

`test_pg_audit.py::test_ensure_schema_never_fabricates_the_migrated_audit_table`
builds a database of its own (the pattern `test_canvas_supported_path.py`
already uses), calls `ensure_schema()` on it, and requires both:

- the call raises `asyncpg.exceptions.UndefinedTableError`, and
- `to_regclass('audit_log')` is still `NULL` afterwards.

Against 34379a166's implementation the same test fails twice over (no raise;
the table exists) — reproduced by restoring that file with
`git show HEAD:.../pg_audit.py` and running it. `unaltered` fake-pool test
`test_ensure_schema_adds_proof_columns_idempotently` is the second, cheaper
witness: it pins the exact ALTER list, so any DDL inserted before it fails.

## Cause 2 (inherited from develop, NOT repaired here): reachability debt

The remaining six red checks are one failure — `quality/reachability` and the
three root-suite tests that read the same baseline:

- `test` (118633345746): `3 failed, 5396 passed` —
  `test_check_reachability.py::test_baseline_matches_the_tree`,
  `test_reachability_baseline_identity.py::test_the_committed_baseline_passes_the_gate_it_now_carries`,
  `::test_the_baseline_is_exactly_the_unreachable_set`.
- `Quality / Reachability` (118633347376): `1419 production modules, 169
  unreachable`, `maistro.runs.admission_identity` NEWLY UNREACHABLE.
- `exact-debt-ledger` (118633345789): the same module through
  `check-reachability-provenance.py`, which then reds
  `check-ratchet-provenance.py` — vulture itself is clean (1326 → 1326).
- `Quality gate (Pillars 1–4, 7, 8)` (118635021246):
  `quality-reachability: dependency did not succeed`.
- `integration-scope` (118633345111) and `gates-ran`: aggregators over the
  above.

`maistro.runs.admission_identity` is develop's, landed by #1851
(`9efe89caa`) with no import edge from any `src` module and no baseline entry.
Scanning the *base tree* (`git archive e20e9f52e`, then
`scripts/check-reachability.py`) reports the identical `NEWLY UNREACHABLE`
module, and `git diff origin/develop...HEAD -- quality/` is empty: this branch
touches no ledger and cannot have moved the set. Banking it is an owner
decision under the two-merge rule (`quality/ratchet-authorizations.json` is
read from the merge base, so a grant added here could never authorize this
candidate), and the entry also asserts an architecture answer about #1851's
root-admission surface — library-and-unwired, or built-but-never-wired. Left to
develop, recorded here so the next reader does not re-diagnose it as this
lane's.

## Re-executed evidence at this head

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_audit.py -v`
  (real `MAISTRO_TEST_PG_DSN`) — 20 passed, including both `ensure_schema`
  witnesses and `test_real_postgres_two_org_scope_and_schema`.
- `uv run pytest packages/maistro-core/tests/persistence packages/maistro-core/tests/test_container_postgres.py`
  (`MAISTRO_REQUIRE_PG_LEGS=1`, `pgvector/pgvector:pg17`) — 850 passed,
  84 skipped.
- `uv run pytest tests/migrations` on a fresh database — 168 passed (the
  chain applies to empty and reverses, exactly what the runtime `CREATE TABLE`
  made impossible).
- `uv run pytest tests/test_check_reachability.py tests/test_reachability_baseline_identity.py`
  — the same 3 inherited failures, naming only `maistro.runs.admission_identity`.
- `uv run ruff check .` / `ruff format --check .` — clean, 3368 files.
- `uv run mypy packages/maistro-core/src` (with `--extra bootstrap` installed) —
  797 files, no issues.
- `scripts/check-durable-table-inventory.py` — 112 tables, each with a declared
  retention (audit_log still found through migration 005, as it should be).
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — 1326 reviewed identities → 1326 findings.

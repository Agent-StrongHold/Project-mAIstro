# REPAIR NOTES — auto-16, coverage-gate round 2 (head `96e915a21`)

Job `b1b2760b74524ee3b99152e04bc2f240`, 2026-10-20. Scope: the red
**Coverage gate (publish-set floor + diff coverage)** from the last merge-queue
evaluation of PR #2205 (head `13c8dc6d64a6`, diff base `fad17a87c341`). No
production code changed in this round; this file is the evidence record.

## What CI actually failed (actions run 39274881136, job 118144067576)

| step | conclusion |
|---|---|
| combine (incl. publish-set floor `--fail-under=87`) | success |
| **Diff coverage gate (per file, lines 90% / branches 80%)** | **failure** |

```
FAIL: 1 file(s) below the diff-coverage floor
  packages/maistro-core/src/maistro/capabilities/effect_context.py:
  83.3% of 6 changed lines (need 90%); uncovered 412
```

Line 412 is the `return await new_postgres_effect_context(...)` leg of
`new_backend_effect_context(pg_pool=...)` (#16/#1133). The commit that fixes it
is already on this branch: `6b144032b` adds
`packages/maistro-core/tests/capabilities/test_backend_effect_context.py` to
the `coverage-postgres` producer's pytest list (`.github/workflows/quality.yml`
line 441) — the only producer that runs that file's PostgreSQL leg; in
`coverage (no services)` the leg skips. CI has not yet evaluated a head
containing `6b144032b`.

## Local proof at this head (CI's exact gate script and bases)

Producers re-run locally under coverage with the workflow's `--source` flags
against `pgvector/pgvector:pg17` on `127.0.0.1:18918`:

- coverage-postgres: `tests/migrations` (168 passed), `alembic upgrade head`,
  then the producer's full append list — persistence, test_container_postgres,
  events, **capabilities/test_backend_effect_context.py**, runs, graph,
  projects, workspaces, goals, scheduling, tasks (2 files),
  security/test_elevation_durable, memory/user_model, quota (6422 passed),
  plus `tests/backlog` as its own invocation (114 passed — CI splits it from
  the append list precisely because `test_backlog_stores_import_no_rsi`
  asserts on process-global `sys.modules`; lumping them reproduces the
  documented false violation, not a product failure).
- coverage-unit, maistro-core leg, no PG env: 15670 passed / 1136 skipped
  (PG legs skip, as designed).
- hive-conductor backend producer (after
  `uv pip install -r packages/hive-conductor/backend/requirements.txt`):
  3771 passed / 23 skipped.

Combined (`coverage combine` + `coverage xml`):

- `scripts/check-diff-coverage.py coverage.xml --base fad17a87c34193a91c...`
  (the failed run's base) → `ok: every measured file this change touches is at
  or above 90% lines / 80% branch arcs`, **exit 0**.
- `scripts/check-diff-coverage.py coverage.xml --base e20e9f52ea94b393184...`
  (current develop base) → **exit 0**.
- `effect_context.py` in the combined report: 108/108 statements, 100%;
  line 412 hits=1 (previously the uncovered line).

Publish-set floor: structurally unchanged by this round. The `combine` step —
which contains `coverage report --fail-under=87` — **succeeded** in the very
CI run above, and `git diff 13c8dc6d..HEAD -- 'packages/*/src'
'packages/*/backend/services' alembic` is empty: no measured source changed
since that green floor measurement.

## Other gates re-proven at this head

- `uv run ruff check .` / `ruff format --check .` → green (driver checks 1–2);
  fixes the Quality/Ruff red seen at `13c8dc6d` (fixed by `18c9869d2`).
- `scripts/check-suite-inventory.py` for `packages/maistro-core/tests`
  (16813) and `packages/hive-conductor/backend/tests` (3794) → ok (driver
  checks 5–6); fixes the `test`-job inventory-drift red seen at `13c8dc6d`.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → 1326 reviewed identities = 1326 findings,
  exit 0 (no ledger amendment; no code changed this round).
- `RATCHET_BASE_REV=e20e9f52e... scripts/check-reachability.py` → exit 0;
  `pytest tests/test_check_reachability.py
  tests/test_reachability_baseline_identity.py` → 39 passed (the exact tests
  develop's own `test` job fails on; banked at this head by `96e915a21`).

## Inherited, NOT this branch's: develop e20e9f52 is itself red

ci.yml on **develop head `e20e9f52`** (run 39369230418, 2026-10-20T04:22)
fails `durable-events`, `test`, and `security` — with no branch content. Three
consecutive develop heads are red (d32ddff76, fad17a87c, e20e9f52).

1. **durable-events** (also fails locally, fresh unmigrated DB,
   `MAISTRO_REQUIRE_PG_LEGS=1`, CI's exact commands): 6 failures in
   `packages/maistro-core/tests/events/test_container_pg_durable_events.py`,
   all from one root cause —
   `asyncpg.exceptions.UndefinedTableError: relation "audit_log" does not
   exist` at `packages/maistro-core/src/maistro/persistence/pg_audit.py:43`.
   Developed in M2 commit `d32ddff76` ("WIP: [MILESTONE M2] Security cage…",
   #2198): `_wire_audit_log` (container.py:2912–2918) began calling
   `PgAuditLog.ensure_schema()`, whose body is three
   `ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS ...` statements — the table
   itself is created only by the alembic chain. Wiring a bare pool against an
   unmigrated database (the exact contract
   `test_wiring_creates_the_schema_it_needs` pins) now crashes at audit wiring
   before the durable-event stores can create their tables, and the remaining
   five failures cascade from the first. Not introduced by this branch: the
   identical failure appears on develop's own run. Owner: the M2/#2198 lane.
   `integration-scope` fails only as a declared dependency of durable-events.
2. **test** job: `tests/test_check_reachability.py::test_baseline_matches_the_tree`
   and `tests/test_reachability_baseline_identity.py` — develop's committed
   reachability baseline drifted from its tree (`maistro.runs.admission_identity`).
   This branch already carries the corresponding fix (`96e915a21`); the two
   tests pass at this head (39 passed, above).
3. **security** job: `pip-audit found advisories outside the triaged
   allowlist` on develop's own dependency set. This diff touches no
   dependency files (no `pyproject.toml`/`uv.lock` changes).

## Residual risks / handoff

- The merge queue will keep failing `durable-events` (+ `integration-scope`)
  for every branch — including this one — until the M2/#2198 lane repairs
  develop's `_wire_audit_log` regression on unmigrated databases.
- `security` (pip-audit) is environment/dependency-derived on develop; needs
  an allowlist triage by the dependency owner, not a code change here.

inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 verification round — job be3316db

Snapshot: issue #1893 only; branch `auto-1893`, clean starting HEAD
`ad7edf2b29a6cb5fb4e807c85d9289272c71a7c2` (develop base `4aa68edc0b6b`, one
read-only `git fetch origin`: origin/develop still resolves to `4aa68edc0b6b`,
already merged at `214b00a7d` — no sync conflict to resolve). Evidence
sources: job `be3316db0d6842be8d537f43345b1209` check-0..4 logs, dispatch
snapshot, prior result `ef44025c/result.json`, and this round's own reruns.

No production code, ledger, grant, gate or test file was edited this round:
independent verification pass with one added evidence note.

## Scope of this round — the legs the previous round never ran

The lane brief repeats `test: failure`, but the captured check-runs at
`d9ea4f3b1671` already showed `test: success` (stale signal), and the prior
round proved only the Python legs. This round closed the gap by executing
every remaining `test`-job leg at this head:

- hive-conductor frontend: `npm ci` → clean (0 vulnerabilities);
  `npm run lint` → **0 errors** (94 style warnings, non-blocking);
  `npm run build` → success.
- Generated-API-types gate (#1048): `uv run python
  scripts/dump-hive-openapi.py` (228 paths, 134 schemas) + `npm run gen:api`
  + `git diff --exit-code -- packages/hive-conductor/frontend/src/api/types.gen.ts`
  → **no diff**.
- canvas frontend: `npm ci` → clean; `npm run test:ci` → **79 passed (5 files)**;
  `npm run lint` → 0 errors; `npm run build` → success.

## Python legs re-proven independently at ad7edf2b2 (CI env, CI-exact args)

- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 pytest packages/maistro-server/tests
  packages/maistro-turing/tests packages/maistro-turing/backend/tests
  packages/maistro-design/tests packages/maistro-ext-harness/tests
  packages/maistro-ext-sdk/tests -q` → **1837 passed, 9 skipped** (62s).
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 RATCHET_BASE_REV=origin/develop
  pytest tests/ --ignore=tests/tools/registry -q` → **4971 passed,
  129 skipped** (4m46s).
- CI-exact `uv run mypy packages/maistro-core/src … packages/maistro-evolve/src`
  → no issues in **956** source files.
- Verifier logs (check-0..4): `uv sync --locked --extra dev` ok;
  `ruff check .` clean; `ruff format --check .` 3270 files formatted;
  focused `pytest test_root_admission_identity.py test_admission_codec.py -q
  -x` → 201 passed, 3 skipped; `check-suite-inventory.py --suite
  packages/maistro-core/tests` ok (16401 identities).

## Exact-debt-ledger legs at CI's exact arguments

- vulture `packages/*/src --min-confidence 60 --exclude '*/third_party/*'` →
  **1323 = 1323, exit 0**, unclassified 0 — the vulture ledger needs **no
  amendment** despite the lane brief's repair paragraph.
- `check-shipped-surface-truth.py` → exit 0.
- `RATCHET_BASE_REV=origin/develop check-reachability-provenance.py` →
  **exit 1** and `check-reachability-dispositions-provenance.py` → **exit 1**,
  each with exactly the two known findings (`maistro.runs.admission_identity`,
  `maistro.tasks.admission_codec` — NEW unreachable module / NEW disposition,
  base `4aa68edc0b6b`). Structural: `ratchet_provenance.load_authorizations`
  reads `quality/ratchet-authorizations.json` from the base revision, so an
  in-branch grant is inert by construction; the issue forbids gate edits that
  green an unwired slice. Resolution unchanged: land the two reachability
  authorizations on the integration base first, then merge it here. External
  to this lane (no GitHub mutations permitted).

## Durability re-proof on a fresh disposable PostgreSQL 18

New container `auto-1893-pg` (`pgvector/pgvector:pg18`,
127.0.0.1:15499/db `maistro`); `alembic upgrade head` ran the real chain to
`062_audit_cursor_indexes`. Then:

- `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=… MAISTRO_TEST_DATABASE_URL=…`
  over `tests/runs/test_root_admission_identity.py` +
  `tests/tasks/test_admission_codec.py` → **204 passed, 0 skipped**.
- `pg_get_constraintdef` for `ck_task_idempotency_v2_identity` (migration 055)
  re-read from the live DB: binding clause is `((task_id IS NULL AND run_id IS
  NULL) OR (task_id IS NOT NULL AND run_id IS NOT NULL AND task_id =
  receipt_id))`; acknowledged requires a bound pair.
- End-to-end probe through the **production** codec (`encode_admission_record`
  → asyncpg INSERT → SELECT → `decode_admission_header`/`decode_admission_record`):
  INSERT satisfied `ck_task_idempotency_v2_identity`; decoded record equals
  the original DTO; re-encode is byte-identical; cleanup left **0 residue
  rows**. The probe and its casts live outside the repo (no tree edit).

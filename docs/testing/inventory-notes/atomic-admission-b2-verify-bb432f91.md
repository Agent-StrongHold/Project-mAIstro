inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 verification round — job bb432f91

Snapshot: issue #1893 only; branch `auto-1893`, clean starting HEAD
`63009d93586d5528c8bfa701a5f81fa56bcb6f72` (develop base `4aa68edc0b6b`;
one read-only `git fetch origin develop` — no sync conflict, no new
origin/develop commits to merge). Delta vs the previously verified head
`ad7edf2b2` is one docs-only commit (`63009d935`, the be3316db evidence
note), so all functional code is identical; every leg was nevertheless
re-executed fresh at this head rather than inherited.

No production code, ledger, grant, gate or test file was edited this round:
independent verification pass with one added evidence note.

## Verifier logs (job bb432f91, check-0..4)

`uv sync --locked --extra dev` ok; `ruff check .` all checks passed;
`ruff format --check .` 3270 files formatted; focused `pytest
test_root_admission_identity.py test_admission_codec.py -q -x` → 201 passed,
3 skipped (the 3 skips are the PG legs before a DSN is configured);
`check-suite-inventory.py --suite packages/maistro-core/tests` ok (16401
identities, 0 duplicates).

## Independent reruns at 63009d935

- Focused: `pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -q` →
  **201 passed, 3 skipped**.
- mypy on the two changed production modules → no issues in 2 source files.
- Packages legs (CI env `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`): server,
  turing, turing/backend, design, ext-harness, ext-sdk → **1837 passed,
  9 skipped** (63s).
- Root tree: `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 pytest tests/
  --ignore=tests/tools/registry -q` → **4971 passed, 129 skipped** (4m54s).
  The lane brief's `test: failure` is stale for the Python legs.
- hive-conductor frontend: `npm ci` clean; `npm run lint` → **0 errors**
  (94 warnings, non-blocking); `npm run build` → success.
- Generated-API-types gate (#1048): `dump-hive-openapi.py` (228 paths,
  134 schemas) + `gen:api` + `git diff --exit-code -- …types.gen.ts` →
  **no diff**.
- canvas frontend: `npm ci` clean; `npm run test:ci` → **79 passed (5 files)**;
  `npm run lint` → 0 errors (13 warnings); `npm run build` → success.

## Exact-debt-ledger legs at CI's exact arguments (vulture-ratchet.yml:77-84)

- vulture `packages/*/src --min-confidence 60 --exclude '*/third_party/*'` →
  **1323 = 1323, exit 0** — no amendment needed.
- `check-shipped-surface-truth.py` → exit 0, matrix complete.
- `RATCHET_BASE_REV=origin/develop check-ratchet-provenance.py`: its own
  ratchets hold (1 tolerated gap → 1 current gap, 0 lifecycle violations),
  but its inventory reports the two reachability legs failing. Run directly:
  `check-reachability-provenance.py` and
  `check-reachability-dispositions-provenance.py` → **exit 1** each, with
  exactly the two known findings (`maistro.runs.admission_identity`,
  `maistro.tasks.admission_codec` — NEW unreachable module / NEW disposition
  against base `4aa68edc0b6b`). Unchanged from be3316db: structural two-merge
  rule (`ratchet_provenance.load_authorizations` reads
  `quality/ratchet-authorizations.json` from the base revision, so an
  in-branch grant is inert by construction) and the issue's explicit "no
  baseline/grant/gate modifications to make an unwired slice green".
  Resolution unchanged and external to this lane: land the reachability
  authorizations on the integration base first, then merge it here.

## Durability re-proof on a fresh disposable PostgreSQL 18

New container `maistro-b2-pg` (`pgvector/pgvector:pg18`, 127.0.0.1:55733,
db `b2probe`, PostgreSQL **18.6**); `alembic upgrade head` ran the real
chain 001 → `062_audit_cursor_indexes` (062 is new since be3316db's
001→061 proof — the chain extension does not touch `task_idempotency`).
Then:

- `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=… MAISTRO_TEST_DATABASE_URL=…`
  over `tests/runs/test_root_admission_identity.py` +
  `tests/tasks/test_admission_codec.py` → **204 passed, 0 skipped** (the
  raw-vs-production-pool codec leg ran live against the migrated schema for
  unbound/bound/acknowledged states).
- `pg_get_constraintdef` for `ck_task_idempotency_v2_identity` (migration
  055) re-read from the live DB matches the shape asserted at
  `test_admission_codec.py:134-137`: binding clause
  `((task_id IS NULL AND run_id IS NULL) OR (task_id IS NOT NULL AND run_id
  IS NOT NULL AND task_id = receipt_id))`; `acknowledged_at` requires a
  bound pair.
- Negative probe on the live DB: a direct SQL INSERT with
  `task_id ≠ receipt_id` and both binding columns set is **rejected by the
  CHECK** — the storage contract `encode_admission_record` writes against is
  enforced by the schema, not just by the codec.
- Post-run residue: `SELECT count(*) FROM task_idempotency` → **0 rows**.

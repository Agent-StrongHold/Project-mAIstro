---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 verification round — job 86cf62ae

Snapshot: issue #1893 only; assigned branch `auto-1893`, clean starting HEAD
`d18a93bf9d9ff816377eb4f03d199ce4261206ef` (develop base `4aa68edc0b6b`).
Evidence sources: job `86cf62ae083542aba7c6d5d8a6bd8920` dispatch snapshot and
check-0..4 logs, the prior result artifact
`0b5778e8d51a4389894b329cf2dc1692/result.json`, captured CI check-runs at
`d9ea4f3b1671`, and this round's own reruns listed below. One read-only
`git fetch origin`; origin/develop still resolves to `4aa68edc0b6b` (the
supplied base is current; there is no new merge to perform and no admission
authorization exists on develop).

No production code, ledger, grant, gate or test file was edited this round:
this is an independent verification pass with one added evidence note.

## CI gate signal at the last pushed head (captured check-runs, d9ea4f3b1671)

- `test`: conclusion **success** — the lane brief's "test: failure" is stale.
- `exact-debt-ledger`: conclusion **failure** — the only red check.
- Every other completed check: success (durable-events, MinIO and the
  container scan are `skipped`, their normal not-applicable state).

## This round's locally executed gates at d18a93bf9 (CI env, CI-exact args)

- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 pytest tests/ --ignore=tests/tools/registry -q`
  → **4971 passed, 129 skipped** (4m45s). Includes the three reachability
  baseline-identity tests that pin the committed ledger to the tree.
- `packages/maistro-server/tests` 545 passed, 8 skipped; `maistro-turing/tests`
  210 passed; `maistro-turing/backend/tests` 90 passed;
  `maistro-design/tests` 572 passed, 1 skipped; `maistro-ext-harness/tests`
  273 passed; `maistro-ext-sdk/tests` 147 passed (same env, ext-harness
  unenv'd, matching the workflow).
- CI-exact `uv run mypy` over the ten src trees → no issues in 1050 files.
- `uv run ruff check .` → clean; `uv run ruff format --check .` → 3270 files
  formatted; `uv run python scripts/check-suite-inventory.py` → ok, 17 suites
  match the recorded inventory.
- Exact-debt-ledger legs at CI's exact arguments: vulture
  `packages/*/src --min-confidence 60 --exclude '*/third_party/*'` →
  **1323 = 1323, exit 0** (zero unbanked identities; the vulture ledger needs
  no amendment); `check-shipped-surface-truth.py` → exit 0;
  `check-promotion-surface-provenance.py` → OK, 270 modules, no expansion.
- Quality truthfulness: `check-reachability.py` → exit 0, 1394 modules, 171
  unreachable; `check-reachability-dispositions.py` → OK, 50 groups cover all
  171 (149 CONNECT, 20 LIBRARY, 2 RETIRE). The committed ledger describes the
  tree exactly; nothing is smuggled.

## Durability re-proof on a fresh disposable PostgreSQL 18.6

Docker `pgvector/pgvector:pg18` (PostgreSQL 18.6) as `auto-1893-pg` on
127.0.0.1:55999, database `admission1893`; `alembic upgrade head` ran the real
chain to `062_audit_cursor_indexes`. Then:

- `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=… MAISTRO_TEST_DATABASE_URL=…`
  over `tests/runs/test_root_admission_identity.py` +
  `tests/tasks/test_admission_codec.py` → **204 passed, 0 skipped** (1.6s).
  Without the DSNs the same files give 201 passed, 3 skipped — the skips are
  never counted as durability proof.
- `pg_get_constraintdef` for `ck_task_idempotency_v2_identity` (migration 055):
  binding clause is `((task_id IS NULL AND run_id IS NULL) OR (task_id IS NOT
  NULL AND run_id IS NOT NULL AND task_id = receipt_id))` — exactly the shape
  `encode_admission_record` emits and `_v2_binding` enforces.
- Raw SQL probes: bound pair (task_id = receipt_id) → `INSERT 0 1` accepted;
  one-sided (run_id NULL) → rejected, `violates check constraint
  ck_task_idempotency_v2_identity`; `task_id <> receipt_id` → rejected by the
  same constraint. Probe row deleted; residue 0, table total 0.

## Exact-debt-ledger residual: unchanged, external, structural

Reproduced at this head with `RATCHET_BASE_REV=origin/develop`:
`check-ratchet-provenance.py` FAILs with exactly two findings per gate —
`maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are NEW
unreachable modules / NEW dispositions "absent from trusted base and not
previously authorized" (base `4aa68edc0b6b`). `load_authorizations` reads
`quality/ratchet-authorizations.json` from the merge base, so an in-branch
grant is inert by construction ("banking is not authorizing", the two-merge
rule), and develop carries no admission authorization (`git show
origin/develop:quality/ratchet-authorizations.json` has none; this branch's
diff for that file against develop is empty). The remaining in-branch moves
are all out of scope or dishonest: wiring the consumer (the C leaf owns it),
an `__init__` re-export (package exports are not runtime reachability), or a
gate edit (the issue forbids gate modifications to make an unwired slice
green). Resolution is unchanged: land the reachability authorizations on the
integration base, then merge that base into `auto-1893`.

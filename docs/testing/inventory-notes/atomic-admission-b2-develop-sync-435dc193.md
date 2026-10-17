---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 verification round — job b1d6b7b4c9bf (develop sync to 435dc193 + full re-validation)

Snapshot: issue #1893 only; branch `auto-1893`, clean starting HEAD
`de74e82e7b1a1418aa801d3735e1e6252aae5f51`, develop base advanced on
origin to `435dc1937e0407ab4de198ffcced49860bb14ad2` (#2021, M9-I3
extension health) one commit past the previously merged `bb4257f0960f`.
This round merges `origin/develop` into the branch and re-validates the
merged head `ee709ea01254e49dd7c593c85fbf14a02caf5af2`. No production
code, test, ledger row, grant or gate file is authored by this round
(`git diff de74e82e7..ee709ea0 --name-status` contains only the merge's
develop-side files plus this note; quality/ diff vs `de74e82e7` is
exactly develop's own +24 `durable-table-retention.json` and +10
`shipped-surface-truth.json` lines). Inventory delta 0.

## Merge integrity

- Merge of `435dc1937` was content-clean (auto-resolved; the only
  overlapping file, `packages/maistro-core/src/_vulture_whitelist.py`,
  had disjoint hunks on both sides — branch's admission-identity
  entries vs develop's extension-health entries).
- AGENTS.md post-merge ledger check (`git diff --numstat origin/develop
  -- quality/`): only the branch's intended +2
  `reachability-baseline.json` rows and +11
  `reachability-dispositions.json` lines differ; `vulture-baseline.json`
  row count identical to develop (1504 lines both sides) — no multiset
  row loss in either direction.

## CI `test` job — status and every leg re-executed fresh at the merged head

The row named by the dispatch ("test: failure") is not reproducible as
current CI state: `gh run list --branch auto-1893 --workflow ci.yml`
(read-only) shows the latest PR run 38062467384 **completed success**
(20m32s, concluded 2026-10-10T15:30Z), and every historical CI run on
the branch is success. The persistent red check on the branch is
Vulture Ratchet's `exact-debt-ledger` job (external residual, below).
Regardless, every `test`-job leg was re-executed locally at
`ee709ea01254` with CI's env (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`):

- `packages/maistro-server/tests` + `maistro-turing/tests` +
  `maistro-turing/backend/tests` + `maistro-design/tests` +
  `maistro-ext-harness/tests` + `maistro-ext-sdk/tests` → **1849
  passed, 9 skipped** (develop's merge added ~12 server-side extension
  health API tests to the prior 1837+9)
- `tests/ --ignore=tests/tools/registry` → **4971 passed, 129 skipped**
  (4m48s; unchanged from the pre-merge head — develop's
  `test_check_reachability.py` edit moved no collected node)
- one-process leakage (`tests/` + hive-conductor backend + design,
  `--timeout=60`) → **9262 passed, 149 skipped** (7m37s)
- `scripts/check-suite-inventory.py` → **17 suites match**, exit 0
  (per-note delta summation absorbs the base move, as designed)
- `scripts/check-test-duplicates.py` → 0 byte-identical groups
- OpenAPI types: `dump-hive-openapi.py` + `npm run gen:api` +
  `git diff --exit-code types.gen.ts` → **no diff**
- hive frontend `npm ci`/`lint`/`build` and canvas frontend
  `npm ci`/`test:ci`/`lint`/`build`/`npm audit` were executed at the
  pre-merge head `de74e82e7` with **every exit 0**; the merge introduces
  zero frontend/package-lock deltas (`git diff de74e82e7..ee709ea0
  --name-only | grep -i 'frontend|package-lock'` is empty), so those
  results carry by content identity.

## exact-debt-ledger with CI's exact arguments (fresh at the merged head)

- vulture leg: `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **1323 reviewed
  identities = 1323 findings, exit 0** (base now resolves to
  `435dc1937`). No vulture-baseline.json amendment needed or made.
- shipped-surface leg: complete, exit 0.
- provenance leg (`RATCHET_BASE_REV=origin/develop
  check-ratchet-provenance.py`): FAIL, byte-identical to the CI log of
  run 38062467386 — `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` are NEW unreachable modules / NEW
  dispositions "absent from trusted base and not previously
  authorized". `origin/develop` re-fetched this round is `435dc1937`
  and its `quality/ratchet-authorizations.json` still contains **zero
  authorization rows** — the reachability grant has not landed.
  Two-merge rule: the grant must land on develop first; the lane's
  ledger exception covers the vulture ledger only (and vulture passes),
  and issue #1893 forbids "no baseline/grant/gate modifications to make
  an unwired slice green". No permitted in-lane action changes this;
  unblock = owner lands the reachability grant on develop, then this
  branch merges develop again.

## Other gates, fresh at the merged head

- `uv run ruff check .` → all checks passed; `uv run ruff format
  --check .` → 3277 files formatted
- mypy over the seven published `src` trees → "Success: no issues found
  in 894 source files" (develop's merge adds 2 scanned files)
- focused admission pytest → 201 passed, 3 skipped (PG legs skip
  without DSN)

## B2 acceptance — disposable-PG durability re-proven live at the merged head

Fresh `pgvector:pgvector:pg18` container (PostgreSQL 18.6), dedicated DB
`maistro_1893_final` on 127.0.0.1:15498; `MAISTRO_TEST_PG_DSN` and
`MAISTRO_TEST_DATABASE_URL` both set to that same DB (separate `export`
lines — see operator note):

1. Destructive-first contract: `tests/migrations/test_migration_chain.py`
   → **18 passed** (walks 001→head and reverses on the disposable DB).
2. `alembic upgrade head` → **062 (head)**.
3. Focused admission suites with `MAISTRO_REQUIRE_PG_LEGS=1`:
   **204 passed, 0 skipped**.
4. Live CHECK probes on the migrated schema (`psql` against
   `pg_constraint`): `ck_task_idempotency_v2_identity` present with the
   expected shape (binding ⇔ `task_id AND run_id AND task_id =
   receipt_id`; `acknowledged_at` ⇒ bound). A bound v2 row with
   `task_id = receipt_id`, `run_id` set, `acknowledged_at` set is
   **ACCEPTED** (`INSERT 0 1`); a partial pair (`task_id` only,
   `run_id` NULL) is **REJECTED** by the CHECK; a `task_id <> receipt_id`
   row is **REJECTED** by the CHECK.
5. Residue: after suites + probes, `task_idempotency` held only the
   positive probe row → `DELETE 1` → **0 rows**.

Operator note: the first `MAISTRO_REQUIRE_PG_LEGS=1` run of this round
showed "3 failed" — the same shell-quoting bug a prior round recorded:
`export DATABASE_URL=… MAISTRO_TEST_PG_DSN="$DATABASE_URL"` expands
`$DATABASE_URL` before the assignment lands, emptying the DSN, and the
test's own guard correctly `pytest.fail`s on the empty variable. Re-run
with separate `export` lines gave 204/0. Product code was never at
fault; recorded so the residue is auditable.

## Premature-closure scan

`git log bb4257f09..HEAD --format="%s%n%b" | grep -iE
'fixes|closes|resolves … #1893'` → no matches (the scan exits 1 =
clean). The merge commit references #2021/#1893 descriptively only.

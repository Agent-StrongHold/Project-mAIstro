---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 verification round — job a7961331 (re-validation at fd0ed75e6; no develop movement)

Snapshot: issue #1893 only; branch `auto-1893`, clean starting HEAD
`fd0ed75e60933ad2ecd0daeeec9176c928ebf892` (unchanged from the previous
round's end head). This round authors no production code, no tests, no
ledger rows, no grants and no gate files; the only tree change is this
note. Its purpose is to re-prove, freshly, the two dispatched claims:
the CI `test:` failure row and the exact-debt-ledger residual.

## CI `test:` failure — not reproducible at this head

Every Python leg of the `test` job (`.github/workflows/ci.yml:496`)
re-executed fresh at this head, CI env (`REQUIRE_AUTH=false`,
`MAISTRO_DRY_RUN=1`):

- `packages/maistro-server/tests`: 557 passed, 8 skipped
- `packages/maistro-turing/tests`: 210 passed
- `packages/maistro-turing/backend/tests`: 90 passed
- `packages/maistro-design/tests`: 572 passed, 1 skipped
- `packages/maistro-ext-harness/tests`: 273 passed
- `packages/maistro-ext-sdk/tests`: 147 passed
- `tests/ --ignore=tests/tools/registry`: 4971 passed, 129 skipped
- cross-suite leakage proof (`tests/` + hive backend + design, one
  process, `--timeout=60`): 9262 passed, 149 skipped
- OpenAPI types: `dump-hive-openapi.py` + `gen:api` + `git diff
  --exit-code` on `types.gen.ts` — no diff; frontend delta vs
  `origin/develop` is zero, so the npm legs carry from develop

## exact-debt-ledger residual — unchanged and external

With CI-exact arguments:

- vulture (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`): exit 0, 1323 reviewed identities = 1323 findings;
  **no amendment made or needed** in this CI-repair round
- `check-shipped-surface-truth.py`: exit 0
- `check-ratchet-provenance.py` (`RATCHET_BASE_REV=origin/develop`):
  exit 1, failing **only** `reachability-dispositions` and
  `reachability` on `maistro.runs.admission_identity` +
  `maistro.tasks.admission_codec` ("NEW ... not previously authorized");
  every other ratchet (adr-status-language, citation-status,
  promotion-surface, shell-execution, contract-markers, enumerations,
  lifecycle) passes

`origin/develop` was re-fetched this round: still `435dc1937e0407ab`,
`quality/ratchet-authorizations.json` still has **0 rows** — the
documented two-merge resolution (land the reachability authorization on
develop first, then merge develop in) remains external-owner action.
The lane's amendment exception covers only
`quality/vulture-baseline.json`, which needs nothing; amending the
reachability ledgers in-lane would fail the same gate by construction
(candidate baseline edits cannot approve themselves) and is forbidden
by the issue text. `origin/develop` is already an ancestor of this
branch (`ee709ea0`), so there is no sync conflict to resolve.

## Issue acceptance re-proven fresh

- all 10 prospective tests present 1:1 in
  `packages/maistro-core/tests/tasks/test_admission_codec.py`
- focused non-PG: 201 passed, 3 skipped; with
  `MAISTRO_REQUIRE_PG_LEGS=1` against the disposable PG 18.6
  (`maistro_1893_final`, alembic head 062): **204 passed, 0 skipped**
- live `ck_task_idempotency_v2_identity` probes on the migrated
  database: production-encoder INSERT of a bound v2 row accepted;
  partial pairs (each direction), `task_id != receipt_id`, and
  acknowledged-without-full-pair each rejected by the CHECK; 0 residue
  rows afterwards
- production diff vs `origin/develop` remains exactly
  `_vulture_whitelist.py`, `runs/admission_identity.py`,
  `tasks/admission_codec.py` and the two test files — no SQL mutation,
  HTTP mapping or queue change
- `ruff check .`, `ruff format --check .` clean; mypy clean (894
  files); suite inventory ok (16,466 collected node identities,
  duplicates 0)

Verdict: branch content unchanged and green on every gate it can
influence; the sole red is the develop-side reachability authorization
(two-merge rule), external to this lane.

# Round-3 repair notes for issue #881 (`auto-881`)

## What actually failed at the last evaluation

Three named CI gates at the previous head `2a123f9d8` (PR #2224, base `e20e9f52e`):
`integration-scope`, `exact-debt-ledger`, `durable-events`.

- **`durable-events`**: 5 failures in
  `packages/maistro-core/tests/events/test_container_pg_durable_events.py`,
  all `UndefinedTableError: relation "audit_log" does not exist` raised from
  `pg_audit.ensure_schema()`. This is a develop-side fix that landed *after* the
  branch's stale base: develop `252950bdbdc2` bootstraps the audit schema
  (+86 in `pg_audit.py`, +41 in `container.py`, +81 in the test). Reproduced
  locally on the branch head; develop `252950bdb` passes the same suite.
- **`exact-debt-ledger`**: `check-ratchet-provenance.py` → FAIL,
  `maistro.runs.admission_identity: NEW unreachable module absent from trusted
  base and not previously authorized`. Round 2 banked the identity on the
  branch, but `load_authorizations` reads grants from the merge base (two-merge
  rule), so a branch cannot self-authorize the tolerance. Develop `252950bdb`
  now classifies `maistro.runs.admission_identity` in `_EXCLUDED_PACKAGE_PYTHON`
  in `scripts/check-reachability.py`, removing it from the unreachable universe
  entirely.
- **`integration-scope`**: downstream aggregator —
  `durable-events is required by integration scope but concluded failure`. The
  required set from the 11 changed paths is docker-build, durable-events,
  hive-conductor-e2e(-ui), object storage (MinIO), postgres (pg17/pg18),
  strike-ladder, wheel-imports. Only durable-events failed; the rest are
  develop-side and unaffected by this branch.

Root cause: the branch's merge base `e20e9f52e` was 215 files behind develop
`252950bdbdc2`.

## Fixed in this round

1. **Synced develop into the branch**: `git merge --no-ff origin/develop`
   (conflict-free; `git merge-tree --write-tree` exit 0). New head
   `a51401c9abe9`. This pulls the durable-events audit-schema bootstrap and the
   reachability exclusion that supersedes round 2's banking.
2. **Reverted round 2's reachability banking** (superseded by develop's
   exclusion): removed the `maistro.runs.admission_identity` row from
   `quality/reachability-baseline.json` and the `runs-admission-identity-leaf`
   group from `quality/reachability-dispositions.json`. Both files now match
   `origin/develop` exactly (`git diff origin/develop -- <file>` is empty).
3. **Reverted the `CONVERGENCE-MATRIX.md` cell** round 2 changed
   (`Run / NodeRun / Attempt lifecycle` Unreachable `none`→`few`): with the
   module excluded the census is `none` again. The file now matches
   `origin/develop` exactly.
4. **Updated the suite inventory note's stale counts**: the prose said formal/
   664→667 and baseline 417; after the develop sync the gate's collected count
   is 670 at this head (667 at `origin/develop`), baseline 664. The front-matter
   delta is unchanged (`formal/: +3`, `tests/: +1`); `check-suite-inventory.py`
   is green.

## Validation executed locally (all green)

- `uv run ruff check .` / `uv run ruff format --check .`
- `RATCHET_BASE_REV=origin/develop python scripts/check-ratchet-provenance.py`
  → OK (0 lifecycle violations, 53 consumers with explicit provenance)
- `python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → exit 0 (1324 reviewed identities, no delta)
- `python scripts/check-shipped-surface-truth.py` → OK
- `python scripts/check-reachability.py` / `check-reachability-provenance.py`
  / `check-reachability-dispositions.py`
  / `check-reachability-dispositions-provenance.py` → OK
- `python scripts/check-convergence-matrix.py`, `check-citation-status.py`,
  `check-security-inventory.py`, `check_ac_state_impl.py`,
  `check-backlog-consistency.py`, `check-merge-markers.py`,
  `check-test-duplicates.py`, `check-m1-convergence-freeze.py`,
  `check-formal-oracle-independence.py` → OK
- `durable-events` step 1: `MAISTRO_REQUIRE_PG_LEGS=1
  MAISTRO_TEST_DATABASE_URL=... pytest packages/maistro-core/tests/events`
  → 385 passed
- `durable-events` step 2: `pytest tests/migrations/test_event_schema_agreement.py`
  → 5 passed
- #881 deliverable: `MAISTRO_TEST_PG_DSN=... pytest
  formal/models/test_execution_lifecycle_state.py` against pgvector:pg18 with
  `alembic upgrade head` → 3 passed

## Residual

- `integration-scope` is a GitHub Actions aggregator that polls check-run
  conclusions for the candidate SHA; it cannot be executed locally. Its only
  failing prerequisite, `durable-events`, now passes locally and the required
  set is unchanged (11 changed paths → the same 9 checks). The gate should go
  green once those checks re-run on the new head.
- `wheel-imports` and `docker-build` are in the required set because the branch
  touches `pyproject.toml`/`uv.lock`; the aiohttp floor lives in the root
  `maistro-workspace` meta-package (not under `packages/`), so no package wheel
  or build input changes. Not re-run locally (an all-wheel build is out of scope
  for this repair).

No `quality/vulture-baseline.json` or grant edits were made: the vulture step
passes unchanged with CI's exact arguments and no existing identity was
eliminated.

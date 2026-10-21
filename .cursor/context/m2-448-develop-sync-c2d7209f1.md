# M2 #448 — second develop sync (c2d7209f1) at merged head 817f68de9fd7

Round: CI-repair, lane L448, branch `auto-448`. Evidence:
`docs/testing/inventory-notes/auto-448-develop-sync-c2d7209f1.md`.

## What the red really was

The branch head `c2e7c2cba74d` was **three commits behind `origin/develop`**
(merge base `e20e9f52e`). Develop's `9417bb2f4` adds the
`maistro/runs/__init__.py` re-export that gives
`maistro.runs.admission_identity` an importer in `src/`. Without it the module
is `NEWLY UNREACHABLE`, which is the whole of:

`test` (3 root-suite reachability tests) · `Quality / Reachability` ·
`exact-debt-ledger` (via `check-reachability-provenance.py` →
`check-ratchet-provenance.py`) · `Quality gate (Pillars 1–4, 7, 8)` ·
`integration-scope` · `gates-ran`.

The prior round's note called this "inherited from develop, not repaired here".
True about ownership, but measured against a stale base: the branch was never
re-synced after develop landed `9417bb2f4`, so the missing import edge
persisted. **No ledger row was banked** — the module was made reachable.

## The merge

`git merge --no-ff origin/develop` → local commit `817f68de9fd7`
(parents `c2e7c2cba74d` + `c2d7209f1dbc`). Two conflicts, both resolved in
place:

1. `packages/maistro-core/src/maistro/persistence/pg_audit.py` — kept
   develop's `to_regclass('public.audit_log')` probe + no-op-when-absent.
   The branch's `c2e7c2cba` form raised `UndefinedTableError` on an unmigrated
   DB (breaks the durable-events fresh-server path); the earlier `34379a166`
   form created the table at runtime (contradicts migrations 005/036/062 and
   bricks `ensure_schema()` → `alembic upgrade head` with
   `DuplicateTable`). Docstring merged to record both facts.
2. `packages/maistro-core/tests/persistence/test_pg_audit.py` — kept **both**
   witnesses: develop's fake-connection no-op test and the branch's real-PG
   "never fabricates the migrated audit table" test (expectation changed from
   "raises" to "no-op and `to_regclass('audit_log')` still NULL"; same node
   ID, so the recorded `+1` is unchanged).

## Post-merge evidence (all at `817f68de9fd7`)

- `uv run ruff check .` → All checks passed; `ruff format --check .` → 3375 files.
- `scripts/check-reachability.py` → 1422 modules, 168 unreachable, no newly unreachable.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → 1326 → 1326, OK.
- `RATCHET_BASE_REV=origin/develop scripts/check-ratchet-provenance.py` → OK.
- `scripts/check-suite-inventory.py` → 21/21 suites, 32509 collected, 0 duplicates.
- `pytest tests/ --ignore=tests/tools/registry` → **5399 passed, 138 skipped** (reds are green).
- `pytest packages/maistro-core/tests/{extensions,runs,sandbox,tools}` → 3206 passed, 380 skipped.
- `pytest packages/maistro-server/tests` → 591 passed, 8 skipped.
- `pytest packages/hive-conductor/backend/tests` → 3791 passed, 24 skipped.
- postgres leg (pg17 **and** pg18, full `ci.yml` step sequence) → `LEG_RESULT fail=0`.
- durable events on a **fresh unmigrated** PG17 → `packages/maistro-core/tests/events` 383 passed, 0 skipped;
  `tests/migrations/test_event_schema_agreement.py` 5 passed.
- strike ladder (PG17) → `test_strike_tracker_conformance.py` 40 passed.
- `scripts/verify-wheel-imports.py --dist dist/ --python 3.12` → all 12 wheels import from a clean venv.
- `docker build -f Dockerfile -t maistro-engine:test .` → OK; `scripts/smoke-engine-canvas.sh maistro-engine:test` → **PASS**
  (run with `MAISTRO_SMOKE_PORT=18000`; host port 8000 was already taken on this machine — environmental, not a code fault).

**Negative control:** restoring the pre-merge `pg_audit.py` from `c2e7c2cba`
reproduces 5 failures in the events suite
(`UndefinedTableError: relation "audit_log" does not exist`); the merged file
was restored byte-identically (empty `git diff`).

## Still open / not provable here

- `hive-conductor-e2e` and `hive-conductor-e2e-ui` need the full compose stack
  and Playwright; not executed in this round.
- The hosted `integration-scope` and `gates-ran` aggregators need GitHub check
  runs for a pushed candidate SHA; the local commit `817f68de9fd7` is not
  pushed (no GitHub mutation from this lane).

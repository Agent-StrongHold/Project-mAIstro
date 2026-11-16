# Issue #325 repair round 4 — develop sync conflict + image-lock gate reconciliation

Starting head `44ad4a841` (round-3 exit head). The worktree arrived with a
preserved, unfinished merge of `ffc27cc43` (develop at capture time) and one
unmerged path: `scripts/check-image-lock-reconciliation.py`. Origin/develop
had since advanced one commit to `db4d3eb09` (the lane's stated base).

## 1. Develop sync (the previous block)

Two merges, both committed:

- `4f7b949e2` — merge `ffc27cc43`: the only unmerged path was the image-lock
  gate. Develop's round-8 (`#1838` lane) reworked `parse_expected` toward the
  same multi-pin problem this branch's **marker-evaluating gate** already
  solves more strongly (evaluate `python_full_version` markers against the
  dumped image interpreter instead of gating nothing). Resolution: HEAD
  wholesale — `parse_expected`/`parse_marker_variants`/`image_python_version`
  supersede develop's pins-set simplification; `_expected_clause` no longer
  existed on HEAD (`_skewed` names the exact applicable pin); `parse_actual`
  already carried develop's `dict[str, str]` typing fix. This continues the
  branch's own prior resolutions (`6e6c6449e`, `74a40c4d4`).
- `545b50bd8` — merge `db4d3eb09` (develop tip, the stated base): clean, no
  conflicts (REPAIR-NOTES-35-ci-gate-repair, dag-run projection tests, chat
  completion changes).

## 2. The contradiction the merge surfaced, and the fix

The `ffc27cc43` merge auto-resurrected two develop-side tests the branch had
deleted (develop modified lines HEAD had deleted):

- `test_conditional_pin_with_multiple_marker_versions_accepts_either_branch`
  — passes under the marker gate unchanged.
- `test_conditional_pin_with_multiple_marker_versions_still_names_an_unknown_branch`
  — **failed**: it demands that an image shipping a third, un-locked version
  of a marker-split name be reported as a *version mismatch naming the
  alternatives*, while HEAD's gate treated "applicable pin cannot be
  determined" (no dumped interpreter version) as gating nothing for the whole
  name — the third version surfaced only as "in image, not locked". Same
  verdict (exit 1), different label.

**Fix: strengthen the gate, keep both policies.** The leniency is now for the
lock's OWN branches only (`scripts/check-image-lock-reconciliation.py`):

- `_expected_clause` returns (develop's message format) for the multi-pin set.
- `_skewed` takes the variants dict; when the applicable pin cannot be
  determined but the installed version is not one of the split's own
  branches, the name is reported as a version mismatch against the whole
  named set. A shipped lock-branch still reconciles leniently
  (`test_marker_split_with_unevaluatable_marker_stays_lenient` unchanged).
- `main()` computes `parse_marker_variants` once and passes it through.

The resurrected develop test now passes **verbatim**; the branch's lenient
test pins the narrowed boundary (docstring updated); no test was added or
removed (43 before and after in the file; root `tests/` suite count unchanged
at 5890 — inventory gate ok, delta +0).

## 3. Validation (all at `545b50bd8` + the gate fix)

- `uv run ruff check .` / `uv run ruff format --check .` — pass.
- `uv run mypy` (CI's 7-package argument set) — Success, 939 files.
- `git diff --check` — clean.
- Driver's 17-suite retention battery — 536 passed, 109 skipped.
- Image-lock suite — 43 passed (was 42+1 failed before the fix).
- `check-durable-table-inventory.py` — `ok: 123 durable tables`.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (CI exact) — 1297 = 1297, exit 0, no ledger amendment.
- `check-radon-baseline.py`, `check-reachability.py`,
  `check-reachability-dispositions.py`, `check-contract-markers.py`,
  `check-convergence-matrix.py`, `check-security-inventory.py` — all exit 0.
- `check-suite-inventory.py` — `tests/` (5890), `packages/maistro-core/tests`,
  `packages/maistro-turing/backend/tests`,
  `packages/hive-conductor/backend/tests` all match.
- Newly merged hive-conductor dag-run projection suites — 61 passed.
- **Coverage gate reproduced end-to-end with CI's producers** (the round the
  CI finding named): migrations suite against an unmigrated database (173
  passed), `alembic upgrade head` on a fresh chain-migrated database, the PG
  producer's exact 17-suite list + persistence (run twice: 6733 and 6983
  passed), full `packages/maistro-core/tests` (17711 passed), turing backend
  (128 passed), root `tests/` producer (5769 passed) — one coverage database,
  then CI's exact invocation:
  `check-diff-coverage.py coverage.xml --base db4d3eb09...` — **exit 0, every
  measured file at or above 90% lines / 80% branch arcs** (also exit 0
  against round-3's base `3825fb9b5`). The publish-set 87% floor passed in
  CI's own failed run at `013b6a0e` (it reached the diff gate) and the branch
  diff touches no publish-set source beyond `maistro-core`, which this
  battery measured in full.

## 4. Residual findings (recorded, not repaired here)

1. **Pre-existing approval-store schema divergence** (round-3 residual #1,
   re-confirmed): 6 `tests/conformance` approval `[postgres]` legs fail
   against a fresh chain-migrated database (alembic 043 unique constraint vs
   runtime bootstrap shape). No CI job runs `tests/conformance` against a
   migrated chain; the branch diff does not touch approvals or alembic 043.
2. **NEW (pre-existing on develop, ordering-dependent):**
   `packages/maistro-core/tests/events/test_container_pg_durable_events.py`
   (lines 190, 240) drops `audit_log` and re-wires the container, so
   `PgAuditLog.ensure_schema` rebuilds it in **bootstrap shape**
   (`org_id TEXT NOT NULL DEFAULT ''`) instead of the chain's nullable
   036 shape. Any later introspection of `information_schema` in the same
   producer run then sees `is_nullable = 'NO'` and
   `test_pg_audit.py::test_real_postgres_two_org_scope_and_schema` fails.
   CI's producer ordering (persistence before events) passes today; the
   failure reproduces when the run starts from an already-rebuilt table.
   Neither file is touched by this branch. Needs its own issue.
3. `persistence/test_schedule_winner_crash.py` (untouched by this branch)
   flaked twice under full-battery load and passes in isolation —
   replica-convergence timing on a busy shared machine.
4. `config/test_loader.py` + `memory/test_engine.py` failures in the full-core
   run were induced by this verification's own exported
   `MAISTRO_TEST_PG_DSN`/`MAISTRO_TEST_DATABASE_URL` (the tests assert
   no-URL behavior); they pass without those variables, as CI runs them.
5. Container-scan timeout raise (30 → 45, `44ad4a841`) is a capacity fix for
   a job killed at its own cap mid-step with every completed step green; the
   gate's logic is unit-proven (43 tests) but the image build/scan path
   itself can only be exercised by CI.

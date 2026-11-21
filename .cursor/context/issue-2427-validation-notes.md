# Issue #2427 (P5a recovered-rediscovery) — local validation evidence

Recorded 2026-11-21 by the CR2427 repair lane at head `956ad29f1ce2`
(develop base `567d584260ce`; stacked PR base = #2425 tip `ccf3fcec09fa`).
**Re-validated 2026-11-21 at head `58a76678efae`** (merge of develop tip
`0d7bdd0a86` into the branch) — see the "Round at `58a76678efae`" section
below; all earlier evidence below was gathered at `956ad29f1ce2` and is kept
for provenance.
Purpose: the previous round ended with no commit ("clean tree is not proof of
repair"). This round re-verified every acceptance criterion against
reachable production behavior with a live Postgres, found **no code defect**,
and records the proof here so the next worker does not re-derive it.

## Acceptance criteria -> executed evidence (live PG: pgvector/pgvector:pg18
on 127.0.0.1:15432, `alembic upgrade head`, `MAISTRO_TEST_PG_DSN` set)

1. **Typed `RECOVERED` rediscovered after interrupted reclaim** —
   `uv run pytest` over the nine recovery suites + `test_spine_conformance.py`
   with PG: **537 passed, 0 skipped**. Whole `packages/maistro-core/tests/runs`
   tree: **2015 passed, 4 skipped** (the 4 are backend-capability skips:
   sqlite has no archive continuation store / durable retention probe).
2. **Spoofed prefix is not authority / newer-Attempt wins / parks own node** —
   `test_interrupted_reclaim_rediscovery.py -v`: every parametrization
   PASSED on memory + sqlite + **postgres**, including the new
   `test_spoofed_reclaim_prefix_without_typed_cause_is_not_rediscovered`
   (the +3 spine case) and
   `test_recovery_tick_does_not_park_behind_a_newer_attempt`.
3. **`RecoveredDispositionRefused` catch + stranded gate to RUNNING only** —
   production: `container.py:1436` and `:1509` catch
   `(RunIntegrityError, RecoveredDispositionRefused)`; `:1502` passes
   `allow_stranded_recovered=node_run.status is RunStatus.RUNNING`;
   `:1542` selects via `is_typed_recovered_attempt` only. The sole caller of
   `_replayable_terminal_attempt` (line 1499) passes the gate explicitly; the
   `True` default is never relied on. Refusal/parking table exercised by
   `test_recovered_attempt_disposition.py` (365 lines) +
   `test_pg_recovered_attempt_disposition.py` (5 passed, SQL-shape stand-in).
4. **Merge kept the typed path over develop's `#1863` prefix path** —
   `consumption.py:511` looks past `is_typed_recovered_attempt` only; the
   only remaining production references to `is_reclaimed_attempt` are its own
   definition + `__all__` row in `lifecycle.py` (no call sites).
5. **Stacked riders are coherent** — `attempt_executor.py` orphan path uses
   the dedicated `recover_leaseless_orphaned_attempt` writer
   (refuses terminal/leased/already-caused rows; lifecycle.py:529); the
   `timeout` marker registration in `pyproject.toml` matches its
   CONTRIBUTING.md documentation.

## CI-exact content gates (all green at 956ad29f1ce2)

| Gate | Invocation | Result |
|---|---|---|
| ruff lint | `uv run ruff check .` | All checks passed |
| ruff format | `uv run ruff format --check .` | 3605 files already formatted |
| mypy strict | `uv run mypy --strict packages/maistro-core/src` (quality.yml:2480) | Success: no issues in 845 files |
| vulture ledger | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (quality.yml:1529) | 1229 reviewed == 1229 findings (base 8f4806be → candidate 956ad29f1ce) |
| radon | `uv run python scripts/check-radon-baseline.py` | 126 == 126 C-or-worse blocks |
| promotion surface | `python3 scripts/check-promotion-surface.py` | ok |
| reachability | `uv run python scripts/check-reachability.py` | 1495 modules, 83 unreachable, rc 0 |
| merge markers / test dupes / backlog / layout | the four scripts | all ok |
| suite inventory | per-suite `check-suite-inventory.py` (driver logs) | ok ×4; core 18775 matches note |

## `test`-job legs (ci.yml env `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`)

- `packages/maistro-server/tests`: **660 passed, 10 skipped**
- `tests/ --ignore=tests/tools/registry`: **5887 passed, 140 skipped**
- turing + turing/backend + design + ext-harness + ext-sdk:
  **1472 passed, 1 skipped**
- canvas `test_canonical_execution.py` + durable-runs store test (PG set):
  **84 passed**

## Inventory note re-measurement (no edit needed)

The note `docs/testing/inventory-notes/m1-232-p5a-recovered-rediscovery.md`
claims +4 vs base 8f4806be. Re-verified independently: the three named files
collect **67** at head (`pytest --collect-only`); base def-counts are
3 / 2 / 42 = 63 collected (new rediscovery case is spine×3, parked-resume
+1 ⇒ +4). The note is accurate; editing it would be cosmetic.

## Environment note for the next worker

`uv sync --locked --extra dev` (the driver's sync) **uninstalls** the
editable `maistro-bootstrap` package, so a bare
`uv run mypy --strict packages/maistro-core/src` afterwards fails with
`import-not-found: maistro_bootstrap.cli`. CI syncs
`uv sync --locked --all-extras` before mypy (quality.yml:2466) — do the same
locally before trusting any mypy result.

## Residual handoff items (GitHub mutations, prohibited in-lane)

1. Push this branch tip to `cursor/m1-b-p5a-recovered-rediscovery-8551`
   (GitHub check runs at 956ad29f1ce were empty at capture — CI has not
   posted on this head).
2. `pr-base` red is the documented stacked state: `check-pr-base.py
   --base develop` → ok rc 0; `--base cursor/m1-b-p4b-…` → FAIL rc 1 with
   the ADR-095 message "must be retargeted to 'develop' before merge".
   Retarget the PR to develop before merge (driver action).
3. Pre-existing (not this branch): PytestWarning on
   `test_receipt_status_hydration_coerces_driver_strings_and_passes_legacy_through`
   exists at base 8f4806be (canvas, non-async fn with asyncio mark).

## Round at `58a76678efae` (develop tip `0d7bdd0a86` merged in; 2026-11-21)

Resolved the prior preflight block: the hosted PR #2427 head snapshot
(`58a76678efae`) equals the local HEAD exactly, so "not the review head" no
longer holds. The merge brought the true develop tip in
(`git merge-base --is-ancestor 0d7bdd0a86 HEAD` → yes; ratchet base is now
`0d7bdd0a86`). `quality/*.json` ledgers are byte-identical to
`origin/develop` (`git diff --numstat origin/develop -- quality/` empty) —
the merge lost no rows.

### Acceptance re-proof at `58a76678efae`

1. **Typed RECOVERED rediscovery / spoofed-prefix / newer-Attempt / RUNNING
   gate / Refused catch** — the five P5a suites
   (`test_interrupted_reclaim_rediscovery.py`,
   `test_recovered_attempt_disposition.py`,
   `test_reconciler_recovered_provenance.py`,
   `test_recover_leaseless_orphaned_attempt.py`,
   `test_pg_recovered_attempt_disposition.py`) with live Postgres
   (`pgvector/pgvector:pg18` on 127.0.0.1:15499, `alembic upgrade head`,
   `MAISTRO_TEST_PG_DSN` set): **68 passed, 0 skipped** (memory + sqlite +
   postgres legs all ran). Without the DSN the same five report 52 passed,
   16 env-skip. Production facts re-read at this head: `container.py:1436` /
   `:1509` catch `RecoveredDispositionRefused`; `:1502`
   `allow_stranded_recovered=node_run.status is RunStatus.RUNNING`;
   `:1542` sole selector `is_typed_recovered_attempt`; `consumption.py:511`
   typed look-past; **zero** production call sites of
   `is_reclaimed_attempt` (definition + `__all__` only, `lifecycle.py`).
2. **Driver batch re-run** (canvas canonical + durable store + the other
   recovery suites + spine conformance): **469 passed, 147 skipped** (all
   skips are the environment-gated postgres parametrizations covered by item
   1); `test_pg_recovered_attempt_disposition.py` + rsi research:
   **32 passed**.
3. **CI-exact gates**: ruff pair green (3608 files); `uv sync --locked
   --all-extras` + `maistro-evolve` editable install (quality.yml:2479-2484)
   then `mypy --strict packages/maistro-core/src` → **Success, 845 files**;
   vulture CI-exact `packages/*/src --min-confidence 60 --exclude
   '*/third_party/*'` → **1222 == 1222** (base `0d7bdd0a86` → candidate
   `58a76678efae`; count dropped from 1229 because the merged develop
   `LayerRecord` retirement removed identities); radon **124 == 124**;
   reachability 1495 modules / 82 unreachable, all dispositioned;
   reachability-dispositions ok; backlog ok; suite inventory ok ×4.
4. **`pr-base`**: `--base develop` → **ok rc 0** (develop tip is now an
   ancestor of HEAD, so a develop-targeted PR has no conflict);
   `--base cursor/m1-b-p4b-…` → FAIL rc 1, the ADR-095 documented stacked
   state.
5. **`test`-job legs at this head** (REQUIRE_AUTH=false MAISTRO_DRY_RUN=1):
   server **697 passed, 10 skipped**; turing + turing/backend + design +
   ext-harness + ext-sdk **1472 passed, 1 skipped**; root `tests/`
   **5891 passed, 140 skipped**. Frontend legs: `dump-hive-openapi.py` +
   `gen:api` → **no diff** on `types.gen.ts`/`openapi.json` (rc 0); hive
   frontend lint 0 errors + build ✓; canvas frontend `test:ci` **84
   passed**, lint 0 errors, build ✓.

### Residual (unchanged in nature, driver actions)

- GitHub PR #2427 still targets base
  `cursor/m1-b-p4b-reconciler-recovered-disposition-8551` (captured at
  `a531f5d7`) with `mergeable_state: dirty`; the conflict is against the
  stale stacked base only (this head contains develop tip; the stacked base
  predates it). Remedy is the documented ADR-095 retarget to develop before
  merge — a GitHub mutation, prohibited in-lane.
- No GitHub check runs had been posted on `58a76678efae` at capture; CI
  verdicts on the head remain a driver observation.

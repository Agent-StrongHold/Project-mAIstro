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

## Round at `51c0c70987` (verification round, 2026-11-21)

Third verification pass. HEAD adds only this evidence file over
`58a76678efae` (`git diff --stat 58a76678efae..HEAD` = 1 file, docs-only),
so all code-level evidence from the previous round transfers verbatim. Every
claim was nevertheless re-proved independently at this head:

1. **Five P5a suites with live Postgres** (`pgvector/pgvector:pg18` on
   127.0.0.1:15499, `alembic upgrade head`, `MAISTRO_TEST_PG_DSN`):
   **68 passed, 0 skipped** (memory + sqlite + postgres legs). Without the
   DSN the same five report 52 passed, 16 env-skip — the skips are exactly
   the postgres parametrizations, all covered by the live run.
2. **Remaining acceptance batch with PG** (canvas canonical, durable-runs
   store, reclaim characterization, parked-resume, spine conformance, rsi
   research): **564 passed**.
3. **Production facts re-read at this head**: `container.py:1436`/`:1509`
   catch `(RunIntegrityError, RecoveredDispositionRefused)`; `:1502`
   `allow_stranded_recovered=node_run.status is RunStatus.RUNNING`;
   `:1542` sole selector `is_typed_recovered_attempt`; `consumption.py:511`
   typed look-past; `is_reclaimed_attempt` has **zero** production call
   sites (definition `lifecycle.py:327` + `__all__` `:734` + a docstring
   comment only).
4. **CI-exact gates at this head**: vulture
   `packages/*/src --min-confidence 60 --exclude '*/third_party/*'` →
   **1222 == 1222** (base `0d7bdd0a86`); radon **124 == 124**; reachability
   rc 0 (82 unreachable, dispositioned); promotion surface ok; backlog ok;
   mypy strict → **Success, 845 files** (after CI's exact sync:
   `uv sync --locked --all-extras` + maistro-evolve editable,
   quality.yml:2479-2488); ruff pair + suite inventory ×4 green in the
   driver logs (check-1/2, check-5..8).
5. **`pr-base`**: `--base develop` → ok rc 0; `--base
   cursor/m1-b-p4b-…` → FAIL rc 1 with the ADR-095 message — the stacked
   state the PR body explicitly expects, retarget to develop before merge.
6. **Ledgers**: `git diff --numstat origin/develop -- quality/` empty
   (byte-identical); develop tip `0d7bdd0a86` is an ancestor of HEAD
   (`git merge-base --is-ancestor` → yes).
7. **Inventory note**: `m1-232-p5a-recovered-rediscovery.md` re-verified —
   its three files collect **67** (`pytest --collect-only`), matching the
   claimed 63→67 **+4**; `check-suite-inventory.py --suite
   packages/maistro-core/tests` → ok (18775). No note edit needed.

Residual (unchanged in nature, driver actions): push this tip
(`51c0c70987`, one docs commit ahead of hosted PR head `58a76678efae`) and
retarget PR #2427 to develop — both GitHub mutations, prohibited in-lane.

## Round at `0ee2bd41f7` (review head; 2026-11-21)

HEAD `0ee2bd41f7e4` is a merge of develop's `99d66477ad` (docker/login-action
+ integration-scope workflow bumps, #2435 family — `.github/` + `tests/ci/*.cjs`
only, zero `packages/` changes) into the previously validated `fd08199120`.
The hosted PR #2427 head snapshot now equals this HEAD exactly, resolving the
prior "Hosted PR snapshot incomplete or not the review head" preflight block.
No code changed under `packages/` between the old merge-base `0d7bdd0a86` and
the new one `99d66477ad` (`git diff --stat 0d7bdd0a86 99d66477ad -- packages/`
is empty), so all package-level evidence transfers; everything below was
re-run at this head anyway.

### Gates and suites at `0ee2bd41f7`

1. **Ledgers vs develop tip `527cff8437`**: vulture/radon/reachability/
   promotion-surface byte-identical (`git diff --numstat origin/develop --
   quality/` shows only `image-pins.json` 10/10); `image-pins.json` differs
   solely because develop's two newest dependabot commits (#2443 python
   3.15.2, #2444 playwright 1.65.1) postdate our merge-base — our tree
   carries the matching older pins and Dockerfiles (internally consistent,
   0 rows lost; structure 3/3 keys equal).
2. **CI-exact quality gates** (after `uv sync --locked --all-extras` +
   `uv pip install -e packages/maistro-evolve`): ruff check + format
   (3608 files) ok; vulture `packages/*/src --min-confidence 60 --exclude
   '*/third_party/*'` → **1222 == 1222** (base `99d66477ad` → candidate
   `0ee2bd41f7`); radon **124 == 124**; mypy `--strict packages/maistro-core/src`
   → **Success, 845 source files**; reachability rc 0 (1495 modules,
   82 unreachable, dispositioned); promotion-surface, backlog, merge-markers,
   test-duplicates, monorepo-layout, suite-inventory (core) all rc 0.
3. **Live-PG acceptance** (standalone `pgvector/pgvector:pg18` on
   127.0.0.1:15499, `alembic upgrade head`, plain `postgresql://` DSN — the
   runs-conftest `pg_pool` fixture feeds `MAISTRO_TEST_PG_DSN` to asyncpg
   directly, so the `+asyncpg://` scheme errors with
   `ClientConfigurationError: invalid DSN`; use `postgresql://`):
   - five P5a suites: **68 passed, 0 skipped** (memory + sqlite + postgres
     legs all ran);
   - acceptance batch (canvas canonical, durable-runs store, reclaim
     characterization, parked-resume, recovery events, evidence pack, spine
     conformance, rsi research): **580 passed**;
   - whole `packages/maistro-core/tests/runs`: **2015 passed, 4 skipped**
     (the 4 are backend-capability skips).
4. **`test`-job legs** (REQUIRE_AUTH=false MAISTRO_DRY_RUN=1): server
   **697 passed, 10 skipped**; turing + turing/backend + design +
   ext-harness + ext-sdk **1472 passed, 1 skipped**; root `tests/`
   **5891 passed, 140 skipped** — all identical to the `58a76678efae` round,
   as expected for a `.github/`-only merge.
5. **Production facts re-read at this head**: `container.py:1436`/`:1509`
   catch `(RunIntegrityError, RecoveredDispositionRefused)`; `:1502`
   `allow_stranded_recovered=node_run.status is RunStatus.RUNNING`; `:1542`
   sole selector `is_typed_recovered_attempt`; `consumption.py:511` typed
   look-past; `is_reclaimed_attempt` has zero production call sites
   (definition `lifecycle.py:327`, `__all__` `:734`, docstring comment
   `:310`).
6. **`pr-base`**: `--base develop` → ok rc 0; `--base
   cursor/m1-b-p4b-…` → FAIL rc 1 (ADR-095 message). `git merge-tree --write-tree
   HEAD origin/develop` at develop tip `527cff8437` → rc 0, **0 conflicts**:
   the PR's GitHub `dirty` state is only against the stale stacked cursor/
   base and disappears on the documented retarget to develop.
7. **Inventory note**: re-verified — the three files collect **67** at this
   head; the note's +4 claim stands; no edit needed.

Residual (driver actions, GitHub mutations prohibited in-lane): CI check
runs had not been posted on `0ee2bd41f7` at dispatch capture (verdicts are a
driver observation); retarget PR #2427 base to develop before merge.

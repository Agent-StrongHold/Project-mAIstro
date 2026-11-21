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

## Round at `9696a5a040` (verification round, 2026-11-21)

HEAD `9696a5a040` is a merge of develop's `884408b066` (#2460 legacy
Dashboard deletion, plus #2443/#2444 image bumps) into the previously
validated `2e33325ac3`. Unlike the `0ee2bd41f7` round, this delta **does**
touch `packages/` (hive-conductor backend + frontend) and four `quality/`
ledgers, so evidence was re-proved at this head instead of transferred.
Develop tip moved again to `971e536838` (#2462, one commit past our merge
point: a core test + docs only); HEAD deliberately stays at the hosted PR
head — merging again would re-break the head alignment prior rounds
established. `git diff --numstat origin/develop -- quality/` is **empty**
(merge lost no ledger rows).

### Verification evidence at `9696a5a040`

1. **Live-PG acceptance** (`pgvector/pgvector:pg18` on 127.0.0.1:15499,
   `DATABASE_URL=…` + `alembic upgrade head`, `MAISTRO_TEST_PG_DSN` plain
   `postgresql://`): five P5a suites (`test_interrupted_reclaim_rediscovery`,
   `test_recovered_attempt_disposition`,
   `test_reconciler_recovered_provenance`,
   `test_recover_leaseless_orphaned_attempt`,
   `test_pg_recovered_attempt_disposition`) → **68 passed, 0 skipped**;
   acceptance batch (canvas canonical, durable-runs store, reclaim
   characterization, parked-resume, recovery events, evidence pack, spine
   conformance, rsi research) → **580 passed**. Numbers identical to the
   `0ee2bd41f7` round, as expected (no P5a file in the delta).
2. **Production facts re-read at this head**: `container.py:1436`/`:1509`
   catch `(RunIntegrityError, RecoveredDispositionRefused)`; `:1502`
   `allow_stranded_recovered=node_run.status is RunStatus.RUNNING`; `:1542`
   sole selector `is_typed_recovered_attempt`; `consumption.py:511` typed
   look-past; `is_reclaimed_attempt` has zero production call sites
   (definition `lifecycle.py:327`, `__all__` `:734`, docstring `:310`).
3. **CI-exact gates**: driver logs check-1/2 (ruff pair, re-run: All checks
   passed / 3609 files); vulture `packages/*/src --min-confidence 60
   --exclude '*/third_party/*'` → **1222 == 1222** (base `884408b066` →
   candidate `9696a5a040`); radon **124 == 124**; mypy `--strict
   packages/maistro-core/src` → **Success, 845 files** (after CI's exact
   `uv sync --locked --all-extras` + `uv pip install -e
   packages/maistro-evolve`, quality.yml:2483-2488).
4. **Merge-affected ledger gates** (all four `quality/` files the merge
   touched): `check-image-pins.py` → 11 pinned images registered, rc 0;
   `check-workspace-retirement.py` → 89 entries match, rc 0;
   `check-shipped-surface-truth.py` → complete, rc 0;
   `check-frontend-typed-client.py` → 26 raw fetch + 96 hand-typed
   tolerated, none new, rc 0.
5. **Suite inventory (CI-exact, no args, ci.yml:744)** → **21 suites ok,
   35887 unique identities, rc 0** — covers the deleted
   `test_dashboard_layout_durability.py` baseline update and the new root
   `tests/test_playwright_harness_version_parity.py` (run separately:
   **3 passed**).
6. **`pr-base`**: `--base develop` → ok rc 0; `--base
   cursor/m1-b-p4b-reconciler-recovered-disposition-8551` → FAIL rc 1
   (ADR-095 policy message). The gate is a pure base-ref-name policy check
   (`check-pr-base.py:66-76`) — ancestry plays no part, so the one-commit
   develop lag is invisible to it.
7. **Bounded `test`-job risk**: vs develop tip `971e536838`, root `tests/`
   and `packages/maistro-design/` are byte-identical; backend delta is +5
   lines in `test_audit_pagination.py` (driver check-4: **32 passed**);
   server/turing/canvas/core src deltas are exactly the P5a/P4 files proven
   in items 1–3. Develop's own full CI ran green on the identical trees
   (check-runs at `9871dbc14350`: Coverage, Quality, SAST, e2e, pg17/pg18,
   wheel-imports all success).
8. **Inventory note**: `m1-232-p5a-recovered-rediscovery.md` re-verified —
   its three files collect **67** at this head (`pytest --collect-only`);
   the 63 → 67 **+4** claim stands; no edit needed.

Residual (driver actions, GitHub mutations prohibited in-lane): retarget PR
#2427 base to develop before merge (pr-base red is the documented stacked
state); no check-runs had been posted on `9696a5a040` at dispatch capture;
HEAD is one develop commit behind (`971e536838`, core test + docs) — rides
in on the next develop sync, no gate at this head expects it.

## Round at `e54207dca9` (verification round, 2026-11-21)

HEAD `e54207dca9` is a merge of develop tip `971e536838` (#2462) into the
previously validated `871ec75095`. The merge delta is exactly 4 files —
`CHANGELOG.md`, `docs/architecture/CONVERGENCE-MATRIX.md`, develop's own
inventory note `docs/testing/inventory-notes/2323-collaboration-park.md`, and
one new core test `packages/maistro-core/tests/test_collaboration_park_2323.py`
(+1, covered by develop's merged note) — zero `packages/*/src` changes, so the
P5a implementation is byte-identical to the `9696a5a040`-validated tree.
`git merge-base --is-ancestor 971e536838 HEAD` → yes; HEAD also contains the
hosted PR head, and `git merge-tree --write-tree HEAD origin/develop` → rc 0
(conflict-free on the documented develop retarget). Everything below was
executed at this head (job `15f4560518c34645a76cfb8c6e7c6ff8`).

### Acceptance re-proof at `e54207dca9`

1. **Five P5a suites with live Postgres** (fresh `public` schema,
   `DATABASE_URL` + `alembic upgrade head` → 068, `MAISTRO_TEST_PG_DSN` plain
   `postgresql://` on 127.0.0.1:15499, container `cr2427-verify-pg`,
   `pgvector/pgvector:pg18`): **68 passed, 0 skipped** — memory + sqlite +
   postgres legs all ran, matching every prior round.
2. **Acceptance batch with PG** (canvas canonical, durable-runs store, reclaim
   characterization, parked-resume, recovery events, evidence pack, spine
   conformance, rsi research): **580 passed**; only the pre-existing base
   canvas PytestWarning. Driver batch without PG (check-3): 501 passed,
   147 env-skips — the live runs above cover every skipped parametrization.
3. **Production facts re-read at this head**: `container.py:1436`/`:1509`
   catch `(RunIntegrityError, RecoveredDispositionRefused)`;
   `_replayable_terminal_attempt` is called with
   `allow_stranded_recovered=node_run.status is RunStatus.RUNNING`;
   `_stranded_recovered_attempt` selects solely via
   `is_typed_recovered_attempt(latest)` on the newest ordinal after refusing
   live leases; `consumption.py:511` typed look-past only;
   `is_reclaimed_attempt` has zero production call sites (definition
   `lifecycle.py:327`, `__all__` `:734`, docstring `:310`).
4. **CI-exact gates**: vulture `packages/*/src --min-confidence 60 --exclude
   '*/third_party/*'` → **1222 == 1222** (baseline shows base `971e536838ca`
   → candidate `e54207dca9a3`); radon **124 == 124**; mypy `--strict
   packages/maistro-core/src` → **Success, 845 source files** (after CI's
   exact sync `uv sync --locked --all-extras` + `uv pip install -e
   packages/maistro-evolve`); ruff check "All checks passed" + format
   "3610 files already formatted".
5. **Suite inventory (CI-exact, no args, ci.yml:744)**: **21 suites ok,
   35888 unique identities, rc 0** — the +1 vs the prior round's 35887 is
   develop's merged `test_collaboration_park_2323.py`, accounted by develop's
   own `2323-collaboration-park.md` note (+1); core suite 18775 → 18776
   matches. That merged test run standalone: **1 passed**. Backend parity
   delta vs develop tip remains `test_audit_pagination.py` +5
   (driver check-4: **32 passed**).
6. **`pr-base`**: `--base develop` → **ok rc 0**; `--base
   cursor/m1-b-p4b-reconciler-recovered-disposition-8551` → **FAIL rc 1**
   with the ADR-095 policy message ("must be retargeted to 'develop' before
   merge") — the documented stacked state; retarget is a driver GitHub action.
7. **Ledgers**: `git diff --numstat origin/develop -- quality/` empty —
   byte-identical, the merge lost no rows; `quality/` clean in `git status`.
8. **Inventory note**: the P5a note's three files collect **67** at this head
   (`pytest --collect-only`); the 63 → 67 **+4** claim stands; no edit needed.

Residual (driver actions, GitHub mutations prohibited in-lane): the dispatch
snapshot shows **0 check runs / 0 statuses posted on `e54207dca9`** — CI has
not yet reported on the hosted head (this was the prior "Hosted PR snapshot
incomplete" preflight block's substance; the head itself now matches exactly).
Retarget PR #2427 base to develop before merge.

## Round at `1667511e5a` (independent verifier round, 2026-11-21)

Prior round's claims were NOT assumed true; every acceptance criterion was
re-proven against reachable production behavior at this head. `1667511e5a`
was first proven docs-only over the validated review head `e54207dca9`
(`git diff --stat`: one file, `.cursor/context/issue-2427-validation-notes.md`,
+64 lines — zero src/test changes), so production behavior is byte-identical
to the validated tree.

1. **Five P5a suites vs live pg18**: fresh `public` schema (DROP/CREATE +
   `CREATE EXTENSION vector`), `DATABASE_URL` → `alembic upgrade head` →
   **068**, `MAISTRO_TEST_PG_DSN` on 127.0.0.1:15499 (`cr2427-verify-pg`,
   pgvector/pg18): **68 passed, 0 skipped** — postgres legs ran, matching the
   prior round exactly.
2. **Acceptance batch vs live PG** (driver check-3's exact 13-file list):
   **648 passed, 0 skipped** — reconciles exactly with driver check-3 without
   PG (501 passed + 147 env-skips = 648): every skipped parametrization ran
   live here.
3. **Production facts re-read at HEAD**: `container.py:1436`/`:1509` catch
   `(RunIntegrityError, RecoveredDispositionRefused)`; `:1502`
   `allow_stranded_recovered=node_run.status is RunStatus.RUNNING`;
   `_stranded_recovered_attempt` selects solely via
   `is_typed_recovered_attempt(latest)` on the newest ordinal after refusing
   live leases; `consumption.py:511` typed look-past;
   `is_reclaimed_attempt(` has zero production call sites (grep over
   `packages/*/src`: definition `lifecycle.py:327` only; sole test caller is
   the characterization suite). Named P5a behaviors exist as tests:
   `test_spoofed_reclaim_prefix_without_typed_cause_is_not_rediscovered`,
   `test_recovery_tick_does_not_park_behind_a_newer_attempt`,
   `test_rediscovery_parks_only_its_own_node` — all in the passing 68.
4. **CI-exact gates re-run at this head**: vulture `packages/*/src
   --min-confidence 60 --exclude '*/third_party/*'` (vulture-ratchet.yml:82)
   → **1222 == 1222** rc 0, baseline base `971e536838ca` → candidate
   `1667511e5a37`; radon `check-radon-baseline.py` with `RATCHET_BASE_REV=origin/develop`
   (quality.yml:844) → **124 == 124** rc 0; mypy CI's exact 7-package list
   (ci.yml:118, strict via pyproject) after `uv sync --locked --all-extras`
   → **Success: no issues found in 1022 source files** rc 0; suite inventory
   no-args (ci.yml:744) → **21 suites / 35888 identities** rc 0; ruff pair
   green (driver check-1/check-2 logs).
5. **`pr-base`** (ci.yml:79 exact form): hosted PR #2427's actual base is
   `cursor/m1-b-p4b-reconciler-recovered-disposition-8551`; reproduced both
   ways — `--base develop` → **ok rc 0**; the hosted cursor base → **FAIL rc 1**
   with ADR-095 "must be retargeted to 'develop' before merge" — the state the
   issue body itself documents as expected while stacked. `git merge-tree
   --write-tree HEAD origin/develop` → rc 0 (conflict-free on retarget).
6. **Ledgers**: `git diff --numstat origin/develop -- quality/` empty;
   `quality/` clean in `git status`.
7. **Inventory notes**: `m1-232-p5a-recovered-rediscovery.md` unchanged and
   re-measured — its three files collect **67** (`pytest --collect-only`),
   the 63 → 67 **+4** `inventory-delta` stands; this round edits no tests, so
   no new delta is owed.
8. **Canvas PytestWarning proven pre-existing on develop**: develop's copy of
   `test_canonical_execution.py` has the same sync function
   (`test_receipt_status_hydration_coerces_driver_strings_and_passes_legacy_through`)
   under `pytestmark = pytest.mark.asyncio` (develop lines 1034/23) — the
   warning is not introduced by this branch.

Residual (driver actions only): retarget PR #2427 base to develop before
merge; dispatch snapshot still shows 0 check-runs posted on the hosted head
(CI verdict pending, not locally reproducible). Nothing pushed; no GitHub
mutations.

## Round at `b80982bf2065` (independent verifier/writer round, 2026-11-21)

Dispatch head `b80982bf206516fad6a9d8e3f58e75ddecdb8ec6` = hosted PR #2427
head = local HEAD (three-way alignment confirmed from the dispatch snapshot's
`linked_pr_heads["2427"]` and `git rev-parse HEAD`). `b80982bf` is docs-only
over the validated `1667511e5a` (`git diff --stat`: one file, this notes
file, +62 lines — zero src/test changes), so production behavior is
byte-identical to the validated tree; everything below was nevertheless
re-executed at this head. Driver deterministic checks (this job's
check-0..8): sync rc 0, ruff check "All checks passed", ruff format "3610
files already formatted", 13-file acceptance batch **501 passed, 147
env-skips**, hive backend audit-pagination **32 passed**, per-suite suite
inventory ok ×4 (hive 4273 / canvas 633 / core 18776 / rsi 1797).

1. **Five P5a suites vs live pg18**: fresh `public` schema (DROP/CREATE +
   `CREATE EXTENSION vector`), `DATABASE_URL` → `alembic upgrade head` →
   **068**, `MAISTRO_TEST_PG_DSN` plain `postgresql://` on 127.0.0.1:15499
   (`cr2427-verify-pg`, pgvector/pg18): **68 passed, 0 skipped** — matches
   every prior round; the 16 env-skips of a DSN-less run all ran live.
2. **Driver's exact 13-file batch vs live PG**: **648 passed, 0 skipped** —
   reconciles exactly with driver check-3 (501 + 147 = 648); only warning is
   the canvas PytestWarning proven pre-existing on develop (verified again:
   `git show origin/develop:packages/maistro-canvas/tests/`
   `test_canonical_execution.py` has the same sync fn at :1034 under
   `pytestmark` :23).
3. **Production facts re-read at HEAD**: `container.py:1436`/`:1509` catch
   `(RunIntegrityError, RecoveredDispositionRefused)`; `:1502`
   `allow_stranded_recovered=node_run.status is RunStatus.RUNNING`;
   `_stranded_recovered_attempt` refuses live leases and selects solely via
   `is_typed_recovered_attempt(max(attempts, key=ordinal))` (`:1542`);
   `consumption.py:511` typed look-past; `grep -rn "is_reclaimed_attempt("
   packages/*/src` minus the definition → **no production call sites**.
   Named P5a tests present and in the passing 68:
   `test_spoofed_reclaim_prefix_without_typed_cause_is_not_rediscovered`
   (rediscovery.py:131), `test_recovery_tick_does_not_park_behind_a_newer_attempt`
   (:159), `test_rediscovery_parks_only_its_own_node` (:180).
4. **CI-exact gates re-run at this head** (after CI's `uv sync --locked
   --all-extras` + `uv pip install -e packages/maistro-evolve`):
   vulture `packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
   (vulture-ratchet.yml:82) → **1222 == 1222** rc 0 (base `971e536838ca` →
   candidate `b80982bf2065`); radon (quality.yml:845) → **124 == 124** rc 0;
   mypy ci.yml:117-127 exact 10-package list → **Success: no issues found in
   1127 source files** rc 0; suite inventory no-args (ci.yml:744) → **21
   suites / 35888 unique identities** rc 0.
5. **`pr-base`** (ci.yml:79 form): `--base develop` → **ok rc 0**; hosted
   base `cursor/m1-b-p4b-reconciler-recovered-disposition-8551` → **FAIL rc
   1** with the ADR-095 "must be retargeted to 'develop' before merge"
   message (`cursor/` is not in `.github/branch-protection.json` topic
   prefixes) — exactly the state the PR body documents as expected while
   stacked (`cursor/` branches are not accepted topic prefixes).
6. **Ledgers**: `git diff --numstat origin/develop -- quality/` → **empty**
   (byte-identical); `git status --short` clean; worktree left clean at the
   dispatch head.
7. **Inventory note re-measured, no edit owed**: the note's three files
   (`test_interrupted_reclaim_rediscovery.py` 18 +
   `test_interrupted_reclaim_characterization.py` 4 + `test_parked_run_resume.py`
   45) collect **67** (`pytest --collect-only`) — the documented 63 → 67
   **+4** `inventory-delta` stands; this round changes no tests, so no new
   delta is owed. (An initial measurement of 97 used the wrong trio —
   `test_recovered_attempt_disposition.py` is not one of the note's files.)

### NEW post-dispatch fact: origin/develop advanced past the dispatch base

`origin/develop` moved `971e536838` → `77f464050e` (2 commits: `efc13c18dc`
#2418 admitted-authority port; `77f464050e` #2419 **P3b** orphan
recover_orphaned_attempt writes CANCELLED+RECOVERED — a sibling M1-B2b
phase). The delta touches `packages/maistro-core/src` files this PR also
touches (`attempt_executor.py`, `execution_store.py`, `lifecycle.py`,
`pg_store.py`, `sqlite_store.py`, `store.py`, `_vulture_whitelist.py`, the
durable-runs store test): `git merge-tree --write-tree HEAD origin/develop`
→ **rc 1 — conflicts exist against the NEW develop tip** (the prior round's
conflict-free rc 0 was against `971e536838`, which IS an ancestor of HEAD;
`quality/` ledgers remain byte-identical even to the new tip — numstat
empty — because neither new commit touches them).

**Decision (recorded, not actioned):** do NOT merge develop in this round.
Prior round `9696a5a040` established that HEAD must stay at the hosted PR
head; the resolved preflight block ("Hosted PR snapshot incomplete or not
the review head") holds precisely because hosted head == dispatch head ==
local HEAD == `b80982bf`. Merging `77f464050e` now would re-break that
alignment and discard the driver's at-head check evidence. The develop sync
+ conflict resolution (both commits overlap the P5a recovery files, so it is
a substantive resolution, not a formality) belongs to the NEXT snapshot
round after the driver re-anchors the hosted head. Branch tip remains the
dispatch head; this round adds one docs commit on top.

Residual (driver actions only, GitHub mutations prohibited in-lane): (a)
push the tip and re-anchor the hosted PR head to include the new docs
commit; (b) after re-anchor, merge the new develop tip `77f464050e` and
resolve the recovery-file conflicts in place; (c) retarget PR #2427 base to
develop before merge (pr-base red is the documented stacked state); (d) CI
check-runs on `b80982bf` were 0/0 at dispatch capture — verdicts remain a
driver observation.

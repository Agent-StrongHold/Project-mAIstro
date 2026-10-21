# Repair #859 — `test` gate: canvas-frontend vite advisory (branch auto-859, head c630b87c2f9f)

Starting head `c630b87c2f9fc4b9eb4020e99ef57bed19d08935` (assigned), develop base
`ac1e2f9556f178fe2597927021d6218d78663101`. Worktree arrived clean; nothing from
the previous rounds was assumed — every claim below was re-derived in this tree.

## 0. What the prior round left wrong

The verify round `a20f90be` recorded MERGE-READY while CI was still queued. It was
not: `test` (check-run 118950389654) was already **red** on this exact head. CI
text was read as evidence, not as instruction:

`gh api repos/.../check-runs/118950389654/annotations` → 19 annotations, 17 of
them eslint `warning`s (pre-existing canvas/hive style warnings, unchanged by this
branch) and the two `##[error]` lines being pytest's
`PytestUnhandledThreadExceptionWarning` text, not failures. The failing step is
the last one, from the job log:

    2026-10-21T00:11:18 ##[group]Run npm audit --audit-level=high   # packages/maistro-canvas/frontend
    vite  8.0.0 - 8.1.5   Severity: high
    launch-editor: escapeCmdArgs() omits % escaping on Windows  GHSA-698v-4r3x-3vcv
    launch-editor: Editor CLI flag misinterpretation ...         GHSA-r825-w8mm-5pxw
    launch-editor: `fs.existsSync()` existence check bypassed ... GHSA-587h-7wmj-h5pm
    ##[error]Process completed with exit code 1.

Because GHA steps abort the job, every earlier step in `test` (server, both Turing
suites, design, ext-harness, ext-sdk, root `tests/`, both frontends, generated
types, hive backend) had already passed in that run.

## 1. Root cause is a stale lock, not the #859 change

`packages/maistro-canvas/frontend/package.json` still pinned `vite: ^8.0.10` and
`package-lock.json` resolved **8.1.5**, the last vulnerable release. The
advisories landed against a `launch-editor` sub-dependency after this branch's
last sync, so an *unchanged* tree turned red — the same shape as the pigeonhole
of the previous round's pillow/certifi fix.

## 2. Repair: mirror what `origin/develop` already ships

`git show origin/develop:packages/maistro-canvas/frontend/package.json` already
pins `vite: ^8.1.6` and its lock resolves 8.3.4. Copied by regeneration, not by
hand:

    packages/maistro-canvas/frontend$ npm install --package-lock-only  # → vite 8.3.4, "found 0 vulnerabilities"
    $ git diff --stat origin/develop -- package.json package-lock.json
    (empty)  # both files are now byte-identical to origin/develop

No new pin was invented and no advisory was suppressed.

## 3. Local evidence (CI's exact commands, CI's order)

| step | command | result |
| --- | --- | --- |
| audit (was red) | `npm audit --audit-level=high` | rc 0, `found 0 vulnerabilities` |
| lock consistency | `npm ci` | 287 packages, 0 vulnerabilities |
| canvas tests | `npm run test:ci` | 5 files / 79 tests passed |
| canvas lint | `npm run lint` | rc 0 (0 errors, 13 pre-existing warnings) |
| canvas build | `npm run build` | rc 0, `✓ built` |
| root suite | `pytest tests/ --ignore=tests/tools/registry` | 5397 passed, 138 skipped |
| server | `pytest packages/maistro-server/tests` | 591 passed |
| design / ext-harness / ext-sdk | per-suite | 575 / 273 / 147 passed |
| hive backend | `pytest packages/hive-conductor/backend/tests` | 3791 passed |
| cross-suite leakage | `pytest tests/ hive/backend/tests design/tests --timeout=60` | 9856 passed, 0 errors |
| inventory | `python scripts/check-suite-inventory.py` | ok, 21 suites, 32493 node IDs |
| duplicates | `python scripts/check-test-duplicates.py` | ok, 1639 files |

The two local runs that reported 3 failed / 4480 errors were a **local
environment artefact, not a code finding**: this box's `/tmp` tmpfs was at
100 % of its 1 Mi inodes (`df -i /tmp` → `IUsed 1048575`), so pytest's
`tmp_path` factory and `mkstemp` failed. Re-running the identical command with
`TMPDIR` on the root filesystem produced the clean 9856-passed result above.
`/tmp` was left untouched — other lanes' artefacts live there.

## 4. Deliberately not done this round

`origin/develop` is 8 commits ahead (131 files) — including gate definitions,
`quality/vulture-baseline.json` (two `personas/store.py::get_for_workspace` rows
this branch still banks and develop no longer needs), `uv.lock`, and
`deploy/scripts/verify-restore.sh`. That is a **merge-time** integration risk,
not the cause of the named gate failure; a sync is proposed as its own round so
this repair stays reviewable as one audit fix. See the round's final report.

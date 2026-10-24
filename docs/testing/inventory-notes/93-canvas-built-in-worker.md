---
inventory-delta:
  packages/maistro-canvas/tests: +28
---
# #93 Built-in Canvas worker service and runner concurrency

Ships the deployment shape for the built-in Canvas worker (SPEC-203, M3-B3):
a `maistro-canvas-worker` console-script service configured entirely through
the environment, plus bounded concurrency for `CanvasJobRunner` so one
deployment can progress independent ready jobs in parallel.

Test deltas:

- Added `packages/maistro-canvas/tests/test_worker_service.py` (14 tests):
  environment parsing fails loudly per-variable; `module:attr` adapter
  targets resolve as instance/class/zero-arg-factory/async-factory and
  refuse malformed targets; the migration preflight refuses an unmigrated
  database naming `alembic upgrade head` (and passes when every required
  spine + canvas table exists); the production composition path provably
  builds through `build_canvas_runtime` with the resolved adapters, scope,
  `prime=False` consumer wiring, and configured concurrency — including the
  SQLAlchemy engine receiving the `postgresql+asyncpg://`-qualified URL while
  the asyncpg pool keeps the plain one (`sqlalchemy_asyncpg_url`; found live:
  the first real start against a migrated database crashed in engine creation
  on the documented `postgresql://` DSN form); `run_worker` starts and
  gracefully stops the composed runner, closes the pool and engine, and exits
  1 when the runner dies mid-flight; `main` maps config errors to exit 2 and
  crashes to exit 1.
- Added `packages/maistro-canvas/tests/test_runner_concurrency.py` (8 tests):
  two ready jobs execute overlapping inside one runner (behavioral barrier,
  not task-structure assertions); `stop()` halts claiming and drains the
  claimed job to DONE; cancelling `start()` reaches the in-flight provider
  call and leaves the receipt leased for the reaper (no fake terminal
  status); extra concurrency slots never double-claim a single job;
  the running loop's reap sweep reclaims a dead worker's expired lease and
  re-executes it under its next attempt; a tick task that raises is
  retrieved and logged without killing the loop; a cancelled tick is
  retrieved silently; non-positive concurrency is rejected.

No existing tests were removed. The `start()` restructure (concurrent tick
tasks with drain-on-stop and cancellation parity with the serial design)
is covered by the pre-existing runner, shutdown-bound, canonical-executor,
migration-parity, and scope-conformance suites, which all still pass.

Postgres-backed legs remain with the existing PG-gated suites
(`test_store_scope_conformance.py`, `test_migration_parity.py`); this note's
tests deliberately prove the service wiring with in-memory substitutes, not
the queue semantics.

## Repair round: reconcile honored a live lease for driver-hydrated receipts

Live re-verification of the two-worker claim race (real pgvector Postgres,
migrated spine, two `maistro-canvas-worker` processes) falsified the
"each claimed exactly once" evidence: reproducibly (1-in-5 runs), worker B's
`reconcile_admissions` requeued worker A's *live-leased* RUNNING receipt back
to PENDING while A was mid-execution (Postgres statement log: `UPDATE ... SET
status='pending'` written with A's unexpired `lease_expires_at` and fences
`expected_status='running', expected_attempts='1'`), so `claim_next_pending`
handed the same physical job to B — attempt 2, provider dispatched twice.

Root cause: `PgCanvasStore._coerce_job` hydrated the status column as a plain
`str`, and `_project_receipt`'s live-lease guard tested `job.status is
JobStatus.RUNNING`. Identity comparison against a `StrEnum` member is always
false for a plain string, so the guard silently never fired on the
PostgreSQL path (the #1531 regression tests pass because in-memory doubles
hydrate real enum members). Fixed twice over:

- `store._coerce_job` now hydrates through `JobStatus(...)`
  (`_coerce_job_status`, tolerant of unrecognized legacy values), so every
  consumer sees the shape the in-memory stores produce;
- `_project_receipt` compares with `==` (exact for `StrEnum`/`str`) instead
  of `is` for the receipt-status tests, so the invariant no longer depends
  on which store hydrated the record.

Test deltas (this round):

- Added to `packages/maistro-canvas/tests/test_canonical_execution.py`
  (+2 tests): `test_recovery_leaves_a_string_status_live_leased_receipt_alone`
  pins the exact production shape (receipt whose `status` is the plain string
  `'running'` with a live 300s lease is left alone — no requeue, no write);
  `test_recovery_requeues_a_string_status_receipt_whose_lease_expired` proves
  the equality fix did not become a blanket "never touch RUNNING": an expired
  lease under a plain-string status is still requeued.

After the fix, 8/8 live two-worker races (2 jobs, 2 workers, fast polls)
claim exactly once each (attempts=1 everywhere); the kill -9 recovery leg
re-proved one Run with attempt 1 `cancelled` and attempt 2 `completed`.

## Repair round: pin the status-hydration hinge directly (diff-coverage gap)

Re-running CI's exact diff-coverage gate
(`scripts/check-diff-coverage.py coverage.xml --base <develop>`) against the
no-services canvas producer failed: `store.py` measured 60% of its 5 changed
lines (floor 90%) — lines 128-129, the `except ValueError` legacy-value
fallback of `_coerce_job_status`, are reachable only through a live driver
row, and no test called the helper directly. The original lane had no direct
coverage for it either; the prior round's evidence never ran this gate.

Test deltas (this round):

- Added to `packages/maistro-canvas/tests/test_canonical_execution.py`
  (+1 test): `test_receipt_status_hydration_coerces_driver_strings_and_passes_legacy_through`
  pins both branches of the hydration hinge — a driver-shaped plain string
  hydrates to the `JobStatus` member (through `_coerce_job`, the real row
  coercion path), and an unrecognized legacy value passes through as a plain
  string instead of crashing a read path.

## Repair round: reject adapter targets the executor cannot call

`resolve_target` accepts whatever a `module:attr` target returns, including a
factory's `None`. The worker's executor awaits `image_client.generate` /
`.refine`, calls `model_registry.is_registered` / `.get_default_draft`, and
awaits `warden.scan_prompt`; an adapter missing one of those composed cleanly
and failed only inside a claimed job — spending that job's retry budget and
terminalizing its canonical Run as failed. `compose_runtime` now validates
every resolved adapter and raises `WorkerConfigError` at startup instead.

Test deltas (this round):

- Added to `packages/maistro-canvas/tests/test_worker_service.py` (+1 test):
  `test_compose_runtime_rejects_adapters_the_executor_cannot_call` drives
  `compose_runtime` with a target that resolves to an object missing `refine`,
  a factory that resolves to `None`, and a warden target missing
  `scan_prompt`, asserting each is a startup `WorkerConfigError` rather than a
  first-claim crash.

(The prior round's hydration test above was collected but not reflected in
this note's `inventory-delta`; the front matter now records both it and this
round's guard test, `+25` -> `+27`.)

## Salvage round: supply-chain gate re-verification + DSN-qualification pin

Re-verified the `Supply chain (pip-audit)` gate at the branch head with CI's
exact sequence (`uv sync --locked --all-extras`; `uv pip install pip-audit`;
`uv pip freeze --exclude-editable`; `uv run pip-audit --strict --format=json`;
`scripts/pip_audit_gate.py`): exit 0, one known advisory (`ecdsa`,
PYSEC-2026-1325) triaged in the allowlist. The three advisories the prior
round cleared were reproduced against the pre-fix versions: `fastmcp==4.0.11`
carries GHSA-7xgj-8392-5q4r and GHSA-vqqp-x5qm-5qp4 (fix >= 4.1.2) and
`setuptools==84.0.0` carries GHSA-xmj3-9gf7-h52w (fix >= 84.1.0); the locked
`fastmcp==4.1.3` / `setuptools==84.2.1` carry none. `uv lock --check` and the
offline direct-dependency ratchet (`pip_audit_gate.audit_direct_dependencies`)
both pass.

Test deltas (this round):

- Added to `packages/maistro-canvas/tests/test_worker_service.py` (+1 test):
  `test_sqlalchemy_asyncpg_url_qualifies_bare_postgres_and_passes_through_qualified`
  pins the DSN driver-qualification contract end to end — bare
  `postgresql://` and `postgres://` are rewritten to `postgresql+asyncpg://`,
  already-qualified URLs (`postgresql+asyncpg://`, `postgresql+psycopg://`,
  `sqlite+aiosqlite://`) pass through, and an unrecognized scheme is passed
  through rather than rewritten to a driver the service does not ship. This is
  the live-found engine-creation crash (`create_async_engine` receiving the
  bare DSN); only the bare-postgres rewrite was asserted before, through
  `test_compose_runtime_builds_the_canonical_seam`.

Front matter `+27` -> `+28`.

## Repair round: radon ratchet — decompress the two new C blocks (no test delta)

The merge queue's radon ratchet flagged two new C-grade blocks introduced by
this lane and never re-checked after the last code commit:
`CanvasJobRunner.start` (runner.py, C 13) and `run_worker`
(worker_service.py, C 11). A grant cannot authorize them in the same merge
(`ratchet_provenance.load_authorizations` reads
`quality/ratchet-authorizations.json` from the merge base), so the repair is
the behavior-preserving decomposition the blocks were missing:

- `start()` delegates its four per-round concerns — `_drain_one_round`
  (post-stop drain), `_retire_finished`, `_fill_free_slots`,
  `_reap_periodically` (returns the new reap counter) — and the
  `CancelledError` path delegates to `_cancel_in_flight`. The in-flight set
  is mutated in place (`difference_update`); the former single-body loop's
  `-=` rebind only worked because everything shared one local frame.
- `run_worker()` delegates the bounded runner shutdown to
  `_shutdown_runner_task`, which returns the exit-code contribution:
  graceful stop, deadline cancel, abandoned-on-suppressed-cancellation
  (done-callback, never re-awaited), crashed runner => exit 1.

No test added or removed: the pre-existing suites already pin every extracted
path (`test_stop_drains_claimed_jobs_before_start_returns`,
`test_cancelled_start_cancels_in_flight_execution`,
`test_start_loop_reaps_expired_leases_while_running`, the three
`test_worker_service.run_worker` shutdown tests), which is the point — the
decomposition changed structure, not behavior. Evidence this round: radon
127 -> 127 reviewed blocks (exit 0); canvas suite 581 passed; ruff check/
format clean; CI's exact multi-package `uv run mypy` invocation clean (1103
files); diff-coverage gate over the canvas + scripts producers at the develop
base passes (90% lines / 80% branches, runner.py and worker_service.py
included); vulture, reachability, reachability-dispositions, promotion
surface, convergence-matrix, suite inventory, backlog consistency,
interrogate, `uv lock --check`, and the Supply chain (pip-audit) gate with
CI's exact sequence all exit 0. The one root-suite failure observed while
collecting the scripts producer
(`test_every_quality_json_state_surface_is_classified_once`) was reproduced
as environmental, not branch-caused: the gitignored runtime artifact
`quality/ac-state.json` (written by `check-ac-state.py --run-tests` in this
worktree) is the only unclassified surface, and the test passes with it
moved aside.

## CI-repair round at af81bcd0 (merge-queue evaluation, 2026-10-24)

The hosted run failed two required checks; neither was caused by the worker
implementation, and both are repaired without touching Python source (so the
`inventory-delta` above is unchanged):

1. **Container scan + SBOM + cosign** — the Trivy step over
   `maistro-engine-research:pr-2266` exited 1 on pypdf 6.21.1
   (CVE-2026-115572/115580/115585, HIGH, all fixed in 6.21.2). pypdf reaches
   only the research image (maistro-server `--extra browser` → browser_use);
   the hive-conductor and `--extra image` exports do not carry it. Repair:
   `uv lock --upgrade-package pypdf` (6.21.1 -> 6.21.2, lock-only). Proof:
   the image was rebuilt locally from this lock and scanned with CI's exact
   invocation (`trivy image --severity HIGH,CRITICAL --exit-code 1
   --ignore-unfixed --ignorefile .trivyignore.yaml`, trivy 0.73.0): exit 0,
   0 vulnerabilities. The Supply chain (pip-audit) gate was re-run over the
   refreshed dev freeze with CI's gate script: OK (1 known, triaged).
2. **test** — the `npm audit --audit-level=high` step over
   `packages/maistro-canvas/frontend` exited 1 on advisory drift (3 HIGH:
   body-parser via express, undici via jsdom, zod via
   eslint-plugin-react-hooks; 3 moderate), all fixed within existing
   semver ranges. Repair: `npm audit fix` in that frontend —
   `package-lock.json` only, `package.json` untouched. Proof: fresh
   `npm ci` then audit exits 0 (0 vulnerabilities), and `npm run lint`
   (13 warnings = the existing budget), `npm run build`, and
   `npm run test:ci` (79 tests) all pass. The `RuntimeError: Event loop is
   closed` lines in that job's log are non-fatal
   `PytestUnhandledThreadExceptionWarning` annotations from aiosqlite in the
   untouched maistro-server suite, not step failures; the job's only failed
   step is the audit. The hive-conductor frontend reports one HIGH (zod) to
   `npm audit` but is gated by no step (`npm ci` exits 0; its image-level
   Trivy scan passed) and is left untouched here.

## CI-repair round at 25a3a85828cf (merge-queue evaluation, 2026-10-24 09:30Z)

The follow-up hosted run still failed **Container scan + SBOM + cosign**, and
the failed step was *not* npm audit (the npm lines in the log tail belong to
the succeeded hive-conductor frontend build stage): job 120834608591's only
failure is step 15, **Trivy scan maistro-rsi-runner (HIGH/CRITICAL only)**;
steps 12–14 (the other three image scans) passed at this head. No code or
lock repair is warranted: the failure does not reproduce on a faithful
rebuild and the tree is provably identical to a clean-scanning one.

Evidence this round (no test delta; the front-matter stays +28):

- Byte-identity: `git diff 73fd7bf3e9c HEAD -- uv.lock Dockerfile.rsi-runner
  .trivyignore.yaml pyproject.toml` is empty against the pr-2264 tree whose
  rsi-runner image (built 10:25Z) scans clean.
- Reproduction: `maistro-rsi-runner:pr-93-round2` rebuilt at this exact head
  with CI's build shape (`buildx-build-retry.sh`, `--no-cache-filter
  runtime-apt`) and scanned with CI's exact invocation (trivy 0.73.0,
  `--severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed --ignorefile
  .trivyignore.yaml`): **exit 0**, 0 HIGH/CRITICAL.
- Grype cross-check (`--fail-on high --only-fixed`) on the rebuilt image:
  exit 0 (Medium/Low findings only, none gated).
- The trivy DB local re-download confirms `updated_at 2026-10-24T01:18Z` was
  already latest at the 09:30Z CI scan, so the failure is not DB drift; the
  moving part is the Debian apt mirror state between CI's 09:13Z
  `apt-get upgrade` and the 10:25Z/10:50Z rebuilds (the same mechanism the
  Dockerfile's `--no-cache-filter runtime-apt` comment documents).
- Frontend license-surface steps re-proven locally: `npm ci && npm run build`
  in both `packages/hive-conductor/frontend` and
  `packages/maistro-canvas/frontend` exit 0; canvas `npm audit
  --audit-level=high` exits 0 (0 vulnerabilities).
- Merge-queue-adjacent gates re-run at this head with CI argv: vulture
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` exit 0 (1302 == 1302 reviewed, 0 unclassified, base
  4de7e906d9dc — nothing genuinely dead, nothing to amend);
  `check-reachability.py` exit 0 (1460 modules); dispositions exit 0 (47
  groups); radon exit 0 (127 == 127); full canvas suite 581 passed / 75
  skipped; suite inventory 636 == recorded (driver check-4). CI's mypy gate
  (`--strict packages/maistro-core/src`) exit 0 after `uv sync --locked
  --all-extras` (the `--extra dev` driver env missed `maistro_bootstrap`, a
  local-env artifact).
- Residual, documented: container-job steps 16–22 (grype over the other three
  images, SBOM/license inventory, image-lock reconciliation) were skipped on
  the hosted run after step 15 failed and are not fully re-proven here;
  steps 12–14 passed on the hosted run at this head and the rebuilt
  rsi-runner passes both its scanners locally, so a hosted re-run is the
  expected green path.

## CI-repair round at 62220a55e9c0 (hosted run 40088232144, 2026-10-24 11:01Z)

The "expected green path" above did not hold: the next hosted run failed the
same step (**Trivy scan maistro-rsi-runner**) with the npm audit log lines in
the step tail again belonging to a succeeded hive-conductor frontend stage
(verified via `gh run view --json` — that job's only failing step is the
rsi-runner trivy scan). The scan's one finding: `libbrotli1 1.1.0-2+b7`
(CVE-2026-111497, HIGH, DSA-6582-1, fixed in 1.1.0-2+deb13u1).

This round the root cause was **proven, and it is not mirror lag** — the
prior round's diagnosis is superseded:

- The same runs' build logs show the re-executed `runtime-apt` stage
  **installing 1.1.0-2+deb13u1** (`Get:54 ... libbrotli1 amd64
  1.1.0-2+deb13u1`, runs 40088232144 at 11:10Z and 40091186336 at 11:55Z),
  yet both scans report the pre-DSA **1.1.0-2+b7** as installed. The loaded
  `maistro-rsi-runner:pr-NNNN` tag was not assembled from the freshly
  executed stage.
- Mechanism: buildx cache keys are computed **pre-execution** (instruction
  string + parent key chain), never from a RUN's fresh bytes. `--no-cache-filter
  runtime-apt` (#795) forces the stage to re-execute but cannot propagate:
  downstream stage keys still match pre-advisory cache entries, and those
  restored layer chains / mode=max cached manifests carry the old OS layer
  into the exported image. The 09:13Z run (40081082641) shows the apt stage
  fully CACHED (pre-DSA chain origin); the auto-373 run independently shows
  the same build-vs-scan contradiction. This failure class already hit the
  bookworm bases once — the #1152 pin-note documents the identical remedy.
- Repair (repo doctrine, same as #1152): bump the digest-pinned
  `python:3.12-slim` base `a6e34c598…` (recorded 2026-10-19) → `a0f57064cbd…`
  (current index digest, still Python 3.12.15, post-DSA OS serialization) so
  the key chain changes from the FROM down and the rebuilt image assembles
  the freshly executed layers. References updated together per the pins
  contract: `Dockerfile.rsi-runner`, `Dockerfile.research` (×2),
  `packages/hive-conductor/tests/Dockerfile`,
  `deploy/sbx/template/Dockerfile.tests`, `quality/image-pins.json`.
  No `.trivyignore.yaml` entry: the fix is real and published, so suppressing
  it would ship a known-fixable HIGH in a containment-boundary image.

Local proof at this head (no Python/test changes; front-matter stays +28):

- Full `Dockerfile.rsi-runner` build from the new digest with CI's shape
  (`--no-cache-filter runtime-apt`): final image
  `docker run dpkg -l libbrotli1` = **1.1.0-2+deb13u1**; trivy 0.73.0 with
  CI's exact invocation (`--severity HIGH,CRITICAL --exit-code 1
  --ignore-unfixed --ignorefile .trivyignore.yaml`): **exit 0**, 0 findings
  (debian 13.7, pkg_num=168 — same analyzer path as the hosted scan).
- `Dockerfile.research` `production-apt` stage rebuilt from the new digest
  and scanned with the same invocation: **exit 0**, 0 findings.
- hive e2e test image builds via its real CI invocation
  (`docker compose -f docker-compose.test.yml --profile test build
  api-tests`): exit 0.
- `check-image-pins.py`: 8 pins across 10 Dockerfiles, all registered; zero
  remaining references to the old digest.
- Gates unchanged by this round re-run: ruff check / format clean (3487
  files), vulture ledger with CI argv exit 0 (1302 == 1302, base
  4de7e906d9dc, nothing to amend), full canvas suite 581 passed / 75
  skipped, suite inventory matches the recorded baseline (21 suites).

## Develop-sync round: re-validation at the 5ecfab63e merge head

Develop advanced (Workspace Home shell #1048, `maistro portability` CLI #34)
and the branch was synced by merging `5ecfab63e040` into `auto-93`, producing
`e8109594ac25`. The only files resolved against both parents are
`docs/architecture/CONVERGENCE-MATRIX.md` and
`quality/reachability-dispositions.json`; both resolutions were verified
row-by-row rather than trusted:

- `reachability-dispositions.json`: develop's removal of the superseded
  `portability` CONNECT group (its modules now ship a real CLI entry point,
  so they are reachable and out of the unreachable ledger) combined with this
  branch's rewritten `canvas-legacy-layerrecord` / `canvas-job-runner`
  rationales — 46 groups, covering 149 unreachable modules.
- The per-identity ledgers that a quiet merge can silently drain
  (`vulture-baseline.json`, `reachability-baseline.json`) came through
  byte-identical to the parent that legitimately owns each side: no #93 rows
  were dropped (the branch added none), and develop's portability row
  removals landed.
- `quality/image-pins.json` and `quality/direct-dependency-exceptions.json`
  are exactly this branch's versions (develop touched neither); the merged
  CONVERGENCE-MATRIX carries both develop's portability rows and this
  branch's `maistro-canvas-worker` rows.
- `scripts/check-merge-markers.py`: no conflict markers in tracked files.

Full gate battery re-executed at `e8109594ac25` (no code changes this round,
so the front-matter delta stays +28):

- `uv run ruff check .` / `uv run ruff format --check .`: clean (3496 files).
- `uv run mypy` over the ten CI-listed `packages/*/src` trees: no issues in
  1105 source files.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI argv): 1297 reviewed == 1297 findings,
  no unbanked identities, nothing to amend.
- `scripts/check-reachability.py` (RATCHET_BASE_REV=5ecfab63e040): 149
  unreachable of 1463 modules, no expansion;
  `scripts/check-reachability-dispositions.py`: 46 groups cover all 149.
- `scripts/check-ratchet-provenance.py` (all nine ratchets against the
  develop base) and `scripts/check-shipped-surface-truth.py`: OK.
- `uv run pytest packages/maistro-canvas/tests -q`: 581 passed, 75 skipped
  (PG-gated legs); `tests/test_check_image_lock_reconciliation.py`: 69
  passed.
- Suite inventory reconciles for every touched suite:
  `packages/maistro-canvas/tests` 636, `tests/` 5916,
  `packages/maistro-core/tests` and `packages/hive-conductor/tests/e2e`
  (develop-side additions) all match baseline + folded deltas.
- Production-shape probe of the shipped entry point at this head:
  `uv run maistro-canvas-worker` with no environment exits 2 with
  `canvas_worker_config_error: MAISTRO_CANVAS_PG_DSN is required...` — the
  documented fail-visible startup contract.

The regression guard added in the earlier repair round
(`test_recovery_leaves_a_string_status_live_leased_receipt_alone` and its
expired-lease companion) still passes against the merged
`store._coerce_job_status` hydration and the `==`-based live-lease guard in
`canonical_execution._project_receipt`. Acceptance remains as recorded:
the product-level E2E under #773/#95 is still pending and KNOWN-GAPS.md
keeps the Canvas-runner entry open for exactly that reason.

## Repair round: second develop sync (`ffc27cc43`, Biscuit ADR) — re-validation at `e854c3efa6ea`

Merge `e854c3efa6ea` folded develop `ffc27cc43` into the branch; against the
prior head `3a080aa11` it is doc-only (11 added files: the Biscuit ADR,
ADR-INDEX row, REPAIR-NOTES-1838 records, and the L1838 beartype-split
inventory note) — no code, test, or ledger file changed, so no ledger merge
audit is needed this round. The gate battery was nevertheless re-executed at
the merged head:

- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI argv): 1297 reviewed == 1297 findings
  against base `ffc27cc43fb8`; nothing unbanked, nothing to amend.
- `uv run ruff check .` and `uv run ruff format --check .`: clean.
- `scripts/check-suite-inventory.py`: 21/21 suites match the recorded
  inventory (canvas 636, `tests/` 5916), 0 duplicate identities.
- `scripts/check-reachability.py`: 149 unreachable of 1463 modules, no
  expansion; `scripts/check-reachability-dispositions.py`: 46 groups cover
  all 149 (128 CONNECT, 20 LIBRARY, 1 RETIRE).
- `uv run pytest packages/maistro-canvas/tests -q`: 581 passed, 75 skipped
  (PG-gated legs); `tests/test_check_image_lock_reconciliation.py`: 69
  passed; the three acceptance-bearing suites
  (`test_worker_service.py`, `test_runner_concurrency.py`,
  `test_canonical_execution.py`) pass as a focused run: 71 passed.
- Production-shape probe re-run at this head: `uv run maistro-canvas-worker`
  with no environment exits 2 with `canvas_worker_config_error:
  MAISTRO_CANVAS_PG_DSN is required...`.

Front-matter delta unchanged (+28: no tests added or removed this round).
Acceptance status is unchanged from the round above; the GH006 merge-queue
block is queue-side, not a tree defect.

## Develop-sync round: re-validation at the `db4d3eb091fe` merge head (`481733195`)

Develop advanced again (M1 #35: `dag_run_store` rebuilt as a reconciled
display projection under the shared #1036 terminality contract, with 27 new
projection authority/lifecycle tests in hive-conductor) and the branch was
synced by merging `db4d3eb091fe` into `auto-93`, producing `4817331952`.
One file conflicted: `docs/architecture/CONVERGENCE-MATRIX.md`, resolved by
keeping both sides where they touch different cells — develop's #35
`dag_run_store` projection wording in the Agent Conductor rows, this
branch's `maistro-canvas-worker` owner cell and the SPEC-203 queue note in
the Canvas rows. `scripts/check-convergence-matrix.py` passes on the
resolution (52 subsystems, 1463 modules, 149 unreachable).

Ledger merge audit (per the `quality/*.json` clean-merge row-drain hazard):
against the merge base `ffc27cc43`, develop changed none of the
`quality/*.json` ledgers, so every merged ledger is byte-identical to the
branch parent (`vulture-baseline`, `reachability-baseline`, `radon-baseline`;
verified by blob hash) and to the branch's legitimate versions of
`image-pins`, `direct-dependency-exceptions` and
`reachability-dispositions`. The branch-side removal of the
`packages/maistro-canvas/pyproject.toml` asyncpg direct-dependency exception
remains truthful after the merge: `worker_service.py` now imports asyncpg
directly (driver pool), so the "declared but never imported" exception no
longer describes reality. Nothing to amend; no grant touched.

Gate battery re-executed at `4817331952` against the new base `db4d3eb091fe`
(no Python changes on this branch side; front-matter delta stays +28):

- `uv run ruff check .` / `uv run ruff format --check .`: clean (3498 files).
- CI's exact `uv run mypy` over the ten `packages/*/src` trees: no issues in
  1105 source files.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI argv): 1297 reviewed == 1297 findings,
  base `db4d3eb091fe`; nothing unbanked, nothing to amend.
- `scripts/check-reachability.py` (RATCHET_BASE_REV=db4d3eb091fe): 149
  unreachable of 1463 modules, no expansion; dispositions: 46 groups cover
  all 149 (128 CONNECT, 20 LIBRARY, 1 RETIRE).
- `scripts/check-ratchet-provenance.py` (RATCHET_BASE_REV=db4d3eb091fe):
  OK, 54 quality-JSON consumers with provenance.
- `scripts/check-suite-inventory.py`: 21/21 suites match (34365 unique
  identities); `scripts/check-backlog-consistency.py`: OK.
- `scripts/check-merge-markers.py`: clean; `check-shipped-surface-truth.py`:
  complete.
- `uv run pytest packages/maistro-canvas/tests -q`: 581 passed, 75 skipped;
  focused acceptance suites (`test_worker_service.py`,
  `test_runner_concurrency.py`, `test_canonical_execution.py`): 71 passed;
  `tests/test_check_image_lock_reconciliation.py`: 69 passed.
- Production-shape probe re-run at this head: `uv run maistro-canvas-worker`
  with no environment exits 2 with `canvas_worker_config_error:
  MAISTRO_CANVAS_PG_DSN is required...` (true exit code captured without a
  pipe this time).

The #35 hive-conductor projection work does not touch the Canvas worker,
its runner, or the canonical-execution seam; the canvas suite results are
identical to the prior rounds (581/75, 71 focused). Acceptance status is
unchanged: the product-level E2E under #773/#95 is still pending and
KNOWN-GAPS.md keeps the Canvas-runner entry open for exactly that reason.

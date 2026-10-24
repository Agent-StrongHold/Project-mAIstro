---
inventory-delta:
  packages/hive-conductor/backend/tests: +13
  packages/hive-conductor/tests/e2e: +5
---
# 290-scheduler-timezone-image

## What moved and why

`packages/hive-conductor/backend/tests/test_scheduler_timezone_health.py`
(+13) pins the health-surface half of #290: the scheduler and its timezone
database become visible signals instead of silent assumptions. The lifespan
swallows `start_scheduler` failure by design, so a zone-less image used to
serve `200 OK` on every probe while scheduling was quietly dead — every
schedule, including a `UTC` one, resolves through `zoneinfo.ZoneInfo`, which
raises for *every* key when the process has no tz database. The new tests
cover: `scheduler_status()`'s never-started / live-loop / crashed-loop /
start-failure-recorded states; the `_timezone_database_state` probe (available
with a recorded source, unavailable when every key fails, unavailable when
`PYTHONTZPATH` names a missing path, and unavailable when a database answers
`UTC` but lost its regions — a lucky single key must not pass); `/health`
flipping `degraded` on either broken signal; and `/health/ready` carrying
`scheduler`/`tz_database` checks plus a `warnings` diagnostic without moving
readiness off its api+workspace keys. One pre-existing assertion in
`test_api.py::test_health_not_degraded_when_all_dependencies_healthy` gained
stubs for the two new `degraded` inputs — it runs without the app lifespan,
so its scheduler probe would truthfully read not-running.

`packages/hive-conductor/tests/e2e/test_scheduler_timezone_container.py`
(+5) is the container half: it runs inside the api-tests image against the
LIVE shipped hive image and verifies what the image ships, not what the
developer environment resolves. It creates a `UTC` schedule (fires naturally
within a tick; `next_run` lands inside a 2-minute window) and a
`Europe/Berlin` 04:30 schedule (fired manually through the same admission
path the tick uses; its cursor must keep 04:30 *Berlin* wall time with the
season-correct CET/CEST offset and the exact expected UTC instant computed
from the api-tests image's own deliberately pinned `tzdata` wheel); refuses
invalid zones with 422; requires `/health` to report `tz_database` and
`scheduler` independently of process liveness; and — behind
`SCHED_TZ_AFTER_RESTART=1`, which CI sets only in the post-restart phase —
verifies schedules and cursors survive a real container restart with the UTC
cursor recomputed by the new process. Both schedules target `daily-status`,
the template the shipped image registers at boot: the fallback admission
path refuses to fire an unregistered template, which would leave `next_run`
unset forever regardless of timezone correctness.

## Verification result (recorded per the issue's definition of done)

Verified against a local build of `packages/hive-conductor/Dockerfile` at
this change, image id
`sha256:e918a0d94d6322a31fa2a82455b578414cea3352f95e39ffadd38f312cd6a3da`
(tag `hive-conductor:290-verify`; the Dockerfile pins the runtime base by
tag to `python:3.13.15-slim-bookworm`):

- Build-time smoke test (Dockerfile `RUN python -c …`): resolves UTC,
  `America/New_York`, and `Europe/Berlin` through the pinned `PYTHONTZPATH`
  and asserts DST-correct Berlin offsets (+1 winter / +2 summer) — the build
  fails if the tzdata wheel or the env pin is lost. Removing the wheel's
  `zoneinfo` dir inside the built image makes that same smoke snippet raise
  `AssertionError` and makes plain `ZoneInfo("UTC")` raise
  `ZoneInfoNotFoundError` — the wheel is the *only* zone source, so the
  dependency cannot be removed without a failing smoke test.
- Timezone database source inside the image (required verification #4):
  `tzdata-wheel:/app/venv/lib/python3.13/site-packages/tzdata/zoneinfo`
  (`tzdata==2026.3` installed into the self-contained venv, selected via
  `PYTHONTZPATH`), reported verbatim by `/health`'s `tz_database.source`.
- Full `docker compose -f docker-compose.test.yml --profile test up --build
  --abort-on-container-exit --exit-code-from api-tests api-tests` run:
  14 passed / 14 skipped (the PM suite's own pre-existing skips), including
  all four pre-restart timezone tests. After `start hive` (same durable
  state dir, fresh process) the `-k restart_recovery` selection passed:
  schedules and cursors persisted, `next_run` recomputed, scheduler healthy.
- Booting the built image with a deliberately broken `PYTHONTZPATH` shows
  the missing-data path is loud, not silent: `/health` reports
  `tz_database.status=unavailable` with an error naming the env var and the
  fix (`reinstall it (pip install tzdata) or rebuild the image`),
  `degraded=true`; `/health/ready` keeps its status semantics but reports
  `checks.tz_database=false` and carries the same diagnostic in `warnings`.

## Re-verification after the develop integration (2026-10-20)

The branch's develop-integration merge (unrelated histories; develop's
`#97`/`#1181` health probes and `#1200` frequency floor, canonical-only
schedule execution per `#1113`) silently invalidated two of the container
proofs above, which the re-run caught:

- The UTC test's `* * * * *` schedule is correctly refused 422 by the new
  `schedule_min_frequency_gap_s` floor (default 900s, operator-bounded,
  hard minimum 300s). The test now asserts that refusal verbatim, creates
  `*/5 * * * *` — the fastest recurrence the harness floor admits — and
  proves *natural* execution by polling until the tick's admission path
  moves the cursor past the computed occurrence with no manual fire.
- The manual fire (Berlin, and any schedule) requires the canonical
  execution spine (`run_store` + `graph_run_store`); a bare harness
  container's ephemeral in-memory Container fails that closed, so every
  fire 409'd. `docker-compose.test.yml` now gives hive the file-backed
  SQLite `DATABASE_URL` the shipped image explicitly supports
  (`aiosqlite` is in `backend/requirements.txt` for exactly this), plus a
  stub `MAISTRO_ROUTER_API_KEY` (`create_container` refuses to build the
  canonical Container without one, and with `DATABASE_URL` set a missing
  roster fails every Workspace request closed, #37) and
  `SCHEDULE_MIN_FREQUENCY_GAP_S=300` (the hard minimum) so the natural-fire
  wait fits the CI job budget. The invalid-zone test uses a floor-passing
  cron so its 422 is attributable to the zone alone.

Re-verified against the merged tree, image id
`sha256:8f36eca8ca5037966a82a24afcc770204a66b3cac5f890c02a42095443751808`
(`hive-conductor-hive:latest`, compose-built with the harness env above;
CLI build of the same Dockerfile at tag `hive-conductor:290-reverify`):

- Build-time smoke green (`tz smoke ok: UTC/America/New_York/Europe/Berlin
  via /app/venv/lib/python3.13/site-packages/tzdata/zoneinfo`); negative
  proof re-run (removing the wheel's `zoneinfo` dir → smoke `AssertionError`
  and `ZoneInfo("UTC")` → `ZoneInfoNotFoundError`).
- Healthy boot: `/health` `tz_database.source`
  `tzdata-wheel:/app/venv/lib/python3.13/site-packages/tzdata/zoneinfo`,
  `scheduler.running=true` with `last_tick_at`; `/health/ready` checks
  `scheduler=true`, `tz_database=true`, `warnings=[]`.
- Broken-`PYTHONTZPATH` boot: `tz_database.status=unavailable` naming the
  env var and the fix, `degraded=true`, `/health/ready`
  `checks.tz_database=false` with the same diagnostic in `warnings`.
- Full compose run against the live stack: **14 passed / 14 skipped** in
  147s, including the UTC schedule's 422-refusal pin, `*/5` creation,
  natural fire (cursor advanced by the tick alone), the Berlin 04:30
  manual fire with wall-time + season-offset + exact-UTC-instant
  assertions, invalid-zone 422s, and the health-surface pins; then the CI
  restart phase (`start hive`, wait healthy, `SCHED_TZ_AFTER_RESTART=1`
  `-k restart_recovery`): **1 passed** — schedules and cursors persisted,
  cursors recomputed, scheduler healthy.
- Backend suite after the merge resolution: **3736 passed, 20 skipped**
  (`packages/hive-conductor/backend/tests`), including the 13
  `test_scheduler_timezone_health.py` pins and the develop-side
  `test_degraded_mode_surface.py` pins (whose healthy-case test now stubs
  the two #290 probes, matching `test_api.py`'s existing pattern).
  `scripts/check-suite-inventory.py`: ok, 17 suites match the recorded
  inventory.

## Re-verification after the second develop sync + image repair (2026-10-24)

This round resolved the preserved develop-sync conflict (two merges:
`e20e9f52` resolved in `b6dd05f66`, then `origin/develop` `4de7e906` in
`f48deb0a3`) and re-proved every acceptance criterion against the merged
tree. The sync exposed two real defects in the container proof, both fixed
here:

1. **The shipped image lost the sqlite `DATABASE_URL` mode.** develop's
   #348 image rewrite installs `uv export --locked --package
   hive-conductor` instead of `backend/requirements.txt`, and aiosqlite
   lives only in core's `sqlite` extra — so the harness's
   `DATABASE_URL=sqlite:////tmp/conductor/canonical.sqlite3` (and the
   homelab single-instance mode requirements.txt documents) booted with
   `No module named 'aiosqlite'`, the roster bridge failed closed (#37),
   and `/health/ready` served 503 forever. Repair: `aiosqlite>=0.20,<1`
   declared in `packages/hive-conductor/pyproject.toml` (same
   carried-for-the-deployment precedent as msgpack) and locked
   (`uv.lock` delta is exactly that one dependency).
2. **The harness handed the compose-secrets gate a key-shaped literal.**
   `MAISTRO_ROUTER_API_KEY=test-harness-not-a-real-key` fails
   `scripts/check-compose-secrets.py` (#367) — and had since it landed in
   3920ad7. The profile now requires the variable
   (`${MAISTRO_ROUTER_API_KEY:?...}` — refuse-to-start, the shape the gate
   blesses; verified: `compose config` without the var exits 1 printing
   the actionable message), and the CI `hive-conductor-e2e` job exports a
   throwaway stub at the job level.

Re-verified against the rebuilt merged image, image id
`sha256:d4673dfbeb3d2ee2d9bdbef0f0c01c7143f6744b72465ff591816c8018b92bfe`
(`hive-conductor-hive:latest`, compose-built; `tzdata==2026.3`, aiosqlite
present, base `python:3.13.16-slim-bookworm` digest-pinned):

- Build-time tz smoke green (`tz smoke ok: UTC/America/New_York/
  Europe/Berlin via /app/venv/lib/python3.13/site-packages/tzdata/zoneinfo`).
  Negative proof: moving the wheel's `zoneinfo` dir away inside the built
  image makes that smoke exit 1 and `ZoneInfo("UTC")` raise
  `ZoneInfoNotFoundError` — the wheel is the only zone source, so the
  Docker dependency cannot be removed without a failing smoke test.
- CI-exact compose run
  (`docker compose -f docker-compose.test.yml --profile test up --build
  --abort-on-container-exit --exit-code-from api-tests api-tests`):
  **14 passed / 14 skipped**, including UTC `*/5` natural fire (cursor
  advanced by the tick alone), Berlin 04:30 wall time + season offset +
  exact UTC instant against the api-tests image's own pinned wheel,
  invalid-zone 422s, and `/health` tz/scheduler pins. Restart phase
  (`start hive`, wait healthy, `SCHED_TZ_AFTER_RESTART=1 -k
  restart_recovery`): **1 passed** — schedules and cursors survived, the
  new process recomputed `next_run`, scheduler healthy. (Local runs
  publish hive on 127.0.0.1:8102 via a /tmp port override: the developer
  stack owns 127.0.0.1:8101. CI is unaffected — the publish is host-side
  only.)
- Timezone database source inside the image (required verification #4),
  read from the live post-restart container's `/health`:
  `tzdata-wheel:/app/venv/lib/python3.13/site-packages/tzdata/zoneinfo`.
- Broken-tz boot (`PYTHONTZPATH=/nonexistent/tzdata`):
  `/health` `degraded=true`, `tz_database.status=unavailable` with the
  diagnostic naming the env var and the fix ("reinstall it (pip install
  tzdata) or rebuild the image"); `/health/ready` reports
  `checks.tz_database=false` and carries the same diagnostic in
  `warnings` — loud, not silently healthy.
- Backend suite on the merged tree: **3957 passed, 26 skipped**
  (`packages/hive-conductor/backend/tests`), including the 13
  `test_scheduler_timezone_health.py` pins. Gates: `ruff check .` and
  `ruff format --check .` clean; `check-suite-inventory.py` ok (21
  suites, no delta — this round adds no tests); `check-compose-secrets`
  ok (9 profiles); `check-compose-resources`, `check-build-context`,
  `check-dependency-namespaces`, `check-backlog-consistency`,
  `check-doc-links` ok; CI-exact mypy (`packages/*/src`, 1001 files) no
  issues; `tests/test_check_compose_secrets.py` 81 passed.

## Independent verifier re-run (2026-10-24, head `4a01f8c39`)

A verification driver re-ran the container file with a bare host-side
`uv run pytest packages/hive-conductor/tests/e2e/test_scheduler_timezone_container.py`
and recorded a failure. That run never reached the harness: outside the
api-tests container `HIVE_BASE_URL` defaults to `http://localhost:8101`, and
the dev stack answering there runs the product default floor (900s), so the
harness-planned `*/5 * * * *` create was refused 422 — the shipped boundary
behaving correctly in the wrong environment, not a regression. This file is
meaningful only inside the compose harness (`docker-compose.test.yml` sets
`SCHEDULE_MIN_FREQUENCY_GAP_S=300`); do not run it bare from the host.

The full CI-exact battery was then re-executed first-hand against this head,
compose-built image `sha256:580a111b860f3f4f781051a942c3be2070bf19dd86ef186b586d3720d00840da`
(`auto-290e2e-hive`; host 8101 was occupied by the developer stack, so this
local run published no ports via a /tmp override — CI is unaffected):

- Phase 1 (`up --build --abort-on-container-exit --exit-code-from api-tests
  api-tests`): **14 passed / 14 skipped** in 147.85s — UTC `*/5` create +
  natural fire, Berlin 04:30 wall time/season offset/exact instant, invalid
  -zone 422s, `/health` tz + scheduler pins, restart-marked test skipped
  pre-restart as designed.
- Phase 2 (CI restart step verbatim: `start hive`, wait healthy,
  `SCHED_TZ_AFTER_RESTART=1 -k restart_recovery`): **1 passed** in 0.43s.
- Post-restart live `/health`: `tz_database`
  `{status: available, source: tzdata-wheel:/app/venv/lib/python3.13/site-packages/tzdata/zoneinfo}`,
  `scheduler.running=true` with fresh `last_tick_at`; `/health/ready` 200
  with `scheduler=true`, `tz_database=true`, `warnings=[]`.
- Negative A (dependency cannot be removed): inside the built image, moving
  the wheel's `zoneinfo` dir away makes the Dockerfile's build-smoke snippet
  raise `AssertionError` and `ZoneInfo("UTC")` raise `ZoneInfoNotFoundError`
  — the pinned wheel is the *only* consulted source (the Debian base's
  apt-installed `/usr/share/zoneinfo` does not rescue it).
- Negative B (broken-tz boot): a container booted with
  `PYTHONTZPATH=/nonexistent/tzdata` reports `/health` `degraded=true`,
  `tz_database.status=unavailable` with the actionable diagnostic naming the
  env var and the fix; `/health/ready` carries `checks.tz_database=false`
  and the same diagnostic in `warnings`.
- Backend suite: **3957 passed, 26 skipped** (`packages/hive-conductor/backend/tests`).
  Targeted: `test_scheduler_timezone_health.py` + `test_schedule_frequency_floor.py`
  + `test_degraded_mode_surface.py` = 31 passed. Gates: `ruff check .` /
  `ruff format --check .` clean; `check-suite-inventory.py` ok (21 suites,
  no delta); `check-compose-secrets` ok (9 profiles);
  `check-compose-resources`, `check-build-context` ok.

## Repair round: the harness stops assuming the deployment's floor (2026-10-24)

The validation driver runs this file bare from the host
(`uv run pytest tests/e2e/test_scheduler_timezone_container.py`), where it
answers whatever listens on `localhost:8101` — the shared dev stack, which
runs the product-default 900s floor and, decisively, is built from another
tree (live `/health` carries no `tz_database` key at all). The previous
round (fc1145670) diagnosed that mismatch and re-ran the compose harness by
hand, but left the file itself assuming the harness's 300s selection, so
the bare command kept failing identically (`*/5 * * * *` → 422 "one fire
per 900s"). This round makes the file environment-truthful instead of
re-recording the workaround; **no production code changed**, and the test
count is unchanged (delta: none).

- Floor discovery: the suite asks the server under test what it enforces —
  the create-time refusal of `* * * * *` names `schedule_min_frequency_gap_s`
  and states the enforced number — and derives the fastest admitted UTC
  recurrence (`*/(floor/60) * * * *`) and the natural-fire budget
  (floor + 30s tick + 120s margin) from that answer. No fixed `*/5` and no
  fixed 420s budget remain; the invalid-zone test uses the discovered
  floor-passing cron so its 422 stays attributable to the zone.
- Foreign-image guard: a module-scoped autouse fixture skips the suite with
  an actionable reason when the server under test lacks this branch's tz
  health surface — the only alternative evidence there is evidence about
  code this change did not ship. The compose harness always exposes the
  surface, so CI still runs everything.
- Bare-host run of the exact driver command: **5 skipped, exit 0**, each
  skip naming the foreign server and the compose fix (verified live against
  the dev stack).
- CI-exact compose re-run at this tree (image
  `sha256:21cd2184ebeafb827d4b3b26c134271734c442f3a63afd486408ee804d6c8e7a`,
  host port unpublished via /tmp override — the dev stack holds 8101; the
  compose-internal `hive:8101` the tests target is unchanged):
  phase 1 **14 passed / 14 skipped** in 182.13s (UTC floor-probe → `*/5`
  create → natural fire by the tick alone, Berlin 04:30 wall time + season
  offset + exact instant, invalid-zone 422s, `/health` tz + scheduler
  pins); restart phase (`start hive`, wait healthy,
  `SCHED_TZ_AFTER_RESTART=1 -k restart_recovery`) **1 passed** in 0.28s;
  post-restart live `/health`: `tz_database.status=available`,
  `source=tzdata-wheel:/app/venv/lib/python3.13/site-packages/tzdata/zoneinfo`,
  `scheduler.running=true` (`degraded=true` is the harness's truthful F3
  no-gateway surface, unchanged from prior rounds).
- Targeted backend: `test_scheduler_timezone_health.py` +
  `test_schedule_frequency_floor.py` = **24 passed**. Gates: `ruff check .`
  and `ruff format --check .` clean; `check-suite-inventory.py` ok (21
  suites, no delta).
- Previous round's block (develop sync conflict preserved in the worktree)
  was already resolved before this round: `origin/develop` (4de7e906d) is
  an ancestor of this branch (merge-base == `origin/develop`, 0 commits
  behind); the resolution commits are b6dd05f66 and f48deb0a3.

## Repair round: the CI gates the branch was failing (2026-10-24, head `2e83601cc`)

The hosted run at `2e83601cc` failed nine checks. Each root cause, the fix,
and the local proof (no code paths of this issue's feature changed this
round; the scheduler/health/tzdata work above is untouched):

1. **A bare error swallow in ci.yml's new restart step** (`|| echo starting`
   with no written reason) failed the workflow-inventory gate, which failed
   the three `tests/test_check_workflow_inventory.py` tree tests, the
   `test` job, `security`, `Quality / Workflow inventory`, the
   `Quality gate (Pillars 1–4, 7, 8)` ("quality-workflow-inventory:
   dependency did not succeed") and the `Coverage gate` (same three tests).
   Fix: the readiness-poll swallow now carries its written reason (a
   still-starting container has no health state to read; the post-loop
   assertion still fails the step). `check-workflow-inventory.py` clean;
   `tests/` root suite **5638 passed, 143 skipped** (the exact CI step).
2. **`hive-conductor-e2e-ui` never started a container**: the compose guard
   added for the harness key (`${MAISTRO_ROUTER_API_KEY:?...}`) fails
   interpolation in every compose command of a job that does not export it,
   and only `hive-conductor-e2e` did. That is the whole
   `integration-scope` failure ("hive-conductor-e2e-ui is required by
   integration scope but concluded failure"). Fix: the same job-level
   throwaway stub (same rationale comment) on `hive-conductor-e2e-ui`.
   Proof: `docker compose config` without the var prints the exact CI
   error; with it, the full CI-exact UI run below is green.
3. **Supply chain (pip-audit)**: `fastmcp==4.0.11` (GHSA-7xgj-8392-5q4r,
   GHSA-vqqp-x5qm-5qp4 → 4.1.2) and `setuptools==84.0.0`
   (GHSA-xmj3-9gf7-h52w → 84.1.0) — trunk-level lock rot, not introduced
   here. Fix: `uv lock --upgrade-package` for fastmcp (→ 4.1.3,
   fastmcp-slim → 4.1.3, openapi-pydantic → 0.6.0), setuptools (→ 84.2.1)
   and, for the Container scan, pypdf (→ 6.21.2; CVE-2026-115572/80/85,
   HIGH ×3 in trivy); the image's exact setuptools pin and
   security.yml's `--member setuptools==...` moved with the lock. The same
   run exposed the gate's second half: the branch's carried-for-deployment
   `aiosqlite` declaration had no reviewed disposition — added to
   `quality/direct-dependency-exceptions.json` (DECLARATIVE_RUNTIME, #290,
   msgpack precedent). Local CI-exact pip-audit + gate: **exit 0**.
4. **The lock-reconciliation step (runs after trivy, so CI never reached
   it) would have failed next**: the image ships `tzdata==2026.3` by
   deliberate ARG pin and tzdata is deliberately not in any lock export —
   `check-image-lock-reconciliation.py` reported `in image, not locked`.
   Fix: `--member tzdata==2026.3` (and `--member setuptools==84.2.1`) on
   the hive-conductor reconciliation with a comment tying the members to
   the Dockerfile pins. Locally, against the rebuilt image: **OK: ships
   exactly the locked set (74 distributions)**.
5. **pm-workflow UI specs 06/07 pinned the spine-absent harness** and would
   have failed `hive-conductor-e2e-ui` as soon as the interpolation fix let
   the job run: the harness's `DATABASE_URL=sqlite:...` (added for the
   scheduler proofs) makes `engine.graph_execution_available` true —
   verified live — so `expect(...graph_execution_available).toBe(false)`
   and the `CanonicalGraphUnavailable` payload pins were dead premises.
   The two specs now pin the harness's documented truth: activation is
   still definition state; the run resolves the spine (real
   `execution_id`), executes, and fails closed at host policy ("host
   policy did not authorize this node"); the failed run persists under its
   DAG in `/v1/dag-runs`; a definition ID as a run ID still 404s
   `{"detail": "run not found"}`. The spine-absent refusal itself stays
   pinned at the unit level (`test_graph_execution_authority.py`). Test
   count unchanged (219 UI specs; the Playwright suite is not a
   suite-inventory ledger suite — inventory re-checked: 21 suites ok).

Re-verified end to end at this tree, compose-built image
`sha256:5f4a713c5d4659a05599fd9ab3e7580b3c3b887c0c16cf76911e8493f3120453`
(`hive-conductor-hive:latest`; setuptools 84.2.1, tzdata 2026.3,
aiosqlite 0.22.1, `PYTHONTZPATH` smoke green in-build; host 8101 is held
by a leaked rootlesskit bind from another stack, so local runs drop the
host publish via an untracked override — CI is unaffected):

- CI-exact api phase (`up --build --abort-on-container-exit
  --exit-code-from api-tests api-tests`): **14 passed / 14 skipped**
  (all four pre-restart timezone tests; restart-marked skipped as
  designed), restart phase (`start hive`, wait healthy,
  `SCHED_TZ_AFTER_RESTART=1 -k restart_recovery`): **1 passed**.
- CI-exact UI phase (`CI=1`, `up --build ... --exit-code-from e2e-tests
  e2e-tests`, fresh stack): **219 passed (4.0m)** — including rewritten
  specs 06/07. An earlier local run showed 10 failures that were (a) the
  06/07 premise flips above and (b) eight spec failures caused by reusing
  a hive container that had already served the api phase (leftover
  canonical state); a fresh stack — what CI's per-job container actually
  is — is fully green, so only (a) was real.
- Negative proofs re-run on the rebuilt image: moving the wheel's
  `zoneinfo` dir away makes the build-smoke snippet raise
  `AssertionError` and `ZoneInfo("UTC")` raise `ZoneInfoNotFoundError`;
  booting with `PYTHONTZPATH=/nonexistent/tzdata` serves `/health`
  `degraded=true`, `tz_database.status=unavailable` naming the env var
  and the fix, and `/health/ready` carries `checks.tz_database=false`
  with the same diagnostic in `warnings`.
- Gates re-run locally: `ruff check .` / `ruff format --check .` clean;
  root `tests/` **5638 passed, 143 skipped**; backend
  **3957 passed, 26 skipped**; `check-suite-inventory.py` ok (21 suites);
  `check-compose-secrets.py` ok (10 tracked profiles); `uv lock --check`
  ok; workflow-inventory gate clean; shellcheck clean on the edited
  `run:` block.

## Repair round: develop sync + typed-client regen (2026-10-24, head `1f154d256`)

Hosted CI at `0c76013e0` failed the `test` job on the *Generated API types
match the backend's OpenAPI document (#1048)* step: this branch's
`warnings: string[]` addition to the scheduler-health schema
(`backend/models/schemas.py`) was never regenerated into the committed
`packages/hive-conductor/frontend/src/api/types.gen.ts`. (The
`RuntimeError: Event loop is closed` lines in that job's log are shutdown
noise from the OpenAPI dump process, not the failure.) Repair: reran
`uv run python scripts/dump-hive-openapi.py` + `npm --prefix
packages/hive-conductor/frontend run gen:api` and committed the 5-line
generated addition; `git diff --exit-code` on the step is now clean. The
round also merged `origin/develop` (`3825fb9b5`, #2307 + #2290) — one
conflict, `.github/workflows/security.yml`, resolved to the union
(setuptools 84.2.1 from develop + this branch's `tzdata==2026.3` member in
the hive image lock-reconciliation assertion).

Re-validated at the merged head, compose-built image
`sha256:62edc22cdc07313d864e2a6c0a2a77eecc81f296da1cbe07474a895eb453ebfc`
(`hive-conductor-hive:latest`; build-time tz smoke green via
`/app/venv/lib/python3.13/site-packages/tzdata/zoneinfo`; host 8101 again
held by another stack, so the local run published `127.0.0.1:18101` via an
untracked override, deleted after use — CI is unaffected):

- CI-exact failing step: green (`git diff --exit-code -- …/types.gen.ts`).
- CI-exact api phase: **14 passed / 14 skipped** in 272s — UTC `*/5`
  natural fire, Berlin 04:30 wall time + CET/CEST offset + exact instant,
  invalid-zone 422s, `/health` tz/scheduler pins; restart-marked test
  skipped pre-restart as designed. Restart phase (`start hive`, wait
  healthy, `SCHED_TZ_AFTER_RESTART=1 -k restart_recovery`): **1 passed**.
- CI-exact `test` job remainder: backend suite **3969 passed, 26
  skipped**; combined one-process run (`pytest tests/
  packages/hive-conductor/backend/tests packages/maistro-design/tests
  -q --timeout=60`) **10365 passed, 170 skipped**; suite inventory ok (21
  suites, 34177 node IDs — no delta, this round adds no tests);
  `check-test-duplicates.py` ok; `check-frontend-typed-client.py` ok (51
  raw fetch / 129 hand-typed, unchanged from base `3825fb9b5`); hive
  frontend `npm run build` green on the regenerated types; `ruff check .`
  and `ruff format --check .` clean.

## Round: final develop-M1 sync + first-hand re-verification (2026-10-24, head `42e32bc11`)

The independent verifier round at PR head `631aa7417` (job `b604d602931848b29e3d88e8f91d4202`) recorded a first-hand compose harness run against image
`sha256:5d4264629424a60f655b46b6780a2e88026a9c8ed665e9e65e37cf3cace7424f`, built from that head: api phase **14 passed / 14 skipped** (~302s) plus the restart
phase **1 passed**. That evidence was pending recording here; it is hereby recorded.

The branch then merged the final develop-M1 drop (`b1c89cdb5`, #2308 durable
Workspace landing + #2284 Attention shell) at `42e32bc11`. No #290 surface
changed — every timezone file is byte-identical to `631aa7417` (`git diff`
empty over Dockerfile, scheduler.py, health.py, both test files, ci.yml,
compose file). `uv.lock` and the Dockerfile are also unchanged, but backend and
maistro-core sources moved, so the shipped image was rebuilt from this head and
re-verified first-hand:

- Image `sha256:68a2a5d9286d040d2242cfbd52c4ec74776b9662a8a2768c6ac8391f8a47844e`
  (`hive-conductor-hive:latest`, compose build). In-image timezone source,
  recorded per the issue's definition of done:
  `PYTHONTZPATH=/app/venv/lib/python3.13/site-packages/tzdata/zoneinfo`,
  `tzdata` wheel **2026.3**; `ZoneInfo("UTC")` and `ZoneInfo("America/New_York")`
  resolve through it.
- CI-exact api phase (`compose --profile test up --build --abort-on-container-exit
  --exit-code-from api-tests api-tests`): **14 passed / 14 skipped in 152s** —
  UTC natural fire, Berlin 04:30 wall time + CET/CEST offset + exact instant,
  invalid-zone 422s, `/health` tz/scheduler pins; restart-marked test skipped
  pre-restart as designed. Restart phase (`start hive`, wait healthy,
  `SCHED_TZ_AFTER_RESTART=1 -k restart_recovery`): **1 passed**.
- Negative mechanism proof (in the shipped image): with the wheel's
  `zoneinfo/` directory shadowed empty, the Dockerfile's literal build-time
  smoke command exits **1** with `ZoneInfoNotFoundError: 'No time zone found
  with key UTC'` — the tz dependency cannot be removed without failing that
  smoke test.
- Backend suite at the merged head: **4012 passed, 25 skipped** (develop's new
  Workspace/dag-run tests included; was 3969/26 at `1f154d256`).
- Gates at this head, all green: `ruff check .` + `ruff format --check .`;
  vulture ledger with CI-exact args (1297 identities = 1297 findings);
  suite inventory for `packages/hive-conductor/backend/tests` and
  `packages/hive-conductor/tests`; `check-test-duplicates.py`;
  `check-frontend-typed-client.py` (46 raw fetch / 129 hand-typed, none new);
  the CI `test` job's OpenAPI step (`dump-hive-openapi.py` + `gen:api`) regenerates
  with zero diff at this head.
- Local-only deviation, as in prior rounds: a foreign stack held host 8101, so
  the run published `127.0.0.1:18101` via an untracked /tmp compose override,
  deleted after use. The harness talks over the compose network
  (`http://hive:8101`), so CI behavior is unaffected. Tree left clean.

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

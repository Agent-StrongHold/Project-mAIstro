---
inventory-delta:
  packages/hive-conductor/tests/e2e: 0
---
# #290: prove execution after restart, not just persisted data

## Evidence and focused repair

The incoming restart test only checked that the stored UTC `next_run` was
newer than five minutes ago. A frozen future cursor satisfies that assertion
without the restarted scheduler admitting anything (also identified in the
cached PR review). The existing recovery test now waits for that cursor to
advance naturally, using the server's enforced recurrence floor and the same
bounded polling helper as the pre-restart test. No manual fire can make this
proof pass. CI's restart step budget now covers its 300-second recurrence,
150-second tick/jitter allowance, and 120-second boot poll (10 minutes).

A host-side re-run against the same image exposed a real minute-boundary
race in the UTC test: its projected occurrence was `22:40:00Z`, and the
subsequent assertion read `22:40:00.024842Z`, failing the requirement that
`next_run` still be in the future. The lower bound now uses the instant just
before schedule creation, not a later assertion time. The natural-fire poll
still must observe that occurrence being consumed; stale cursors cannot make
the test pass. This changes no production behavior or test count.

A fresh CI-shaped compose run exposed a second defect: Hive was still running
after `up --abort-on-container-exit ... api-tests`. The old `start hive`
command left `StartedAt=2026-10-25T22:26:06.265678681Z` unchanged. CI now
explicitly uses `restart hive` and asserts that `StartedAt` changes, so a
no-op restart cannot produce false recovery evidence.

The image smoke test already checked winter/summer offsets, but those do not
exercise a transition. A second build-time smoke executes the production
`maistro.scheduling.cron` implementation against the shipped timezone database
at fixed 2026 Berlin transitions: the nonexistent spring 02:30 is skipped,
and the repeated fall 02:30 fires only on its first occurrence, followed by
the next day's 02:30. These are container-build assertions, not new pytest
node IDs; the existing recovery test count is unchanged.

Architecture: ADR-082126-f69c and ADR-082426-82c7 remain authoritative. The
repair observes the existing canonical admission path; it introduces no
scheduler, store, execution authority, or authorization shortcut.

## Validation

First-hand compose validation (only local deviation: host ports unpublished
via a job-directory override; all test traffic uses the unchanged internal
`http://hive:8101` address):

- UI phase, fresh `repair290fresh` stack: **241 passed (4.9m)**, exit 0.
- API phase, fresh `repair290api` stack: **14 passed / 14 skipped (272.32s)**,
  exit 0; all four pre-restart timezone tests passed. Other skips belong to
  the pre-existing PM suite and the intentionally post-restart selection.
- Host-side driver command, pointed explicitly at that same image via
  `HIVE_BASE_URL=http://172.31.0.2:8101` after the minute-boundary repair:
  `uv run pytest packages/hive-conductor/tests/e2e/test_scheduler_timezone_container.py
  -q -x`: **4 passed / 1 skipped (327.72s)**. This used the host test file
  with the repaired assertion against the same pinned runtime image (the
  last edit affects only the external test runner, not runtime contents).
- Explicit restart: `StartedAt` changed from the value above to
  `2026-10-25T22:31:22.780071609Z`. The strengthened post-restart test passed
  in **240.78s**, observing natural cursor advancement in the new process.

The driver's bare-host container pytest failed with ConnectTimeout because
no harness was reachable at its default host address; that is not container
acceptance evidence. No skip-on-disconnection workaround is added.

## Pinned image and acceptance evidence

The rebuilt shipped image used by the API and restart phases is pinned by
local immutable image ID
`sha256:cd865a1ddce0e121995c5c7956114be9d2727ab9d97fd2710e19cfa0c734470a`
(runtime config `sha256:2c77be5b4eee1a0d036bb0ca12f7cf1c24dfd048d4f9df37b56b5c1bc474368f`).
The build executed both timezone smokes successfully. In-image inspection
reported **tzdata 2026.3**, with `zoneinfo.TZPATH` containing only
`/app/venv/lib/python3.13/site-packages/tzdata/zoneinfo`; live `/health`
reported the same `tzdata-wheel:` source and a running scheduler with a
fresh tick timestamp.

- Deliberate source and dependency-removal regression: moving the wheel out
  of the disposable image's import/search paths makes the literal existing
  Dockerfile smoke exit 1 at its path assertion. This was executed as root
  so the failure is the smoke's assertion, not a failed filesystem mutation.
- UTC/IANA parsing, persistence, next-run computation, execution, and invalid
  zones: the four container tests passed against that image. UTC fired
  naturally; Berlin fired through the canonical manual admission path and
  retained its wall time, offset, and exact expected UTC instant.
- Deterministic DST transition behavior: the image's new production-cron
  smoke passed for Berlin's spring gap and fall fold; deliberately replacing
  its zone resolver with UTC makes it fail at the spring assertion.
- Actual restart recovery: the changed `StartedAt` and natural cursor
  advancement were observed in the strengthened recovery test, not inferred
  from stored rows or task liveness.
- Sensitivity to broken recovery: replaying frozen live schedule/health
  responses makes the **incoming test pass** and the **repaired test fail**
  (`never fired naturally`). Only the poll budget was reduced to zero for
  that deterministic replay; the real container test used the full budget.
- Missing/corrupt timezone readiness diagnostics: two disposable image boots
  were exercised, one with `PYTHONTZPATH=/nonexistent/tzdata`, the other with
  the wheel's UTC file replaced by invalid bytes before process startup.
  Both kept `/health` alive, set `degraded=true`, reported timezone data
  unavailable, and returned `checks.tz_database=false` plus an actionable
  tzdata/rebuild diagnostic in `/health/ready.warnings`. Scheduling health
  remains separate from process liveness; readiness retains the existing
  api/workspace/engine semantics rather than treating scheduler loss as a
  total outage.

## Focused validation and limits

Commands run with the repository's uv environment:

- `uv run ruff check .` and `uv run ruff format --check .`: clean.
- Scheduler timezone-health, canonical-admission, frequency-floor, and
  degraded-surface backend tests: **52 passed**, one pre-existing Pydantic
  serializer warning in the degraded-surface recovery test.
- `uv run pytest packages/maistro-core/tests/scheduling -x -q`:
  **289 passed / 38 skipped** (database-backed variants without configured
  external services). The canonical recurrence/admission tests passed.
- `node --test tests/ci/integration-scope.test.cjs`: **12 passed**. Both
  Hive integration producers were also executed above; no gate was weakened
  or replaced by a fabricated success payload.
- `check-workflow-inventory.py`, `check-compose-secrets.py`,
  `check-compose-resources.py`, `check-build-context.py`, and
  `check-doc-links.py`: passed. Shellcheck on the extracted CI restart
  `run:` block: clean. `git diff --check`: clean.
- `check-suite-inventory.py` for backend/tests and tests/e2e: **4105 / 28**,
  both matching their recorded inventory; no pytest count delta.
- CI-exact `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`: **1256 reviewed identities = 1256 findings**.
  No dead identities or unbanked findings were reported, so no quality
  ledger or authorization change is justified or made.

Raw logs and deterministic negative/replay probes are in job directory
`/home/dev/maistro/jobs/3ef1298ce4e34ab6b04e55cb5a9174c2/`:
`repair-ui.log`, `repair-api.log`, `repair-restart.log`,
`repair-negative.log`, and `repair-sensitivity.log`.

This is local writer handoff evidence only. Hosted integration-scope still
requires exact-candidate producer checks and separate integration approval;
no claim is made about current hosted queue state, and no GitHub mutation
was performed. The full repository suite was not run (validation was scoped
to the changed package and relevant CI gates).

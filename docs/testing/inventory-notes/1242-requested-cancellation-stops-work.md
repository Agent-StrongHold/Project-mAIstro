---
inventory-delta:
  packages/maistro-core/tests: +10
---

# #1242 — a requested cancellation stops the running work

`DELETE /tasks/{id}` went through `TaskQueue.cancel`, which terminalized the
receipt and reported success while the runner's coroutine ran on: the executor
the caller cancelled kept consuming compute and writing into the workspace, and
when it eventually finished, its result was attached to a receipt that already
said CANCELLED. The queue had no handle to the physical work, so a cancellation
could only rewrite the receipt.

The fix gives the queue a registry of in-flight executions: the runner registers
the `asyncio.Task` dispatching each claimed task and unregisters it from that
task's own done callback, and `TaskQueue.cancel` cancels the registered
execution and waits (bounded by `CANCELLATION_SETTLE_TIMEOUT`) for the
`CancelledError` handlers to finish before answering. The unwinding work no
longer fights the receipt: both `claim()`'s exception path and the worker's
`CancelledError` handler distinguish a *requested* cancellation (receipt already
CANCELLED — leave it, it is the truth the caller acted on) from a shutdown
cancellation (receipt not terminal — keep recording
`Task cancelled during shutdown` exactly as before).

## Reconciliation with the canonical cancellation path (#1320)

Develop independently fixed the same class end to end through the canonical
model (#1169/#1320): `TaskQueue.cancel` calls `admitter.cancel_run(run_id)`
first, which fences the Run CANCELLED and signals the in-process owner of the
physical Attempt. Merging the two branches kept both halves:

* For admitted work the canonical Run is cancelled first — the receipt is a
  projection and follows afterwards. The registry stop still applies to work
  this queue dispatched itself, including deployments with no admitter, where
  no Run exists to carry the signal.
* The canonical stop delivers its `CancelledError` to the worker *before* the
  receipt flips to CANCELLED (the Run is cancelled first and the runtime
  settles the victim inside `cancel_run`). The worker's shutdown branch
  therefore also guards `set_result` behind the FAILED transition: when the
  already-CANCELLED Run refuses that transition, nothing is written, and the
  receipt records the requested cancellation with no result — pinned by the
  `receipt.result is None` assertion in
  `test_a_requested_cancellation_records_a_cancelled_attempt_and_run`.

## The tests

Ten tests in `packages/maistro-core/tests/tasks/test_requested_cancellation.py`:

- `test_cancel_stops_the_running_work` — the regression. Proves the failure
  mode on the unfixed tree (executor completed after `cancel()` returned True;
  a result landed on the cancelled receipt) and its absence on the fixed one.
- `test_a_cancelled_receipt_keeps_no_result_after_the_work_stopped` — the
  secondary defect isolated: the executor observes its `CancelledError` at
  cancel time and the receipt keeps `result is None`.
- `test_a_requested_cancellation_records_a_cancelled_attempt_and_run` — the
  canonical spine must agree with the receipt: Attempt CANCELLED (via the
  existing `CancellationCause.REQUESTED` reconciliation), NodeRun cancelled,
  Run CANCELLED, all driven through `queue.cancel` — the product path, not the
  never-wired `TaskAttemptExecutor.cancel`.
- `test_cancel_does_not_report_success_before_work_settles` — a
  cancellation-suppressing executor keeps the cancellation response from
  claiming success while it remains alive, and cannot attach a later result.
- `test_cancelled_work_cannot_attach_a_late_failure` — work that handles
  cancellation and then raises cannot attach a late error result to the
  already-cancelled receipt.
- `test_cancel_reaches_work_still_waiting_for_a_lane` — a dispatched task
  parked at the lane gate is stopped too, and the gate's handed-permit
  cancellation branch is exercised end to end.
- `test_cancel_a_queued_task_and_it_never_starts` — no registered execution
  yet: the receipt transition still succeeds and the dispatcher refuses the
  stale dequeue.
- `test_cancelling_finished_work_reports_false` — terminal work cannot be
  cancelled; the response must not claim a cancellation that did not happen.
- `test_shutdown_cancellation_still_records_a_failure` — the shutdown
  semantics are pinned so the requested/shutdown distinction cannot swallow
  them.
- `test_the_execution_registry_does_not_retain_finished_work` — unregistration
  runs from the done callback; no stale handle survives a completed task.

Verified to bite: with the source fix reverse-applied (tests kept), six of
these fail — the regression, the settle-timeout honesty, the late-failure
defect, the spine disagreement, the registry mechanism, and the
result-attachment defect — and the four guard tests pass, matching the paths
the transition refusal already protected.

## Independent verification (head 10a49a14, 2026-09-10)

Re-executed at the exact head, not taken from the implementing run:

- `uv run pytest packages/maistro-core/tests/tasks/test_requested_cancellation.py -q`
  → 10 passed.
- `uv run pytest packages/maistro-core/tests/tasks -q` → 256 passed;
  `packages/maistro-server/tests/api/test_tasks.py test_tasks_run_identity.py`
  → 28 passed (DELETE /tasks/{id} → 400 on refused cancellation).
- Bite check in a throwaway copy of the head with the `queue.py`/`runner.py`
  hunks reverse-applied (tests kept): 6 failed / 4 passed, the six listed
  above; the primary regression fails with the executor completing after
  `cancel()` returned True.
- `uv run ruff check .` clean; canonical six-package `uv run mypy` clean;
  `scripts/check-suite-inventory.py --suite packages/maistro-core/tests` ok.
- Full `packages/maistro-core/tests` on this host: 9475 passed; the 46
  failures are environmental, both pre-existing and untouched by this diff —
  21 bwrap sandbox probes (`Resource temporarily unavailable`: the backend
  applies `RLIMIT_NPROC` to bwrap itself pre-exec, which fails under this
  host's process load; CI documents the same class of bwrap namespace
  failure) and 25 postgres-leg tests against the shared host container,
  which runs PostgreSQL 16 below the `MIN_POSTGRES_VERSION = 17` floor that
  the develop base already sets at `container.py:1798`. The postgres-leg
  failures were additionally flaky run-to-run (shared container under
  concurrent load) and pass when the container is quiet.
- No premature GitHub closure keywords (`fixes/closes/resolves`) in any
  commit message on 551c38b5..10a49a14.

## Independent verification at merge head 21d6e73c84988908f57cbf0c03ca1d79d3820c5f

Re-executed after the aud6 branch absorbed the develop base
(8bb344e32b8693574fc0be7a93f86d941616b62c via ffd6fdb16). Not taken from any
prior run's claims:

- `uv run pytest packages/maistro-core/tests/tasks/test_requested_cancellation.py
  -q` → 10 passed; `packages/maistro-core/tests/tasks -q` → 319 passed.
- Bite check in a throwaway worktree at this head with the execution-stop
  block deleted from `TaskQueue.cancel` (receipt-only terminalization, the
  audited defect): 4 failed / 6 passed — `test_cancel_stops_the_running_work`,
  `test_cancel_does_not_report_success_before_work_settles`,
  `test_cancelled_work_cannot_attach_a_late_failure`,
  `test_a_cancelled_receipt_keeps_no_result_after_the_work_stopped`. The
  regression holds the fix.
- Full `packages/maistro-core/tests packages/maistro-server/tests` against a
  live PostgreSQL 17.10 (`MAISTRO_TEST_PG_DSN`): **10820 passed, 116 skipped,
  1 xfailed, 0 failed** — no environmental residue at this head, and the
  persistence suite (614) includes `test_pg_sessions_concurrency.py`, green
  again 3× in isolation after the 23b4de340 DB-clock retention fix.
- Gates: `uv run ruff check .` and `uv run ruff format --check .` clean;
  six-package `uv run mypy` Success (711 files); `scripts/check-suite-inventory.py`
  ok (13 suites); `scripts/check-doc-links.py` 0 broken.
- No gate weakening: `git diff ffd6fdb16..21d6e73c8 -- .github/ scripts/
  pyproject.toml uv.lock .pre-commit-config.yaml` is empty — every
  workflow/gate delta on this branch came in from the develop side of the
  merge, not from the #1242 repair commits.

## Independent verification at exact head 25fd3551c669687b4410aaad558db1568b16ecd9

Re-executed after the aud6 branch absorbed the develop base 8bb344e32 via
25fd3551c. Not taken from any prior run's claims; job 36f3416a (repair lane
LAUD6, 2026-09-23). The prior repair attempt at this job died at startup with
zero tree changes, so this record is the first verification made at this head.

- `uv run pytest packages/maistro-core/tests/tasks/test_requested_cancellation.py -q`
  → 10 passed; re-run 3× in one invocation (30 test executions), all green.
- `uv run pytest packages/maistro-core/tests/tasks -q` → 319 passed.
- Bite check, re-derived here: throwaway copy of the head in `/tmp/bite1242`
  with the execution-stop block of `TaskQueue.cancel` replaced by `return True`
  (restoring the audited receipt-only terminalization), run via
  `PYTHONPATH=/tmp/bite1242/src uv run pytest ... -o pythonpath=`: **4 failed /
  6 passed** — `test_cancel_stops_the_running_work`
  (`AssertionError: the executor ran to completion after cancel`),
  `test_cancel_does_not_report_success_before_work_settles`,
  `test_cancelled_work_cannot_attach_a_late_failure`,
  `test_a_cancelled_receipt_keeps_no_result_after_the_work_stopped`. The
  regression bites on exactly the audited defect.
- Full CI-parity suites at this head against a live pgvector pg17 container on
  :55917 (`MAISTRO_TEST_PG_DSN`/`MAISTRO_TEST_DATABASE_URL`, `REQUIRE_AUTH=false`,
  `MAISTRO_DRY_RUN=1`): `packages/maistro-core/tests` → **10702 passed, 46
  skipped, 1 xfailed, 0 failed** in 3m37s; `packages/maistro-server/tests` →
  369 passed (includes DELETE /tasks/{id} → 200 `cancelled: true` and status
  `cancelled`, the product path this fix serves).
- Persistence suite in that run: 624 passed including
  `test_pg_sessions_concurrency.py` (the prior exact-head flake at line 89);
  that file additionally green 5× in isolation back-to-back — the 23b4de340
  DB-clock retention fix holds under repetition on this host.
- Gates at this head: `uv run ruff check .` clean; `uv run ruff format --check .`
  clean (2528 files); nine-package `uv run mypy` Success (831 files);
  `scripts/check-suite-inventory.py --suite packages/maistro-core/tests` ok;
  `scripts/check-doc-links.py` all links resolve.
- No gate weakening, re-proven at this head: `git diff
  8bb344e32..25fd3551c -- .github/ scripts/ pyproject.toml uv.lock
  .pre-commit-config.yaml` is empty, and a regex over the full branch diff for
  added `skip|xfail|deselect` lines finds none (`tests/config/__init__.py` is
  an import-isolation proxy, not a skip).
- Closure-keyword scan over every commit message in
  `8bb344e32..25fd3551c` (subject+body): no `fixes/closes/resolves #NNN`
  forms. No PR body exists for a local branch; no GitHub mutations were made.

## Independent re-verification at the true exact head 9d16dec8e

Job 639fdfa8 (repair lane LAUD6, 2026-09-24). 9d16dec8e is 25fd3551c plus
inventory-note lines only (`git diff --stat 25fd3551c..9d16dec8e` touches two
notes files), so the code under test is identical; every claim below was
executed fresh at 9d16dec8e, not inherited.

- `uv run ruff check .` → clean; `uv run ruff format --check .` → clean.
- `uv run pytest packages/maistro-core/tests/tasks -q` → 319 passed (all ten
  #1242 regression tests among them).
- Bite check, re-derived against the whole pre-fix tree rather than a local
  revert: throwaway worktree at `55f59f334^` (1e52dc174, before the execution
  registry existed), head's `test_requested_cancellation.py` copied in →
  **6 failed / 4 passed**; the headline regression fails with exactly
  `AssertionError: the executor ran to completion after cancel`. The suite
  cannot pass on the audited receipt-only terminalization.
- `uv run pytest packages/maistro-core/tests -q` → **10094 passed, 654
  skipped, 1 xfailed, 0 failed** (2m49s).
- `packages/maistro-server/tests` + canvas + bootstrap + turing + evolve + rsi
  → **2604 passed, 9 skipped, 0 failed**. `packages/hive-conductor/tests/e2e`
  shows 17 fixture errors (`Login failed: Invalid credentials` — needs the
  seeded reference-app stack); environment-dependent, untouched by this
  branch's change surface (queue.py/runner.py/tests/docs).
- Prior-finding residual closed: `test_pg_sessions_concurrency.py` against a
  real Postgres 18 on :5433 (`alembic upgrade head` applied, `MAISTRO_TEST_PG_DSN`)
  → green 3× back-to-back; the 23b4de340 DB-clock retention fix holds here too.
- No gate weakening, re-proven from provenance: none of the aud6-local commits
  (55f59f334, b93ad5925, 847e02916, 3877bcd3f, 23b4de340, 4eb2e75e8 and the
  three notes commits) touch `scripts/`, `quality/`, `.github/` or gate
  configs; the `check-credential-authority` deletions visible in the
  `60862b6c..9d16dec8e` diff are upstream develop state — the file is already
  absent from every merged develop snapshot (ba2f1f077, 71d0c1120, 551c38b5e,
  78bb72906, aa9502100, ffd6fdb16, 8bb344e32).

## Independent verification at exact head 0a52fea57

Job 9594f87d (repair lane LAUD6, 2026-09-25). 0a52fea57 = 60862b6c5 (develop
merge) + this note file's own commits, so the code under test is the merge's.
Every claim below was executed fresh in this round; nothing inherited.

- `uv run ruff check .` → clean; `uv run ruff format --check .` → clean
  (2534 files).
- `uv run mypy` over all six `packages/*/src` trees → Success, 713 files.
- Vulture per-identity ledger gate at this head:
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0, 1415 reviewed
  identities / 1415 findings, baseline base 60862b6c5, candidate 0a52fea572ae.
- `uv run pytest packages/maistro-core/tests/tasks/test_requested_cancellation.py
  -q` → **10 passed**; `uv run pytest packages/maistro-core/tests/tasks -q` →
  **319 passed**.
- Bite check re-derived independently: throwaway worktree at `55f59f334^`
  (1e52dc174), head's `test_requested_cancellation.py` copied in → **6 failed /
  4 passed**; `test_cancel_stops_the_running_work` among the failures. The
  regression suite cannot pass on the audited receipt-only terminalization and
  passes on this head.
- Real-Postgres leg (fresh throwaway `pgvector/pgvector:pg18` container,
  `alembic upgrade head` applied, `MAISTRO_TEST_PG_DSN` set):
  `uv run pytest packages/maistro-core/tests/persistence -q` → **624 passed**;
  the previously flaked `test_pg_sessions_concurrency.py` (line-89 retention
  race) green **5× back-to-back** — the 23b4de340 DB-clock cutoff holds.
- CI-shaped pytest shards (env as in ci.yml:243 — `MAISTRO_TEST_PG_DSN` +
  `MAISTRO_TEST_DATABASE_URL`, `DATABASE_URL` unset, matching formal-
  conformance.yml:115 which scopes `DATABASE_URL` to the Alembic step only):
  `packages/maistro-core/tests` → **10783 passed, 46 skipped, 1 xfailed**;
  `packages/maistro-server/tests` → 369 passed;
  `packages/hive-conductor/backend/tests` → 2667 passed, 1 skipped.
- Full-tree `uv run pytest -x -q` probed twice for the exact-head doctrine and
  stopped on two order/environment artifacts, neither attributable to this
  branch (branch diff vs origin/develop is 8 files: the two #1242 notes,
  pg_sessions.py, queue.py, runner.py, tests/config/__init__.py,
  test_pg_sessions.py, test_requested_cancellation.py — `container.py`,
  `persistence/__init__.py` and every polluting consumer untouched):
  1. With `DATABASE_URL` also exported (over-broad env, not CI's shape),
     `TestGetTaskResult::test_task_with_result_returns_result_body` fails:
     the test calls `queue.set_result` synchronously and `_persist` reaches
     `asyncio.create_task` with no running loop (queue.py:182). Production
     callers all run inside the loop; with `DATABASE_URL` unset (CI) the
     factory is None and the test passes — reproduced green in the CI-shaped
     server shard above.
  2. In CI's env, the full-tree run fails at
     `hive-conductor .../test_auth_throttle_routes.py::
     test_a_forwarded_header_from_a_trusted_proxy_is_used`
     (`assert '10.1.2.3' == '203.0.113.9'`): cross-package settings-cache
     pollution that only exists when maistro-core/server suites share one
     pytest process with hive-conductor — a shape no CI job creates (ci.yml
     shards per package; the only multi-path job, ci.yml:499, combines
     `tests/` + hive-conductor + maistro-design only, and that exact shape
     was run here: 6525 passed, 1 failed — see 3).
  3. That ci.yml:499 shape's single failure is
     `tests/migrations/test_pg_store_wiring.py::
     test_an_unreachable_server_fails_without_leaking_the_password`, whose
     premise is instant ECONNREFUSED on `127.0.0.1:1`. A raw socket probe on
     this host shows connects to port 1 **time out (3×30 s)** instead of
     refusing — a WSL/firewall blackhole — so the test exercises a timeout
     path under load that CI never sees; it passes in isolation (60 s of
     timeouts) and its import path is untouched by this branch.
  Residual: a single-process, whole-tree pytest run is not a CI shape and is
  not green on this host for reasons 2–3; every CI-shaped invocation above is
  green.
- Prior finding "no PR body/ID supplied" — resolved at 44e21388e: PR 1265
  now exists (draft), its supplied body and the live read-only refresh carry
  no closure keywords, and the branch's commit messages scan clean (see the
  44e21388e verification record below).

## Independent verification at exact head 44e21388e

Job 27de3c34 (verify lane LAUD6, 2026-09-25). 44e21388e520f10c6579882e490d178a29197df3
= merge of develop 2c8022fe into aud6; `git diff 2c8022fe..44e21388` is the same
8-file surface as before (2 notes, queue.py, runner.py, pg_sessions.py, 3 test
files) — the develop merge added no code to this branch and touched no gate
(`scripts/`, `.github/`, quality) paths. Every claim below executed fresh in
this round.

- Driver checks (check-0..check-4 logs): `uv sync --locked --extra dev` ok,
  `ruff check .` clean, `ruff format --check .` clean (2546 files), driver
  trio (config, test_pg_sessions.py, test_requested_cancellation.py) →
  **21 passed**, `scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests` → ok (10904 recorded).
- Own run: `uv run pytest
  packages/maistro-core/tests/tasks/test_requested_cancellation.py -q` →
  **10 passed** (3.01 s).
- Bite check re-derived this round in a throwaway dir (no worktree mutation):
  `git archive 1e52dc174` (55f59f334^) sources + head's test file →
  **10 failed / 0 passed**; at head the same file is 10/10 green. The suite
  fully discriminates receipt-only terminalization from the fix.
- Real-Postgres leg: fresh scratch database on the pgvector pg18
  `maistro-postgres` container (127.0.0.1:5433), `alembic upgrade head`
  exit 0, `MAISTRO_TEST_PG_DSN` set: targeted persistence + cancellation +
  config → **24 passed**; `test_pg_sessions_concurrency.py` green **5×
  back-to-back** — the line-89 retention race did not recur at this head
  (see `1242-exact-head-retention-clock.md`).
- Closure keywords: `git log 2c8022fe..44e21388 --format='%s|%b'` grep for
  `(fixes?|closes?|resolves?) #[0-9]+` → no matches. Supplied PR 1265 body
  ("Refs #1242. Draft claim-stake for exact branch aud6; independent
  verification and CI remain required.") carries none either, and a read-only
  `gh pr view 1265 --json number,body,headRefOid,isDraft,statusCheckRollup`
  confirmed the live body/head match (draft, headRefOid = this head). This
  resolves the prior round's "no PR body" UNVERIFIED.
- CI status at the read-only refresh: 13 checks SUCCESS (lint-and-type-check,
  security, SAST, pip-audit, postgres pg17/pg18, durable-events,
  strike-ladder, hive-conductor-e2e, formal-conformance, exact-debt-ledger,
  DevSkim, workflow-lint, pr-base) but CI `test`, quality coverage ×3,
  Gate C, integration-scope, MinIO, hive-conductor-e2e-ui and docker-build
  were still IN_PROGRESS with `gates-ran` PENDING — **CI green on the exact
  head remains UNVERIFIED until the rollup settles**.

## Independent verification at exact head c74d5709 (2026-09-25)

Resolves the prior round's "CI green on the exact head remains UNVERIFIED"
and re-proves the line-89 retention stability at the current merge head.

- Driver checks (all exit 0): `uv sync --locked --extra dev`; `ruff check .`
  clean; `ruff format --check .` clean (2551 files); focused trio
  (config, test_pg_sessions.py, test_requested_cancellation.py) →
  **21 passed**; `scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests` → ok (10943 recorded, +2 delta).
- Own run: `uv run pytest
  packages/maistro-core/tests/tasks/test_requested_cancellation.py -q` →
  **10 passed** (2.81 s).
- Bite check re-derived in a throwaway dir (no worktree mutation):
  `git archive 55f59f334^` (1e52dc174) sources + head's test file →
  **10 failed / 0 passed**; at head the same file is 10/10 green. The suite
  discriminates receipt-only terminalization from the fix.
- Real-Postgres leg: `aud6-v1242-pg` (127.0.0.1:5599, pg18, migrated),
  `MAISTRO_TEST_PG_DSN` set: `test_pg_sessions_concurrency.py` green
  **6× back-to-back** — the line-89 retention race did not recur;
  `packages/maistro-core/tests` → **10826 passed / 116 skipped / 1 xfailed**
  (273 s); `packages/hive-conductor/backend/tests` → **2718 passed /
  6 skipped** (85 s).
- Closure keywords: `git log 8440274..c74d5709 --format='%s|%b'` grep for
  fixes/closes/resolves → no matches. Live read-only
  `gh pr view 1265 --json number,body,headRefOid,isDraft,statusCheckRollup`:
  body "Refs #1242. Draft claim-stake…", draft, headRefOid = this head.
- **CI green on the exact head VERIFIED**: statusCheckRollup all SUCCESS —
  CI `test`, `lint-and-type-check`, quality `coverage` ×3 + Quality gate +
  Coverage gate, Gate C, integration-scope, postgres pg17/pg18,
  durable-events, strike-ladder, hive-conductor-e2e(-ui), docker-build,
  formal-conformance, Compliance registry, exact-debt-ledger, DevSkim, SAST,
  pip-audit, workflow-lint, pr-base, `gates-ran` SUCCESS; only the
  conditional "Container scan + SBOM + cosign" is SKIPPED.
- Residual, not a regression of this branch: one full-repo combined
  `uv run pytest -x -q` run (all testpaths, single process) hit
  `hive-conductor/backend/tests/test_auth_throttle_routes.py::
  TestTheClientKeyCannotBeSpoofed::test_a_forwarded_header_from_a_trusted_proxy_is_used`.
  The same file passes alone and the whole hive-conductor suite passes alone;
  `packages/hive-conductor/` has zero diff at this head. Mechanism: multiple
  top-level `config` modules across packages
  (hive-conductor/backend/config.py, maistro-turing/backend/config.py,
  maistro-core/tests/config) share one `sys.modules['config']` slot in a
  combined run, so a `get_settings` cache cleared against one module object
  is not the one `routes.auth` read. CI deliberately runs one pytest
  invocation per package (`quality.yml` "pytest with coverage" step, comment
  at lines 128-134), so no CI lane exercises that combination. Recorded so
  future combined-run flakes here are not misattributed to task/persistence
  changes.

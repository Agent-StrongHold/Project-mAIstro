---
inventory-delta:
  packages/maistro-core/tests: +23
  packages/maistro-server/tests: +2
---

Closes the cross-replica task-visibility gap (#1690): `GET /v1/tasks/{id}`,
`GET /v1/tasks/{id}/result` and `DELETE /v1/tasks/{id}` no longer answer only
from the accepting replica's in-process `TaskQueue`.

`packages/maistro-core/tests` (+23) splits across four files:

- `tests/runs/test_find_run_by_task_id.py` (+4) — the new
  `find_run_by_task_id` store read answers identically on all three backends
  (in-memory scan, SQLite `json_extract`, PostgreSQL JSONB provenance
  expression; the PostgreSQL leg skips without `MAISTRO_TEST_PG_DSN`), a
  foreign `admission_source` filter does not answer a task receipt id, a miss
  is a plain `None`, and the test's own assumption that the foreign source is
  the chat admission source is pinned.
- `tests/tasks/test_cross_replica_receipt_reads.py` (+18) — two `TaskQueue`
  "replicas" over one shared canonical Run store and one shared durable
  TaskRecord sink, no in-memory state in common: a replica that never admitted
  the task answers `get_shared` with the same receipt identities (including
  when the fire-and-forget TaskRecord write has not landed — the SIGKILL
  case, answered from the Run alone); the landed row serves a replica on its
  own; a foreign principal gains nothing through either durable source;
  terminal Run truth converges the projection and a stale durable success
  over a failed Run is not resurrected; a non-terminal Run caps a
  terminal-claiming row at not-done (the stale row replaces the landed one in
  place, so the demotion branch is exercised deterministically); cancellation
  works from a replica holding no receipt, through the same canonical Run
  authority, with the owning replica's refused transition reconciling its
  projection; a claim-lost dispatcher's dropped receipt reads the winner's Run
  truth; a read with no durable source is a plain miss; a malformed run
  payload answers nothing; an admitter store outage degrades to the durable
  row verbatim; a queue with no admitter and an admitter predating the finder
  degrade the same way; the pure owner rule (provenance user_id, else the
  task payload's, else none) is pinned; an ownerless Run is visible only to
  empty scoping; `cancel_shared`'s local half is `cancel` unchanged; and a
  durable receipt with no Run behind it is refused cancellation rather than
  fabricated an anchor; the projection pins the Run identity over a
  disagreeing row; and the provenance read is scoped to the task queue's own
  admission source.
- `tests/tasks/test_workspace_routing.py` (+1) — the workspace-routing
  admitter resolves a task receipt id through its default binding, the same
  Workspace-independent way it resolves a run id.
- `tests/tasks/test_admission.py` (±0) — the duplicate-delivery loser now
  asserts its unauthoritative receipt is dropped (reads fall through to the
  durable projection) instead of parked stale in memory; same node count.

`packages/maistro-server/tests` (+2) — `test_task_cross_replica_visibility.py`
is the two-process durable composition the issue requires: real
maistro-server subprocesses over one migrated PostgreSQL, requests alternated
across their ports the way the load balancer alternates across replicas. The
first test covers the full failover arc — a task admitted through replica A
read back through replica B (which never saw the POST), replica A SIGKILLed
while the task is still QUEUED with the receipt remaining queryable, two fresh
replicas recovering and racing the same task with the canonical consumer claim
deciding a single owner (one execution, one NodeRun, one Attempt on the
spine), load-balanced polling answering 200 through every door until terminal,
and an idempotent resubmission replaying the original admission (#1176)
without executing again. The second pins authorization end to end: a foreign
authenticated principal gets 404s on every read shape through the durable tier
and the per-replica listing never leaks the task. Both skip without
`MAISTRO_TEST_PG_DSN`.

## Re-validation 2026-10-24 (head ab69178370ab)

Independent re-run of the full battery at the exact head this note ships on
(pgvector:pg18 `pgvector/pgvector:pg18` @ 127.0.0.1:5590, `alembic upgrade head`
clean before pytest):

- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- `uv run pytest packages/maistro-core/tests/tasks -q` → **542 passed**
  (includes the 18 projection/cancellation reads and the 4-file +23 delta
  above).
- `uv run pytest packages/maistro-core/tests/runs -q` → **1659 passed,
  3 skipped**; `tests/runs/test_find_run_by_task_id.py` → **4 passed** with the
  PostgreSQL JSONB leg active.
- `uv run pytest packages/maistro-server/tests/test_task_cross_replica_visibility.py -v`
  → **2 passed in 13.15s**; `test_task_restart_recovery.py -v` → **1 passed**.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests` and `--suite packages/maistro-server/tests` →
  both ok (recorded inventory still matches collection).
- `uv run mypy` (canonical 7-package command) → Success, 905 source files.

Residual, **pre-existing at the develop base** `4de7e906d` (not this diff):
three server tests fail only when `DATABASE_URL`/`MAISTRO_TEST_PG_DSN` is set —
`api/test_tasks.py::TestGetTaskResult::test_task_with_result_returns_result_body`
(`_persist` calls `asyncio.create_task` from the sync `set_result` test path,
`RuntimeError: no running event loop`) and the two
`api/test_taskrunner_quota_ledger.py` cases (`request_count` 4 vs 1 with a DB
configured). Both reproduce identically at `4de7e906d` in a detached checkout
with the same env, and both pass without the env — an environment-coupled
hazard of the #91/#849 durable-receipt wiring, recorded here so it is not
re-diagnosed as a #1690 regression.

## Re-validation 2026-10-24 (head 35055b17833a)

Independent re-run at the current merge head (pgvector:pg18 @ 127.0.0.1:5590,
`alembic upgrade head` clean before pytest):

- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- `uv run pytest packages/maistro-core/tests/runs/test_find_run_by_task_id.py
  packages/maistro-core/tests/tasks/test_admission.py
  packages/maistro-core/tests/tasks/test_cross_replica_receipt_reads.py
  packages/maistro-core/tests/tasks/test_workspace_routing.py
  packages/maistro-server/tests/test_task_cross_replica_visibility.py
  packages/maistro-server/tests/test_task_restart_recovery.py -q` (with
  `MAISTRO_TEST_PG_DSN` set) → **101 passed**.
- `uv run pytest packages/maistro-server/tests/test_task_cross_replica_visibility.py -v`
  → **2 passed**; `test_task_restart_recovery.py -v` → **1 passed**.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`
  and `--suite packages/maistro-server/tests` → both ok.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → 1302 findings, ratchet ok.
- `uv run python scripts/check-radon-baseline.py` → 127 blocks, ratchet ok.
- `uv run python scripts/check-promotion-surface.py` / `check-reachability.py` → ok.
- `uv run mypy` (canonical 7-package command) → Success, 937 source files.

The three env-coupled server failures recorded above reproduce identically at
the develop base `4de7e906d` in a detached checkout with the same env, so they
are not #1690 regressions.

## Re-validation 2026-10-24 (head 15a051f366e0)

Final repair pass on the exact head above (pgvector:pg18 @ 127.0.0.1:5590,
`alembic upgrade head` clean before pytest):

- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- `uv run pytest packages/maistro-core/tests/runs/test_find_run_by_task_id.py
  packages/maistro-core/tests/tasks/test_admission.py
  packages/maistro-core/tests/tasks/test_cross_replica_receipt_reads.py
  packages/maistro-core/tests/tasks/test_workspace_routing.py
  packages/maistro-server/tests/test_task_cross_replica_visibility.py
  packages/maistro-server/tests/test_task_restart_recovery.py -q`
  (with `MAISTRO_TEST_PG_DSN` set) → **101 passed**.
- `uv run pytest packages/maistro-server/tests/test_task_cross_replica_visibility.py -v`
  → **2 passed**; `test_task_restart_recovery.py -v` → **1 passed**.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`
  and `--suite packages/maistro-server/tests` → both ok.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → 1302 findings, ratchet ok.
- `uv run python scripts/check-radon-baseline.py` → 127 blocks, ratchet ok.
- `uv run python scripts/check-promotion-surface.py` / `check-reachability.py` /
  `check-wiring-reads.py` → ok.
- `uv run mypy` (canonical 7-package command) → Success, 937 source files.
- `TaskQueue._persist` is now loop-safe for sync callers (`set_result`,
  `update_progress`, `settle_terminal_receipt`): it skips the fire-and-forget
  write when no event loop is running instead of raising
  `RuntimeError: no running event loop`; the durable tier converges from the
  canonical Run on the async paths. `GET /tasks/{id}/result` now resolves on
  a replica that never held the receipt.

## Re-validation 2026-10-24 (head a71b9a7f8e0a)

`a71b9a7f8e0a` is a docs-only commit over `15a051f366e0` (one inventory-note
file), so the code evidence carries over; every command below was re-run
first-hand at that exact head (pgvector:pg18 @ 127.0.0.1:5590, migrated):

- `uv run pytest packages/maistro-server/tests/test_task_cross_replica_visibility.py -v`
  with `MAISTRO_TEST_PG_DSN` → **2 passed in 14.04s** — the two-process
  composition: replica-B 200 on a task it never admitted, SIGKILL of the
  accepting replica before claim, two gated replicas recovering and racing
  the same task to exactly one execution / one NodeRun / one Attempt on the
  spine, every door answering 200 through terminal, idempotent replay
  executing nothing (#1176); and the foreign-principal 404s end to end.
- The five remaining targeted files (`runs/test_find_run_by_task_id.py`,
  `tasks/test_admission.py`, `tasks/test_cross_replica_receipt_reads.py`,
  `tasks/test_workspace_routing.py`,
  `server/test_task_restart_recovery.py`) with the DSN → **99 passed**.
- `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -q` → **2093 passed, 365 skipped**.
- `uv run pytest packages/maistro-server/tests -q` (whole suite) →
  **644 passed, 8 skipped** beyond the E2E file above.
- Root tests around the branch surface (`tests/test_check_frontend_api_routes.py`,
  `tests/migrations/test_migration_chain.py`, the first eleven
  `tests/test_a*` files incl. the autonomous-merge/quality classes the CI
  log showed) → **385 passed, 18 skipped**, no `Event loop is closed`
  reproduction.
- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests` and `--suite packages/maistro-server/tests`
  → both ok; `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → 1302 identities, ratchet ok;
  `check-radon-baseline.py` → 127 blocks, ratchet ok;
  `check-promotion-surface.py` / `check-reachability.py` /
  `check-wiring-reads.py` → ok; `mypy` (canonical 7-package command) →
  Success, 937 source files.

Hosted-CI residual at this head, **not from this branch**: the failing
`Container scan + SBOM + cosign`, `SAST / Gitleaks` ("dependency did not
succeed"), `security` / `Supply chain (pip-audit)` ("produced no usable
report after 3 attempts … registry/network outage"), and `test` (npm audit)
jobs all have inputs this diff never touches — `git diff 4de7e906d..HEAD
--name-only` lists no `package.json`, `package-lock.json`, `Dockerfile*`,
workflow, or `uv.lock` file. Reproduced locally: `npm audit --audit-level=high`
fails on the unchanged frontend lockfiles (zod < 4.6.6,
GHSA-mrhx-c7xc-m3w5, published after the base pins; `npm ci` itself exits 0),
so the identical tree at the develop base fails these jobs the same way.
They are trunk/environment failures to retry or fix on the trunk, not
blocking evidence against this change.

## Repair 2026-10-24 (head cd0eadd028a6) — SAST / Gitleaks

The gitleaks failure **was** from this branch: the `pull_request` scan mode
(`gitleaks git --log-opts="$BASE_SHA..$HEAD_SHA"`, security.yml `sast-gitleaks`)
scans the branch's own commits, and commit `593295177` assigned two synthetic
principal literals — secret-shaped values on `*_token` variables, spelled with
the literals recorded in the fingerprints below — in the auth-composition
test. (Quoting the flagged lines verbatim here would re-trip the rule, as
`.gitleaksignore`'s own header notes.) Two `generic-api-key` findings,
reproduced locally with the pinned gitleaks 8.30.1 and the exact CI argv.
Repair, per the `.gitleaks.toml` guidance that
secret-shaped lines in code are fixed at source:

- `test_task_cross_replica_visibility.py` renames the variables to
  `alice_bearer`/`mallory_bearer` and the values to principal-shaped strings
  (`alice-principal-1690`/`mallory-principal-1690`) so no line presents a
  credential shape; the test is behaviorally unchanged (the `API_KEYS` stub
  matches values, not shapes).
- `gitleaks git` scans each commit's own patch, so the range scan keeps
  reporting the introducing commit until history is rewritten, which a PR
  branch must not do — the two fingerprints of `593295177` are recorded in
  `.gitleaksignore` (the mechanism the repo already uses for exactly this,
  cf. the `de04b449` allowlist rationale in `.gitleaks.toml`).
- Verified: `gitleaks git --log-opts="4de7e906d..HEAD"` → **no leaks found**;
  the untouched-file finding set is otherwise unchanged.

First-hand battery at `cd0eadd028a6` (pgvector:pg18 @ 127.0.0.1:5590,
`alembic upgrade head` clean before pytest), **re-confirmed at the branch
tip** — every commit after `cd0eadd02` differs only by `.gitleaksignore`
entries and this note, and the gitleaks range scan at the tip reports no
leaks (the two historical patches are fingerprinted, not rewritten):

- `uv run pytest packages/maistro-server/tests/test_task_cross_replica_visibility.py -v`
  with `MAISTRO_TEST_PG_DSN` → **2 passed in 14.04s** (the renamed auth test
  among them); the six-file targeted battery → **101 passed**.
- `uv run pytest packages/maistro-core/tests/tasks -q` → **670 passed,
  3 skipped**.
- Whole `packages/maistro-server/tests` **without DB env** (CI's env for the
  `test` job's server step) → **644 passed, 10 skipped**.
- `uv run ruff check .` / `uv run ruff format --check .` → clean;
  `check-suite-inventory.py` for both touched suites → ok;
  `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → 1302 findings == 1302 reviewed, ratchet ok;
  mypy (canonical 7-package command) → Success, 937 source files.

Correction to the env-coupled residual above: at this head the
`api/test_tasks.py::TestGetTaskResult` case **passes** with DB env (the
`_persist` loop-safety fix), while
`test_main.py::TestCanvasAbilityWiring::test_the_lifespan_without_a_database_wires_nothing`
joins the two quota-ledger cases in failing — only in full-suite runs, and
**identically at the develop base `4de7e906d`** (re-run in a detached
worktree with the same env: same 3 failures; each passes in isolation at
both heads). All three are pre-existing suite-interference artifacts of the
#91/#849 durable-receipt wiring, not #1690 regressions.

Remaining hosted-CI failures at `06cda0c3`, each pinned to the trunk with
first-hand evidence (read-only `gh` queries of the runs at both heads):

- `test` job: every pytest step and the OpenAPI-types freshness step pass;
  the job fails at `npm audit --audit-level=high` on the unchanged canvas
  frontend lockfile. **Fixed this round** — see the repair below.
- `Supply chain (pip-audit)` / `security`: `fastmcp==4.0.11`
  (GHSA-7xgj-8392-5q4r, GHSA-vqqp-x5qm-5qp4 → 4.1.2) and `setuptools==84.0.0`
  (GHSA-xmj3-9gf7-h52w → 84.1.0) — locked-dependency advisories published
  after the base pins; this diff adds no dependency.
- `SAST / Gitleaks` on **develop pushes** fails independently via the
  `--all` history mode (34 pre-existing findings in files/commits this
  branch never touches; the PR range mode is the one this PR owes and it is
  green after the repair above).
- Same-named jobs fail on develop's own head `4de7e906d9` (this PR's base):
  security.yml run 40033451919 → Supply chain (pip-audit), SAST / Gitleaks,
  SAST (bandit + semgrep + gitleaks); ci.yml run 40033451855 → test,
  security. ci.yml was green at `161dedc063` the same day, pinning the
  breakage's arrival to trunk dependency data, not this branch.

## Repair 2026-10-24 (head 3994c8e039f6 +1) — the `test` job's npm audit gate

The gate named by this repair round. Reproduced first-hand at the branch tip:
`npm audit --audit-level=high` in `packages/maistro-canvas/frontend` exits 1
with 6 advisories (3 high: body-parser GHSA-27r3-jxmh-p828, undici
GHSA-4qv8-2p9j-2685/GHSA-f72v-6w45-q472/GHSA-xjj6-f33q-929c, zod
GHSA-mrhx-c7xc-m3w5; 3 moderate: @vitest/mocker, ip-address). All are in-range
semver fixes; `npm audit fix` (no `--force`) updates only
`packages/maistro-canvas/frontend/package-lock.json` — package.json is
untouched, so the dependency contract itself does not move.

Every CI `test`-job step for that tree re-proven first-hand against the fixed
lockfile (node 22.22.1 / npm 9.2.0, the CI versions' majors):

- `npm ci` → clean install, 0 vulnerabilities (also proves lock ↔ manifest
  sync).
- `npm run test:ci` → **79 passed** (5 files).
- `npm run lint` → 0 errors (13 pre-existing warnings; the CI step sets no
  `--max-warnings`).
- `npm run build` → succeeds.
- `npm audit --audit-level=high` → **exit 0, 0 vulnerabilities** (re-run after
  the clean `npm ci`).

The canvas frontend's npm tree enters no container image (root `Dockerfile:106`
installs the maistro-canvas *wheel*; `Dockerfile:191` notes the wheel carries
no on-disk frontend), so this lockfile cannot move the `Container scan` job.

Correction to the residual list above: the `Container scan + SBOM + cosign`
job does **not** fail on npm audit (its `npm audit fix` log lines are npm's
informational report from `npm ci`); the failing step is `Trivy scan
maistro-engine-research (HIGH/CRITICAL only)` — re-pinned first-hand via the
job's step list at both this branch's head and develop's `4de7e906d9`
(security.yml run 40092758331, the latest at repair time — still failing
identically on the base head, as are `Supply chain (pip-audit)` at the
pip-audit gate step and the full-history Gitleaks jobs). Those three gates
remain trunk residuals with inputs (`uv.lock`, `Dockerfile.research`) this
diff never touches.

Re-confirmed at the repair commit, tree otherwise identical to `3994c8e039f6`:
`uv run ruff check .` / `ruff format --check .` → clean; the six-file targeted
battery → **90 passed, 11 skipped**; `check-suite-inventory.py` for
`packages/maistro-core/tests` and `packages/maistro-server/tests` → both ok
(no test added or removed; the frontmatter delta above is unchanged).

## Repair 2026-10-24 (head ad40a37561b4) — the named `Container scan` gate, and
the E2E foreign-principal leg

The gate this round names is `Container scan + SBOM + cosign`. It **was**
failing at `55f506401948`, and it is **green at the current head**
`ad40a37561b4` — not by a change to this diff, but because the develop sync
this branch already carries supplies the fix. The step-level evidence, read
from the two jobs rather than inferred:

- Failing job `120902903427` (`actions/runs/40104376632`, head
  `55f506401948`): **every** build, Trivy, Grype, frontend and SBOM step
  passed; the failure is step 22, `Reconcile installed packages to uv.lock`,
  whose log line is
  `version mismatch : beartype==0.22.9 (image) != beartype==0.23.1`.
  The lock splits `beartype` across `python_full_version` markers, the
  Python 3.13 image correctly ships the `<'3.15'` pin, and the then-current
  `scripts/check-image-lock-reconciliation.py` keyed pins by name alone and
  kept only the last line's version.
- The develop commit `f956a814275c` (`#2285`), merged into this branch at
  `ad40a37561b4`, is the fix: `scripts/check-image-lock-reconciliation.py`
  now keeps every version per name and accepts whichever the environment
  selects (`_expected_clause`, split-pin sets). Same commit also adds the
  `.trivyignore` `CVE-2026-111497` entry and bumps the hive-conductor
  frontend lockfile.
- At the branch tip the gate passes: job `120916183586` (security.yml run
  `40108870387`), `completed`/`success` at `2026-10-24T16:11:31Z`, with step
  22 `Reconcile installed packages to uv.lock` → `success`. A live `gh api
  repos/Agent-StrongHold/Project-mAIstro/commits/ad40a37561b4.../check-runs`
  at repair time returns 70 `success`, 2 `skipped` (MinIO / durable-events,
  services this job does not need) and 1 `in_progress` (`Coverage gate`) —
  **zero failures**.

Correcting the paragraph above it: the earlier attribution of this job's
failure to `Trivy scan maistro-engine-research` was wrong — all four Trivy
steps passed at `55f506401948` (step list of job `120902903427`). The
failing step was the `uv.lock` reconciliation, and the develop sync above is
what closes it. Nothing in this branch's own diff (`git diff
f956a814275c...ad40a37561b4 --name-only`) feeds that step: its inputs are
`uv.lock`, the Dockerfiles and the reconciliation script, none of which this
branch touches. (The canvas frontend `package-lock.json` this branch does
carry feeds only the job's `Build frontend license surfaces` step, which
passed at both heads.)

### E2E foreign-principal leg now reads through a peer replica

The issue's first acceptance clause pairs "read from either replica,
authorized as the originating principal" with "foreign principals cannot
gain visibility through the durable lookup". The authorization half was
pinned only against the *admitting* replica, whose live receipt answers
`get()` before any durable lookup runs — so the projection's own owner check
was never exercised end to end, and the module docstring's "from a
differently-keyed replica" was not true of the code.
`test_a_foreign_principal_cannot_read_a_task_through_the_durable_tier` now
spawns a **stock peer replica first** (its startup recovery has nothing to
pick up, so it never admits or dispatches this task), submits through the
admitting replica, and asserts:

- Alice (originating principal) reads the **same** `task_id`, `run_id` and
  `queued` state through the peer, which holds no receipt for it;
- Mallory gets 404 on `GET /v1/tasks/{id}`, `GET .../result` and `DELETE`
  through **both** doors, and never sees the task in either replica's
  listing.

Both halves were shown load-bearing by mutation at this head (each mutation
applied, the test run, the file restored byte-identically — `git status`
shows only the test edit):

- `get_shared` → durable lookup unscoped (`_shared_receipt(..., user_id=None)`)
  ⇒ **fails** at `assert 200 == 404` (Mallory reads Alice's receipt through
  the peer): the peer's denial is the durable owner filter, not the absence
  of a local receipt.
- route read → pre-#1690 `queue.get` ⇒ **fails** at `assert 404 == 200` on the
  peer: the Alice assertion is the shared read, not process memory.

### Re-validation at ad40a37561b4 (pgvector:pg18 @ 127.0.0.1:5590)

`alembic upgrade head` clean at revision `068` before pytest:

- `uv run pytest` over the six-file targeted battery (this suite's two cases
  among them, `MAISTRO_TEST_PG_DSN` set) → **101 passed**.
- `uv run pytest packages/maistro-server/tests/test_task_cross_replica_visibility.py -v`
  → **2 passed in 14.86s** (the extended peer leg included); without the DSN
  the same file → **2 skipped**, unchanged.
- `uv run ruff check .` / `uv run ruff format --check .` → clean (the edited
  test file was reformatted by `ruff format` before the battery re-run).
- `check-suite-inventory.py` for `packages/maistro-core/tests` and
  `packages/maistro-server/tests` → both ok. No test added or removed, so the
  front-matter delta above is unchanged.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` → 1302 reviewed == 1302 findings, ratchet ok;
  `check-radon-baseline.py` → 127 == 127; `check-promotion-surface.py`,
  `check-reachability.py` (1459 modules), `check-wiring-reads.py` (11 == 11)
  → ok; `check-deployment-claims.py` and `check-doc-links.py` (2980 files, 0
  broken) → ok; `mypy` (canonical 7-package command) → Success, 937 source
  files.

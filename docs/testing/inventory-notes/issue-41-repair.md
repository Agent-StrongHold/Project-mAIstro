---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  tests/: +1
---
# Issue 41 repair

Added one Hive Conductor regression test proving the demo LocalTaskBackend
passes the canonical task-admission claim store into TaskQueue, and one live
PostgreSQL migration-chain test proving migration 034 refuses a table whose
column names match but whose type/default does not.

## Round 2 (verification pass, lane auto-41)

Live-PostgreSQL validation against a fresh pgvector/pg18 server exposed two
real failures that the recorded findings missed:
`TestTheChainSurvivesRuntimeSelfProvisioning::test_upgrade_head_adopts_the_runtime_provisioned_table`
and `::test_adopts_runtime_provisioned_table_without_a_primary_key` both
asserted `alembic_version == [("038",)]` after `upgrade head`. That literal was
written when 038 was the chain tip; the reconciliation onto develop's chain
(`038 -> 039 -> 040 -> 036_audit_log_org_scope`) moved the tip, so the
production upgrade reached head correctly while the tests kept demanding the
old revision id.

Fix: both assertions now compare against `_head_revision()`, resolved from
`alembic heads` at run time, so the assertion stays about "the upgrade stamped
the chain's head" rather than about a revision number that belongs to history.
The behavioral checks those tests exist for (claim columns, expiry index,
primary-key reconstruction) were already asserting correctly and are untouched.
No production code changed in this round; all 15 tests in the file pass against
a live server, and `scripts/check-suite-inventory.py` records the consolidated
delta in `auto-41-5cc9.md`.

## Round 3 (final validation record, head 03f512946)

Full battery re-run at the finished head; no code changed, evidence only.
Against a fresh pgvector/pg18 server (`MAISTRO_TEST_DATABASE_URL`):
`tests/migrations/test_migration_chain.py` 15 passed — `EXPECTED_TABLES`
matches the live catalog exactly, and all four runtime-self-provisioning
scenarios (adoption, PK-less adoption, incompatible-type refusal, foreign-shape
refusal) behave as asserted. The chain applies `038 -> 039 -> 040 ->
036_audit_log_org_scope` to head on a clean database. With the chain applied and
`MAISTRO_TEST_PG_DSN` set, `test_idempotency_durable.py` 27 passed including the
real-server reconcile test (`quota_usage` requires the full schema, which is why
the DSN-only run must follow `alembic upgrade head`). Sans DSN, the core tasks
suite is 333 passed / 1 skipped, `test_tasks_idempotency.py` 13 passed,
maistro-server API 359 passed, integration E2E 5 passed,
`packages/maistro-core/tests/runs` + `graph/durable_runs` 1324 passed / 224
skipped, hive-conductor 2661 passed / 1 skipped. `ruff check`,
`ruff format --check`, the six-package mypy command from AGENTS.md (713 files),
`check-suite-inventory.py`, `check-doc-links.py`, and
`check-durable-table-inventory.py` all pass. Residual (out of tree scope):
issue tracker closure of #1176 is a GitHub mutation workers are prohibited from
performing; the code contract it owns is implemented and proven here.

## Round 4 (repair pass, lane auto-41)

Addressed the recorded findings against this head:

- **EXPECTED_TABLES / live migration chain (finding 1).** Already repaired on
  this branch by `eb6b7b36b` (chain-owned tables only; runtime-provisioned
  capability/workspace-lifecycle tables excluded). Re-verified against a fresh
  pgvector/pg18 server: `tests/migrations/test_migration_chain.py` 15 passed —
  `EXPECTED_TABLES` matches the live catalog exactly, head stamps via
  `_head_revision()`, and all four runtime-self-provisioning scenarios behave
  as asserted.
- **038 reconcile-path validation (finding 3).** Already repaired on this
  branch: full shape check (compiled type names, nullability, `completed_at`
  zero default, `scope_key` PK reconstruction, expiry index) plus loud refusal
  of foreign shapes. The salvaged uncommitted hunk comparing compiled type
  names (`str(actual["type"]).upper() != str(expected.type).upper()`) is kept
  and the file's `CLAIM_COLUMNS` comment updated to describe it: live
  PostgreSQL reflection hands back exactly `sqltypes.TEXT`/`sqltypes.BIGINT`
  (verified on the live server), so the comparison matches a real reconcile
  byte-for-byte while tolerating a dialect subclass that compiles to the same
  DDL. No gate weakened: missing columns, nullability, default, PK and index
  checks are untouched and still refuse.
- **Stale revision references.** The renumbering left `migration 034` docstring
  pointers in `maistro/tasks/idempotency.py` (the revision is now 038;
  `034_hitl_deadline_index` is unrelated). Corrected. Noted, out of this
  issue's scope: `capabilities/invocation_store.py` cites revision 034 for the
  capability schema, which now lives in `035_capability_invocations`.
- **LocalTaskBackend idempotency wiring (finding 2).** Already implemented:
  `LocalTaskBackend.__init__` takes `idempotency_store` and hands it to
  `TaskQueue`; the server (`main.py`) and conductor engine pass the container's
  claim store. Proven by the suites below.
- **#1176 tracker state (finding 4).** The issue remains open on GitHub;
  closing it is a GitHub mutation this worker is prohibited from performing.
  The durable admission-idempotency contract it owns is implemented and proven
  here.

## Round 5 (verification pass, head 50fa8824d, no code changed)

All four prior findings re-validated against the current head and confirmed
resolved. Finding 1 (EXPECTED_TABLES vs live catalog): fresh pgvector/pg18
container (port 5591), `tests/migrations/test_migration_chain.py` 15 passed.
Finding 2 (demo backend idempotency): `engine.py` passes
`container.task_idempotency` into `LocalTaskBackend(idempotency_store=...)`;
`test_engine_service.py` proves the store reaches `TaskQueue`; backend suite
2716 passed / 6 skipped. Finding 3 (038 reconcile validation): full shape
check (compiled types, nullability, zero default, PK reconstruction, expiry
index) with loud foreign-shape refusal, all four scenarios proven live.
Finding 4 (#1176 open): the issue is now CLOSED on GitHub (verified read-only;
no mutation performed).

Full battery at this head: `ruff check .`, `ruff format --check .` (2545
files), six-package mypy (713 files) clean; with the chain applied and
`MAISTRO_TEST_PG_DSN` set, `packages/maistro-core/tests/runs` + `tests/tasks`
1397 passed / 3 skipped; `packages/maistro-server/tests` 375 passed;
`packages/hive-conductor/backend/tests` 2716 passed / 6 skipped;
`tests/integration` (chat→graph E2E) 5 passed. Gates exit 0:
`check-vulture-baseline.py` (1415 reviewed = 1415 banked, unclassified 0),
`check-durable-table-inventory.py`, `check-wiring-reads.py`,
`check-execution-lifecycles.py`, `check-suite-inventory.py`, and
`check-m1-convergence-freeze.py --base 55c5ad892e68bdd015db00ebe034ea6818a8c1f5`.
Environment note (not a tree defect): an untracked root `.env` with a
non-JSON `API_KEYS` breaks any suite/gate that imports `Settings` when run
from the repo root (dotenv parse error); validation was run with that file
briefly set aside (restored byte-identical) or from a dotenv-free CWD.

Round 4 record (superseded in place, kept for provenance): fresh evidence at
that round's head (dedicated pgvector/pg18 container, port 55491):
`test_migration_chain.py` 15 passed (live);
`test_idempotency_durable.py` 27 passed (`MAISTRO_TEST_PG_DSN`, chain at head);
core tasks 333 passed / 1 skipped; `test_tasks_idempotency.py` 13 passed;
`maistro-core/tests/integration` 5 passed (chat→graph E2E);
`test_engine_service.py` 35 passed; `ruff check`, `ruff format --check`, mypy
on `maistro/tasks/idempotency.py`, `check-suite-inventory.py`,
`check-doc-links.py`, `check-durable-table-inventory.py` all clean.

## Round 6 — independent verification at 955050394 (develop merged in)

Head under review: `9550503945ea97db479816b35293275fcb9abe2c` (merge of
develop `55c5ad892e68bdd015db00ebe034ea6818a8c1f5` into auto-41). All checks
below were executed this round by the verifier against the dedicated pg18
container at `127.0.0.1:5591` (`auto-41-repair-pg`), from a dotenv-free CWD
because the untracked root `.env` (non-JSON `API_KEYS=test`) still breaks any
`Settings`-importing suite started at the repo root — environment, not tree.

Executed battery (all green):
- `test_idempotency_durable.py` + `test_tasks_idempotency.py` live-PG:
  40 passed / 0 skipped (driver's check-3 ran them DSN-less: 91 passed /
  1 skipped — the durable tier only runs with `MAISTRO_TEST_PG_DSN`).
- Acceptance battery: `tasks/test_admission.py`, `runs/test_chat_admission.py`,
  `runs/test_execution_is_correlated.py`, `integration/test_chat_to_graph_e2e.py`:
  67 passed. `hive-conductor test_chat_run_admission.py`: 20 passed.
- `packages/maistro-core/tests/runs` (migrated chain, live PG):
  1063 passed / 3 skipped. Procedural note: one intermediate run showed
  4 failed / 567 errors solely because `test_migration_chain.py`'s
  `empty_database` fixture leaves the shared database downgraded to `base`;
  after `alembic upgrade head` the same suite is fully green. Re-migrated and
  re-run before recording.
- `tests/migrations/test_migration_chain.py` live: 15 passed.
- `ruff check .`: clean (driver check-1; re-run confirmed). Driver also ran
  `ruff format --check .`, `test_engine_service.py` (35 passed) and the three
  `check-suite-inventory.py` gates (2725 / 10927 / 375) — all ok.

Governance checks: PR #1325 body contains no closure keywords ("Refs #41"
only); commit messages 55c5ad892..HEAD scanned — none. Issue #1176 re-checked
read-only: state CLOSED (prior finding stands resolved). Issue #41 OPEN.

Open items (not acceptance-blocking, for the driver/human): PR #1325 is a
draft claim-stake; its CI at this head shows "Quality gate (Pillars 1–4, 7, 8)"
FAILURE with the run still in progress (logs unavailable) and several checks
pending — CI state is UNVERIFIED and was not inferred green. The previous
round's push rejection (non-fast-forward) remains a driver-level action;
workers are prohibited from pushing.

## Round 7 — independent verification at 77d18bdf (develop merged in)

Head under review: `77d18bdf750cdb21046d8fde89aa90185d38c8d3` (merge of develop
`84402748f4ac3df538b0fa85beb33bc991013bb6` into auto-41; the merge touches only
M2-A7 learnings-persistence files, not the #41 admission surfaces — confirmed by
`git diff --stat 4c573dee8..77d18bd`). All checks below were executed this round
by the verifier against the pg18 container at `127.0.0.1:5591`
(`auto-41-repair-pg`), from a dotenv-free CWD where needed because the untracked
root `.env` (non-JSON `API_KEYS`) still breaks any `Settings`-importing suite
started at the repo root — environment, not tree.

Executed battery (all green, this round, this head):
- `tests/migrations/test_migration_chain.py` live PG: **15 passed** (53s) —
  prior finding 1 (EXPECTED_TABLES vs live catalog) stands resolved.
- `alembic upgrade head` on the same DB: chain reaches `036_audit_log_org_scope`
  via 037 -> 038 -> 039 -> 040 -> 036_audit_log_org_scope.
- Idempotency trio with `MAISTRO_TEST_PG_DSN` (`test_idempotency.py`,
  `test_idempotency_durable.py`, server `test_tasks_idempotency.py`):
  **92 passed / 0 skipped** — the durable tier genuinely ran, unlike the
  driver's DSN-less check-3 (91 passed / 1 skipped).
- Acceptance battery `tasks/test_admission.py`, `runs/test_chat_admission.py`,
  `runs/test_execution_is_correlated.py`, `integration/test_chat_to_graph_e2e.py`:
  **67 passed**. Conductor `test_chat_run_admission.py` +
  `test_engine_service.py`: **55 passed**.
- `packages/maistro-core/tests/runs` (migrated chain, live PG):
  **1063 passed / 3 skipped** (61s).
- `packages/maistro-server/tests`: **375 passed** (16s).
- `packages/hive-conductor/backend/tests`: **2719 passed / 6 skipped** (97s).
- `ruff check .` re-run from a dotenv-free CWD: clean. Driver's own checks 0–7
  all green this round (uv sync, ruff check, ruff format --check 2550 files,
  DSN-less idempotency trio 91/1s, engine service 35, inventory gates
  2725/10956/375).
- Production-wiring spot-check at this head: `engine.py:233-235` passes
  `admitter=self.task_admitter, run_store=self.run_store,
  idempotency_store=self.task_idempotency` into `LocalTaskBackend`;
  `maistro_server/main.py:334` wires `idempotency_store=container.task_idempotency`;
  `tasks/queue.py` mints receipts and admits via `TaskRunAdmitter.admit() ->
  run_id` without fabricating Runs when no admitter is wired;
  `runs/admission.py:direct_work_graph` is the one-node Graph seam.

Governance: `gh issue view 1176` read-only = **CLOSED** (finding 4 resolved);
#41 itself OPEN. Closure-keyword scan of the PR body ("Refs #41" only) and all
27 commits in `84402748..77d18bd`: none. PR #1325 `headRefOid` confirmed equal
to the reviewed head via read-only refresh.

Previous block resolved: the round-6 push rejection (non-fast-forward) no longer
stands — after `git fetch origin auto-41`, `git rev-list --left-right --count
auto-41...origin/auto-41` is `0 0`: the remote branch already points at this
head. No push was performed (prohibited).

Outstanding (driver/human, not acceptance-blocking): PR CI at this head has
**Quality gate (Pillars 1–4, 7, 8) = FAILURE** (run 36180011060, job
108219796165) — the same gate that was failing in round 6; its logs are
unavailable while the run is still in progress (Coverage gate job pending), so
the cause is UNVERIFIED and was not inferred either way. 26 other checks are
SUCCESS (incl. postgres pg17/pg18, coverage PostgreSQL, lint-and-type-check,
hive-conductor-e2e); `integration-scope`, `test`, and the Coverage gate were
still in progress at review time.

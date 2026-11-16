---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 bounded CI revalidation — f856

## Frozen scope and disposition

Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`, clean
starting HEAD `8001365aac0cc43c166ea6c279b5cc556b475b19`; supplied and resolved
base `af799688335f9a7dba7999a05e0e13f102c6c5ae`. Only #1893 was processed:
codec, adjacent identity/schema/tests, inventory evidence and the explicitly
permitted vulture identity ledger. No remote changes or re-enumeration.

Read repository instructions, captured issue/PR review evidence, prior result,
and driver check-0 through check-4 logs in job
`/home/dev/maistro/jobs/f8560b27e6b143cbb228be224e8f1b3b`.
Read accepted ADRs 081226-a66b, 082826-b601 and 083126-5e62. Reconciliation:
the explicit lane assignment establishes the local owner/base, not activation
permission. The staged codec cannot acquire a production consumer merely to
silence a gate; candidate banking cannot authorize new reachability debt.
The canonical execution hierarchy and authorization path remain unchanged.

**BLOCKED.** No new source defect or vulture mismatch was established in this
round, so this commit records evidence only. The old bound-encoding defect is
already fixed at the starting HEAD. No cosmetic source edit, new test, ledger
amendment, grant change or gate weakening is justified. There is no sync
conflict to resolve. The remaining failure requires trusted-base coordination,
not another isolated codec repair.

## Executed validation at the starting source

Logs below are in the job directory; these are new executions, not inherited
verification claims.

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **PASS**, 1328 reviewed
  identities / 1328 findings (`repair-vulture.log`). No unbanked or eliminated
  identity requires a ledger amendment.
- `RATCHET_BASE_REV=af799688335f9a7dba7999a05e0e13f102c6c5ae uv run python
  scripts/check-ratchet-provenance.py`: **FAIL**, NEW unauthorized unreachable
  modules and dispositions for `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` (`repair-provenance.log`). This is not
  vulture debt; the lane's ledger exception does not cover these policies.
- Created dedicated disposable PostgreSQL 18 database
  `maistro_1893_f8560b27`; `DATABASE_URL=postgresql:///maistro_1893_f8560b27
  uv run alembic upgrade head`: **PASS**, real chain to 060
  (`repair-migrate.log`). No destructive downgrade test or schema imitation.
- Set both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` to
  `postgresql:///maistro_1893_f8560b27`, and `MAISTRO_REQUIRE_PG_LEGS=1`.
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job>/repair-focused.xml`:
  **204 passed, no skips** (`repair-focused.log`). Collected node IDs retained
  via the same files with `--collect-only -q` in `repair-nodes.log`.
- Real raw/production pool backend PID pairs: unbound **3140293/3140294**,
  bound **3140295/3140296**, acknowledged **3140297/3140298**, same database
  over the Unix socket. Each case asserts a non-None production pool, distinct
  sessions, exactly one persisted scoped row, identical TEXT values and DTOs,
  and safe errors after corrupt TEXT injection. Final SQL: migration **060**,
  **0 admission rows / 0 distinct generations / 0 distinct Run identities**
  after test cleanup. Database retained for inspection.
- Regression sensitivity: an isolated `uv run python` process replaced only
  the in-memory encoder's task_id expression with `None`, then ran pytest
  `-k test_v2_round_trip_preserves_all_snapshot_bytes`. **2 expected failures,
  1 passed**: bound and acknowledged cases fail at test line 134, independently
  asserting `task_id == receipt_id` (`repair-mutation.log`). Disk source was
  never changed. This reproduces the supplied old defect, not a new repair.
- Without PG environment, `uv run pytest packages/maistro-core/tests -x -q`:
  **14623 passed, 986 skipped, 1 xfailed, 52 warnings** in 196.67 seconds
  (`repair-core.log`). Skips are not durability proof. Warnings include
  aiosqlite callbacks after event-loop closure and an unawaited test coroutine.
- `uv run ruff check .`: **PASS**. `uv run ruff format --check .`: **PASS**,
  3166 files. `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: **PASS**.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: **PASS**, 15610 collected nodes, delta zero.
- `uv run python scripts/check-<name>.py` for `reachability`,
  `reachability-dispositions`, `promotion-surface`, `radon-baseline`:
  **PASS** (`repair-<name>.log`). Candidate scans do not override the failed
  trusted-base provenance gate.

## Acceptance and remaining handoff

All ten prospective codec contracts execute in the focused suite: v2 snapshot
round trips; owner UUID hex storage; distinct bound/unbound/partial legacy
states; expired scalar evidence without invented identity; header expiry
surviving malformed snapshots; fingerprint surviving partial bindings;
unknown-format rejection; tagged nonfinite preservation without fingerprint
changes; invalid/duplicate JSON rejection; actual raw/registered-pool TEXT
round trips. Additional tests cover header mismatch, signed scalar validation,
safe typed errors, Unicode and lossy-number rejection. Migration 055 accepts
all three encoded v2 binding states in the real database.

Production reachability remains absent (codec lines 50–53, independently
confirmed by source import search and provenance scan). The database tests
exercise the codec directly with synthetic identity strings; they do **not**
prove authorized admission with real principals, Workspace/Project or Graph,
model_of/model_of_json materialization, Run JSONB object writes, live expiry/409
precedence, or full hosted CI. Those integration criteria are **UNVERIFIED**.
No execution, expiry policy, claim, HTTP mapping or queue behavior was changed.

The supplied generic `test: failure` has no failing traceback in inspected
artifacts and was not reproduced by the scoped core run. Captured PR #1945
checks at `05d3e2f799f2` instead show `test: success` and
`exact-debt-ledger: failure`; neither is current-HEAD hosted verification.
Do not guess a test repair from the status label.

Progress: checked 1 issue, validation/handoff done 1, skipped 0 issues,
1 required gate failed. Next: coordinate the separately authorized integration
consumer or already-landed trusted-base authorization; obtain the actual
hosted test failure trace before assigning another repair. No integration,
activation, merge approval or issue closure is asserted.

---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 bounded CI repair handoff — 4efc6180

## Frozen scope and disposition

Assigned branch/worktree: `auto-1893`, `/home/dev/Git/wt/auto-1893`.
Exact inspected/tested source: `9922f395daa39249991f18210a6d4da68a3a76cb`.
Trusted develop base: `435dc1937e0407ab4de198ffcced49860bb14ad2` (also the
local `origin/develop`). The starting worktree was clean. This round processes
only #1893 and changes only this evidence note: no source, tests, ledgers,
grants, gates, production wiring, or authorization policy changed.

**BLOCKED, not a successful repair.** The independent-review blocker still
reproduces against the assigned trusted base. There is no evidenced Vulture
identity defect to fix. Adding fake callers, changing reachability grants,
or weakening the gate would not be a permitted repair. The generic hosted
`test: failure` remains UNRESOLVED: the supplied deterministic check logs
contain no failing test traceback, and the focused/adjacent tests below pass.
This is not proof that the complete hosted job passes.

Read repository instructions, the frozen dispatch issue body and supplied
PR #1945 review evidence, prior result `ef58dd966639404a897b5e884b7fea54`, and
accepted ADRs 081426-1f7c, 082526-7f02, 082826-b601, 082826-d9f5. Their immutable
provenance and single canonical execution/store/consumer constraints remain
unchanged. Reconciliation: a B2 codec-only stage is not authorization to wire
a new consumer merely to satisfy reachability. The assigned lane is authority
for bounded local validation, not production activation or integration approval.

## Independently executed validation

Logs, collected node IDs, and JUnit session evidence are retained under
`/home/dev/maistro/jobs/4efc61808b8740e5b290dd530171f359/` as `worker-*` artifacts.
Driver `check-0.log` through `check-4.log` were inspected separately; their
201 passed / 3 skipped result is not used as database durability evidence.

Commands and outcomes at the source SHA above:

- `uv sync --locked --extra dev`: passed.
- `createdb maistro_1893_4efc6180`, then
  `DATABASE_URL=postgresql:///maistro_1893_4efc6180 uv run alembic upgrade head`:
  passed on a fresh dedicated PostgreSQL **18.6** database through the real
  migration chain to **062**. No schema recreation or SQLite substitute.
- Set `MAISTRO_TEST_PG_DSN=postgresql:///maistro_1893_4efc6180`,
  `MAISTRO_TEST_DATABASE_URL=postgresql:///maistro_1893_4efc6180`, and
  `MAISTRO_REQUIRE_PG_LEGS=1`, then ran
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=<job>/worker-focused.xml`:
  **204 passed, zero skipped**. Separate `--collect-only -q` invocation saved
  all 204 node IDs in `worker-collected.log`.
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`
  without PG environment: **1918 passed, 310 skipped, 6 warnings**. Warnings
  are aiosqlite callbacks after event-loop closure. These skipped tests are
  not database evidence and no passing hosted-job claim is made.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3277 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`:
  passed, two source files.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  passed, **16466** nodes, no inventory delta.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  passed, **1323 reviewed identities / 1323 findings**; no unbanked or removed
  identity justifies a Vulture ledger amendment.
- `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python scripts/check-ratchet-provenance.py`:
  **exit 1**. Reachability and reachability-dispositions reject
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` as new
  unreachable modules/dispositions absent from the trusted base and not
  previously authorized. All other executed sub-ratchets pass. This is the
  required gate in `.github/workflows/vulture-ratchet.yml:77`, not Vulture debt.
  The candidate entries remain at `quality/reachability-baseline.json:131,147`
  and `quality/reachability-dispositions.json:606-613`; untouched this round.

### Actual database boundary

Existing parametrized two-pool tests assert a non-None production `pg_pool`,
compare database/server identities against an independently created raw
asyncpg pool, insert/read a real migration-055-constrained row with named
columns, compare flat mappings and DTOs, and delete their scoped rows.
Recorded production/raw backend PID pairs (same database over Unix socket):

| State | Production | Raw | Persisted scoped rows |
| --- | ---: | ---: | ---: |
| unbound | 329888 | 329889 | 1 |
| bound | 329890 | 329892 | 1 |
| acknowledged | 329893 | 329894 | 1 |

The tests also inject escaped-surrogate corruption into each snapshot TEXT
column and require safe typed failures through both pools without losing
header fingerprint evidence. Final direct SQL counts: **0 admission rows,
0 generation IDs, 0 Run IDs** in `task_idempotency`; migration revision **062**.
The disposable DB remains available for inspection. No new test or mutation
was introduced, so no new pre-fix failure is claimed.

## Acceptance assessment and residual risks

- Immutable header/shared codec interfaces, named storage fields, strict UUID
  hex and signed timestamps, fresh flat encoding: exercised by the focused
  suite and source inspection. Bound encoding independently checks both
  `task_id` and `run_id`, rather than relying only on encode/decode agreement.
- Legacy unbound/bound/partial/receipt-only evidence, unsupported formats,
  header mismatch, expiry/fingerprint evidence surviving full decode failure:
  exercised by existing positive and negative focused tests. No identity is
  manufactured and no clock or incoming fingerprint is accepted by the codec.
- Canonical snapshot bytes and evidence tags, invalid/duplicate/nonobject/
  nonfinite JSON, lossless-number checks, error-chain suppression, owner-token
  storage-only representation: existing focused tests pass. All ten named
  prospective tests in the issue execute, including all three real PG cases.
- Scope boundary: source and provenance scan confirm the codec remains
  inactive; no production SQL mutation, HTTP/queue/assessment/scope utility
  change. DTO construction is not authorized admission. Tests use synthetic
  identities for storage-contract proof, not actual admitted principals,
  authorized Workspace/Project objects, or registered Graph execution.
- Model materialization via evidence-json helpers, fingerprinting the original
  model before tagging, Run JSONB object insertion, live expiry/409 precedence,
  and authorization/concurrency/crash invariants: **UNVERIFIED** by these B2
  tests. No production-consumer acceptance or activation claim follows.
- Complete required hosted CI: **UNVERIFIED**. The scoped tests do not reproduce
  the unnamed hosted failure and do not substitute for the entire `test` job.
- Independent mergeability: **BLOCKED** by the reproduced trusted-base gate.
  Required next step is owner-coordinated trusted-base reachability resolution
  or separately reviewed canonical integration, not another candidate-side
  grant/baseline update in this lane. Do not repeat this repair expecting a
  different result while the same source/base/policy remains unchanged.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 gate;
next: owner coordination on trusted-base blocker and concrete hosted failure
traceback. This local documentation commit is a handoff, never merge approval.

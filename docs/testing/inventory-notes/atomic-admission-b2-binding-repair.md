---
inventory-delta:
  packages/maistro-core/tests: +5
---
# B2 binding storage repair (#1893)

Starting source: `7157f4bbdbea70cb2010f5ccf751ae7f42d11328`; develop base
`b1f17b8d6246d347f617fb2c0b969e6798e0152b` (fetch + merge: already up to date).

The existing encoder/decoder agreed on an invalid storage shape: a bound Run
with NULL task_id. Migration 055 explicitly requires both binding columns,
with task_id equal to the immutable receipt_id. Encoding that receipt is not
inventing identity; it is the forward schema's required representation of the
existing v2 binding. Legacy decoding remains unchanged. Accepted ADRs
082526-7f02, 082826-b601 and 082826-d9f5 preserve admission provenance and the
single canonical Run/NodeRun/Attempt store and consumer; this repair adds no
admission decision, clock, mutation, queue, authorization or runtime wiring.

Added evidence (five additional collected nodes):
- Existing pure round-trip test now independently asserts the SQL binding
  columns for unbound, bound and acknowledged records (+2).
- Existing real migrated PostgreSQL raw/production pool contrast now inserts
  and reads all three states, comparing the complete original DTO (+2).
- A one-sided Run-only v2 row must fail with invalid_v2_record (+1).

These test-only codec calls do not establish runtime reachability or admission
atomicity. Skipped database tests do not count as durability proof.

## Executed evidence

All commands below ran in the assigned worktree on the starting source plus
this repair. Logs and collected node identities (JUnit XML) are retained in
job directory `/home/dev/maistro/jobs/9be184ee64ad458aa32b5abd8ebb7ac6`.

### Regression proof and PostgreSQL

- Before editing production code:
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py -q
  -k 'v2_round_trip_preserves_all_snapshot_bytes or v2_run_without_task'`
  produced **3 failures, 1 pass**. Both bound states emitted NULL task_id;
  the one-sided Run row failed to raise.
- Docker's socket was unavailable, but the local PostgreSQL 18.6 cluster was
  usable. Created dedicated disposable DB `maistro_1893_9be184ee`, then ran
  `DATABASE_URL=postgresql:///maistro_1893_9be184ee uv run alembic upgrade head`:
  **passed**, empty DB through real chain 001–060, including migration 055.
  No schema recreation or stamping, no migration edits or downgrade test.
- For every PostgreSQL pytest command set
  `MAISTRO_TEST_PG_DSN=postgresql:///maistro_1893_9be184ee`,
  `MAISTRO_TEST_DATABASE_URL=postgresql:///maistro_1893_9be184ee`, and
  `MAISTRO_REQUIRE_PG_LEGS=1`.
- With those settings, before the production fix,
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py -q
  -k raw_and_production` produced **2 failures, 1 pass**: bound and acknowledged
  INSERTs violated `ck_task_idempotency_v2_identity`. This injects the defect
  at the actual bound-parameter INSERT, not a fake database response.
- After the fix, `uv run pytest
  packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job-directory>/repair-focused.xml`:
  **148 passed, no skips** (75 codec nodes, 73 identity nodes).
- Raw/production session backend PIDs recorded by the three PG cases:
  unbound **1564591 / 1564580**, bound **1564593 / 1564592**, acknowledged
  **1564597 / 1564594**. All connected to `maistro_1893_9be184ee` over the
  local Unix socket (network address/port NULL). Distinct sessions are asserted.
  Each case persisted exactly **one** scoped row, read it through both pools,
  compared every column and the original DTO, then deleted its scoped row.
- `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q`: **2015 passed, 3 skipped, 6 warnings**.
  The skips are not counted as proof; the warnings are aiosqlite worker-thread
  callbacks after event-loop closure. No unrelated SQLite changes attempted.

### Gates

- `uv run ruff check .` and `uv run ruff format --check .`: **passed**.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: **passed**.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: **passed**, 15055 nodes, delta +5.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **passed**, 1328 findings,
  1328 reviewed identities. No unbanked identity exists to amend; no ledger edit.
- `uv run python scripts/check-radon-baseline.py`: **passed**, 138/138,
  no new, regressed or stale identity.
- `uv run python scripts/check-reachability.py`,
  `check-reachability-dispositions.py`, `check-shipped-surface-truth.py`, and
  `check-convergence-matrix.py` (each via `uv run python scripts/`): **passed**.
- `uv run pytest tests/test_check_reachability.py
  tests/test_reachability_baseline_identity.py -x -q`: **38 passed**. These
  are the saved CI test-job regression files, not a full root-suite claim.
- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py`: **FAILED**, only the two new unreachable
  modules and dispositions `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` lack trusted-base authorization.

## Acceptance boundary and remaining blocker

The codec's pure tests execute strict UUID/scalar decoding, header/record
separation, invalid/duplicate/nonobject/nonfinite JSON refusal, owner-token
error hygiene, explicit legacy partial dispositions, unknown-format rejection,
and snapshot/fingerprint preservation. The real database tests now prove
all three v2 storage shapes through the migrated TEXT schema and both pools.

The stage is intentionally inactive: no production consumer imports this
codec, so these results do **not** prove v2 production admission, authorized
Workspace/Project/Graph admission, Run JSONB materialization through this
codec, expiry/409 classification or claim atomicity. Those integration claims
remain **UNVERIFIED**, not inferred from DTO fixture identities or fake callers.
The canonical execution and authorization paths are unchanged.

The exact-debt-ledger blocker cannot be solved by banking vulture identities
(they already match), editing a candidate grant, deleting retained work, or
activating the out-of-scope C consumer. It requires separately authorized
coordination on the trusted integration base. Existing reachability ledgers
are preserved without alteration. Full hosted required CI has not been run
by this worker. This is a locally validated repair handoff, not merge approval.

## Independent repair revalidation (job 04817d65)

Revalidated source `c1351bffe8aa4fe20e7f9460940bab533f2bb472` against the
resolved dispatch base `b1f17b8d6246d347f617fb2c0b969e6798e0152b`. The tree
started clean. The earlier binding defect is already repaired at this head;
no new production/test change or inventory delta is justified by this round.
The front-matter +5 remains the preceding repair's delta, not five more tests.
Read the supplied check-0 through check-4 logs and prior result, but executed
validation again rather than adopting their claims. Current logs, commands,
and JUnit node/session identities are retained under job directory
`/home/dev/maistro/jobs/04817d651dca4dc8bd5e18382e116326`.

### Commands and results

- `createdb maistro_1893_04817d65` then
  `DATABASE_URL=postgresql:///maistro_1893_04817d65 uv run alembic upgrade head`:
  **passed** on a new disposable local PostgreSQL database, real chain through
  060 including 055. No stamping, recreated schema, downgrade or Docker claim.
- With both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
  `postgresql:///maistro_1893_04817d65`, and `MAISTRO_REQUIRE_PG_LEGS=1`:
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job-directory>/repair-focused.xml`:
  **148 passed, no skips** (75 codec nodes, 73 identity nodes).
  Production/raw backend PIDs were **1667141/1667142** (unbound),
  **1667156/1667158** (bound), **1667162/1667164** (acknowledged), all on the
  same database over the Unix socket. Each case independently inserted one
  admission row, read identical TEXT columns through both pools, compared the
  complete DTO and removed its scoped row. No mocked transaction proof.
- With the same PostgreSQL environment,
  `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q`: **2015 passed, 3 skipped, 6 warnings**.
  Warnings report aiosqlite worker callbacks after event-loop closure; skipped
  cases do not count as proof. Final SQL inspection after this broader suite
  found migration **060**, **3** task_idempotency rows, **0** distinct non-NULL
  generation IDs and **2** distinct non-NULL Run IDs (legacy adjacent-test
  residue, not codec-generated v2 rows).
- `uv run ruff check .`, `uv run ruff format --check .`, and
  `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: **passed**.
- Exact requested `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **passed**,
  1328 findings / 1328 reviewed identities. There are no unbanked identities
  to amend; the vulture exception does not authorize other ledger changes.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: **passed** with default environment, **15055**
  nodes. An earlier invocation with the PostgreSQL variables set failed with
  **15072** collected versus **15055** expected (+17). No tests changed between
  invocations: this is environment-sensitive collection, not a new test delta;
  neither the inventory baseline nor a compensating delta was edited.
- Each of `scripts/check-radon-baseline.py`, `check-reachability.py`,
  `check-reachability-dispositions.py`, `check-shipped-surface-truth.py`,
  `check-convergence-matrix.py`, and `check-promotion-surface.py`, invoked via
  `uv run python`: **passed**. Candidate-ledger consistency does not authorize
  newly banked debt.
- `RATCHET_BASE_REV=b1f17b8d6246d347f617fb2c0b969e6798e0152b uv run python
  scripts/check-ratchet-provenance.py`: **FAILED**. Both
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are new
  unreachable modules and new dispositions without trusted-base authorization.
  Other provenance checks passed. This reproduces the exact-debt-ledger
  blocker; it is not a vulture failure.

### Acceptance and handoff boundary

The executed codec tests cover all ten named prospective contracts: immutable
snapshot round-trip; storage-only owner-token hex; distinct legacy unbound,
bound and partial evidence; expired-header identity preservation; scalar
expiry/fingerprint preservation across full-decode failures; unknown-format
refusal; tagged nonfinite/fingerprint preservation; invalid and duplicate JSON
refusal; and actual raw/production pool equivalence. Further tests exercise
header mismatch, signed timestamp/UUID validation, safe typed errors and both
one-sided v2 binding failures. Regression failures against the old encoder are
recorded above from the earlier repair; this round did not mutate the code.

Accepted lifecycle ADR 081226-a66b and consumer ADR 082826-b601 still require
the single canonical Run/NodeRun/Attempt spine. No production caller reaches
this codec: the B2 contract explicitly leaves activation to C. Therefore
production admission with authorized principals/Workspace/Project/Graph,
Run JSONB materialization through this slice, live expiry/409 ordering, claim
atomicity, and full required hosted CI remain **UNVERIFIED**. DTO fixtures and
TEXT-row tests cannot prove those integration properties.

Disposition: **BLOCKED**, not merge-ready. The only change in this round is
this evidence update. Existing restricted reachability ledgers/grants, gates,
and implementation are preserved. Resolving the blocker needs separately
coordinated trusted-base authorization or the separately assigned integration
consumer; neither fake callers nor a vulture ledger edit can resolve it.

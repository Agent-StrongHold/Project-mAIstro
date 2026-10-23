# Issue #1893 repair handoff — 214909c5

## Frozen scope and outcome

Only issue #1893, assigned worktree `/home/dev/Git/wt/auto-1893`, branch
`auto-1893`. Clean starting HEAD: `e5dc3b7273996e21e4090faf8d07c7076e85a897`.
Assigned base, local `origin/develop`, and independently resolved merge base
all equal `435dc1937e0407ab4de198ffcced49860bb14ad2`.

**BLOCKED.** No codec failure was reproduced. This report is the only changed
file; no source, tests, inventory, ledger, grant, or gate changes are justified.
No test additions or inventory delta. Local commit is handoff, not approval.
There was no incoming work or sync conflict to discard or resolve. No remote
fetch, push, PR mutation, activation, or issue closure was performed.

Read repository instructions, accepted ADR-081226-a66b (canonical lifecycle),
ADR-082526-7f02 (immutable admission provenance; Attempt-owned dispatch), and
ADR-083126-5e62 (trusted-base quality authority), the codec and adjacent
codec/identity tests, identity constructors, migration 055's field constraints,
production-codec pool fixture, and exact-debt-ledger workflow. Reconciliation:
receipt-less legacy pairs remain partial because the binding constructor
requires a receipt; inventing identity or activating a new consumer to satisfy
reachability would violate this staged leaf. Nothing changes the canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` authority.

## Evidence and unresolved CI signal

Job artifacts: `/home/dev/maistro/jobs/214909c594d5467783b4744824056758`.
Inspected `dispatch-context.json`, `check-0.log` through `check-4.log`, and the
supplied prior result. Driver logs show successful dependency sync, ruff and
format checks, 201 passing tests with three PG skips, and inventory count
16,466. Prior claims are not counted as independently executed acceptance.

Captured check-run evidence was extracted to `captured-failures.log`. The
captured failed `test` check belongs to linked head `3f2c79a70d9e`, not this
assigned HEAD; its summary/text are null. Linked head `9922f395daa3` reports
failed `exact-debt-ledger`. No current-head failing test traceback was supplied.
An initial extraction assumed a wrapped check-runs object; the captured data
is a list. Corrected once, without refreshing the snapshot. The generic
`test: failure` remains **UNVERIFIED**, not grounds for speculative code repair.

## Commands independently executed

Commands ran at the starting source HEAD with 1,200-second validation timeouts
(1,500 for DB orchestration). Logs are in the job directory above.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1,323 findings, zero unclassified; `vulture.log` |
| `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1: two unauthorized module entries and two dispositions; `provenance.log` |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3,277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS: two source files |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 201 passed, three PG skips without DB configuration |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `uv run alembic upgrade head` with disposable `DATABASE_URL` | PASS: real empty-schema chain 001 through 062, including 055; `migrate.log` |
| Same focused pytest command with both PG URLs, `MAISTRO_REQUIRE_PG_LEGS=1`, `-o junit_family=legacy --junitxml=<job>/postgres-tests.xml` | **204 passed, zero skipped**, 1.54s; `postgres-tests.log` |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16,466 nodes, no duplicate evidence; `inventory.log` |
| `rg -n 'admission_codec\|runs.admission_identity' packages/*/src` | Only codec's DTO import and Vulture whitelist import, no production consumer |

The failed gate compares 169 trusted modules/dispositions to 171 candidate
entries. It rejects `maistro.runs.admission_identity` and
`maistro.tasks.admission_codec` in `quality/reachability-baseline.json:131,147`
and `quality/reachability-dispositions.json:606-613`. The workflow invokes this
provenance gate before Vulture (`.github/workflows/vulture-ratchet.yml:77`).
The explicit Vulture-ledger exception does not authorize reachability grants;
Vulture has no unbanked identities anyway. Do not amend a passing ledger.

## Real PostgreSQL evidence

Verified the already-running lane container `auto-1893-pg` uses PostgreSQL
18.6 on loopback port 15498. Verified new DB `maistro_1893_job_214909c5` did not
exist, then created and migrated it. Credentials were retrieved in memory,
never printed or committed. `DATABASE_URL`, `MAISTRO_TEST_PG_DSN` and
`MAISTRO_TEST_DATABASE_URL` selected this same disposable DB. No existing DB
was reused/truncated; no destructive downgrade tests ran.

JUnit records 204 collected cases. The three raw/production pool contrasts
report the same database and server `172.17.0.9/32:5432`, with distinct backend
PID pairs (production/raw): unbound **11841/11842**, bound **11843/11844**,
acknowledged **11845/11846**. Each persisted exactly one scoped admission row,
compared all named encoded fields, and round-tripped immutable DTOs. Bound rows
satisfied migration 055's paired binding constraint. Each case injected escaped
surrogate corruption into each snapshot TEXT column, proving safe typed failure
through both pools without changing header fingerprint. Final SQL inspection:
revision **062**, admission rows/distinct scopes **0/0**, canonical Runs **0**,
NodeRuns **0**, Attempts **0** (`postgres-counts.log`). DB retained for inspection.

These are storage/representation tests with fixture identities, not authorized
production admission or transaction/crash/dispatch proofs. No new mutation or
pre-fix claim is made: this round changed no test or production code.

## Acceptance review

| Criterion | Executed evidence or limit |
| --- | --- |
| Frozen/slotted header, shared API, six typed decode codes | Source review and existing scalar/header/schema/DTO tests PASS |
| Strict UUID .hex storage, signed timestamps, #1851 constructors | Owner/generation/scalar boundaries and invalid constructor tests PASS |
| Exact immutable v2 snapshots, fresh flat named mapping, optional binding/acknowledgement | Three-state round-trip tests PASS in memory and real PG; independent binding column assertions at `test_admission_codec.py:134-137` |
| Legacy bound/unresolved/partial, receipt-only, announced-without-Run, no invented identity | Existing pairing, absent-receipt, malformed-evidence and completed_at tests PASS |
| Expiry/fingerprint header evidence survives full-decode failures | Both prospective separation tests PASS; no clock or incoming fingerprint in codec |
| Unknown formats and scalar/header mismatches fail closed | Existing unsupported-format and invalid-header tests PASS |
| TEXT JSON rejects duplicate keys/nonobjects/bare nonfinite values; safe scope/errors | Existing JSON, nesting, lossy-number, surrogate and diagnostic tests PASS |
| Tagged program_context preserved without fingerprint recalculation/double decoding | Tagged-nonfinite round-trip, Unicode/numeric evidence tests PASS; tags remain objects |
| Raw and production JSON-codec pools on real migrated schema | All three PG cases PASS with non-null production pool and distinct sessions on same DB |
| Evidence-json/model_of/model_of_json materialization; fingerprint before tagging | UNVERIFIED end-to-end: tests use hand-built tags, not complete TaskResponse/Run materialization |
| Run payload text::jsonb remains an object | UNVERIFIED: these tests insert admission TEXT, not canonical Run payloads |
| Explicit authorized principals/Workspace/Project and registered Graph kinds | UNVERIFIED: fixture strings prove representation, not authorization |
| No SQL/HTTP/queue/assessment/claim/scope-utility/policy change | Source review: DTO/mapping layer only; this round changes documentation only |
| Consumer expiry/409 precedence and crash/dispatch invariants | UNVERIFIED C/F2 integration, explicitly not B2 decisions |
| Reachable production behavior | NOT ESTABLISHED: codec documents absent consumer at `admission_codec.py:49-52`; source search and failed provenance confirm the gap |
| Focused validation, inventory, Vulture, shipped surface | Independently PASS as recorded above |
| Unchanged full required CI / reported test failure | UNVERIFIED; full suite not claimed, required provenance FAILS |
| Coordination/activation | Assignment permits repair only; trusted-base prerequisite unresolved; activation remains blocked |

## Required next action

Owner must resolve the trusted-base reachability prerequisite through the
existing authorization/integration process before another readiness evaluation.
Merging the identical develop base or modifying this candidate's ledger cannot
supply that authorization. Provide an actual failing current-head test traceback
if a separate test repair is expected. Do not redispatch this unchanged head as
an unbanked-Vulture repair. Remaining integration acceptance stays unverified.

Progress: checked 1 issue, done 0 code repairs, skipped 0 issues, errors 1
required gate; evidence handoff completed. Next: prerequisite owner resolution,
then unchanged required CI and remaining production acceptance.

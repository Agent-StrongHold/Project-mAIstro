# Issue #1893 repair validation

## Frozen scope

- Assigned writer worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting head: `a525cb7174144b9c8229f01bf800aba227bc4b9a`.
- Supplied develop base: `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Process only issue #1893 and its supplied job snapshot
  `3073278d883c4501a11cf422b441fcee`; no GitHub mutations.
- Validation scope: admission codec, immutable identity DTOs, adjacent admission
  tests, applicable ADRs, and the named local quality gates. Potential edits are
  limited to those implementation/test files, their inventory note, this report,
  and reviewed vulture identities only if the requested scan finds a real issue.

## Initial evidence and assumptions

The worktree was clean. `git diff --name-only` between the supplied base and
starting head returned no files. This does not establish issue completion.
Supplied driver logs report ruff check/format passing, focused tests 201 passed /
3 skipped, and suite inventory passing (16466 nodes). These are prior driver
results, not live database evidence from this repair round.

The dispatch names only `test: failure`, without a failing test traceback.
Assumption: reproduce focused admission behavior and exact named gates before
making any code or ledger repair. Activation and independent merge approval
remain outside this leaf.

## Measured gate result

- Exact requested Vulture scan: exit 0, 1323 findings / 1323 reviewed identities;
  no unclassified findings, so no ledger repair is justified.
- `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python
  scripts/check-ratchet-provenance.py`: exit 1. The trusted gates report both
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` as NEW
  unauthorized unreachable modules and NEW unauthorized dispositions. This
  reproduces the prior blocker despite the equal candidate/base file trees;
  ordinary tree equality is not authorization evidence.
- `git merge-base HEAD 435dc1937e0407ab4de198ffcced49860bb14ad2` resolves to
  the supplied base itself. No unresolved ref or merge conflict is present.

The permitted vulture exception does not authorize reachability grant edits,
consumer activation, or weakening trusted provenance checks. That blocker
cannot be repaired within this leaf.

## Focused checks at the starting source SHA

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: 3277 files already formatted.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: passed.
- `uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py
  packages/maistro-core/tests/tasks/test_admission_codec.py -x -q`:
  201 passed, 3 skipped (the PostgreSQL parametrizations).
- Production-source search for `admission_codec|decode_admission_record`
  finds only the codec module itself: no reachable consumer is demonstrated.
  Pure tests cannot establish production admission, authorization, Run JSONB
  insertion, or dispatch behavior.
- Read repository instructions and accepted ADR-081226-a66b and
  ADR-082526-7f02. The typed-only leaf must preserve immutable admission
  provenance and the canonical execution hierarchy; wiring a second admission
  authority to evade reachability failure is not an acceptable repair.

No implementation defect has been reproduced. PostgreSQL validation is next;
local PostgreSQL responds on port 5432. The prior note's TCP test credentials
failed authentication, including the attempted Alembic command (exit 1; no
migration applied). A second attempt using OS-user peer authentication via
`/var/run/postgresql` succeeded against PostgreSQL 18.6 and created a new,
dedicated `maistro_1893_job3073278` database. No existing database was reused.
No tests were added or changed, so no inventory delta is required.

## Live PostgreSQL evidence

Both DSN variables were set to
`postgresql://dev@/maistro_1893_job3073278?host=/var/run/postgresql`.
`DATABASE_URL` used the same URL for `uv run alembic upgrade head`, which
successfully applied the real chain from empty schema through **062**.
With `MAISTRO_REQUIRE_PG_LEGS=1`, the focused pytest command above plus
`-o junit_family=legacy --junitxml=/tmp/issue1893-job3073278-pg.xml` executed
**204 tests, all passed, zero skipped**.

Raw/production backend PID pairs were 580179/580178 (unbound),
580189/580180 (bound), and 580205/580203 (acknowledged). Each pair read the
same database over the local Unix socket (server address/port SQL fields NULL,
as expected). Each case recorded exactly one persisted admission row. The
independent final query found migration 062 and zero rows in task_idempotency,
tasks, canonical_runs, canonical_node_runs, and canonical_attempts. The empty
disposable database is retained for inspection.

This proves TEXT storage/pool-codec independence, valid bound SQL shape, and
safe corrupt-surrogate rejection through both pools. It does **not** prove
real authorized admission or Run JSONB insertion: these tests directly insert
codec fixtures using string identities, not a production admission consumer.

Additional executed gates: core suite inventory passed (16466 nodes, no
duplicates); reachability passed (1396 modules, 171 unreachable); dispositions
passed (50 groups); shipped-surface truth passed. These candidate-tree passes
do not override the failed trusted-base provenance checks.

## Acceptance and remaining limits

The 204-node focused run includes the issue's named prospective tests:

| Contract | Executed evidence |
| --- | --- |
| Immutable v2 snapshots and fresh flat mappings | `test_v2_round_trip_preserves_all_snapshot_bytes` (three states) |
| Owner UUID hex only at storage boundary | `test_owner_token_is_hex_at_storage_only` |
| No guessed legacy binding identity | `test_legacy_binding_unbound_and_partial_are_distinct` |
| Scalar-only header, no clock or admission choice | `test_expired_legacy_header_does_not_invent_missing_identity` |
| Header expiry survives corrupt snapshots | `test_header_preserves_expiry_even_when_legacy_snapshot_decode_fails` |
| Header fingerprint survives partial binding | `test_header_preserves_fingerprint_even_when_legacy_binding_is_partial` |
| Unknown formats fail closed | `test_unknown_format_cannot_be_reinterpreted_as_legacy` |
| Tagged nonfinite evidence without fingerprint recalculation | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change` |
| Invalid/duplicate JSON rejected safely | `test_invalid_and_duplicate_json_is_rejected` plus deep nesting, lossy number and surrogate cases |
| Raw/production codec TEXT round trip | `test_raw_and_production_pool_codecs_read_identical_text_snapshots` (three live PG states) |

`uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs
-x -q` additionally passed **1918**, skipped **310**, with **4 warnings**.
This broader run had no DSN configured; its skips are not database proof.
Warnings were aiosqlite worker threads reporting closed event loops in the
adjacent SQLite store suite; no source change is justified in this codec lane
by these non-failing warnings.

The captured dispatch check for PR #1945's source head `9922f395daa3`
(check 114346705414) says `test: success`. It does not establish current-head
CI. The supplied `test: failure` remains **UNRESOLVED**: no current-head
traceback was supplied, and neither focused nor adjacent tests reproduce it.
Full unchanged required CI, production model materialization/authorized
admission, Run JSONB insertion, and coordination/activation approval are
**UNVERIFIED** in this round. No pre-fix/mutation result is claimed: no code
repair or new regression test was made.

## Handoff

**BLOCKED**, not merge-ready. Only this report changed; implementation, tests,
inventory counts, ledgers, grants, and gates are untouched. The reproduced
trusted-base reachability blocker requires an authorized integration-owner
resolution outside this leaf; a vulture ledger edit cannot resolve it.
Do not repeat speculative repairs or treat earlier green runs as current-head
integration approval. Obtain the failing CI traceback if the `test` failure
still applies.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 unresolved
provenance blocker. Next: owner-authorized reachability resolution and exact
current-head CI failure evidence. Local PostgreSQL evidence remains in the
named disposable database and JUnit file above.

## Fresh bounded repair round: job 840837ee22644323bac40aa96e17de9e

Source SHA: `76acfdf718e6bde644d7dbc928eb7610f12722d7`; resolved develop
base and merge base: `435dc1937e0407ab4de198ffcced49860bb14ad2`. Worktree
started clean. Only #1893 was processed, with no remote mutations or ref refresh.
The supplied driver `check-0.log` through `check-4.log` were inspected; they
show successful dependency setup, lint, format, 201 passed / 3 skipped focused
tests, and 16466 inventory nodes. None proves current live PostgreSQL behavior.

Correction to the earlier report's tree-equality claim: the explicit range
`git diff --stat 435dc1937e0407ab4de198ffcced49860bb14ad2..HEAD` at this
round's starting SHA reports **65 changed files**, including the codec, DTOs,
tests, and reachability ledgers. The earlier unqualified no-files claim is
not accepted as evidence.

### Executed validation

Logs and JUnit are retained in
`/home/dev/maistro/jobs/840837ee22644323bac40aa96e17de9e/` as `worker-*.log`
and `worker-pg.xml`. No previous execution result is substituted for these:

- `uv run ruff check .`: passed (`worker-ruff.log`).
- `uv run ruff format --check .`: 3277 files already formatted.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: two files passed.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`:
  201 passed / 3 skipped without a DSN.
- The same command with both PostgreSQL DSN variables below and
  `MAISTRO_REQUIRE_PG_LEGS=1` in the environment, adding pytest arguments
  `-o junit_family=legacy --junitxml=<job-directory>/worker-pg.xml`: **204 passed,
  zero skipped**, including all ten named prospective contracts in the table
  above. It tests corrupt storage injection as well as valid round trips.
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs
  -x -q`: **1918 passed, 310 skipped, 6 warnings**, without database variables.
  Warnings report aiosqlite worker threads encountering closed event loops;
  these are not a reproduced admission codec failure.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: 16466 nodes, zero duplicate identities, passed.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: passed, 1323 reviewed
  identities / 1323 findings, zero unclassified. No amendment justified.
- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py`: **exit 1**, rejecting NEW unreachable
  modules and NEW dispositions for `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` absent from the trusted base/authorization.
  This is the workflow's exact-debt-ledger provenance command, not a guessed
  scanner finding. See `worker-provenance.log:20-31`.

### Independent PostgreSQL evidence

Peer authentication confirmed PostgreSQL 18.6 and absence of the proposed DB
before `createdb -h /var/run/postgresql -U dev maistro_1893_job840837ee`.
`DATABASE_URL='postgresql://dev@/maistro_1893_job840837ee?host=/var/run/postgresql'
uv run alembic upgrade head` applied the real empty-schema chain through 062.
Both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` used that same URL.
No downgrade or destructive migration test was run on an existing database.

JUnit records production/raw backend PID pairs **674054/674056** (unbound),
**674057/674058** (bound), and **674059/674060** (acknowledged). Each pair
shares the named DB, with NULL server address/port for the Unix socket, and
reads one persisted admission row. The independent final query confirms
migration **062** and **zero** rows in task_idempotency, tasks, canonical_runs,
canonical_node_runs, and canonical_attempts. The empty disposable DB is retained.

### Acceptance boundary and handoff

Re-read accepted ADR-081226-a66b and ADR-082526-7f02, codec implementation,
its tests, adjacent immutable DTO tests, and production-pool fixture. Source
search of `packages/*/src` finds no consumer of `admission_codec` or
`decode_admission_record` outside the defining module. This is consistent
with the inactive B2 scope, but not proof of reachable production admission.
No new scheduler, lifecycle, identity, authorization path or activation is
introduced to bypass the gate.

The executed tests establish typed DTO/header separation, strict storage UUIDs
and timestamps, explicit legacy partial failures, safe corrupt JSON rejection,
unchanged stored fingerprints, fresh SQL mappings, and raw/production TEXT
pool equivalence. Fixture principals are strings, not authorized admission
actors. Actual model materialization using evidence-json helpers, original-model
fingerprinting, registered Graph admission, Run JSONB insertion, consumer
expiry/409 precedence, full unchanged required CI, and coordination/activation
approval remain **UNVERIFIED** by this round. No pre-fix or mutation failure is
claimed because no implementation or regression test was changed.

The dispatched `test: failure` remains **UNRESOLVED** without a current-head
failing traceback; focused and adjacent tests do not reproduce it. The measured
provenance failure is outside the permitted vulture-ledger exception. Resolving
it requires an integration-owner decision consistent with the two-merge rule
and the issue's no-activation/no-gate-change constraints, not a speculative
codec patch or candidate self-authorization.

**BLOCKED.** Only this validation report changed; no tests, inventory counts,
implementation, ledger, grant or gate changed. Therefore no inventory delta
note is needed. Progress: checked 1, done 0 repairs, skipped 0, errors 1 unresolved
provenance blocker. Next: owner-authorized provenance resolution and exact
current-head `test` failure evidence. The local documentation commit is an
evidence handoff, not merge or activation approval.

## Fresh bounded repair round: job 6e7c70c2225d4c2fb82614872a19798c

Frozen item: #1893 only, starting source
`12183c0278b79db1f3804a66da4c923ca019546d`, clean assigned worktree.
`origin/develop` resolves to supplied base
`435dc1937e0407ab4de198ffcced49860bb14ad2`. No ref refresh, conflict,
remote mutation, production activation, or ledger edit was performed.
Read the supplied dispatch, prior result, driver `check-0.log` through
`check-4.log`, repository instructions, accepted ADR-081226-a66b and
ADR-082526-7f02, codec, DTO constructors, focused tests and pool fixture.
Preserving immutable provenance and the canonical execution hierarchy rules
out adding a competing admission authority to bypass the gate.

### Fresh command outcomes

Logs are in `/home/dev/maistro/jobs/6e7c70c2225d4c2fb82614872a19798c/`.
All Python validation used `uv run`; commands had 1200-second timeouts.

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **passed**, 1323 findings
  and reviewed identities, zero unclassified (`worker-vulture.log`). No
  evidence warrants the permitted Vulture ledger amendment.
- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py`: **exit 1**. Lines 20–31 of
  `worker-provenance.log` reject both `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec`: NEW unauthorized dispositions and NEW
  unauthorized unreachable modules. This reproduces the exact-debt-ledger
  workflow blocker; no candidate-side grant can authorize it.
- `uv run ruff check .` and `uv run ruff format --check .`: **passed**.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: **passed**.
- `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q`: **1918 passed, 310 skipped,
  4 warnings**, without a database DSN (`worker-adjacent.log`). Warnings
  are aiosqlite worker-thread closed-event-loop reports, not codec failures.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: **passed**, 16466 nodes, zero duplicates.

### Fresh PostgreSQL acceptance evidence

Preflight confirmed PostgreSQL 18.6 and absence of the proposed disposable
DB; `createdb -h /var/run/postgresql -U dev maistro_1893_job6e7c70c2`
created it. With `DATABASE_URL` set to
`postgresql://dev@/maistro_1893_job6e7c70c2?host=/var/run/postgresql`,
`uv run alembic upgrade head` applied the real empty-schema chain through
**062**. Both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` then used
that URL, with `MAISTRO_REQUIRE_PG_LEGS=1`, for:

```text
uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=<job-directory>/worker-pg.xml
```

Result: **204 collected/executed, 204 passed, zero skipped**. All ten named
prospective contracts in the acceptance table above executed. The cases prove
immutable DTOs, header/full-decode separation, strict UUID/timestamp decoding,
explicit legacy partial dispositions, safe invalid/duplicate JSON rejection,
unchanged stored fingerprint and tagged evidence, and fresh flat SQL mappings.
Storage injection covers malformed surrogate TEXT through both pools as well
as unbound, bound and acknowledged round trips satisfying migration 055.

JUnit production/raw PID pairs: **754644/754645**, **754647/754654**,
**754705/754730**, respectively. Each pair identifies the same disposable DB
and distinct backend sessions; each reads exactly one persisted admission row.
Independent final SQL confirms migration **062** and **zero** rows in
`task_idempotency`, `tasks`, `canonical_runs`, `canonical_node_runs`, and
`canonical_attempts`. The empty disposable DB is retained. Logs:
`worker-migrate.log`, `worker-pg.log`, `worker-pg.xml`, `worker-db-final.log`.

### Disposition

**BLOCKED.** The dispatched `test: failure` is **UNRESOLVED**: no failing
current-head traceback was supplied, and fresh focused/adjacent tests pass.
No implementation defect or new Vulture debt was reproduced. Reachability
provenance is an actual failure outside this lane's ledger exception. Obtain
owner-authorized resolution consistent with the two-merge rule and the exact
current-head failing CI traceback, rather than repeating speculative repairs.

A production-source search (`worker-consumers.log`) finds no consumer of
`admission_codec`/`decode_admission_record` outside the defining module.
These tests use string fixture identities, not authorized admission actors.
Reachable authorized admission, actual evidence-json model materialization,
original-model fingerprinting, registered Graph admission, Run JSONB insertion,
consumer expiry/409 precedence, full required CI and coordination approval
remain **UNVERIFIED**. Consumer behavior belongs to C/F2, not this B2 repair.
No mutation/pre-fix failure is claimed because no code or tests were changed.

Only this report changed. No test addition or count change means no inventory
note delta is needed. Progress: checked 1, done 0 repairs, skipped 0, errors 1
unresolved provenance blocker. This local documentation commit is a handoff,
not integration or activation approval.

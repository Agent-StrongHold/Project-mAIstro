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

## Fresh bounded repair round: job 20d9de45cd5047f09c8f9e82abe995f7

Frozen scope: #1893 only, clean assigned worktree at
`ce518cead25af593272c68ed78b2e1d47b6d6593`. Supplied base, resolved
`origin/develop`, and merge base are all
`435dc1937e0407ab4de198ffcced49860bb14ad2`. No sync conflict exists.
Read repository instructions, the captured issue contract, prior result,
driver check-0 through check-4 logs, accepted ADR-081226-a66b and
ADR-082526-7f02, codec, DTO constructors and adjacent tests/pool fixture.
Prior green claims were not substituted for the following fresh executions.
Logs named below are under this round's job directory.

### Executed commands and results

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: passed, **1323 reviewed
  identities / 1323 findings, zero unclassified** (`worker-vulture.log`).
  No evidence justifies a Vulture ledger amendment.
- `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python
  scripts/check-ratchet-provenance.py`: **exit 1**. This uses the resolved
  develop base for the workflow's exact-debt-ledger gate. Lines 20–29 of
  `worker-provenance.log` reject NEW unauthorized unreachable modules and
  dispositions for both admission modules. The permitted Vulture exception
  does not authorize reachability grant/ledger edits or consumer activation.
- `uv run ruff check .`: passed; `uv run ruff format --check .`: 3277 files
  already formatted. `uv run mypy
  packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: passed.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`:
  **201 passed, 3 skipped** without DSNs (`worker-focused.log`).
- `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q`: **1918 passed, 310 skipped,
  6 warnings**, without DSNs (`worker-adjacent.log`). Warnings are aiosqlite
  worker-thread closed-event-loop reports, not a reproduced codec failure.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: passed, **16466 nodes**, zero duplicates.

### Independent database and acceptance evidence

Preflight confirmed PostgreSQL **18.6** and absence of the proposed DB.
`createdb -h /var/run/postgresql -U dev maistro_1893_job20d9de45` created
an isolated disposable database. With `DATABASE_URL` set to
`postgresql://dev@/maistro_1893_job20d9de45?host=/var/run/postgresql`,
`uv run alembic upgrade head` applied the real chain through **062**.
The focused pytest command above, with both `MAISTRO_TEST_PG_DSN` and
`MAISTRO_TEST_DATABASE_URL` set to that same URL, `MAISTRO_REQUIRE_PG_LEGS=1`,
and `-o junit_family=legacy --junitxml=<job-directory>/worker-pg.xml`,
executed **204 tests, all passed, zero skipped** (`worker-pg.log`).
All ten prospective contracts in the earlier acceptance table executed.
They establish immutable DTOs, strict scalar/UUID/snapshot decoding, safe
error messages, explicit legacy partial dispositions, header/full-decode
separation, unchanged stored fingerprints, and fresh flat SQL mappings.

The three raw/production TEXT round-trip states recorded distinct backend
PID pairs **860284/860285**, **860287/860288**, **860289/860294**, with one
persisted admission row per case in that same DB (`worker-sessions.log`).
Corrupt surrogate TEXT was injected and rejected through both pools.
Independent final SQL confirmed migration **062** and zero rows in
`task_idempotency`, `tasks`, `canonical_runs`, `canonical_node_runs`, and
`canonical_attempts` (`worker-db-final.log`). The disposable DB is retained.

Source search still finds no production codec consumer
(`worker-consumers.log`). Positive tests use string fixture identities, not
an authorized Workspace/Project admission. Reachable authorized admission,
evidence-json model materialization, original-model fingerprinting, registered
Graph admission, Run JSONB insertion, consumer expiry/409 precedence, full
unchanged CI and coordination approval remain **UNVERIFIED**. No new execution
or authorization path was added; accepted ADRs and B2's inactive scope remain
intact. No pre-fix/mutation claim is made because no code/test repair was made.

### Handoff

**BLOCKED.** The dispatched `test: failure` remains **UNRESOLVED** without a
current-head failing traceback; focused and adjacent executions do not
reproduce it. The proven provenance blocker needs an owner-authorized
resolution consistent with the two-merge rule, outside this repair's grant
permissions. Do not rerun this unchanged lane as a speculative code repair.
Only this report changed; no test/inventory, source, ledger, grant or gate
changed. No inventory delta is needed. Progress: checked 1, done 0 repairs,
skipped 0, errors 1 unresolved provenance blocker. Next: owner resolution and
the exact failing CI traceback. Local commit is an evidence handoff only.

## Repair job 4f181543 — independent validation at 8c7334ef

Frozen scope: issue #1893 only, assigned `auto-1893` worktree. Starting HEAD
`8c7334ef1b8ce91e4d268de67bc60a19bf22249b` was clean; trusted develop base
`435dc1937e0407ab4de198ffcced49860bb14ad2` resolves locally. No remote mutation,
merge, production activation, source/test repair or ledger/grant edit was
performed. This report is the only changed file; test inventory delta is zero.

Read repository instructions, the frozen dispatch issue/PR evidence, prior
result, driver `check-0.log` through `check-4.log`, adjacent codec/DTO tests,
production codec/DTO implementations, migration 055, and accepted ADR-018,
ADR-056, ADR-097 and ADR-082526-7f02. Reconciliation: immutable admission
facts do not become execution identity or authorization. No change to
`Goal -> Graph -> Run -> NodeRun -> Attempt` or any admission authority is
permitted by this staged leaf. Passing DTO tests is not production activation.

All following logs are under
`/home/dev/maistro/jobs/4f181543d440481089d341fdacb06774/` and were generated
in this round, not inherited from previous verification claims:

| Executed command | Result / log |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Passed: 1323 findings, 1323 reviewed identities, zero unclassified; `worker-vulture.log` |
| `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python scripts/check-ratchet-provenance.py` | **Exit 1**; `worker-provenance.log:20-29` rejects both new admission modules and dispositions against the trusted base |
| `uv run ruff check .` | Passed; `worker-ruff.log` |
| `uv run ruff format --check .` | Passed, 3277 files; `worker-format.log` |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | Passed, two files; `worker-mypy.log` |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q` | 201 passed, 3 PG skips without DSNs; `worker-focused.log` |
| `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q` | 1918 passed, 310 skipped, 6 aiosqlite closed-event-loop thread warnings; `worker-adjacent.log` |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Passed: 16466 nodes, zero duplicate evidence; `worker-inventory.log` |
| `uv run python scripts/check-shipped-surface-truth.py` | Passed; `worker-surface.log` |

### Live database acceptance

Preflight confirmed PostgreSQL 18.6 and absence of the dedicated database.
Created `maistro_1893_job4f181543` with
`createdb -h /var/run/postgresql -U dev maistro_1893_job4f181543`.
Set `DATABASE_URL`, `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL`
to `postgresql://dev@/maistro_1893_job4f181543?host=/var/run/postgresql`
in separate shell assignments. `uv run alembic upgrade head` applied the
real migration chain to **062** (`worker-migrations.log`). No destructive
downgrade tests ran; downgrade behavior is not claimed.

With `MAISTRO_REQUIRE_PG_LEGS=1`, reran the focused command above with
`-o junit_family=legacy --junitxml=<job-directory>/worker-pg.xml`:
**204 passed, zero skipped** (`worker-pg.log`). All ten prospective named
codec contracts executed, including all three raw/production pool states.
JUnit records production/raw backend PID pairs **1039426/1039427**,
**1039428/1039429**, **1039430/1039431**, each on this same socket/database,
with one persisted admission row per state (`worker-sessions.log`). SQL
independently confirmed migration **062** and zero final rows in
`task_idempotency`, `tasks`, `canonical_runs`, `canonical_node_runs` and
`canonical_attempts` (`worker-db-final.log`). The scratch database is retained.

Acceptance boundaries:

- Immutable DTOs, matching scalar headers, signed timestamps, strict UUID hex,
  fresh named-column SQL mappings, bound/unbound/acknowledged v2 state,
  legacy partial/receipt-only rejection, and safe typed errors: **proven by
  the 204 executed tests**. The binding tests independently assert migration
  055's task/receipt identity shape, not merely encode/decode agreement.
- Header expiry/fingerprint survives corrupt snapshot or partial binding;
  unknown formats fail closed; invalid/duplicate/nonobject/nonfinite JSON
  fails; valid tags/nested evidence and stored fingerprints survive:
  **proven at the codec boundary**. Corrupt surrogate TEXT was also injected
  into all snapshot columns and rejected through both real pools.
- New evidence-json encoding, model materialization via `model_of` or
  `model_of_json`, original-model fingerprinting, Run JSONB object insertion,
  authorized principals/Workspace/Project/registered Graphs and consumer
  expiry/409 ordering: **UNVERIFIED** by these fixture-based codec tests.
- Production reachability: source search (`worker-consumers.log`) finds only
  the codec importing its DTO module and a Vulture whitelist import; no
  runtime codec caller. No reachable admission claim is made.
- Full required CI, coordination approval, activation-policy resolution and
  a current-head reproduction of dispatched `test: failure`: **UNVERIFIED**.
  No failing-test traceback was supplied; scoped executions do not reproduce
  that status. No new pre-fix/mutation claim is made in this report-only round.

### Unresolved handoff

**BLOCKED**, not merge-ready. The reproducible failure is trusted-base
reachability provenance (`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-614`), not Vulture debt. Vulture
passes, so the special Vulture amendment permission provides no repair.
Do not invent a runtime caller, add a local grant, or change a gate to make
this inactive leaf green. Owner-authorized resolution must precede another
integration attempt; the two-merge rule cannot be satisfied in this branch
alone. Also request the exact failing CI test traceback before assigning a
source repair. Progress: checked 1 issue, done 0 repairs, skipped 0, errors 1
provenance blocker; validation complete and locally committed as a handoff.

## Repair job 95ffb825 — current evidence at 0bc1e234

Frozen scope: #1893 only; clean assigned `auto-1893` worktree at
`0bc1e2347c72a1508dce4694298f7aefb2e944f2`. Local `origin/develop` resolves
to the supplied base `435dc1937e0407ab4de198ffcced49860bb14ad2`; no merge
conflict or unresolved ref exists. Inspected the supplied dispatch, previous
result and all five driver logs, repository instructions, codec/DTO source
and adjacent tests. Read accepted ADR-081226-a66b, ADR-081226-69ee,
ADR-081426-1f7c and ADR-082526-7f02. Reconciliation: this inactive typed leaf
cannot invent a production caller or admission authority to evade reachability.
The canonical execution hierarchy and immutable admission provenance remain
unchanged. No GitHub mutation or ref refresh was performed.

### Fresh executed checks

Logs are under `/home/dev/maistro/jobs/95ffb82571f240d7a77dd0be9d2e38bf/`.
Prior results were not substituted for these executions.

| Command | Current result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Passed: 1323 findings / reviewed identities, zero unclassified (`worker-vulture.log`) |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py` | **Exit 1**: both admission modules and dispositions absent from trusted base/authorization (`worker-provenance.log:20-29`) |
| `uv run ruff check .` | Passed (`worker-ruff.log`) |
| `uv run ruff format --check .` | Passed: 3277 files (`worker-format.log`) |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | Passed: two source files (`worker-mypy.log`) |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q` | 201 passed, 3 PG skips without DSNs (`worker-focused.log`) |
| Same focused command with live DB environment below and `-o junit_family=legacy --junitxml=<job-directory>/worker-pg.xml` | **204 passed, zero skipped** (`worker-pg.log`) |
| `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q` | 1918 passed, 310 skipped, 6 aiosqlite closed-event-loop warnings; no DSNs (`worker-adjacent.log`) |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Passed: 16466 nodes, zero duplicate evidence (`worker-inventory.log`) |
| `uv run python scripts/check-shipped-surface-truth.py` | Passed (`worker-surface.log`) |

Preflight confirmed PostgreSQL 18.6 and absence of `maistro_1893_job95ffb825`.
Created it with `createdb -h /var/run/postgresql -U dev maistro_1893_job95ffb825`.
Set `DATABASE_URL`, `MAISTRO_TEST_PG_DSN`, and `MAISTRO_TEST_DATABASE_URL`
to `postgresql://dev@/maistro_1893_job95ffb825?host=/var/run/postgresql`.
`uv run alembic upgrade head` applied the real empty-schema chain through
062 (`worker-migrations.log`); focused pytest used `MAISTRO_REQUIRE_PG_LEGS=1`.
No downgrade test ran. Production/raw session PID pairs were
1118716/1118717 (unbound), 1118718/1118719 (bound), and 1118721/1118722
(acknowledged), on the same socket/database, one persisted admission row per
case (`worker-sessions.log`, full node IDs in `worker-pg.xml`). Final SQL
confirmed migration 062 and zero rows in task_idempotency, tasks,
canonical_runs, canonical_node_runs and canonical_attempts (`worker-db-final.log`).
The disposable database is retained.

### Acceptance and unresolved handoff

All ten named prospective codec tests executed in the 204-node run. They
prove immutable snapshot/mapping round trips, strict storage UUIDs and signed
timestamps, matching scalar headers, no inferred legacy binding, expiry and
fingerprint evidence surviving full-decode failures, unknown-format rejection,
tag preservation without fingerprint recomputation, safe corrupt JSON errors,
and identical TEXT reads through raw and production-codec pools. Corrupt
surrogate TEXT was injected into every snapshot column through real PostgreSQL;
the decoder rejected it safely without altering header evidence.

These tests do not establish production admission: their principals are fixture
strings and source search finds no codec caller outside its defining module.
New model-based evidence encoding/materialization, original-model fingerprinting,
Run JSONB object insertion, authorized Workspace/Project/Graph admission,
consumer expiry/409 precedence, full unchanged CI, and coordination/activation
approval remain **UNVERIFIED**. No pre-fix/mutation evidence is claimed because
no production code or test was changed.

**BLOCKED.** The actual failed command is trusted-base provenance, not Vulture.
The Vulture-only ledger exception cannot authorize reachability changes; no
ledger, grant, gate, whitelist or runtime consumer was altered. The dispatched
`test: failure` remains **UNRESOLVED** without its exact current-head traceback;
neither focused nor adjacent execution reproduced it. Do not assign another
speculative codec repair before obtaining that traceback and an owner-authorized
resolution of the reachability blocker. Only this report changed; tests and
inventory counts are unchanged, so no inventory note is required.

Progress: checked 1 issue, done 0 repairs, skipped 0, errors 1 provenance blocker.
Next: integration-owner resolution and exact CI failure evidence, not another
unqualified green-run claim. This local commit is a blocked handoff only.

## Repair job 2fbeda4b — validation at 47df7782


- Assigned issue: #1893 only; branch `auto-1893`.
- Starting HEAD: `47df778298fefc285ed416ba5005c2055b7561a6` (verified); supplied develop base: `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Initial worktree clean; no incoming edits to salvage.
- Inputs: supplied dispatch-context.json, check-0.log through check-4.log, prior result if present.
- Files under review: admission codec, admission identity types, adjacent admission tests, existing atomic-admission inventory notes, relevant CI configuration and quality gates. Edits limited to evidence-backed #1893 repairs and this validation report; vulture ledger only if the assigned scan proves a need. No reachability/grant/gate edits or production activation.
- Ambiguity: dispatch reports `test: failure` without a failing test. Proceed by inspecting saved logs and running focused validation; do not invent a repair.

## Progress

- Confirmed assigned HEAD and clean worktree; read repository instructions and issue acceptance body from saved dispatch evidence.
- Inspected saved driver logs (all pass, focused tests skip three PG cases),
  prior result, codec/identity source, adjacent tests, binding inventory note,
  and exact-debt-ledger workflow. Read accepted ADR-081226-a66b and
  ADR-082526-7f02: immutable admission provenance must not become an alternate
  execution or authorization authority. No activation is justified by this leaf.

### Fresh executed validation

All commands ran at the starting source SHA, with 1000–1200 second timeouts.
Logs for lint, format, mypy, focused tests, inventory and consumer search are
`worker-*.log` in the assigned job directory.

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: passed, 1323 findings,
  zero unclassified. No evidence warrants a Vulture ledger amendment.
- `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python
  scripts/check-ratchet-provenance.py`: **exit 1**. Both admission modules
  have unauthorized NEW reachability dispositions and unreachable-module
  rows. This is the exact-debt-ledger workflow's gate against the resolved
  supplied develop base. The local `origin/develop` resolves to the same SHA.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3277 files already formatted.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: two files passed.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`:
  **201 passed, 3 skipped**, 204 collected nodes. The skips are PostgreSQL
  parametrizations, not durability evidence.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: passed, 16466 nodes, zero duplicate evidence.
- `rg -n 'admission_codec|decode_admission_record' packages/*/src`: only the
  codec's export and definition; no reachable production consumer established.

### Acceptance and blocked handoff

The focused run executes the first nine named prospective contracts: immutable
snapshot round trips; storage-only owner UUID hex; explicit unbound/bound/partial
legacy evidence; expired-header identity preservation; header expiry and
fingerprint preserved despite full-decode failure; unknown-format rejection;
tagged nonfinite evidence and unchanged stored fingerprint; invalid/duplicate
JSON rejection. Additional cases cover scalar/header mismatch, signed timestamps,
strict UUIDs, safe error chains, corrupt numeric/Unicode TEXT, receipt-only
legacy failures, fresh SQL mappings, and v2 task/receipt binding consistency.
These are codec-boundary tests, not production admission or authorization proof.

The tenth contract (real raw/production PostgreSQL pools), actual model-based
encoding/materialization, original-model fingerprinting, Run JSONB object
insertion, authorized Workspace/Project/Graph admission, consumer expiry/409
precedence, full unchanged required CI, and coordination/activation approval
are **UNVERIFIED in this round**. No database was provisioned and no new mutation
or pre-fix failure is claimed. Previous PostgreSQL claims above are historical,
not substituted for current execution.

**BLOCKED.** The dispatched `test: failure` remains **UNRESOLVED** without a
current-head failing traceback; focused tests do not reproduce it. The proven
provenance blocker requires integration-owner resolution outside the permitted
Vulture-only ledger exception. Do not invent a caller, self-authorize a grant,
or change gates to bypass it. Obtain that resolution and the exact failing CI
traceback before assigning another speculative repair.

Only this report was appended; all earlier report content is preserved. No
source, tests, ledgers, grants or gates changed. Inventory delta is zero, so no
new inventory note is needed. Progress: checked 1, done 0 repairs, skipped 0,
errors 1 unresolved provenance blocker. The local commit is a blocked evidence
handoff, not integration approval.

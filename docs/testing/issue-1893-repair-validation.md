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

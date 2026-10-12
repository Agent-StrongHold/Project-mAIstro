# Issue #1893 repair validation — job 429cf218

## Frozen scope

- Assigned writer worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD: `6889a90c21a010cd52e05679273b7f715d1f8fc8` (verified); clean working tree.
- Supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- One item: #1893 admission codec repair; no other issues/PRs will be processed.
- Files inspected for acceptance: admission codec and identity DTOs, their two test
  files, adjacent idempotency/runtime code, relevant ADRs, CI workflows and gate
  implementation, supplied dispatch/check logs. Planned write scope: this report;
  production/test/ledger changes only if actual validation establishes a scoped defect.
- Ambiguity: dispatch says generic `test: failure` without a failing node and
  separately identifies a reachability-provenance blocker. Treat both as claims
  requiring fresh checks, not authorization to alter gates or reachability ledgers.
- The explicit vulture-ledger repair exception does not authorize reachability
  ledger/grant edits. Production activation remains outside B2 scope.

## Progress

Read repository instructions, full issue body and supplied prior result/report.
Driver logs report passing sync, ruff/format, focused 201 passed/3 skipped and
core inventory 16466 nodes. These claims are not PostgreSQL proof.

Fresh execution at the starting source SHA:

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 findings,
  zero unclassified. No evidence warrants a vulture ledger amendment.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python
  scripts/check-ratchet-provenance.py`: FAIL. Both admission modules add
  unreachable-module rows and dispositions without trusted-base authorization.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`:
  201 passed, 3 skipped. Unspecified CI test failure not reproduced.

No source changes or new tests. The provenance blocker is reproduced; no
permission exists in this lane to amend the reachability authorization/ledgers.

Read complete codec/identity source and both test files, accepted ADRs
081226-9944, 082526-7f02 and 083126-5e62, plus the exact-debt-ledger workflow.
Source import search finds no production codec consumer (only codec-to-identity
and whitelist imports). DTO tests do not establish runtime activation, authority,
or canonical Run admission. Reconciliation: preserve B2's inactive scope and
canonical ownership rather than adding fake callers to pass reachability.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3277 files).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS.
- Local PostgreSQL version query: 18.6; dedicated disposable database name
  `maistro_1893_429cf218` verified absent before creating it for live validation.

## Live database and adjacent validation

Executed against the starting source SHA (only this report changed):

```sh
createdb maistro_1893_429cf218
DATABASE_URL=postgresql:///maistro_1893_429cf218 uv run alembic upgrade head
MAISTRO_TEST_PG_DSN=postgresql:///maistro_1893_429cf218 \
MAISTRO_TEST_DATABASE_URL=postgresql:///maistro_1893_429cf218 \
MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest \
  packages/maistro-core/tests/tasks/test_admission_codec.py \
  packages/maistro-core/tests/runs/test_root_admission_identity.py \
  -x -q -o junit_family=legacy --junitxml=/tmp/1893-429cf218-live.xml
```

- Real migration chain from empty DB through 001->062: PASS. SQL confirms 062.
- 204 collected nodes: **204 passed, zero skipped**. Three database cases
  round-trip unbound, bound and acknowledged rows through raw/production pools.
- Production/raw session PID pairs: 60736/60737, 60738/60739, 60740/60741,
  respectively; same named local database over Unix sockets, distinct sessions.
  Each case records one persisted admission row in the JUnit properties.
- Fault boundary: escaped-surrogate TEXT injected in each snapshot column;
  both pools produce typed safe failures preserving header fingerprint evidence.
- Final SQL counts: task_idempotency=0, canonical_runs=0,
  canonical_node_runs=0, canonical_attempts=0. Disposable DB retained.
- No mutation/pre-fix run or destructive downgrade performed in this round.

Additional commands:

- `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q`: **1918 passed, 310 skipped**;
  six aiosqlite closed-event-loop thread warnings. No PG environment supplied
  for this adjacent run; its skips do not establish database durability.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: PASS, 16466 nodes, zero duplicate evidence.

## Acceptance accounting

| Criterion | Executed evidence / limitation |
| --- | --- |
| Exact interfaces; immutable/slotted header; named columns; strict UUID hex and signed scalar timestamps | Source inspection, scoped mypy, focused scalar/generation/owner rejection tests PASS |
| V2 snapshots, binding and acknowledgement; fresh flat SQL mapping | Three-state unit and live PostgreSQL round-trips PASS; independent task_id/run_id assertions at test_admission_codec.py:134-137 |
| Legacy bound, unbound, partial and receipt-only rows remain distinct without identity invention | Focused legacy tests PASS, including missing receipt and unreadable original evidence |
| Header/full-decode separation; expiry/fingerprint evidence survives failures; mismatched header rejected | Focused preservation/mismatch tests PASS; codec has no clock or incoming fingerprint |
| Unsupported schema/format, invalid scalar and snapshot data fail closed with safe diagnostics | Focused schema, format, duplicate/nonobject/nonfinite, precision, Unicode and suppressed-chain tests PASS |
| Evidence tags/program_context preserved without recomputing fingerprint | Tagged-nonfinite and snapshot round-trip tests PASS |
| TEXT snapshots independent of JSON codec registration on real migrated schema | All three live pool-contrast cases PASS; both nonempty DSNs name the same DB; pg_pool is non-None |
| Materialization via model_of/model_of_json; Run payload INSERT yields JSONB object | UNVERIFIED: this inactive codec does not materialize models or insert Run payloads |
| Explicit principals, authorized Workspace/Project and registered Graph kinds in production admission | UNVERIFIED: DTO tests use identity strings, not an authorized admission path |
| No new authority, SQL mutation, HTTP/queue mapping, live _assess, scope/fingerprint utility or policy changes | Source inspected, including adjacent live idempotency classifier; this round changes only this report |
| Focused tests, lint, formatting, applicable mypy and inventory | PASS; no tests added/removed, so no inventory delta required |
| Unchanged full required CI and provenance | Full integration CI UNVERIFIED; required trusted-base provenance FAILS |
| Reported CI test failure repaired | UNRESOLVED: no failing node/traceback supplied; focused and adjacent test runs pass |

## Disposition and handoff

**BLOCKED.** The required provenance gate reproduces unauthorized unreachable
modules/dispositions for `maistro.runs.admission_identity` and
`maistro.tasks.admission_codec`. This is not a develop-sync conflict. The passing
Vulture scan warrants no ledger amendment. Do not manufacture runtime consumers,
change gates or self-authorize reachability to make this staged slice green.

Only `docs/testing/issue-1893-repair-429cf218.md` changed. No production, test,
baseline, grant or gate edits; no GitHub mutation or activation. This is a
validation-only blocked handoff, not a successful repair or integration approval.

Progress: checked=1, done=0, skipped=0, errors=1. Next: owner-governed resolution
of trusted-base reachability authorization/coordinated integration, and the exact
failing CI test log before another repair of this unchanged source is dispatched.


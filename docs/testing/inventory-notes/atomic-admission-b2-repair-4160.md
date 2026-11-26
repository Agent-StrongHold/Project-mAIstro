---
inventory-delta:
  packages/maistro-core/tests: 0
---

# Issue #1893 repair validation — job 4160

## Frozen scope and source

Assigned clean HEAD `707dccc2010c6735fdc00ef59b1324629c065315`, branch
`auto-1893`, worktree `/home/dev/Git/wt/auto-1893`; supplied develop base
`feb19affc965155aede51b1d99825405e67e3786` resolves. Only #1893 is processed.
Candidate edit scope: existing codec and its tests, this note, and the explicitly
permitted vulture ledger only if the actual scan requires amendment. No unrelated
inherited base differences, GitHub state, grants, or other ledgers are changed.
Frozen evidence is the supplied dispatch-context.json and check-0 through
check-4.log in `/home/dev/maistro/jobs/4160a986d6804040b101fd904978e2f5`.

Read repository instructions, migration 055, adjacent identity types/tests, and
accepted ADRs 081426-1f7c, 082526-7f02, 082826-b601, 082826-d9f5. Preserve the
canonical execution spine and immutable admission provenance. Ambiguity: the
issue stages an inactive codec yet requires runtime reachability gates; assume
this assignment authorizes local validation/repair only, not activation or a new
consumer. No ADR behavior is changed. No merge conflict or uncommitted salvage
exists at the assigned starting head.

## Recorded results

Driver logs were inspected, not treated as independently verified acceptance:
sync/lint/format pass; focused suite 201 passed, 3 skipped; core inventory 15111.
The prior job result was inspected: it reports BLOCKED, not integration approval.

Current source independently confirms that bound encoding sets
`task_id = binding.receipt_id` alongside `run_id`; migration 055 requires precisely
that pair. Both one-sided v2 pairs and mismatched task/receipt identity are rejected.
The prior finding about `task_id=None` is stale at this starting head.

Executed the exact requested command:
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'`: PASS, 1328 reviewed identities / 1328 findings. No
unbanked or stale identity requires a ledger amendment; none is made.

Executed `RATCHET_BASE_REV=feb19affc965155aede51b1d99825405e67e3786 uv run python
scripts/check-ratchet-provenance.py`: FAIL, trusted merge base `b1f17b8d6246`.
`maistro.runs.admission_identity` and `maistro.tasks.admission_codec` each add
unauthorized unreachable modules and dispositions. This is not vulture debt;
the explicit vulture allowance cannot authorize other ledger changes. Production
source search confirms no consumer of `decode_admission_record` outside its own
module. Importing it artificially is not an acceptable reachability repair.

The captured hosted `test` failure has no diagnostic text in its check output;
it is not evidence of a particular codec defect.

Created the dedicated disposable database `maistro_1893_4160`; executed
`DATABASE_URL=postgresql:///maistro_1893_4160 uv run alembic upgrade head`:
PASS through the real chain to 060 (including 055), recorded in migrate.log.
With both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
`postgresql:///maistro_1893_4160`, and `MAISTRO_REQUIRE_PG_LEGS=1`, executed:
`uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
-o junit_family=legacy --junitxml=<job>/focused.xml`: **204 passed, no skips**.
The tests require a non-None production-codec pool, use a separate raw pool on
the same server/database, and persist unbound/bound/acknowledged mappings through
the real v2 constraint. focused.log and focused.xml retain evidence.

Executed the CI core-package leg with its environment:
`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests
-x -q`: **14142 passed, 968 skipped, 1 xfailed, 54 warnings**, 199.23 seconds.
This non-PG full-package run does not replace the no-skip focused PG proof.
Warnings include SQLite datetime/fork deprecations, aiosqlite event-loop-closed
callbacks and an unawaited fake-process coroutine. See core.log. No core test
failure reproduced; other packages and the complete hosted test job remain
unverified. No speculative production or test repair is justified by this run.

Executed `uv run ruff check .`, `uv run ruff format --check .`, and
`uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS.
`uv run python scripts/check-suite-inventory.py --suite
packages/maistro-core/tests`: PASS, 15111 collected nodes. No tests added or
removed; inventory delta is zero. See static.log.

Additional candidate gates all PASS: `uv run python scripts/check-reachability.py`,
`check-reachability-dispositions.py`, `check-promotion-surface.py`, and
`check-radon-baseline.py` (138/138). See gates.log. Candidate-ledger consistency
is not trusted-base authorization; the provenance failure above still blocks.
`git diff --check`: PASS.

## Acceptance evidence and limits

All ten prospective contracts execute in focused.xml (204 collected node IDs
also saved in collected-nodes.log):

- v2 snapshot round trip: byte equality for canonical snapshots in unbound,
  bound, and acknowledged states; independent binding-column assertions.
- owner storage: UUID .hex only, rejection of noncanonical forms, safe messages.
- legacy bound/unbound/partial: distinct DTOs or typed failures, including
  receipt-only and bound-pair-without-receipt evidence; no identity fabrication.
- expired legacy header: scalar expiry preserved without clock or invented IDs.
- malformed legacy snapshot: full decode fails while header expiry survives.
- partial legacy binding: header fingerprint survives full-decode failure.
- unknown formats: fail closed, including attempted mismatching-header decode.
- tagged nonfinite data: tags remain intact and fingerprint is unchanged.
- invalid/duplicate/nonobject/bare nonfinite JSON: typed safe rejection;
  additional numeric-loss, Unicode, nesting and header validation cases pass.
- real raw/production pools: same migrated TEXT evidence through independent
  sessions in all three v2 states, including corrupt escaped-surrogate rejection.

The actual bound-encoding regression was injected **in memory only**, wrapping
`encode_admission_record` to set `task_id=None` without changing source files.
Running pytest's existing `test_v2_round_trip_preserves_all_snapshot_bytes`
selection produced **2 failed, 1 passed**, precisely the bound and acknowledged
assertions at test_admission_codec.py:134 (binding-mutation.log). This proves
those assertions detect the named regression; the unmutated focused suite is
green. No new production fix is claimed in this round.

PostgreSQL session PID pairs (production/raw) recorded in focused.xml:
unbound 2960848/2960849, bound 2960850/2960851, acknowledged 2960852/2960853.
All use `maistro_1893_4160` over the local Unix socket. Each test observed
exactly one scoped admission row. Final SQL: migration 060; zero admission rows,
zero distinct generations, zero bound Run IDs, zero canonical Runs after cleanup.
A diagnostic query against `runs` failed because that table does not exist;
the source-confirmed `canonical_runs` query then returned zero. This diagnostic
mistake is not a test failure and changed no database state.

These are codec representation tests, not authorized admission tests: their
identity strings are fixtures and no Workspace/Project authorization or registered
Graph admission is exercised. Production consumer reachability, evidence-json
model materialization via model_of/model_of_json, real Run JSONB object writes,
end-to-end admission, live replacement/409 precedence, and the complete hosted CI
job remain **UNVERIFIED**. No fake imports, alternate execution authority,
activation, HTTP response changes or gate weakening were introduced.

## Handoff

Only this evidence note changes. The reported storage-shape bug is already
repaired at the assigned head; the required vulture scan needs no amendment.
The full core test leg now has independent passing evidence, but the supplied
hosted failure lacks an established traceback. **BLOCKED** on trusted-base
reachability/disposition authorization or coordinated consumer integration,
which cannot be manufactured in this bounded repair. Next: dependency owners
resolve that gate through the approved process and provide the actual hosted
failure trace before another speculative repair round.

Progress: checked 1 issue, validation done 1, skipped 0; 1 required gate failed.
No issue closure or integration approval is implied. Preserve the dedicated
local DB and job logs as validation artifacts.

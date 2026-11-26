---
inventory-delta:
  packages/maistro-core/tests: 0
---

# Issue #1893 repair — job 8b24

## Frozen scope

Only issue #1893, assigned worktree `/home/dev/Git/wt/auto-1893`, branch
`auto-1893`, clean starting HEAD `ac84e2907dfc3b6eb95a57f6b19024f9db04f82c`.
Supplied develop base `28614700bd9ab0223eac06924a204af4a5cc25d9` resolves.
Frozen inputs: dispatch-context.json, check-0.log through check-4.log in
`/home/dev/maistro/jobs/8b242d79c6b94f079be1ab064131d676`, and supplied prior
job 4160 result. No GitHub re-enumeration or mutation. Candidate repair files
are the codec, its existing tests, this note, and the explicitly permitted
vulture ledger only if demonstrated necessary. Unrelated base differences
are not repairs for this issue.

Read repository instructions; accepted ADRs 081426-1f7c, 082526-7f02,
082826-b601, 082826-d9f5; migration 055's binding constraint; identity types
and adjacent tests. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt,
immutable admission provenance and canonical store ownership. Ambiguity:
the staged leaf forbids production activation but requires runtime reachability.
Proceed with validation only unless a real in-scope defect is established;
no fake import, alternative consumer, or new authorization path is permitted.

## Initial independently checked evidence

Driver logs show sync/lint/format passing, 201 passed / 3 skipped in focused
pytest, and 15111 collected core nodes. These are not live-PG proof.

The reported `task_id=None` bound-encoding defect is stale: current
`admission_codec.py:291` writes the binding receipt identity alongside the Run,
as migration 055 requires. Existing tests assert this independently and reject
one-sided or mismatched binding pairs. No speculative production repair.

Executed exact requested vulture command:
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'`: PASS, 1328 reviewed identities / 1328 findings.
No unbanked or stale identity; no vulture ledger amendment is justified.

Executed `RATCHET_BASE_REV=28614700bd9ab0223eac06924a204af4a5cc25d9 uv run python
scripts/check-ratchet-provenance.py`: FAIL, trusted merge base b1f17b8d6246.
Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` add
unauthorized unreachable modules and dispositions. This is not vulture debt;
permission to amend that ledger does not authorize other ledger/grant changes.
Production source search finds no codec consumer outside its own module.

## Executed validation

All commands below ran in the assigned worktree at the starting source SHA;
only this note changes. Logs are retained in the job directory above.

- Created dedicated disposable `maistro_1893_8b24` on local PostgreSQL 18.6.
  `DATABASE_URL=postgresql:///maistro_1893_8b24 uv run alembic upgrade head`
  passed through the real chain including 055 to 060 (`migrate.log`). No
  synthetic schema, shared DB, or downgrade used.
- With `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` both set to
  `postgresql:///maistro_1893_8b24`, and `MAISTRO_REQUIRE_PG_LEGS=1`:
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job>/focused.xml`: **204 passed, no skips**.
  `focused.log`, `focused.xml`, and `collected-nodes.log` retain results and
  collected identities (131 codec, 73 identity tests).
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
  packages/maistro-core/tests -x -q`: **14142 passed, 968 skipped, 1 xfailed,
  60 warnings**, 242.80 seconds (`core.log`). This non-PG package leg does
  not substitute for the focused no-skip PG run. Warnings include SQLite
  datetime/fork deprecations, aiosqlite closed-loop callbacks, and an unawaited
  fake-process coroutine. No core failure reproduced.
- `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy
  packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: PASS, 15111 nodes; no test additions/removals.
- `uv run python scripts/check-reachability.py`,
  `check-reachability-dispositions.py`, `check-promotion-surface.py`, and
  `check-radon-baseline.py`: PASS (`static-gates.log`). Candidate consistency
  does not override the failed trusted-base provenance check recorded above.

The real-pool tests require a non-None production-codec pool and contrast
independent raw asyncpg sessions against the same migrated DB. PID pairs
(production/raw) in focused.xml: unbound 3500050/3500053, bound
3500055/3500057, acknowledged 3500058/3500060. Each persisted exactly one
scoped admission row. Final SQL (`final-sql.log`) reports migration 060,
zero admission rows, zero distinct generations, zero bound Run IDs, and zero
canonical Runs after test cleanup. These are representation tests, not
claims of authorized admission, transactions spanning Run creation, or dispatch.

Regression sensitivity was independently checked without editing source:
wrapped `encode_admission_record` in memory to force `task_id=None`, then ran
pytest selecting `test_v2_round_trip_preserves_all_snapshot_bytes`.
**2 failed, 1 passed**: the bound and acknowledged variants fail at line 134;
the unbound variant passes (`binding-mutation.log`). The wrapper process
exited successfully only after asserting pytest reported TESTS_FAILED.

## Acceptance and limits

The ten prospective B2 contracts execute in focused.xml:

1. V2 snapshot byte round trip: independent binding-column assertions and
   equality in unbound, bound and acknowledged states.
2. Owner token: storage-only UUID .hex; noncanonical encodings rejected;
   generated repr and typed errors omit the token.
3. Legacy binding: bound/unbound/partial distinguished; receipt-only and
   absent receipt evidence fail without fabricating identity.
4. Expired legacy header: scalar timestamps preserved without clock or IDs.
5. Malformed legacy snapshot: full decode fails while expiry header survives.
6. Partial legacy binding: fingerprint header survives full decode failure.
7. Unknown formats: fail closed even under a supplied supported header.
8. Tagged nonfinite snapshots: evidence tags and original fingerprint survive.
9. Invalid/duplicate/nonobject/bare nonfinite JSON: safe typed rejection,
   including nesting, numeric loss and escaped-surrogate corruption cases.
10. Raw/production pools: identical TEXT through real migrated storage in all
    three v2 binding states, including corrupt snapshot rejection.

Source inspection confirms the required frozen/slotted header, enum/error
surface, named-column mapping, signed scalar validation, strict UUID parsing,
header equality check, fresh encoding map, and no clock, incoming fingerprint,
SQL mutation, HTTP mapping or queue changes. ADRs require no reconciliation
beyond leaving activation, canonical execution authority and provenance intact.

**UNVERIFIED:** reachable production consumer, model_of/model_of_json
materialization of evidence tags, Run JSONB object writes, authorized admission
with real principals/Workspace/Project/registered Graph, live replacement/409
precedence, and complete hosted CI. Hand-authored snapshot fixtures do not prove
those integration contracts. The dispatch's captured `test` check for #1945
head 7157f4bbdbea is success; its captured failure is #1855 head 3f2c79a70d9e,
with null output title/summary/text. Neither supplies a traceback for the
assignment's merge-queue `test: failure`; its cause remains unestablished.
No unrelated package or gate is edited on a guessed diagnosis.

## Handoff

**BLOCKED**: trusted-base reachability/disposition authorization or coordinated
consumer integration is required. Vulture has no debt to amend. Only this
inventory/evidence note changes, with delta zero; no code repair is claimed.
No conflicts or uncommitted salvage existed and no branch sync was attempted.
Next: resolve the dependency through its approved owner/process and supply the
actual merge-queue test traceback before redispatching a speculative repair.

Progress: checked 1 issue, validation done 1, skipped 0, errors 1 required gate.
This is not integration approval or issue closeout. Preserve the disposable DB
and job logs as validation artifacts. The note is committed locally.

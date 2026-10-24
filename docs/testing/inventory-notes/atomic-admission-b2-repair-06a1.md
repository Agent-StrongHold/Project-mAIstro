---
inventory-delta:
  packages/maistro-core/tests: 0
---

# Issue #1893 — repair validation 06a1

## Scope and current evidence

Assigned branch `auto-1893`, clean starting source commit
`43b8f1a62194df949f9efc88587609658bf8a90f`; supplied develop ref
`e3233939343b43249aa65a32b6d3b3aeb35d4dc5` resolves. Frozen input is issue
#1893 and the dispatch/check logs in job
`/home/dev/maistro/jobs/06a10de4f393418abacc505b2e3648fa`. No GitHub changes,
new consumer, activation, authorization, or unrelated repair is permitted.

Read repository instructions and accepted ADRs 081226-a66b (canonical
Run/NodeRun/Attempt ownership), 082826-b601 (one canonical consumer), and
083126-5e62 (trusted-base quality authority). Reconcile the request for runtime
reachability with the leaf's explicit no-consumer scope by reporting the
missing integration, not fabricating an import or expanding execution authority.

The reported bound encoder defect is already fixed at the starting commit:
`admission_codec.py:291` emits the existing binding receipt as `task_id`,
and `_v2_binding` rejects one-sided and receipt-mismatched pairs. Existing tests
assert the SQL shape independently of encoder/decoder agreement. This round
must not claim that prior repair as a new code change.

Driver check logs show lint/format/inventory success and 201 focused tests
passing with three PostgreSQL skips. Those skips are not durability proof.

Fresh exact vulture command:
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` passed: **1328 reviewed identities, 1328 findings**
(`repair-vulture.log`). There is no evidenced unbanked/stale identity to amend.
The permitted vulture-ledger exception does not authorize other ledger edits.

Fresh required provenance command:
`RATCHET_BASE_REV=e3233939343b43249aa65a32b6d3b3aeb35d4dc5 uv run python
scripts/check-ratchet-provenance.py` **failed**, resolving trusted merge base
`b1f17b8d6246`. It names precisely two unauthorized new unreachable modules
and their dispositions: `maistro.runs.admission_identity` and
`maistro.tasks.admission_codec` (`repair-provenance.log`). Production source
search finds no codec consumer outside its defining module. Candidate ledger
consistency cannot authorize these additions. No gates or grants were changed.

## Executed validation

All commands run against the starting source SHA; only this note changes.
Logs below live in the job directory above.

- Created dedicated disposable database `maistro_1893_06a1` on PostgreSQL 18.6.
  `DATABASE_URL=postgresql:///maistro_1893_06a1 uv run alembic upgrade head`
  passed the real chain including 055 through 060 (`repair-migrate.log`).
- With both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
  `postgresql:///maistro_1893_06a1`, and `MAISTRO_REQUIRE_PG_LEGS=1`, ran
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job>/repair-focused.xml`:
  **204 passed, no skips** (131 codec and 73 identity cases).
- Raw/production-codec session PID pairs in `repair-focused.xml`: unbound
  3778733/3778735; bound 3778736/3778738; acknowledged 3778739/3778740.
  All connect to the same disposable DB; each case asserts one stored scoped
  admission row and exact TEXT/mapping/DTO equality through both pools.
- `uv run ruff check .`, `uv run ruff format --check .`, and focused
  `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py` passed.
- `uv run python scripts/check-reachability.py`,
  `check-reachability-dispositions.py`, `check-promotion-surface.py`, and
  `check-radon-baseline.py` passed candidate-consistency checks. This does not
  supersede the failed trusted-base provenance gate above.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests` passed: **15111 nodes**, unchanged inventory.
  Static outputs are in `repair-static.log`.

An initial post-test SQL audit incorrectly queried nonexistent `runs` and
failed. This is an audit command error, not a codec/test failure; corrected
schema-verified counts follow: migration **060**, **zero** admission rows,
generations, bound Run IDs and canonical Runs after test cleanup. The corrected
command uses `canonical_runs`, as named in `runs/pg_store.py:126`, and passes
(`repair-final-sql-corrected.log`). These are representation tests, not
successful authorized Run admissions.

- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
  packages/maistro-core/tests -x -q`: **14142 passed, 968 skipped, 1 xfailed,
  59 warnings**, 197.49 seconds (`repair-core.log`). This non-PG package run
  does not substitute for the no-skip focused PG proof above. Warnings include
  aiosqlite closed-loop callbacks and an unawaited fake-process coroutine.
- Regression sensitivity: an in-memory wrapper around
  `encode_admission_record` forced `task_id=None` without changing source.
  Pytest selection `-k test_v2_round_trip_preserves_all_snapshot_bytes`
  produced **2 failed, 1 passed**, with bound and acknowledged cases failing
  at `test_admission_codec.py:134`. The probe asserts TESTS_FAILED before
  exiting successfully (`repair-binding-mutation.log`).

## Acceptance evidence and limits

The focused XML records execution of all ten prospective B2 contracts:

1. Snapshot byte round trips and independent binding-shape assertions pass
   for unbound, bound and acknowledged records.
2. Owner UUIDs use strict storage-only `.hex`; noncanonical forms fail safely.
3. Legacy bound, unbound and partial evidence is distinguished without
   fabricating missing identities, including receipt-only rows.
4. Expired legacy headers expose exact timestamps without clock/identity
   inference.
5. Expiry evidence survives malformed legacy snapshot rejection.
6. Fingerprint evidence survives partial legacy binding rejection.
7. Unknown formats fail closed even with a supplied supported header.
8. Tagged nonfinite evidence and the stored fingerprint survive round trips.
9. Invalid/duplicate/nonobject/bare-nonfinite JSON fails safely, along with
   nested, numeric-loss and invalid-Unicode cases.
10. Raw and production-codec pools return identical TEXT and exact DTOs from
    the same real migrated schema; all three PostgreSQL cases execute.

Inspection additionally confirms the frozen/slotted header, required enum and
error API, scalar/header matching, signed timestamps, strict UUID decoding,
constructor validation, fresh flat SQL parameter mapping, and no clock,
request-fingerprint comparison, fingerprint recomputation, SQL mutation, HTTP
mapping, claim decision or queue change in this leaf. Migration 055 agrees
with the existing binding repair. No changes to canonical execution ownership.

**UNVERIFIED / blocked integration:** production codec reachability;
`model_of`/`model_of_json` materialization of real request/receipt/Run evidence;
Run JSONB object insertion; authorized admission with real principals,
Workspace/Project and registered Graph; live replacement/409 precedence; and
complete hosted CI. Synthetic snapshots prove representation only, not those
end-to-end contracts. C/F2 own decision precedence, not this leaf.

The generic merge-queue `test: failure` is not reproduced in the core suite or
focused tests. Supplied check logs contain no failed-node traceback. Earlier
comment/result claims are not proof of its cause, and unrelated packages or
policy must not be edited on that guess.

## Handoff

**BLOCKED** on the executed trusted-base provenance failure. Resolve the
reachability dependency through the approved integration/authorization owner;
the vulture-only amendment allowance cannot resolve it. Supply the actual
hosted failed-node traceback before another speculative CI repair. No ledger,
grant, gate, runtime code or test changed this round. Only this zero-delta
inventory/evidence note is committed locally; this is not integration approval.

Progress: checked 1 issue; validation done 1; skipped 0 items; errors 1 required
gate (plus the corrected audit query recorded above). Disposable DB and job
logs are preserved. No sync conflict existed; no merge or remote mutation was
attempted.

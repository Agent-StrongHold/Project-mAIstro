---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 bounded repair — 13c9

Snapshot: issue #1893 only; assigned branch `auto-1893`, initial HEAD
`78225f3a07cf9eedcf0f8299adb38436c2b52137`, supplied develop base
`8fbbbfb91d78d30d756cf675b7b1a4c1ccff06e5`. Worktree initially clean.
Scope: admission codec, adjacent codec tests, their inventory note; reviewed
vulture ledger amendments only if the requested scan demonstrates a need.
Read-only dependencies: immutable admission types, migration 055, admission
consumer, relevant ADRs and CI scripts. No activation or ownership changes.

Evidence inspected: dispatch issue body, latest captured comments, supplied
check-0 through check-4 logs. Driver reports lint/format passing and 201 tests
passing / 3 skipped; database acceptance is not established by these logs.
Assumption: the explicit repair assignment authorizes this local staged repair,
not production activation or resolution of the parent's policy decisions.

Initial fresh results: exact Vulture scan passes (1326 reviewed identities /
1326 findings), so no ledger amendment is justified. The reported bound-encode
bug is already repaired at the assigned HEAD: `task_id` uses the binding's
receipt identity, validated independently by adjacent state-parametrized tests.
Production-reference search finds no codec consumer; do not add a fake caller.
Docker is unavailable on the prescribed socket; check the existing local
PostgreSQL alternative before declaring database validation blocked.

## Fresh validation checkpoint

- `uv sync --locked --extra dev`: passed.
- `createdb maistro_1893_13c9` followed by
  `DATABASE_URL=postgresql:///maistro_1893_13c9 uv run alembic upgrade head`:
  passed, real migration chain through 061 (including 055), no stamping.
- With both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
  `postgresql:///maistro_1893_13c9`, and `MAISTRO_REQUIRE_PG_LEGS=1`:
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=.pytest_cache/repair-13c9/focused.xml`:
  **204 passed, zero skips**. Same paths with `--collect-only -q`: 204 nodes,
  recorded in `.pytest_cache/repair-13c9/nodes.log`.
- Three real raw/production pool legs use distinct session PIDs on the same
  disposable DB: 2249880/2249882 (unbound), 2249883/2249884 (bound),
  2249885/2249886 (acknowledged). Each asserts exactly one persisted admission
  row, equal named-column TEXT mappings and exact DTO round trips. They also
  inject escaped-surrogate corruption into every snapshot column and assert
  safe typed errors through both pools. Final SQL counts after cleanup:
  zero admissions, distinct generations and bound Runs. DB retained.
- `uv run ruff check .`: passed; `uv run ruff format --check .`: passed
  (3195 files); `uv run mypy
  packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: passed.
- `RATCHET_BASE_REV=8fbbbfb91d78d30d756cf675b7b1a4c1ccff06e5 uv run python
  scripts/check-ratchet-provenance.py`: **failed**, exit 1. Fresh log
  `.pytest_cache/repair-13c9/provenance.log:21-30` reports NEW unauthorized
  reachability/dispositions for `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` against trusted merge base `e46ad6708fda`.
  Candidate ledgers cannot authorize these entries (accepted quality ADR).

- Process-local mutation of `encode_admission_record` to emit `task_id=None`,
  then `pytest.main` on the codec file with `-q -k
  test_v2_round_trip_preserves_all_snapshot_bytes`: **2 failed, 1 passed,
  128 deselected**, as expected. Both bound states fail the independent
  storage assertion at test line 134. No on-disk source mutation.
- `uv run pytest packages/maistro-core/tests/extensions/test_cli_certification.py::test_certify_refuses_a_malformed_signing_key -x -q`:
  **failed** at line 287. Rich wraps `not\na hex Ed25519 private key`, breaking
  the contiguous substring assertion. This is a reproduced adjacent-package
  test failure, not an admission codec defect. Whether it is the reported
  hosted `test: failure` is **UNVERIFIED** without that hosted traceback.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: passed, 15932 unique identities, no delta.
- Exact Vulture command from the assignment: passed again, 1326/1326.
- `uv run python scripts/check-<name>.py`, for `shipped-surface-truth`,
  `reachability`, `reachability-dispositions`, `promotion-surface`: each
  passed. These candidate checks do not override failed trusted provenance.

All validation uses the initial source SHA above, with only this note added.
Logs live under ignored `.pytest_cache/repair-13c9/`.

## Acceptance audit

The executed 204-test run proves the internal codec contracts below, not
reachable production admission. The test file's ten prospective contracts
are all present and passed, with all three real database legs enabled.

- Frozen/slotted header and immutable constructor-backed records; named
  columns; signed timestamp/hex validation; mismatched headers and unsupported
  schemas/formats fail closed; flat mappings are fresh. Source inspection and
  header/schema/encode tests passed.
- V2 snapshots and stored fingerprint survive unbound, bound and acknowledged
  round trips; binding equals the receipt identity required by migration 055.
  State-parametrized tests, real SQL inserts and regression mutation prove it.
- Owner remains UUID in the DTO and strict lowercase hex only at storage;
  invalid UUID forms/nil values are rejected and owner repr is hidden.
- Legacy complete explicit binding, unresolved absence, partial pairs,
  receipt-only and unreadable evidence stay distinct; missing receipt identity
  is never fabricated. The codec ignores optional `completed_at`.
- Legacy header expiry survives full snapshot errors; header fingerprint
  survives partial bindings; no clock/request fingerprint is accepted and no
  expiry/mismatch/claim decision is introduced. Unknown formats never fall
  through to legacy. All corresponding tests passed.
- Tagged nan/inf/-inf evidence remains tagged JSON without fingerprint changes.
  Strict snapshot tests reject duplicate keys, nonobjects, bare nonfinite,
  overflow/lossy numbers, excessive nesting and invalid Unicode with sanitized
  typed errors and suppressed parsing chains. Valid Unicode/numbers survive.
- Raw versus production-codec pools return identical snapshot TEXT from the
  actual migrated table, proven above rather than by skipped/fake PG tests.
- Physical `request` TEXT maps to DTO `request_snapshot`; the shipped migration
  governs this mapping, not a new column invented from ambiguous prose.
- Stage constraints preserved: no SQL mutation code, queue/HTTP policy,
  scheduler, Goal store, authorization path or consumer activation changed.
  Accepted ADR-081226-a66b retains Run lifecycle authority and canonical
  Goal -> Graph -> Run -> NodeRun -> Attempt. ADR-083126-5e62 prevents candidate
  observations from granting their own quality authorization.

**UNVERIFIED / not established:** model-level evidence materialization through
`encode_evidence` and `model_of`/`model_of_json` (fixtures use synthetic JSON);
arbitrary permitted program_context through production model materialization;
authorized Workspace/Project/principal and registered Graph admission; Run
`json_of(run)` TEXT-to-JSONB object insertion; live inclusive-expiry/409 ordering;
transaction/crash/dispatch invariants; migration downgrade/adoption; full
required hosted CI. The codec is still an inactive contract leaf, so unit
imports, exports and whitelist entries are not runtime reachability evidence.

## Handoff — BLOCKED

Changed file: this inventory/handoff note only; zero added tests. The old
binding defect is already fixed and Vulture has no discrepancy. Editing source
or a Vulture ledger without an observed defect would not repair the failed
provenance gate. Its two inactive modules require coordinated genuine consumer
wiring or separately landed trusted-base authorization, neither authorized by
this lane. No grant/ledger/gate edits, GitHub mutations or discarded work.

Progress: checked 1 issue; done 1 validation/handoff; skipped 0 issues;
errors 2 unresolved checks (provenance and the CLI assertion). Next: obtain
provenance resolution from the integration owner and route the actual test
traceback to the CLI owner. Do not redispatch the unchanged codec as a Vulture
repair. Local commit required; no integration approval or rollout claim.


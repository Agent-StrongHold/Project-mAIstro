# Issue #1893 repair — e40476a8

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `760a60f61edc3f6ade198f72221db0a66ad66724`;
  supplied develop base `ac69535ef165ded3ca82cd3428728569de3251fa`.
- Only issue #1893; no GitHub mutations, integration, activation, or new ownership.
- Initial worktree clean; no incoming edits to salvage.
- Inspection scope: admission codec/identity modules and their adjacent tests,
  repository instructions, relevant ADRs, CI workflows, supplied job evidence,
  exact-debt gates. Intended edit scope: this evidence note; production/test or
  permitted vulture-ledger repairs only if a reproduced failure establishes need.
- Ambiguity: dispatch says `test: failure` without a failing test/node/log.
  Assume focused existing tests and named gates are the initial reproduction.
  No speculative repair or unauthorized reachability grant.

## Supplied driver evidence (not fresh execution)

Job `/home/dev/maistro/jobs/e40476a8927d4871a7631950862c9f9a`:
`check-0.log`: dependency check succeeds; `check-1.log`: lint passes;
`check-2.log`: 3292 files formatted; `check-3.log`: 312 passed, 3 skipped;
`check-4.log`: 16540 core test nodes, inventory passes.
Skipped database tests do not establish durability.

## Fresh results

- Supplied base resolves. `RATCHET_BASE_REV=ac69535ef165ded3ca82cd3428728569de3251fa uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1). Both admission modules are new unreachable modules and new dispositions without trusted-base authorization. Other provenance subgates passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 reviewed identities, zero unclassified/never-allowlist. No Vulture repair or ledger amendment is warranted.
- No develop-sync conflict exists. The reproduced blocker cannot be repaired with the lane's Vulture-only ledger exception. No reachability baseline/grant edits will be made.
- `uv run pytest packages/maistro-core/tests/extensions/test_pack_contracts.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -x -q -rs`: PASS, 312 passed / 3 skipped (315 collected), 1.46s. PostgreSQL skips at `test_admission_codec.py:470` require both DSNs; not durability evidence.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS (3292 files).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS (2 files).
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `rg -n 'admission_codec|admission_identity' packages -g '*.py' -g '!**/tests/**'`: only the codec imports identity, plus `AdmissionAssessment` in the Vulture whitelist. No production codec consumer found; source explicitly acknowledges inactivity at `admission_codec.py:50-53`.
- Read accepted ADR-081226-a66b, ADR-082526-7f02, ADR-082526-1899, ADR-083126-5e62. Reconciliation: preserve Goal -> Graph -> Run -> NodeRun -> Attempt; admission evidence is not dispatch identity or authorization; passing tests are not runtime use; candidate bookkeeping cannot authorize its own reachability expansion. No artificial consumer will be added to make a staged leaf pass.
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests -x -q`: PASS (exit 0), 15467 passed, 1070 skipped, 3 xfailed, 55 warnings in 236.36s. Log: `/tmp/1893-e40476a8-core-pytest.log`. Warnings include aiosqlite threads encountering closed event loops and an unawaited `_FakeProc.communicate`; no failing test reproduced in the changed package. This does not establish that a different CI environment/head passes.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 16540 collected nodes, no duplicate identities or byte-identical test files.

## Acceptance audit at the starting source SHA

| Criterion | Executed evidence / limitation |
| --- | --- |
| Required shared interfaces and immutable DTOs | Inspected `admission_codec.py:127-299` and identity constructors; focused tests pass for frozen snapshots, v2 variants and fresh flat mapping. Header is frozen/slotted with the specified fields. |
| Named columns, strict UUID hex, signed timestamps, matching header | Focused format, scalar, missing-column, UUID, header-mismatch and constructor rejection tests pass. Encode emits `task_id` and `run_id` together; binding identity matches the envelope. No positional SELECT decoding. |
| Legacy bound/unbound/partial, no inferred identity | Focused legacy tests pass: pairs with explicit receipt bind; missing pair/receipt evidence is partial; neither-set remains unbound. `completed_at` is ignored. Bound pair without receipt is deliberately partial because the #1851 constructor requires explicit receipt evidence. No invented identity. |
| Header/full decode separation | Named expired-header, invalid-snapshot and partial-binding tests pass and preserve scalar expiry/fingerprint. Codec takes neither clock nor incoming fingerprint. Consumer inclusive-expiry/409 decision precedence is outside B2 and UNVERIFIED. |
| Strict snapshot TEXT and safe typed errors | Duplicate keys, nonobjects, bare nonfinite, overflow, nesting, numeric precision, UTF-8, predecoded objects and suppressed-chain tests pass. Errors carry only a validated hash and sanitized descriptions. |
| Evidence tags, arbitrary context and unchanged fingerprint | Pure tagged-nonfinite, numeric and Unicode tests pass, with stored fingerprint unchanged. Tests use constructed tagged payloads; original-model fingerprinting, `encode_evidence` and `model_of`/`model_of_json` end-to-end materialization remain UNVERIFIED. No materialization caller exists in this leaf. |
| Raw/production pools on migrated disposable PostgreSQL | UNVERIFIED: three database tests skipped for absent DSNs. No migrations or DB provisioning performed in this round, no backend/session identities or row counts claimed. Run INSERT JSONB object shape is also UNVERIFIED. |
| Explicit principals, authorized Workspace/Project and Graph kinds | UNVERIFIED as production admission: representation tests use fixture strings, not admission authorization. No mock-return or fixture assertion is counted as transaction/dispatch proof. |
| Focused tests, lint, format, applicable mypy, inventory | All PASS as listed above. No new test added, no inventory delta required; existing inventory notes preserved. No fresh mutation/pre-fix run performed, and historical mutation claims are not reused. |
| Required quality gates and reachable behavior | Vulture and shipped-surface PASS; promotion provenance subgate PASS; required reachability/disposition provenance FAIL. Production codec consumer absent. Full cross-package integration CI and other standalone promotion gates UNVERIFIED. |
| No mutation, HTTP/queue/assessment/scope-policy changes or competing execution authority | Preserved by report-only diff. Source inspection finds representation-only code. No activation or policy decision made. Coordination/activation constraints remain open. |

## Handoff — BLOCKED

Only `docs/testing/issue-1893-repair-e40476a8.md` changed this round. No concrete
codec defect or unbanked Vulture finding was reproduced, so no speculative code
or ledger repair was made. All validation used the starting source SHA; the
only subsequent change is this report.

Inherited entries at `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:604-614` still fail required provenance
at `.github/workflows/vulture-ratchet.yml:77`. Candidate edits cannot supply
trusted-base authorization. The narrow Vulture exception does not authorize
reachability grants or a production activation. Resolution needs an owner-led,
separately reviewed trusted-base authorization/coordination decision, or an
explicitly authorized real consumer integration. Neither can be fabricated in
this B2 repair lane. No merge/push/remote mutation performed.

Residual risks: exact original CI failing node/log remains unavailable in the
assignment; core tests pass but skip service-dependent coverage; live database,
model materialization and full integration acceptance remain unverified. Do not
redispatch the unchanged head expecting a Vulture amendment to fix provenance.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: trusted-base authorization/coordination}`.
This committed evidence is a blocked handoff, not integration approval.

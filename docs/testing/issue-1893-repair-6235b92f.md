# Issue #1893 repair checkpoint — job 6235b92f

## Frozen scope

- Assigned writer worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting source: `2bc8f8bd866d9bece32a7fc7f98022fdd2620182`.
- Dispatch base: `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Process only issue #1893: immutable admission codec and its identity types,
  adjacent tests, relevant ADRs, CI workflow/gates, and supplied job evidence.
- Candidate edit scope: those codec/identity source and test files only if an
  actual defect is reproduced; this report; inventory note if tests change;
  vulture ledger only if the explicitly authorized repair scan requires it.
  No reachability ledger/grant edits, HTTP/queue/assessment activation, or
  GitHub mutations.
- Initial worktree clean. No incoming edits require salvage.

## Evidence so far

Driver logs in `/home/dev/maistro/jobs/6235b92f7d4b4e79a01f16f40e592e14`:
`check-0.log` dependency sync succeeded; `check-1.log` ruff passed;
`check-2.log` format passed (3277 files); `check-3.log` reports 201 passed,
3 skipped; `check-4.log` inventory passed (16466 core nodes). These are driver
observations, not new worker executions or PostgreSQL durability proof.

Ambiguity: dispatch says `test: failure` without a failure traceback and carries
an earlier reachability-provenance blocker. Reproduce focused tests and exact
ledger checks before making any code repair. Existing policy bars banking an
unwired slice or authorizing it in this branch; the vulture-only exception does
not authorize reachability changes.

## Reproduced gate blocker

Fresh commands (1200-second timeout), at the starting source SHA:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed, 1323 reviewed findings, zero unclassified. No ledger amendment warranted.
- `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python scripts/check-ratchet-provenance.py`: exit 1. Both admission modules add unauthorized reachability/disposition entries (169 trusted entries -> 171). All other constituent checks passed.

Both base SHA and local `origin/develop` resolved to the dispatch base. No sync
conflict exists. Logs: `worker-vulture.log` and `worker-provenance.log` in the
job directory. Workflow `.github/workflows/vulture-ratchet.yml:77` requires
provenance independently of the Vulture identity scan. Changing the Vulture
ledger would not repair this failure.

Read accepted ADR-082526-7f02 (immutable admission provenance; dispatch identity
belongs to Attempt) and ADR-081426-1f7c (Attempt-owned runtime mechanics only).
No ADR reconciliation requires activation or another execution authority.

## Focused validation

Fresh worker executions at the starting source SHA, with 1200-second timeouts:

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3277 files).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: passed (two files).
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s`: **201 passed, 3 skipped**, 204 nodes, 1.25s. All three skips require PostgreSQL environment variables; see `worker-focused.log`.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: passed (16466 nodes, no duplicated evidence); see `worker-inventory.log`.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- Production-source search `rg -n 'admission_codec|admission_identity' packages --glob '**/src/**/*.py'`: only codec-to-DTO and Vulture-whitelist imports. No reachable runtime consumer.

Read both codec/identity source files and both focused test files completely.
Inspected supplied prior result and captured dispatch check-run diagnostics;
no actionable failed-test traceback was supplied. Latest captured issue comments
report repeated blocked attempts, not changed prerequisites. Extraction recorded
in `worker-dispatch-failures.log`. No network re-enumeration was performed.

## Acceptance evidence and limits

| Criterion | Executed evidence or limit |
| --- | --- |
| Frozen/slotted header, public interfaces, typed decode codes | Source inspection and passing header/schema/format validation tests. |
| Exact immutable v2 mapping, fresh flat parameters, named SQL fields | Passing three-state `test_v2_round_trip_preserves_all_snapshot_bytes` and `test_encode_returns_a_fresh_flat_mapping`; binding columns checked independently of encoder/decoder agreement. Physical `request` TEXT maps to DTO `request_snapshot`. |
| UUID hex only at storage; signed timestamp validation and #1851 constructors | Passing owner-token, strict-generation, invalid-scalar, lease-window and invalid-DTO tests. |
| Legacy bound/unbound/partial, receipt-only, announced-without-Run; no inferred identities | Passing `test_legacy_binding_unbound_and_partial_are_distinct`, receipt-only, missing-receipt, one-sided and unreadable-evidence tests. No synthetic identity generation in codec. |
| Header evidence retained despite full decode failure; reject mismatched header | Passing expiry/fingerprint preservation, expired-header and scalar-mismatch tests. |
| Unknown format/schema fail closed | Passing unsupported-format and missing-column tests, including supplied-header laundering rejection. |
| Strict JSON object snapshots; duplicate/nonfinite rejection; safe errors | Passing invalid/duplicate JSON, excessive nesting, lossy-number and invalid-Unicode tests. Parsing errors suppressed; scope contains only validated hash. |
| Tagged program_context evidence preserved; fingerprint unchanged | Passing tagged nonfinite and exact-number/Unicode round trips at representation boundary. Tests compare unchanged stored fingerprint; no recomputation exists in codec. |
| Real evidence-json/model_of/model_of_json materialization, original-model fingerprinting, Run JSONB object insertion | **UNVERIFIED**. Handwritten tagged fixtures do not prove materialization or Run INSERT behavior. This leaf does not materialize models. |
| Raw and production pools against same real migrated PostgreSQL DB | **UNVERIFIED**: all three real-PG cases skipped. No database session identities or final SQL counts collected this round; prior database results are not adopted as fresh evidence. |
| Explicit authorized principals, Workspace/Project and registered Graph | **UNVERIFIED**: fixtures contain plain identity strings, not authorization/admission evidence. |
| No clock, assessment, mutation, HTTP/queue or execution-authority change | Source inspected: representation-only functions. No source changes this round. Canonical execution model preserved; no activation claimed. |
| Inclusive expiry/replacement/409 behavior | **UNVERIFIED**, belongs to downstream consumer C/F2, not this inactive codec. |
| Focused tests, lint, formatting, mypy, inventory and Vulture scan | Passed as recorded above; no test additions, so no inventory delta. |
| Unchanged full required CI and reported `test: failure` | **UNVERIFIED**. Focused failure not reproduced; actionable traceback absent. Required provenance gate independently **FAILED**. |
| Coordinated stack/ownership and production activation | **UNVERIFIED/BLOCKED**. Repair assignment does not authorize activation, grant edits or integration ownership changes. |

No new regression test or mutation proof is claimed. Existing tests inject
corrupt storage mappings/TEXT, not transactions or crash boundaries. Full CI,
PG durability and model integration are not inferred from pure codec tests.

## Final handoff

Only `docs/testing/issue-1893-repair-6235b92f.md` changed. No source, test,
whitelist, ledger, grant or gate edit was justified. The required gate rejects
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613`; these inherited entries remain
unchanged. The Vulture-only repair exception cannot authorize their expansion.

**BLOCKED**: integration owner must supply an already-landed reachability
allowance under the two-merge policy, or coordinate a separately authorized
runtime integration. This worker cannot self-authorize either. Supply the actual
current-head `test` failure traceback before dispatching another code repair.
No merge conflict, missing ref or uncommitted incoming work was found.

Progress: checked 1; done 0 repairs; skipped 0 issues; errors 1 reproduced
provenance blocker; next: external authorization and actionable CI evidence.
This local report commit is a blocked handoff, not integration approval or issue
closeout. No push or GitHub mutation performed.

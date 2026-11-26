# Issue #1893 repair checkpoint — e22b72b1

## Frozen scope

- Sole item: #1893, branch `auto-1893`, starting head
  `d026b97dfed91b3909c2c3cda547e7f46789600f`, assigned base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Inspect existing admission codec, immutable identity DTOs, adjacent tests,
  applicable ADRs and CI gates. Only evidence-backed repairs are authorized.
- Planned write scope: this validation record; implementation/tests only if a
  reproducible in-scope defect is found. No reachability/grant/gate edits.
- Initial worktree clean; no incoming edits to salvage.

## Initial evidence and ambiguity

Read supplied dispatch issue body, prior result and driver check logs 0–4.
Driver reports sync/lint/format/inventory pass and 346 tests passed, 3 skipped.
These are driver results, not new worker execution.
The assignment names `test: failure` without a failing test or traceback.
Proceed by testing the codec and adjacent contracts; do not guess a defect.
Prior result reports a trusted-base reachability authorization blocker. Recheck
that gate independently; vulture ledger permission does not authorize changing
reachability ledgers. Production activation remains explicitly out of scope.

## Worker validation

- Independently ran exact Vulture command: PASS, 1322 findings, zero
  unclassified. No retained-identity ledger amendment is warranted.
- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py`:
  FAIL (exit 1). Both admission modules lack trusted-base authorization for
  their new unreachable-module entries and dispositions (four violations).
  The resolved local `origin/develop` equals the assigned base; no sync
  conflict exists. Do not manufacture runtime imports to evade this gate.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs`:
  204 nodes, 201 passed, 3 skipped (missing PG DSN/database URL). Not durability
  proof. No failing codec test reproduced.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS, 3301 files.
- Source review: codec and codec tests read completely. Header/full decoding
  is separate; encoder emits both task/run binding columns. Module explicitly
  has no runtime consumer. PostgreSQL tests exercise only storage DTOs, not
  authorized Workspace/Project/Graph admission.
- An exploratory ADR-number glob matched no files (exit 2); skipped, then
  resolved the actual ADR filenames from existing references. No guessed ref
  was used for a Git operation. A search at root `migrations/` also found no
  directory; no migration or DB was changed.
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`:
  2229 nodes, 1919 passed, 310 skipped, four aiosqlite closed-event-loop thread
  warnings. This did not reproduce the unspecified hosted `test` failure.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`:
  PASS, two source files.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  PASS, 16567 nodes, no duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `git diff --check`: PASS. Validation commands used 1000–1800 second timeouts.

## Acceptance accounting

All executed tests above use source head `d026b97dfed91b3909c2c3cda547e7f46789600f`;
this round changes only this report. Existing test names below are in
`packages/maistro-core/tests/tasks/test_admission_codec.py` and passed in the
focused execution unless marked otherwise.

| Criterion | Evidence / limit |
| --- | --- |
| Exact immutable DTOs, separate header/full decoder, fresh SQL mapping | Read both implementations and focused tests completely; `test_encode_returns_a_fresh_flat_mapping`, header mismatch and frozen DTO tests pass. |
| v2 snapshot bytes and SQL field mapping | `test_v2_round_trip_preserves_all_snapshot_bytes` passes all three states, independently asserting task_id/receipt_id and run_id shape. No new live SQL proof. |
| Owner token hex only at storage; strict UUIDs and timestamps | `test_owner_token_is_hex_at_storage_only`, strict generation and scalar-header tests pass. |
| Legacy bound, unresolved and partial distinct; no identity invention | `test_legacy_binding_unbound_and_partial_are_distinct`, receipt-only, bound-without-receipt and unreadable-evidence tests pass. |
| Expiry/header evidence survives broken legacy data | `test_expired_legacy_header_does_not_invent_missing_identity`, `test_header_preserves_expiry_even_when_legacy_snapshot_decode_fails` pass. No consumer expiry/409 decision is claimed. |
| Fingerprint preserved even for partial legacy | `test_header_preserves_fingerprint_even_when_legacy_binding_is_partial` passes. |
| Unknown schema/format fail closed | `test_unknown_format_cannot_be_reinterpreted_as_legacy` and missing-column tests pass. |
| Tagged nonfinite evidence, unchanged fingerprint | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change` passes; uses explicit tagged DTO fixtures, not materialized TaskResponse/Run models. Production evidence-json/model_of integration is UNVERIFIED. |
| Malformed/duplicate/nonobject/bare nonfinite JSON; safe typed errors | `test_invalid_and_duplicate_json_is_rejected`, numeric-loss, surrogate and excessive-nesting tests pass, checking suppressed chains and no raw snapshot in messages. |
| Raw and production pools, migrated schema, session identity/row counts | UNVERIFIED this round: three real-PG tests skipped. No DSNs configured, no disposable DB started, no migration chain or residual-row count claimed. |
| Authorized principal/Workspace/Project/registered Graph admission; Run JSONB object | UNVERIFIED; DTO fixtures do not establish these integration requirements. |
| No live assessment, mutation, queue/HTTP policy, scheduler or authority change | No implementation edits. Source import search finds only the codec's DTO import and a Vulture whitelist reference, no production caller. |
| Required integration CI and quality gates | Local lint/format/mypy/Vulture/inventory/shipped-surface checks pass. Exact-debt provenance FAILS. Full integration CI and the unspecified hosted test failure are UNVERIFIED. |

No tests were added, removed or modified; inventory delta is zero, so no new
inventory note is required. No new regression fix or mutation experiment was
performed; existing assertions do not imply a fresh pre-fix failure.

## ADR reconciliation and disposition

Read accepted ADR-081226-69ee, ADR-082826-b601 and ADR-083126-5e62 completely.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` and explicit opt-in
consumption. The issue's inactive-contract staging constraint does not authorize
an artificial consumer, competing execution authority or candidate self-grant.

**BLOCKED**, not repaired or merge-ready. Reproduced evidence:
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613` contain the two unapproved
modules/dispositions. `.github/workflows/vulture-ratchet.yml:77` requires the
failing provenance gate. The Vulture-only repair exception cannot resolve it.
No source or ledger change is justified by the supplied `test: failure` label.

Owner action is required outside this worker's permissions: resolve staged
reachability authorization on the trusted base through the two-merge process,
then dispatch against that resolved base (or explicitly revise the approved
integration scope). Supply the actual failing hosted test traceback if a test
repair is still requested. Repeating this same frozen head/base with no new
evidence cannot remove the blocker.

Progress: checked 1, done 0, skipped 0, errors 1 (confirmed provenance gate);
next: owner resolves trusted-base authorization and supplies localized CI failure.
Only this report is changed and will be committed locally; no GitHub mutation.

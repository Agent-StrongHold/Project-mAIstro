# Issue #1893 repair checkpoint — 177e4310

## Frozen scope

- Assigned worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Inspected starting HEAD: `6dce02e1ee60a95f918248c5ea00ee40e1aa7976` (clean).
- Dispatch base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- One item: issue #1893, immutable admission codec CI repair.
- Inspection scope: admission codec and identity source/tests, their existing inventory
  notes, applicable repository/ADR guidance, CI gate definitions and supplied job evidence.
- Planned edit scope: this validation report; codec/tests only if reproduced evidence
  warrants repair. Vulture ledger edits only for reproduced retained identities.
  No reachability ledger/grant edits, production activation, or GitHub mutations.

## Initial evidence and ambiguity

The supplied job's `check-0.log` reports dependency resolution success;
`check-1.log` ruff success; `check-2.log` 3301 formatted files;
`check-3.log` 324 passed / 3 skipped; `check-4.log` inventory success
(16543 core tests). These are driver results, not independent validation.

The dispatch names `test: failure` without a failing test/log, and reports a prior
reachability authorization blocker. Assumption: reproduce the named gates and
focused behavior first; do not invent a test repair or bypass governance. The
issue describes a staged codec, explicitly not production activation. Runtime
wiring cannot be fabricated merely to silence reachability.

## Independently reproduced gate results

- `uv sync --locked --extra dev`: PASS (256 resolved, 214 checked).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  PASS, 1322 findings / 1322 reviewed identities, zero unclassified. There is no
  evidence warranting a Vulture ledger amendment.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`:
  FAIL. Both admission modules add unauthorized unreachable modules and
  dispositions (169 trusted -> 171 candidate). The checked local `origin/develop`
  resolves to this exact dispatch base. All other provenance subgates passed.
  This reproduces the blocker rather than assuming the prior report is true.

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q`:
  PASS, 327 collected, 324 passed / 3 PostgreSQL skips (1.90s).
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files already formatted.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`:
  PASS, two source files.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  PASS, 16543 collected nodes, no duplicate evidence.

No source or test changes. No merge conflict exists. No ledger edits made.
Test count is unchanged, so no inventory-delta note is required.

Inspection correction: two initially guessed descriptive ADR filenames were
not found; skipped those paths and resolved the real filenames by ID. No git
ref was guessed or unresolved. The source import search confirms the codec
has no production consumer; the identity module is imported only by the codec
and the Vulture whitelist. Tests/export declarations are not runtime wiring.

## Additional validation

- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`:
  PASS, 2229 collected, 1919 passed / 310 skipped / 4 warnings (50.06s).
  Warnings were aiosqlite worker threads encountering a closed event loop in
  existing `test_sqlite_store.py` tests; no failing test reproduced.
- `uv run python scripts/check-reachability.py`: PASS against candidate ledger,
  1403 production modules / 171 unreachable. This does NOT override provenance.
- `uv run python scripts/check-reachability-dispositions.py`: PASS against
  candidate ledger, 50 groups / 171 modules. Same provenance limitation.
- `uv run python scripts/check-promotion-surface.py`: PASS, 74 tolerated modules.
- `git diff --check`: PASS.

## Architecture and acceptance audit

Read accepted ADR-081226-a66b (Run/NodeRun/Attempt lifecycle),
ADR-082526-7f02 (immutable admission provenance, Attempt-owned dispatch identity),
and ADR-083126-5e62 (protected-base quality authority), plus repository
instructions and `docs/quality-gates.md`. Reconciliation: preserve the staged,
non-authorizing codec and canonical `Goal -> Graph -> Run -> NodeRun -> Attempt`
model. Unit passing is not runtime reachability, and candidate ledger entries
cannot authorize their own additions.

All test names below refer to the executed `test_admission_codec.py` file unless
otherwise stated. Evidence is for the starting source SHA recorded above; this
round only adds this report.

| Issue acceptance | Executed evidence / limitation |
| --- | --- |
| Exact immutable v2 DTO and fresh flat mapping | `test_v2_round_trip_preserves_all_snapshot_bytes` (three states), `test_encode_returns_a_fresh_flat_mapping`; constructor validation in adjacent identity suite. PASS, library contract only. |
| Owner/generation strict UUID hex at storage only | `test_owner_token_is_hex_at_storage_only`, `test_v2_generation_ids_are_strict_storage_hex`. PASS. |
| Bound/unbound/partial legacy evidence without guessed identity | `test_legacy_binding_unbound_and_partial_are_distinct`, receipt-only, missing-receipt, unreadable/whitespace evidence cases. PASS. |
| Minimal header and separate full decode; expiry evidence survives | `test_expired_legacy_header_does_not_invent_missing_identity`, `test_header_preserves_expiry_even_when_legacy_snapshot_decode_fails`. PASS; no expiry decision claimed. |
| Fingerprint evidence survives partial binding | `test_header_preserves_fingerprint_even_when_legacy_binding_is_partial`. PASS; no 409/replacement behavior claimed. |
| Reject mismatched headers, invalid signed scalars, missing schema and unknown formats | Header scalar/schema tests and `test_unknown_format_cannot_be_reinterpreted_as_legacy`. PASS. |
| Preserve tagged nonfinite context and fingerprint | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change`, numeric/unicode preservation cases. PASS for stored evidence. Production model materialization/fingerprinting end to end is UNVERIFIED: fixtures supply tagged JSON and a fingerprint, not an authorized request path. |
| Reject duplicate/nonobject/bare nonfinite JSON and suppress unsafe errors | `test_invalid_and_duplicate_json_is_rejected`, excessive nesting, lossy number and non-UTF8 snapshot cases. PASS; invalid TEXT is injected after valid row construction. |
| Named SQL fields, binding shape, legacy completed_at has no authority | Round-trip tests independently assert task_id/receipt_id shape; partial/corrupt v2 binding tests and `test_legacy_completed_at_is_never_read`. PASS at mapping level. |
| Raw versus production pool TEXT equality on migrated disposable PostgreSQL | Three `test_raw_and_production_pool_codecs_read_identical_text_snapshots` cases SKIPPED. UNVERIFIED this round; no migration, DB sessions or final SQL counts claimed. |
| Valid real principals, authorized Workspace/Project, registered Graph, Run JSONB object rather than double-encoded string | UNVERIFIED. Current codec tests exercise DTO/storage mappings, not full authorized admission/Run INSERT. No mocks/skips counted as durability. |
| No clock, assessment, claim mutation, queue/HTTP/scope-policy changes | Source inspection: codec consumes mappings, emits DTOs/mappings, no live consumer; no source changes in this round. Activation remains out of scope. |
| Required quality/CI and coordination | Focused lint/type/tests/inventory and listed gates pass, but trusted-base provenance FAILS. Full integration CI and the unspecified remote `test: failure` remain UNVERIFIED. Starting head/base match assignment; no ownership or activation release inferred from remote comments. |

No new test or repair was introduced, so no pre-fix/mutation-failure claim is
made. Prior PostgreSQL claims are not promoted to fresh evidence.

## Disposition and handoff

**BLOCKED**, not merge-ready. The concrete failing locations remain
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`. A Vulture-only CI-repair
exception does not authorize those reachability changes, and no Vulture
mismatch exists to amend.

Next action belongs to the integration/governance owner: resolve the staged
reachability authorization on the trusted base (the documented two-merge
process), or supply an explicitly authorized integration scope. Supply the
SHA-qualified failing CI test log/node before another test-repair attempt.
Do not keep dispatching unchanged evidence as a speculative code fix. This
worker performed no fetch, merge, push, grant change, gate weakening, or
GitHub mutation. Only this report is committed locally.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 blocking
gate. Validation/handoff complete; issue remains blocked.

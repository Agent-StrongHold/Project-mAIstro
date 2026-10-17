# Issue #1893 repair — job 625738a2

## Frozen scope and starting state

Only issue #1893 at assigned worktree `/home/dev/Git/wt/auto-1893`, branch
`auto-1893`, starting SHA `c6223906cc19cb4c044552ab9d06d9cdadcc5721`.
Supplied develop base `2154f845347c9541016288c760f8da3f5cd2e064` resolves locally.
Initial worktree was clean. No remote refresh or GitHub mutation performed.
Review scope: codec, identity DTOs, adjacent tests, relevant ADRs and CI gates.
Edit scope: this report unless a concrete in-scope failure warrants repair.

Dispatch ambiguity: `test: failure` has no failing node or traceback in the
supplied driver logs. Do not infer a defect or alter tests speculatively.
Driver logs check-0 through check-4 were inspected: dependency sync, lint,
format and inventory passed; tests reported 324 passed / 3 skipped. These are
not live PostgreSQL evidence. The prior result was read, not accepted as fresh
verification.

## Reproduced gate evidence

Executed on the starting SHA:

- `uv sync --locked --extra dev`: PASS (256 resolved, 214 checked).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  PASS, 1322 reviewed findings, zero unclassified. No Vulture ledger amendment
  is warranted by this scan.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`:
  FAIL, exit 1. Reachability dispositions and unreachable modules both expand
  from 169 trusted to 171 candidate. `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` lack already-landed authorization. The other
  provenance subgates passed. This is the exact-debt-ledger workflow's enforced
  gate, not a missing dependency or Vulture identity mismatch.
- Source import search under `packages/**/src/**/*.py`: no production consumer
  imports the codec. Identity imports are from the codec and Vulture whitelist.
  Test imports and whitelist references do not establish runtime reachability.

The inherited additions at `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613` are outside this round's
Vulture-only ledger exception. Do not edit grants, add fake callers, or activate
production to bypass the failure. No develop-sync conflict exists to resolve.

Inspection correction: an attempted read of
`ADR-081226-a66b-canonical-execution-model.md` was not found; skipped. Directory
inspection resolved the actual ADR filename before continuing.

## Architecture reconciliation

Read repository `AGENTS.md` and accepted ADR-081226-a66b (Run/NodeRun/Attempt
lifecycle), ADR-082526-7f02 (immutable admission provenance, Attempt-owned
dispatch identity), and ADR-083126-5e62 (trusted-base quality authority).
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. A DTO is not admission
or authorization. B2 forbids runtime activation; that stage constraint cannot
be reconciled with the gate by candidate-approved banking or fake imports.
The owning integration/governance process must resolve the blocker.

## Fresh focused validation

All commands below ran in the assigned worktree against unchanged Python at
the starting SHA, with long timeouts:

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q`:
  327 nodes, **324 passed / 3 skipped**, 1.95s.
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`:
  2229 nodes, **1919 passed / 310 skipped / 4 warnings**, 48.83s. Warnings are
  aiosqlite worker-thread closed-event-loop exceptions in existing
  `test_sqlite_store.py` tests. No unrelated repair attempted.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`:
  PASS, two source files.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  PASS, 16543 collected nodes, zero duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-promotion-surface.py`: PASS, 74 tolerated modules.
- `uv run python scripts/check-reachability.py`: PASS against candidate ledger,
  1403 production modules / 171 unreachable.
- `uv run python scripts/check-reachability-dispositions.py`: PASS against
  candidate ledger, 50 groups / 171 modules. These two passes do not override
  the failing trusted-base provenance check.
- `git diff --check`: PASS.

## Acceptance audit

Test bodies and codec/DTO constructors were inspected. Evidence below is
library-contract evidence only, not a reachable production admission path.
All named tests are in `packages/maistro-core/tests/tasks/test_admission_codec.py`.

| Criterion | Executed evidence or explicit limitation |
| --- | --- |
| Frozen/slotted header, signed scalar timestamps, exact hashes/formats, matching supplied header | Source declarations plus `test_header_scalar_mismatch_is_invalid_header`, `test_invalid_scalar_headers_fail_closed` and missing-column tests PASS. |
| Immutable v2 DTO and fresh flat named-column mapping | `test_v2_round_trip_preserves_all_snapshot_bytes` (three states), `test_encode_returns_a_fresh_flat_mapping`, and identity constructor tests PASS. Canonical text preserved; harmless noncanonical formatting normalizes. |
| UUID hex only at storage; safe typed errors with validated scope | `test_owner_token_is_hex_at_storage_only`, `test_v2_generation_ids_are_strict_storage_hex`, `test_decode_error_scope_key_is_only_a_validated_hash` PASS; invalid snapshot tests assert suppressed chains and no raw evidence in messages. |
| Bound, unresolved, partial, receipt-only legacy evidence; no invented identity | `test_legacy_binding_unbound_and_partial_are_distinct`, `test_legacy_receipt_only_row_is_partial_not_unbound`, missing-receipt and unreadable-evidence tests PASS. |
| Header/full-decode separation, expiry/fingerprint preserved without clock or classifier | `test_expired_legacy_header_does_not_invent_missing_identity`, `test_header_preserves_expiry_even_when_legacy_snapshot_decode_fails`, `test_header_preserves_fingerprint_even_when_legacy_binding_is_partial` PASS. Replacement and 409 ordering belong to C/F2, not this leaf. |
| Unknown formats cannot become legacy | `test_unknown_format_cannot_be_reinterpreted_as_legacy` PASS, including seven invalid versions and mismatched supported header. |
| Strict TEXT JSON: duplicate keys, nonobjects, bare nonfinite and corrupt evidence rejected | `test_invalid_and_duplicate_json_is_rejected`, excessive nesting, lossy-number and non-UTF-8 cases PASS. Invalid bytes are injected at the storage-row boundary. |
| Tagged nonfinite context and unchanged fingerprint | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change` PASS for nan/inf/-inf. Fixtures prebuild tags and pin a fingerprint: actual evidence-json encoding, original-model fingerprinting and model_of/model_of_json materialization are UNVERIFIED end to end. |
| Exact SQL binding fields and legacy completed_at not authority | Independent paired task/run assertions at test lines 134-137 and partial-v2-binding cases PASS; `test_legacy_completed_at_is_never_read` PASS. |
| Raw/production pool contrast on the same migrated disposable PostgreSQL | Three `test_raw_and_production_pool_codecs_read_identical_text_snapshots` cases SKIPPED. Live DB durability, migration/downgrade, session identities and final SQL row/identity counts are UNVERIFIED this round. No fake/SQLite result is substituted. |
| Explicit authorized principals, Workspace/Project, registered Graph and Run JSONB object INSERT | UNVERIFIED: DTO fixtures use string identities; these tests do not exercise authorized production admission or a Run INSERT. |
| No SQL mutation, HTTP/queue/scope/assessment/policy change or competing execution authority | Codec inspection and import search confirm mapping/DTO-only inactive surface; this round changes only this report. No activation or ownership release inferred. |
| Required checks and inventory | Focused checks above PASS; provenance FAILS. Full integration CI and the unspecified remote `test: failure` remain UNVERIFIED. |

No source or tests changed, so no inventory-delta note or pre-fix/mutation
failure claim is warranted. Prior live-PG/full-CI claims are not fresh evidence.

## Disposition and handoff

**BLOCKED.** No test failure was reproduced, and the exact Vulture scan supplies
no evidence for a ledger repair. The actual reproduced failure is the existing
unauthorized reachability expansion, outside this lane's ledger exception.

Only `docs/testing/issue-1893-repair-625738a2.md` changes this round. Commit this
report locally; do not infer repair completion, merge readiness or issue closure.
No source, test, ledger, grant or gate edits; no fetch, merge, push or GitHub
mutation performed.

Next: integration/governance owner resolves trusted-base authorization via the
existing two-merge process or provides explicitly authorized integration scope.
Supply the SHA-qualified failing CI node/traceback before another speculative
repair dispatch. Live PostgreSQL and full integration acceptance still need
fresh execution after that prerequisite. Repeating candidate-ledger scans will
not resolve the trusted-base failure.

Progress: checked 1; done 0 repairs; skipped 0 issues; errors 1 blocking gate;
next: owner resolution and concrete failing-test evidence.

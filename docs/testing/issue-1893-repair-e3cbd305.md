# Issue #1893 repair validation — e3cbd305

## Frozen scope

- Assigned issue: #1893 only; worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD: `564c00ba0d8e22dcd7e62201e1b4e723e19fc2d9`; supplied base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- Initial worktree clean; no incoming edits to salvage.
- Inspect existing `admission_codec.py`, `admission_identity.py`, adjacent tests, relevant ADRs/workflows, supplied dispatch/prior-result artifacts. Validate codec and reported test/vulture/provenance gates. Only evidence-based repairs to these files are in scope; no activation or unrelated repair.
- Supplied check logs: dependency sync, ruff check, format check, focused tests (312 passed, 3 skipped), core suite inventory passed. These are driver evidence, not independent execution.
- Assumption: writer role; the issue's stage constraints prohibit inventing a runtime caller merely to satisfy reachability. Prior provenance blocker must be independently checked; only vulture ledger amendments are authorized in this round.

## Execution results

- Independently executed exact Vulture CI scan: PASS, 1322 findings, zero unclassified/never-allowlist. No Vulture ledger amendment justified.
- Independently executed `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`: FAIL. Both admission modules are new unreachable modules and dispositions without already-landed authorization. Other provenance subgates pass. This is not a Vulture issue or a merge conflict; the permitted Vulture exception cannot repair it.
- Prior result read: previous head's only new change was its validation note. The current independently reproduced blocker remains outside this lane's authority.
- `uv sync --locked --extra dev`: PASS.
- `uv run pytest packages/maistro-core/tests/extensions/test_pack_contracts.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -x -q -rs`: 312 passed, 3 skipped, 315 collected (1.61s). Required PostgreSQL DSNs absent; skips at codec test line 470 are not durability evidence.
- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS (3301 files).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 16541 nodes, no duplicate identities/files.
- Read repository instructions and accepted ADR-081226-a66b, ADR-082526-7f02, ADR-083126-5e62. Preserve the canonical execution hierarchy and immutable admission provenance. Protected-base authorization cannot be replaced by candidate ledger edits; no fake caller or activation is authorized.
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests -x -q`: PASS, 15468 passed, 1070 skipped, 3 xfailed, 54 warnings in 238.57s. Log: `/tmp/1893-e3cbd305-core-pytest.log`. Includes aiosqlite closed-event-loop warnings and an unawaited fake-process coroutine warning. Reported `test: failure` not reproduced in the changed package; this is not full integration CI.
- Production source import search finds only codec -> identity and Vulture whitelist imports. No runtime consumer; codec lines 50-53 explicitly document its inactive contract status.

## Acceptance audit

Evidence is from the starting source SHA above. This round changes no executable code.

| Criterion | Executed evidence / limitation |
| --- | --- |
| Frozen/slotted header and shared interfaces; immutable DTOs; fresh flat SQL mapping | Source inspection and passing header/identity/round-trip/fresh-mapping tests. Storage columns are named, not positional. |
| Strict UUID hex, signed timestamps, exact matching header, #1851 constructor validation | Passing token/generation, invalid scalar, header mismatch, lease/window, acknowledgment and binding tests. Bound encode asserts task_id = receipt_id plus run_id independently of decode. |
| Typed safe errors and validated scope | Passing duplicate/nonobject/nonfinite JSON, excessive nesting, precision-loss, surrogate, invalid-scope and suppressed-chain tests; errors omit raw snapshot/token bytes. |
| Legacy bound/unbound/partial distinctions without guessing | Passing partial pairs, receipt-only, unreadable evidence and completed_at tests. Both task/run IDs without receipt evidence fail partial because the required DTO cannot invent a receipt. |
| Header/full-record separation; unsupported schema/format fail closed | Passing expiry/fingerprint preservation across full-decode failures, unknown-format and missing-column tests. Consumer expiry/409 decision precedence remains outside B2, UNVERIFIED. |
| Snapshot evidence and unchanged fingerprint | Tagged nan/inf/-inf, Unicode and exact numeric evidence tests pass. Tags and fingerprints are fixtures: original-model fingerprint -> evidence encoding -> model_of/model_of_json materialization is UNVERIFIED, not established by fixture equality. |
| Raw and production pool TEXT round trips on the same migrated disposable DB | UNVERIFIED this round: three tests skipped for absent DSNs. No live migration-chain, session identity, final SQL count or Run JSONB object proof claimed. |
| Real explicit authorized principals, Workspace/Project, registered Graph kinds | UNVERIFIED for production admission; representation fixture strings are not authorization evidence. |
| No SQL mutation, clock, assessment, HTTP/queue/scope-policy changes or competing authority | Codec source remains pure representation; no code changes this round. Activation remains prohibited. |
| Inventory, focused tests, lint/format, mypy | PASS as recorded above; no tests added, so no inventory delta required. No new pre-fix or mutation run claimed. |
| Full required CI, vulture/reachability/disposition/promotion | Vulture and shipped-surface pass; provenance fails specifically on reachability/dispositions while promotion provenance passes. Scoped core tests pass; full integration CI and other standalone gates UNVERIFIED. |
| Reachable production behavior | UNVERIFIED: intentionally inactive leaf, no runtime consumer. Unit test imports do not establish production reachability. |

## Blocked handoff

Only changed file: `docs/testing/issue-1893-repair-e3cbd305.md`. No evidence-based code repair or Vulture amendment was justified. The specific reported CI failing test is unidentified and not reproduced by the scoped suite. No full-CI success is claimed.

The required gate at `.github/workflows/vulture-ratchet.yml:77` rejects the existing entries in `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:604-614`. Resolution needs an owner-coordinated authorization already landed on the trusted base and subsequent integration, or a separately authorized real consumer. This lane cannot edit reachability grants/ledgers or activate the staged codec. No sync conflict was present; no fetch/merge was justified by the frozen evidence.

Residual risks: skipped live PostgreSQL proof, end-to-end materialization, production authorization/reachability and full integration CI remain unverified. Repeating unchanged-source repairs cannot solve the independently reproduced policy blocker.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: owner-coordinated trusted-base authorization}`. Validation/reporting complete; issue repair blocked. Local commit required; no push, GitHub mutation, gate weakening or destructive operation.


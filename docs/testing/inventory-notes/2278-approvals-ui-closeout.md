---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
  packages/hive-conductor/tests/e2e: +0
---
# 2278 Approvals UI closeout (Parity P-1)

Product UI already landed on `develop` via #2294 (`2014ab888`). This note
records the **verification closeout**: tighten contracts for AC gaps that
were only partially pinned, and document the AC evidence matrix.

## packages/hive-conductor/backend/tests: +3

`test_approvals_ui_contract.py` grows from 4 → 7 collected tests:

- `test_capability_resolve_body_matches_cli_approve_and_deny` (AC-2)
- `test_hitl_foreign_ids_fail_closed_on_answer_and_cancel` (AC-3)
- `test_ui_and_cli_share_capability_approval_doors` (AC-1/AC-2/AC-4)

Existing four retained (list shape, capability foreign 404, anon 401, HITL
pending list-or-unavailable). List-shape assertion also requires `tier` +
`requester` (CLI print fields).

## packages/hive-conductor/tests/e2e: +0

Playwright `workspace-approvals-shell.spec.ts` is not collected by pytest.
Added three scripted cases (AC-5 HITL answer + Run link; capability approve
body parity; foreign capability fail-closed toast) — inventory count unchanged.

## AC evidence matrix

| AC | Verdict | Evidence |
|----|---------|----------|
| AC-1 UI lists same pending set as API/CLI | **met** | SPA `GET`s `/v1/capabilities/approvals` + `/v1/hitl/pending` (`Approvals.tsx` / `lib/approvals.ts`); CLI `maistro approvals list` hits the same capability path (`cli/_approvals.py`); contract `test_ui_and_cli_share_capability_approval_doors` + list shape |
| AC-2 Approve/deny/cancel → same canonical state | **met** | UI `POST`s `{approved}` to `/v1/capabilities/approvals/{id}` and HITL answer/cancel doors; CLI approve/deny identical body; E2E posts `{approved:true}`; backend resolve round-trips already in `test_capabilities_routes` / `test_hitl_door` |
| AC-3 Foreign ids fail closed | **met** | Capability 404 + HITL answer/cancel 404 in UI contract; E2E foreign deny → error toast; deeper foreign-workspace isolation in `test_hitl_door` |
| AC-4 No parallel store | **met** | Page imports only `lib/approvals` path helpers; contract asserts no `/v1/approvals`, no `localStorage`/`indexedDB` queue; FEATURE-PARITY-MATRIX P-1 |
| AC-5 E2E pending → answer → Run resume | **met** | Playwright: stubbed HITL pending → Submit answer → `Run {id}` link `href=/dag-runs?run=…` visible (terminal/resume surface via #1036 dag-runs) |

## Behavior

No product behavior change in this closeout — tests + evidence only. No
CHANGELOG entry.

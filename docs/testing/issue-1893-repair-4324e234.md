# Issue #1893 repair checkpoint — job 4324e234

## Frozen scope

- Only issue #1893, assigned worktree `/home/dev/Git/wt/auto-1893`.
- Starting HEAD `38d00f5f16c0bb7ce21aa19c47b58d16855de044`; dispatch base `435dc1937e0407ab4de198ffcced49860bb14ad2`; clean on arrival.
- Inspect existing `admission_codec.py`, `admission_identity.py`, their two test files, repository instructions, relevant ADRs and CI definitions. Changes restricted to evidence-backed repairs in those files, required inventory notes, and this report; vulture ledger only if the exact authorized gate reports retained debt. No reachability grants/ledger edits.
- Dispatch evidence is frozen in job `4324e23448a44d1cbb17c6a4e34c6491/dispatch-context.json`. No GitHub mutations or re-enumeration.

## Initial evidence / assumptions

Driver logs check-0 through check-4 report dependency sync, lint, format and inventory success; focused tests: **201 passed, 3 skipped**. These are driver results, not new executions. PostgreSQL acceptance remains unverified until real execution. The generic `test: failure` has no failing node in the prompt. Assumption: reproduce named gates and focused tests before considering any code change. Prior report's claims are not treated as current proof.

## Results

Fresh execution (1200-second timeout) of the exact requested Vulture command passed: 1323 findings/reviewed identities, zero unclassified. No vulture ledger amendment is justified.

`RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python scripts/check-ratchet-provenance.py` exited **1**: `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` each lack both trusted-base reachability authorization and a trusted disposition. Logs: job-local `worker-vulture.log`, `worker-provenance.log`.

Read accepted ADR-081226-a66b (one execution lifecycle), ADR-082526-7f02 (immutable admission provenance), and ADR-083126-5e62 (protected-base quality authority). Reconciliation: a representation-only staged leaf is not production activation or independent merge readiness. Do not wire a fake consumer or self-authorize reachability to satisfy the gate. The vulture-only exception does not authorize those changes. The existing source explicitly documents that neither module has a production consumer.

## Focused validation executed

All commands used 1200-second tool timeouts at the starting source SHA. Logs are in the supplied job directory.

| Command | Outcome | Log |
| --- | --- | --- |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | **201 passed, 3 skipped**, 204 nodes | `worker-focused.log` |
| `uv run ruff check .` | Exit 0 | `worker-ruff.log` |
| `uv run ruff format --check .` | Exit 0, 3277 files | `worker-format.log` |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | Exit 0, two files | `worker-mypy.log` |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Exit 0, 16466 nodes, zero copied-file duplicate evidence | `worker-inventory.log` |
| `uv run python scripts/check-shipped-surface-truth.py` | Exit 0 | `worker-shipped.log` |

No tests were added or removed, so no inventory delta is required. No new pre-fix/mutation proof is claimed: this round makes no source repair.

## Acceptance audit

These are representation tests, not proof of reachable admission behavior.

| Criterion | Evidence / remaining limit |
| --- | --- |
| Required interfaces, frozen/slotted header, six decode codes | Source inspected; format, scalar mismatch, schema and header tests passed. |
| Exact v2 DTO, fresh flat named SQL mapping, original binding | All three round-trip states passed; tests independently assert both binding columns and `task_id == receipt_id`; fresh-mapping test passed. |
| Strict UUID hex only at storage, signed timestamps, #1851 constructors | Owner/generation rejection, signed-range, DTO immutability and constructor tests passed. |
| Legacy bound/unbound/partial distinctions; receipt-only and announced-without-Run | Pair, receipt-only, missing-receipt and invalid-evidence tests passed. No missing identity is invented. |
| Header/full-decode separation, header matching, unknown formats fail closed | Expiry/fingerprint preservation tests passed despite snapshot or binding failure; mismatch and unsupported-format tests passed. No clock or incoming fingerprint is accepted. |
| TEXT-only JSON, duplicate/nonobject/bare nonfinite rejection | Invalid JSON, numeric-loss, nesting, Unicode and predecoded-value tests passed. |
| Safe errors, validated scope, suppressed unsafe chains | Snapshot failure, owner-token redaction and validated-scope tests passed. |
| Tagged nonfinite/context snapshots and unchanged fingerprint | Tagged, Unicode and exact-number representation tests passed. Actual `encode_evidence` / `model_of` / `model_of_json` materialization and original-model fingerprinting remain **UNVERIFIED** by these fixtures. |
| Raw/production pool equivalence against migrated disposable PostgreSQL | **UNVERIFIED**: all three cases skipped at test_admission_codec.py:470 for missing DSNs. No migration, database session identities or final SQL row counts established this round. |
| Run payload remains a JSONB object, not double encoded | **UNVERIFIED**: the codec tests insert only admission rows; no Run payload insertion executed. |
| Explicit principals, authorized Workspace/Project, registered Graph kinds | **UNVERIFIED**: fixture strings are not authorization or admission evidence. |
| No SQL mutation, HTTP mapping, queue/assessor/scope-utility/decision/policy changes | Inspected source remains representation-only; this repair round changes only this report. Canonical execution and authorization paths unchanged. |
| Expired replacement / mismatch-409 precedence | **UNVERIFIED**, reserved for C/F2 consumer rather than this codec. |
| Truthful inventory, focused tests, lint, format, types and unchanged integration CI | Focused checks passed as above. Full integration CI **UNVERIFIED**; required provenance gate **FAILED**. |
| Coordination and production activation | Repair ownership supplied by lane; broader stack coordination and activation **UNVERIFIED/BLOCKED**, not inferred from this assignment. |

## Failure attribution and handoff

The exact current failure is the reachability provenance blocker, not Vulture debt. Candidate rows in `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:606-613` cannot authorize themselves. `.github/workflows/vulture-ratchet.yml:77-85` requires the failing gate. Existing rows are preserved; no quality file was changed.

`rg -n 'admission_codec|admission_identity' packages/*/src` found only the codec-to-DTO import and the whitelist import (`worker-callers.log`). No production consumer was found, consistent with both source docstrings and the reachability gate. Test imports and whitelists are not production callers.

Inspected the frozen dispatch check-run records rather than assuming the generic `test: failure` belongs to this head. The only captured failed `test` is at `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828` (#1855), with null output summary/text. The captured #1945 head `9922f395daa39249991f18210a6d4da68a3a76cb` has `test: success`. Neither proves the assigned head's CI outcome. Extracted evidence: `worker-captured-test-checks.json`. Attribution is **UNRESOLVED**; no speculative test edits. CI's `test` job (`.github/workflows/ci.yml:496-612`) spans other packages/root suites; the focused core pass does not reproduce that job.

**BLOCKED.** Required next inputs: an independently landed, owner-coordinated reachability authorization (then an explicitly authorized base sync), or separately authorized real consumer integration; and a current-head failing CI traceback for any test repair. Repeating unchanged-source checks or amending the Vulture ledger cannot resolve either missing input. No develop conflict existed on arrival, so no fetch/merge was undertaken.

Changed file: this report only. No source/tests/ledgers/grants/gates modified; no GitHub mutations. Commit this handoff locally. Progress: checked 1, done 0, skipped 0, errors 1 reproduced gate blocker; next: owner coordination above.

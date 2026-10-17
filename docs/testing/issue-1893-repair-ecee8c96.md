# Issue #1893 repair validation — ecee8c96

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `aa1466fe74a2ea783f76d7948e4af8e7a0ecb7bc`; supplied develop base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- One item: issue #1893, reported `test: failure` and exact-debt-ledger repair.
- Inspect the supplied dispatch snapshot and check-0 through check-4 logs, admission codec/identity implementation and adjacent tests, relevant ADRs and CI gates. No other issues or remote updates are in scope.
- Initial worktree clean; no salvage necessary.
- Assumption: writer assignment permits a local evidence commit even if no production defect reproduces. Activation and consumer wiring remain outside B2; staged readiness is not rollout approval.

## Results

Driver logs inspected: dependency sync, lint, format (3277 files), focused tests (201 passed, 3 skipped), core inventory (16466 nodes) pass. They contain no failing test traceback.

Fresh execution with 1200-second timeout:
- Exact requested Vulture command passed: 1323 findings, zero unclassified. No ledger amendment justified.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` failed (exit 1): admission_identity and admission_codec each add an unauthorized unreachable module and disposition. Other provenance checks passed.

This reproduces the external blocker. The Vulture-only exception cannot authorize reachability ledger/grant edits; no fabricated caller or gate change will be made. Further validation is limited to focused acceptance and report completion.

## Fresh focused acceptance

All commands below executed against the unchanged starting Python tree, with a 1200-second timeout:

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s`: **201 passed, 3 skipped**, 1.22s; 204 nodes. Skips are the DB cases at `test_admission_codec.py:470`, missing both DSNs.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3277 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: passed, 2 files.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: passed, 16466 nodes, zero duplicate evidence.
- `git diff --check`: passed.

Exact Vulture command: `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`.

| Criterion | Current evidence |
| --- | --- |
| Frozen/slotted header, named-column mapping, six typed decode codes, #1851 constructors | Source inspected; focused tests pass. |
| Strict UUID .hex, signed timestamps, header mismatch and unsupported-format rejection | Focused scalar, generation, owner-token and header tests pass. |
| Header retains expiry/fingerprint when full decoding fails; no clock/decision | Header separation tests pass; codec accepts neither clock nor incoming fingerprint. |
| Legacy bound/unbound/partial/receipt-only, no invented identity | Focused cases pass. A pair lacking receipt evidence is partial because the canonical binding constructor requires receipt identity; none is fabricated. completed_at grants no authority. |
| Duplicate/nonobject/bare nonfinite TEXT rejected; error hygiene | Malformed JSON, nesting, numeric-loss and Unicode cases pass with suppressed parsing context and validated scope. |
| Exact canonical snapshot bytes, tags, stored fingerprint, fresh flat mapping | Three-state round trip and tagged evidence tests pass. Actual evidence_json serialization/model_of materialization and original-model fingerprint generation remain UNVERIFIED: fixtures supply tags and fingerprints directly. |
| Same migrated disposable DB, raw and production pools, non-null pg_pool, session IDs and residue counts | UNVERIFIED this round: all three PG cases skipped. Prior result's 204-pass live-DB claim was inspected but is not adopted as fresh evidence. |
| Run JSONB object, explicit authorized principals/Workspace/Project/registered Graph | UNVERIFIED by representation-only tests; fixture identity strings do not establish authorization. |
| No SQL mutation, HTTP/queue/claim/assessment/scope-policy changes | Codec maps values only; this round edits only this report. |
| Inventory and pre-fix evidence | No tests added/removed, so no inventory delta. No fresh mutation experiment claimed. |
| Production reachability and unchanged required integration CI | NOT proven: codec and identity docstrings explicitly identify inactive leaves; actual provenance scan reports both unreachable. Full integration CI UNVERIFIED. |
| Coordination and activation | External ownership/activation prerequisite UNVERIFIED; dispatch authorizes neither merge nor activation. |

## Architectural reconciliation and CI evidence

Read repository instructions and accepted ADRs 081226-a66b, 082526-7f02, and 083126-5e62. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt, immutable admission provenance, Attempt-owned dispatch identity, and trusted-base authorization. The requested Vulture exception cannot self-authorize reachability debt. B2 forbids activating its future consumer; adding a fake caller would not resolve this correctly.

Required gate location: `.github/workflows/vulture-ratchet.yml:77`. Actual blockers: `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`.

The supplied captured checks report `test` failure for dependency head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with null output text, not the assigned head. Captured #1945 head `fcc8b437f209a35aa68a61d6f0a5387414938355` has an exact-debt-ledger failure, also with null output. No assigned-head test traceback was supplied. `.github/workflows/ci.yml:574-612` excludes core from the `test` job, so the focused core pass does not establish that job. Generic `test: failure` remains UNRESOLVED, not declared repaired.

The supplied prior result artifact was present and inspected: it also reports BLOCKED on the same provenance debt. No re-fetch, remote mutation, ledger amendment, or sync performed; there is no merge conflict in this worktree.

## Handoff

Only changed file: `docs/testing/issue-1893-repair-ecee8c96.md`. No evidenced production repair is authorized by this round. Commit this report locally as a blocked handoff, not implementation completion or integration approval.

Next: owner-coordinated trusted-base authorization must land separately, or separately authorized consumer integration must resolve reachability; supply the assigned-head failing test step/traceback before attempting a test repair. Do not redispatch unchanged inputs expecting a Vulture ledger edit to resolve reachability.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 required gate. Residual risks: unverified live DB/materialization/authorization/full CI, inactive production slice, unresolved generic test failure.

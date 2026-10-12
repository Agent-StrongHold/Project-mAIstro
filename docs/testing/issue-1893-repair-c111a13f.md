# Issue #1893 repair — c111a13f

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting head `6648fdbf17e47c472c686bf3ba0d8e78932f0517`; supplied develop base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Initial worktree clean; no incoming work to salvage.
- Process only #1893: `tasks/admission_codec.py`, `runs/admission_identity.py`, their existing tests, associated inventory notes, and reported test/exact-debt-ledger evidence. This report is the only planned edit absent a reproduced defect.
- Dispatch context and check-0.log through check-4.log in job `c111a13f5a9248d1aefdfa66ce49390c` are the frozen evidence snapshot; no GitHub mutations or refreshed issue lists.

## Assumptions and constraints

Writer assignment governs this run. The issue authorizes staged typed representation, not production activation. Reachability authorization is a separate owner-controlled dependency; only the explicitly permitted vulture ledger may be amended if actual scanner evidence requires it. No guessed fix for an unnamed `test: failure`.

## Results

Fresh blocking evidence: exact Vulture command passed (1323 findings, no unclassified identities); `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` exited 1. Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` lack trusted-base reachability and disposition authorization. This is not a Vulture-ledger defect and cannot be repaired under the limited ledger exception.

Driver logs inspected: dependency sync, ruff check, format (3277 files), focused tests (201 passed / 3 skipped), and suite inventory (16466 nodes) pass. The database skips are not durability proof. Fresh focused validation (1200-second timeout): `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` passed 201 tests, with 3 skips at `test_admission_codec.py:470` for missing database DSNs. `uv run ruff check .`, `uv run ruff format --check .` (3277 files), and `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` all passed. Prior reports are not current execution evidence.

Read accepted ADRs 081226-a66b (canonical execution lifecycle), 082526-7f02 (immutable admission provenance), and 083126-5e62 (protected-base quality authority). Reconciliation: an inactive representation-only leaf does not authorize a reachability waiver, and this repair cannot add a runtime consumer contrary to its stage constraint. No production or ledger edits warranted by the executed checks.

`uv run python scripts/check-shipped-surface-truth.py` passed. `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` passed: 16466 collected nodes, zero duplicate evidence. No tests were added or removed; no inventory delta is required.

## Acceptance audit and limits

| Criterion | Executed evidence / limit |
| --- | --- |
| Exact public interfaces, frozen/slotted scalar header, six codes and #1851 constructors | Source inspected; focused codec/identity suite passed. |
| Strict UUID .hex storage, signed timestamps, fresh flat named-column mappings | Owner-token, generation, scalar and mapping tests passed. Binding round-trip explicitly asserts migration-055 task_id/receipt_id equality independently of decode/encode agreement. |
| Header mismatch fails; expiry/fingerprint survive malformed records; unknown formats fail closed | Focused header-separation, mismatch, invalid-format and invalid-snapshot cases passed. No clock or incoming fingerprint enters the codec. |
| Legacy unbound/bound/partial/receipt-only evidence without invented identity | Focused legacy cases passed. A bound pair lacking receipt evidence is rejected because the canonical binding requires a receipt; none is fabricated. |
| TEXT strict JSON and safe failure messages/chains | Duplicate/nonobject/nonfinite, precision loss, nesting and Unicode cases passed. Error cause suppression and retained header evidence asserted. |
| Tagged program_context and fingerprint preserved | Hand-constructed tagged evidence round trips pass. Real evidence-json -> model_of/model_of_json materialization, original-model fingerprint generation, and arbitrary permitted model context remain UNVERIFIED. |
| Real migrated disposable PostgreSQL, matching raw/production sessions, non-null pg_pool, SQL row counts | UNVERIFIED this round: 3 tests skipped for missing DSNs. Prior live-PG report is historical, not fresh evidence. |
| Run JSONB object, authorized principals/Workspace/Project/registered Graph | UNVERIFIED by this representation-only suite; it does not create a Run or prove admission authorization. |
| No SQL/HTTP/queue/claim/assessment/scope/policy changes | Source-only mapping leaf inspected; this round changes only this report. Canonical Goal -> Graph -> Run -> NodeRun -> Attempt remains unchanged. |
| Runtime reachability | NOT satisfied: source search finds only codec-to-identity and Vulture-whitelist imports, not a production consumer. Tests and exports are not reachability. |
| Focused pytest, lint, format, mypy, inventory | Fresh commands above pass, subject to explicit DB skips. No new mutation/pre-fix or crash/transaction proof claimed. |
| Unchanged required integration CI and no gate workaround | BLOCKED: provenance gate fails; full integration CI UNVERIFIED. No gate/ledger/authorization edits made. |
| Coordination/base ownership and activation policy | External coordination UNVERIFIED. Repair dispatch is not activation or merge authorization. |

## Blocked handoff

Actual failure: `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613` are not authorized by the supplied trusted develop base. `.github/workflows/vulture-ratchet.yml:77` invokes the failing provenance check in the required exact-debt-ledger job. Accepted protected-base authority and the two-merge rule prohibit candidate self-approval. Resolution requires external base/ownership coordination, not a Vulture amendment or fake caller. No develop sync conflict exists in this clean starting tree, so no fetch/merge was performed.

The generic `test: failure` remains UNRESOLVED: supplied check logs have no failing test traceback, and the focused suite did not reproduce one. `.github/workflows/ci.yml:574-612` explicitly partitions core tests out of the `test` job; focused success must not be advertised as that entire job passing. Obtain the assigned-head failing step/node/traceback before proposing a repair.

Only changed file: `docs/testing/issue-1893-repair-c111a13f.md`. No source, tests, inventory, ledger or grants changed. No GitHub mutation. Report committed locally as a blocked handoff.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 required gate. Next: owner-coordinated trusted-base resolution and assigned-head CI failure evidence. Do not integrate or close #1893 on this evidence.

# Issue #1893 repair checkpoint — b0bc8f84

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `18f12deddb23730d88156f87a061b46352d2be26`; supplied base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Only issue #1893. Working tree initially clean; no salvage required.
- Inspect existing admission codec/identity implementations, adjacent tests, applicable ADRs, CI definitions, supplied dispatch evidence and check-0 through check-4 logs. Candidate edits limited to evidenced admission defects, their tests/inventory, this report, and explicitly authorized vulture ledger repairs. No reachability ledger/grant edits or production activation.
- Ambiguity: dispatch reports `test: failure` without a failing node. Reproduce focused tests and inspect supplied checks; do not invent a repair.
- Prior claims are not evidence of current success.

## Recorded results

Driver check-0 through check-4 logs inspected: dependency sync, ruff, format (3277 files), focused pytest (201 passed, 3 skipped), and core inventory (16466 nodes) pass. No failing test traceback is present in those logs.

Fresh exact Vulture scan passed: 1323 findings, zero unclassified identities. No Vulture amendment is justified. Fresh `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` failed: two new unreachable modules and two unauthorized dispositions (`maistro.runs.admission_identity`, `maistro.tasks.admission_codec`). This is an actual required exact-debt-ledger failure, not guessed scanner debt.

Repository instructions and accepted ADRs 081226-a66b, 082526-7f02, and 083126-5e62 inspected. Reconciliation: immutable admission evidence must not create execution identity or another lifecycle; staged representation does not permit candidate self-authorization. The explicit Vulture repair exception does not permit reachability grants/ledger changes or a fake production caller. No sync conflict exists, so the conditional fetch/merge instruction does not apply.

`.github/workflows/ci.yml:574-612` partitions core tests out of the `test` job. Focused codec success cannot prove that entire job. The reported generic `test: failure` remains UNRESOLVED without assigned-head failing step/node evidence. Captured PR #1945 checks are for a different head, `fcc8b437f209a35aa68a61d6f0a5387414938355`; their only failure is exact-debt-ledger, with no output text. The local JSON extraction initially assumed an object instead of a list and raised AttributeError; corrected extraction read 31 captured checks. No remote refresh performed.

## Fresh focused validation

Executed with 1200-second command timeouts, against the unchanged starting Python tree:

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s`: **201 passed, 3 skipped**, 1.25s (204 collected). All three DB cases skip at codec test line 470 for missing DSNs; no durability claim.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3277 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: passed, 2 files.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: passed, 16466 collected nodes, zero duplicate identities/files.
- `git diff --check`: passed.
- Source import search: only codec-to-identity and Vulture-whitelist imports; no runtime consumer found. This agrees with the failing reachability gate, not with an activation claim.

## Acceptance audit

| Criterion | Evidence / limitation |
| --- | --- |
| Exact frozen/slotted header, named mapping interfaces, six error codes, #1851 constructors | Source inspected; focused tests pass. No mutable snapshot dictionary is retained. |
| Strict storage UUID .hex, signed scalar timestamps, fresh flat mapping | Focused owner/generation/scalar/mapping cases pass; bound mapping asserts task_id equals receipt_id and both binding columns are present. |
| Header mismatch rejection; expiry/fingerprint preserved despite failed full decode; unsupported formats fail closed | Focused header-separation/mismatch/format tests pass; codec accepts neither clock nor incoming request fingerprint. |
| Legacy bound/unbound/partial/receipt-only evidence without invented identity | Focused legacy tests pass, including whitespace/unreadable evidence. Bound pair without receipt is explicitly partial because #1851 binding requires receipt evidence; none is invented. completed_at ignored. |
| Strict TEXT JSON, duplicates/nonobject/bare nonfinite rejection; safe error chains | Focused malformed/nesting/lossy-number/Unicode cases pass; source suppresses unsafe parsing context and retains validated scope only. |
| Canonical snapshot bytes/tags and stored fingerprint preserved | Focused unbound/bound/acknowledged and hand-tagged nonfinite cases pass. Actual evidence_json -> model_of/model_of_json materialization and original-model fingerprint generation are UNVERIFIED; fixtures supply tags/fingerprints directly. |
| Raw and production pools, same migrated disposable DB, non-null pg_pool, final row/identity counts | UNVERIFIED: three skipped DB cases. No DB session IDs or row counts obtained this round; previous runs do not substitute. |
| Run JSONB object, explicit authorized principals/Workspace/Project/registered Graph | UNVERIFIED by representation-only tests; fixture strings are not authorization evidence. |
| No SQL mutation, HTTP/queue/claim/assessment/scope-policy change, no competing lifecycle | Codec source is mapping-only. This round changes only this report; canonical Goal -> Graph -> Run -> NodeRun -> Attempt unchanged. |
| Focused pytest, lint, format, mypy, truthful inventory | Fresh commands above pass with explicit DB skips. No tests added/removed; no inventory delta required. No fresh mutation/pre-fix experiment claimed. |
| Reachable production behavior / unchanged full required integration CI | NOT established: no runtime consumer; provenance fails on unauthorized reachability entries. Full integration CI UNVERIFIED. |
| Coordinated staging and activation limits | External ownership/activation prerequisite remains UNVERIFIED. This repair dispatch grants neither merge nor activation authority. |

## Blocked handoff

Actual blocking files: `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`. Required workflow `.github/workflows/vulture-ratchet.yml:77` runs the failing provenance gate. Resolution needs owner-coordinated trusted-base authorization already landed separately, or the separately authorized production consumer integration. Neither is permitted in this repair. Do not retry this unchanged lane expecting a Vulture amendment to fix reachability.

Only changed file: this report. No source, test, inventory, ledger, grant or gate modification is supported by the current evidence. No GitHub mutation. Commit locally as a blocked handoff, not an implementation completion or integration approval.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 required gate. Next: resolve external trusted-base/ownership prerequisite and supply assigned-head `test` traceback. Residual risks: live PG and materialization acceptance unverified, inactive production slice, generic CI failure unreproduced.

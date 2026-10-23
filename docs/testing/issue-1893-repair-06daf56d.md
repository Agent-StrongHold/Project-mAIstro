# Issue #1893 — bounded repair verification (06daf56d)

## Frozen scope and checkpoint

- Assigned issue only: #1893; writer worktree `/home/dev/Git/wt/auto-1893`.
- Starting head: `0507a6d3255ebac854c5c2476daacbb619ec3d3b` (verified); clean on entry.
- Supplied base and local `origin/develop`: `3c761d14db944a727fa0744444bc67cfe36d49f7` (verified). No sync conflict exists.
- Frozen inspection scope: admission codec, admission identity DTOs, their two test files, associated ADRs, CI workflows/gate implementations and existing quality rows. Only this evidence note is planned to change unless validation identifies an in-scope repair.
- Evidence source: supplied job `06daf56d30e7426191c09bcdc6e524ba` dispatch snapshot and check-0 through check-4 logs. No GitHub mutations or re-enumeration.
- Driver logs report dependency sync, ruff and format passing; focused tests 201 passed / 3 skipped; core suite inventory 16466. These are driver observations, not live database evidence or independent reruns.
- Ambiguity: `test: failure` has no failure traceback in the assignment. Proceed by checking captured CI details and running the focused tests and named debt gate. Do not invent a code fix for an unobserved failure.
- Previous reachability provenance block will be independently checked. No authorization to edit reachability ledgers/grants or activate a runtime consumer. Vulture ledger edits are permitted only for actual reviewed scanner findings.

## Validation

Fresh execution at the assigned head (1200-second timeout):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed, 1323 reviewed findings, zero unclassified. No vulture ledger amendment is justified.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: FAILED. Two new unreachable modules and their dispositions lack trusted-base authorization: `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`. Other component provenance gates passed. The failure is reachability, not the permitted vulture-ledger repair.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s`: 201 passed, 3 skipped in 1.44s. Missing database DSNs caused the three skips; this execution proves no durability claim.

Additional fresh commands (1200-second timeout) all passed:

- `uv run ruff check .`
- `uv run ruff format --check .` (3277 files)
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` (2 files)
- `uv run python scripts/check-shipped-surface-truth.py`
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` (16466 nodes, zero duplicate evidence)

No tests were added or removed; no inventory delta or baseline amendment is needed.

## Architecture and acceptance audit

Read the codec and DTO implementations, both focused test files, CI job definitions, and accepted ADRs `081226-a66b`, `082526-7f02`, and `083126-5e62`. Reconciliation: immutable admission evidence and the canonical Goal -> Graph -> Run -> NodeRun -> Attempt model remain unchanged. A staged representation leaf does not authorize a second admission path or a candidate-controlled reachability waiver. The allowed vulture exception cannot authorize changes to reachability policy.

| Criterion | Current evidence / limit |
| --- | --- |
| Required interfaces; frozen/slotted header; six typed decode codes; #1851 immutable constructors | Source inspected; 201 focused tests pass. |
| Named scalar SQL mappings; strict storage UUID .hex; signed timestamps; header mismatch rejection | Source and strict UUID, invalid-header, scalar-mismatch, and flat fresh-mapping tests pass. |
| Exact canonical snapshot round trips and fingerprint retention | Bound/unbound/acknowledged round-trip and tagged-evidence tests pass. SQL task_id/receipt_id shape is asserted independently of encode/decode agreement at test_admission_codec.py:134-137. |
| Strict TEXT JSON and error hygiene | Duplicate/nonobject/nonfinite, nesting, lossy numeric and invalid Unicode tests pass; codec suppresses unsafe parser chains and exposes only validated scope hashes. |
| Legacy bound/unresolved/partial/receipt-only distinctions without identity invention | Focused cases pass. A bound pair lacking receipt evidence fails explicitly instead of fabricating the receipt required by the canonical binding. Optional completed_at is ignored. |
| Header scalar evidence survives malformed snapshot/partial binding; no expiry or mismatch decision | Header-separation tests pass. Decoder takes no clock or incoming fingerprint. Consumer replacement/409 ordering is explicitly outside this leaf, not proven here. |
| Existing evidence-json serializer and model_of/model_of_json materialization; arbitrary permitted program_context | Tagged dictionaries round-trip, but actual model materialization and original-model fingerprint generation are UNVERIFIED by these tests. |
| Both raw and production pools against one real migrated disposable PostgreSQL database | UNVERIFIED this round: all three database cases skipped for missing DSNs; no current DB session identity, migration, row count or durability claim. Prior live-PG reports are historical only. |
| Run JSONB object rather than double-encoded string; authorized principals/Workspace/Project/registered Graph | UNVERIFIED: codec fixtures are synthetic DTOs, not authorized Run admission. |
| No SQL mutation, HTTP/queue changes, live _assess or scope utility change, new authority or policy | Codec is mapping-only; no production edit this round. No activation performed. |
| Reachable production behavior and unchanged integration CI | NOT established: provenance gate reports both modules unreachable and unauthorized by trusted base. Unit imports and whitelist references do not establish runtime reachability. Full integration CI remains UNVERIFIED. |
| Focused pytest, lint, format, mypy and inventory | Passed as recorded above, with the three DB skips explicitly excluded from durability evidence. No new pre-fix/mutation/crash claim. |
| Coordinated owner/base and activation policy | Assigned worktree/head honored; external coordination and activation choices remain UNVERIFIED. No merge or rollout authorized. |

The reported generic `test: failure` is not reproduced by the focused suite. `.github/workflows/ci.yml:574-612` excludes core tests from that job, so these passes are not a claim that the entire `test` job passes. No failing test traceback was supplied in the driver logs. A repair to unrelated test suites without concrete failure evidence would be speculative. The frozen dispatch check-run records contain a successful `test` and failed `exact-debt-ledger` for linked #1945 head `fcc8b437f209a35aa68a61d6f0a5387414938355`, not the assigned head. They provide no assigned-head traceback; check output text/summary is null. Those statuses cannot be promoted to current-head verification.

## Blocked handoff

- Confirmed failure locations: `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`. The required `.github/workflows/vulture-ratchet.yml:77` provenance gate rejects these modules against the supplied trusted base.
- Source import inspection finds only the codec's dependency on the DTOs and the Vulture whitelist reference. No production consumer makes either module reachable.
- Resolution requires owner-coordinated trusted-base authorization/integration outside this repair scope. The existing candidate rows are preserved, not removed or self-authorized. No ledger, grant, gate, source or test changes were made.
- Generic `test: failure`: UNRESOLVED pending assigned-head failing step/node/traceback. Full integration CI and current PostgreSQL durability remain unverified.
- Only changed file: `docs/testing/issue-1893-repair-06daf56d.md`. `git diff --check` passed. This report is committed locally; no push, PR mutation, merge, issue closure or activation.
- Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 required provenance gate. Next: externally resolve the trusted-base blocker and supply concrete current-head test failure evidence.

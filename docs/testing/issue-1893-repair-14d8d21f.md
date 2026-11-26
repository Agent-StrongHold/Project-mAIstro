# Issue #1893 repair — job 14d8d21f

## Frozen scope and initial evidence

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `0743521dbca870fd5d5ae86fd5a372ef7d5ab485`; supplied develop base `2154f845347c9541016288c760f8da3f5cd2e064`.
- One item: #1893 immutable admission codec CI repair. No re-enumeration of remote issues/PRs; dispatch-context.json is the frozen evidence source.
- Tree was clean. No incoming edits needed salvage.
- Supplied check-0 through check-4 logs: dependency sync, ruff, formatting and inventory pass; focused tests report 324 passed, 3 skipped. These are driver observations, not this worker's executions.
- Prior result reports unauthorized reachability ledger additions and an unreproduced `test: failure`. Neither is assumed resolved.
- Ambiguity: dispatch supplies no failing test node or test-job log. Proceed with focused tests and exact quality gates, without guessing a code repair.
- Planned edits: this evidence note only unless executed checks expose an in-scope defect. Do not modify reachability ledgers/grants or activate the staged codec. Vulture ledger amendment is permitted only for actual reviewed scan findings.

## Worker validation

- Exact requested Vulture command `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1322 reviewed findings, zero unclassified. No Vulture ledger change is warranted.
- Supplied base resolves locally. `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1). Both admission modules are new unauthorized unreachable modules and new unauthorized dispositions. Other wrapper checks pass. This reproduces the previous blocker; the Vulture-only repair exception cannot authorize a reachability ledger change.
- Fresh focused execution: `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`: **324 passed, 3 skipped**, 327 nodes, 1.82 seconds. The three skips are PostgreSQL codec cases at test_admission_codec.py:470; both required database variables are unset.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS (3301 files).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS (2 files).
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS (16543 nodes, no duplicate evidence).
- Validation commands used 1200-second timeouts. No source or test repair is justified by these executions.

## Architecture and acceptance checkpoint

Read repository instructions, accepted ADR-081226-a66b (canonical lifecycle) and ADR-083126-5e62 (protected-base quality authority), the codec and its tests, and the immutable DTO constructors. Source import search finds no production caller of admission_codec; admission_identity is referenced by the codec and Vulture whitelist only. Inactive staging is not runtime acceptance. Adding a dummy caller or editing reachability policy to make the slice pass would violate the lane constraints and trusted-base governance.

- Frozen/slotted header, signed scalar validation, strict schema/format, header-row mismatch: existing focused tests PASS.
- Immutable v2 round trips, named TEXT fields, fresh mapping, paired binding columns, UUID hex and owner-token hygiene: existing focused tests PASS. The storage-shape assertion is independent of encode/decode agreement (test_admission_codec.py:134–137).
- Legacy bound/unbound/partial/receipt-only, ignored completed_at, no invented identity: focused tests PASS. A task/run pair without receipt fails partial because the shared binding requires receipt identity; no receipt is guessed.
- Header expiry/fingerprint retention despite corrupt snapshots/partial binding, no clock or classifier: focused tests PASS. Consumer expiry/409 precedence is outside B2 and UNVERIFIED.
- Strict JSON objects, duplicate/nonfinite rejection, numeric and Unicode preservation or safe typed failure: focused tests PASS. Tests inject corrupt raw TEXT and assert safe suppressed exception chains.
- Existing evidence tags and stored fingerprints survive decoding: focused tests PASS. Original production fingerprint computation and model_of/model_of_json materialization are UNVERIFIED: fixtures assert tag retention, not that full model path.
- Raw/production PostgreSQL pools on the migrated chain, SQL row/session counts, JSONB Run payload object, and real authorized Workspace/Project/principals/Graph: UNVERIFIED in this round. Skipped PG tests and synthetic DTO fixtures are not durability or authorization evidence.
- No new scheduler, authorization path, SQL mutation, HTTP/queue/assessor/scope changes: this round edits documentation only; staged production behavior remains unchanged.
- Full integration CI and the unspecified merge-queue `test: failure`: UNVERIFIED. The supplied snapshot has no failing-node log in the dispatch brief; focused execution does not reproduce a test failure.
- No new tests or inventory counts changed; an inventory-delta note is not required. No fresh pre-fix/mutation claim is made.

## Final disposition

Additional fresh execution: `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q` (1200-second timeout): **1919 passed, 310 skipped, 6 warnings**, 2229 nodes, 49.01 seconds. The warnings are aiosqlite worker-thread `Event loop is closed` reports in test_sqlite_store.py, not failed codec assertions. A bounded extraction of failed `test` check-run output from the supplied dispatch snapshot produced no failing-node evidence. The reported merge-queue test failure remains UNRESOLVED, not disproven.

**BLOCKED:** the reproduced provenance failure requires protected-base authorization/coordination outside this lane. Existing source and ledger changes are preserved; no candidate policy/grant edit, dummy production caller, fetch/merge, or GitHub mutation was performed. No develop-sync conflict exists in this clean starting tree. The supplied starting SHA and base are unchanged apart from this evidence-only commit.

Changed file: `docs/testing/issue-1893-repair-14d8d21f.md` only. No inventory delta is needed. This is a blocked local handoff, not integration approval. Further repeated repair dispatches without new evidence cannot resolve the policy prerequisite.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 blocking provenance command. Next: owner resolves the protected-base reachability prerequisite and supplies the actual SHA-qualified failing test log; then revalidate the authorized integration, including disposable PostgreSQL durability and full CI.

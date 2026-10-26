# Issue #57 repair checkpoint — c0e0b6ff

## Frozen scope
- Assigned worktree: `/home/dev/Git/wt/auto-57`, branch `auto-57`.
- Starting HEAD verified: `b2d10a96773bb5f28d2333a27c86ee40cc00ab77`; base: `5647c34bfb8be091e5935191aed37d56dca974e0`.
- Single item: issue #57, including explicit exact-debt-ledger vulture repair and reported SECURITY.md reversibility claim drift. No remote changes or issue closure.
- Input snapshot: `/home/dev/maistro/jobs/c0e0b6ff0100482c9d4ee8a99e1ffcec/dispatch-context.json`. No re-fetch/re-enumeration.
- Initial worktree clean. No `check-*.log` files present in supplied job directory at initial listing; driver validation is not assumed.
- Prior result read: `/home/dev/maistro/jobs/6a5c846069b44ac2bc4f70855e7fcf55/result.json` (BLOCKED, older head). Its test claims require revalidation.

## Assumptions and boundaries
Writer assignment permits edits and requires a local commit. #847 closure is external and cannot be performed in this lane; captured open status blocks full issue acceptance. No migration of scheduler or authorization authority is intended. Inspect existing production/tests/ADRs first; amend only evidence-backed defects and the explicitly permitted vulture ledger.

## Progress
- Verified starting ref and read repository instructions and supplied issue body (12 acceptance criteria).
- Exact vulture CI scan executed at starting HEAD: exit 0, 1317 findings against 1321 reviewed base identities, no unbanked identities. No ledger amendment justified.
- SECURITY.md:35 already accurately documents registry construction and separates classification from approval gating. Reported stale claim is not reproduced; do not cosmetically re-edit it.
- Read ADR-050, ADR-068 and ADR-081226-6b46: tool contracts are exposure/validation, never a second authority. Classification does not itself approve an effect. Legacy DAG parity remains visibly incomplete (`legacy_dag_node.py` invokes directly without registry tier).
- Inspection typo: attempted to read a nonexistent guessed ADR-050 filename once, returned ENOENT. Resolved actual path from local directory inventory; no command executed against an unresolved ref.
- Reproduced actual criterion-4 defect with an end-to-end `GovernedToolExecutor.execute` probe: a registered property schema `{'type': 'integre'}` accepted `{'count': 'not-an-integer'}` and backend returned `executed`. `_reject_wrong_type` defaults unsupported types to an always-true predicate. This is evidence, not a scanner guess.

## Frozen focused repair files
- `packages/maistro-core/src/maistro/tools/contracts.py`: reject unsupported declared schema types rather than allow unrestricted provider input.
- `packages/maistro-core/tests/tools/test_governed_contracts.py`: regression through real governed dispatch, including nested schemas and supported-type controls.
- `docs/testing/inventory-notes/issue-57-unsupported-schema-types.md`: required inventory delta/evidence.
- This checkpoint: executed validation and acceptance limitations.
- No other production files or ledgers unless the exact scan reports retained unbanked identities caused by this fix.

## Executed repair validation (current diff)
- Dependency sync: `uv sync --locked --extra dev` passed.
- Red: `uv run pytest packages/maistro-core/tests/tools/test_governed_contracts.py -k 'unsupported_schema_type or supported_schema_types' -q`: 7 failed, 7 passed, 8 deselected (`/tmp/issue-57-c0e0-red.log`). Unknown/empty/null/malformed/nested declarations reached dispatch; union declaration raised unhandled TypeError instead of a typed refusal.
- Changed `_reject_wrong_type` to refuse every explicitly declared type outside the supported seven single-type names with `ToolArgumentError`. Absence of a type declaration remains compatible with intentional unconstrained JSON values.
- Green focused core (contracts, Agent base/factory/spec, ReAct, BuildersLearning, artificer, effect-context, Sentinel audit): 317 passed (`/tmp/issue-57-c0e0-core.log`).
- Full `uv run pytest packages/maistro-core/tests -x -q`: 16002 passed, 1158 skipped, 7 xfailed, 54 warnings, 311.75 seconds (`/tmp/issue-57-c0e0-core-full.log`). Warnings include SQLite thread teardown (`Event loop is closed`), fork/datetime deprecations and a fake coroutine not awaited; not suppressed or repaired out of scope.
- Hive production seam/legacy DAG/Agent model tools/core adapter test files: 101 passed (`/tmp/issue-57-c0e0-hive.log`).
- `uv run pytest packages/maistro-bootstrap/tests -x -q`: 236 passed, 7 skipped (`/tmp/issue-57-c0e0-bootstrap.log`). Skips are not live backend equivalence evidence.
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed, 3413 files formatted. Logs `/tmp/issue-57-c0e0-{ruff,format}.log`.
- Post-fix exact vulture scan: passed, unchanged 1317 findings (`/tmp/issue-57-c0e0-vulture.log`). No retained unbanked identities; do not edit the ledger merely because the lane permits it.
- Same schema defect at the shared validator root: five new cases all failed before the root check (`/tmp/issue-57-c0e0-root-red.log`). Model strategies call this function without ToolContract construction; now it checks explicitly declared root types too. Inventory delta is +19 total (7 dispatch refusals + 5 root refusals + 7 supported-type controls).
- Final focused core run after the root fix: 322 passed (`/tmp/issue-57-c0e0-core-final.log`). The earlier full-core run above preceded the root check addition.
- Architecture regression tests: `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q`: 74 passed (`/tmp/issue-57-c0e0-gate-tests.log`).
- `uv run python scripts/check-suite-inventory.py`: all 21 suites match; core 17172 node IDs, 33158 unique node IDs across suites, no duplicate evidence (`/tmp/issue-57-c0e0-inventory.log`).
- `uv run mypy packages/maistro-core/src/maistro/tools/contracts.py`: passed, one source file (`/tmp/issue-57-c0e0-mypy.log`).
- Direct-effect gate passes: 51 sites, 4 TOOL_EFFECT. Model-egress passes its ratchet but explicitly reports 12 reachable escapes awaiting #56 migration; this is not proof of repository-wide M1 completion. Security-inventory gate passes 23 rows/61 paths but does not audit all prose. Convergence-matrix passes 52 subsystems/1437 modules. Logs `/tmp/issue-57-c0e0-check*.log`.
- Independently read captured `issues/847` object: state=open, updated_at=2026-10-07T12:55:04Z. This is frozen evidence only, not refreshed GitHub state.
- `git diff --check` passed; only the four frozen repair files differ. No quality ledgers/grants were changed.
- Final full-core run **after** root validation: `uv run pytest packages/maistro-core/tests -x -q`: 16007 passed, 1158 skipped, 7 xfailed, 54 warnings in 270.57s (`/tmp/issue-57-c0e0-core-full-final.log`).
- Final Hive subset: 101 passed (`/tmp/issue-57-c0e0-hive-final.log`). Final lint/format/exact-vulture scans all pass; Vulture unchanged at 1317 findings (`/tmp/issue-57-c0e0-{ruff,format,vulture}-final.log`).
- Targeted contracts coverage diagnostic: 27 passed, module 90% statement coverage (`/tmp/issue-57-c0e0-contract-coverage.log`); not repository/diff-coverage approval. Initial diagnostic explicitly disabled the aggregate threshold for this narrow module; no tracked gate/configuration was edited. Re-run **without** a threshold override: `uv run pytest packages/maistro-core/tests/tools/test_governed_contracts.py --cov=maistro.tools.contracts --cov-report=term-missing -x -q` also passed, 27 tests/90% (`/tmp/issue-57-c0e0-contract-coverage-default.log`).
- `uv run python scripts/check-radon-baseline.py`: exit 0, 128 C-or-worse blocks versus 129 baseline entries, zero new/regressed/improved blocks and one reported stale entry (`/tmp/issue-57-c0e0-radon.log`). This focused schema change adds no complexity hotspot; no radon ledger edit is permitted in this lane. Stale-entry warning is retained for owner review, not silently changed.

## Acceptance evidence and limits

| # | Criterion | Fresh evidence / remaining limitation |
|---|---|---|
| 1 | Consume real #55 Invocation seam | Core Invocation/effect-context tests and Hive boot/legacy tests pass; `contracts.py` calls existing `effects.invocations.invoke`. **UNVERIFIED** repository-wide #55 prerequisite: model-egress still reports 12 banked reachable escapes. No competing execution authority introduced. |
| 2 | Canonical authorization and policy-required expected effects | Core `test_governed_tool_persists_expected_evidence_on_canonical_invocation` passes; asserts persisted Invocation prediction and policy/completed event correlation. Hive records production registry tier. High-impact behavior is configured in the core test; Hive's shipped registry is read-only. |
| 3 | Effective authorized set before provider | Agent base/factory, ReAct, artificer, BuildersLearning and Hive refusal tests pass. Legacy effective-envelope equivalence remains **UNVERIFIED**; no global completion claim from the new schema fix. |
| 4 | Missing/unknown schemas fail closed | Existing unknown-tool/no-schema tests pass. New 7 dispatch-level cases first failed, now refuse before Binding/provider/events; 5 root cases first failed, now return typed refusals; 7 supported-type controls pass. Validator supports a subset, not complete JSON Schema; undeclared constraints remain optional. |
| 5 | Structured command arguments across backends | Bootstrap suite 236 passed, 7 skipped. `test_agent_loop_command_contract.py` proves argv schema, raw `cmd` refusal before sandbox, and metacharacter refusal. Live container/microVM parity **UNVERIFIED**. |
| 6 | Host-owned reversibility | Hive registry-tier Invocation test passes. **UNVERIFIED** legacy parity: `legacy_dag_node.py:437` invokes with task/config but no registry reversibility, unlike governed contract request. |
| 7 | Recomputable exact expected-effect evidence | Core SQLite reopen test passes both interrupted append modes; asserts Invocation id, capability/provider, exact arguments/digest, pre-state digest, expected/observed states and policy version after reopening stores. Live PostgreSQL restart **UNVERIFIED** (skipped service-dependent tests not counted as proof). |
| 8 | Durable correlated immutable mismatch | Core mismatch/reopen/replay tests pass: one durable correlated mismatch event, first mismatch cannot be overwritten with later matching observation, no provider redispatch, replay raises PredictionMismatch. |
| 9 | Missing required high-impact prediction detectable | `test_high_impact_contract_without_expected_effect_fails_closed` passes with refusal and complete-contract positive control. |
| 10 | All historical seven TOOL_EFFECT sites migrated/hardened or retired | Inventory gate passes current 51 sites/4 TOOL_EFFECT and Hive effect tests pass. Historical full seven-site control parity **UNVERIFIED**, especially legacy classification/effective envelope; matching census is not control equivalence. |
| 11 | Architecture gate rejects introduced raw tool bypass | 74 direct-effect/model-egress gate tests pass, including new raw Hive/browser path rejection tests. Gate scope is curated; no claim it finds arbitrary dynamic Python effects. |
| 12 | #847 closes from adversarial evidence first | **UNMET**: captured issues/847 says open. No GitHub mutation performed and no closure inferred from passing subsets. |

## Handoff

One assigned issue checked; one focused schema defect repaired. External blocker and
legacy/M1/live-backend evidence gaps remain, so verdict is **BLOCKED**, not integration
approval. SECURITY.md and vulture findings supplied in the brief were already absent;
no cosmetic/security-prose change or unnecessary ledger amendment was made.

Changed files are exactly the source validator, its adjacent tests, +19 inventory
note, and this checkpoint. No scheduler, Goal store, event authority, authorization
path, quality grants or remote refs were added/changed. Finalize with a local commit;
never push or close issues. Remote head CI remains **UNVERIFIED**: no supplied
check-*.log artifacts and no remote checks requested/refreshed.

Progress: checked 1, focused repair done 1, skipped 0, unexpected validation failures 0.
Expected red tests are retained in logs, not hidden. Next: authorized owner verifies
legacy control parity and prerequisites #55/#847; integration remains outside this lane.

# Issue #57 repair — 0df5a4ee

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-57`, branch `auto-57`.
- Starting HEAD verified: `18da8110eece05bed0ea1c1bf7d9a8f6286d04e3`.
- Base: `161dedc06344b3d9630f3b79be9418088a5bff99`.
- One item only: issue #57, using supplied job `0df5a4eeb5034888a752acc0d4bc61b2/dispatch-context.json`. No remote re-enumeration or GitHub mutations.
- Initial worktree clean; no salvage required. No `check-*.log` files supplied in this job directory.
- Inspect existing changed production code/tests and applicable ADRs; reproduce reported SECURITY.md drift and exact vulture gate. Amend only an evidenced defect/retained vulture identity, plus this report and inventory notes if tests change.
- Frozen inspection targets: SECURITY.md; tools/contracts.py; capabilities/{expected_effect,effect_context,invocation,governed_invocation}.py; agents/{base,strategies/react,artificer/strategy}.py; Hive governed_tools and legacy adapter; bootstrap agent_loop; their adjacent changed tests; repo gate scripts/workflows and relevant ADRs/docs.
- Prior result is evidence, not proof: prior round BLOCKED on snapshot prerequisite #847 and unverified CI, with exact vulture passing.

## Ambiguities / decisions

- This is a writer repair round (explicit lane instruction), not a read-only verifier run.
- A prerequisite issue cannot be closed locally and no GitHub mutations are allowed; report its frozen status rather than claiming completion.

## Results

- Exact required vulture gate PASS (exit 0): 1,298 findings, 0 unclassified, 0 never_allowlist; base 1,302 reviewed identities. Log `/tmp/auto-57-0df5-vulture.log`. No unbanked identity exists to repair; ledger unchanged.
- `SECURITY.md:35` already states governed contracts construct the registry and distinguishes missing Sentinel reversibility approval (#346). Reported drift does not reproduce at starting HEAD; no cosmetic repair warranted.
- Frozen issue #57 supplies 12 acceptance criteria; frozen prerequisite #847 is open. Criterion 12 is unmet and cannot be resolved by a local code change.
- Repository AGENTS.md and docs authority map read. `uv sync --locked --extra dev` PASS; 468 resolved packages / 218 audited.
- Existing production inspection: `GovernedToolExecutor` admits via registered canonical Bindings, records host registry tier, snapshots arguments, invokes the existing lifecycle service, persists/replays mismatch evidence. Hive Agent/chat constructor reaches it. Current legacy `_run_tool_node` now resolves `hive_tool_reversibility` and records the registry tier too (the older implementation checkpoint's missing-tier observation is stale). Pure materialized legacy schema validation remains separate from canonical Invocation admission; not a second authority.
- Meaningful existing core tests inspect backend calls, canonical evidence, SQLite reopen, interrupted mismatch append/ack and immutable verdicts, mutation at real await points, schema/allowlist refusals before binding/backend. Executed independently: core focused suite **384 passed** (exit 0), `/tmp/auto-57-0df5-core-tests.log`. Includes Agent base/factory/seam/identity/schema/trust/spec, ReAct, BuildersLearning, artificer, governed contracts, effect-context policy and Sentinel audit.
- Accepted ADR-050, ADR-068 and ADR-081226-6b46 read: reversibility classification is not approval authority; tool exposure narrows but does not grant Binding authorization; actual dispatch/evidence belongs to Invocation. No reconciliation requiring an architecture change identified.
- Hive focused suite **112 passed**: governed tools, legacy DAG, Agent model tools, core adapter (`/tmp/auto-57-0df5-hive-tests.log`). Bootstrap package **255 passed, 7 skipped** (`/tmp/auto-57-0df5-bootstrap-tests.log`); skipped integration paths are not proven live-backend parity.
- `uv run ruff check .` PASS. `uv run ruff format --check .` PASS (3,490 files already formatted). Logs `/tmp/auto-57-0df5-ruff-{check,format}.log`.
- Root architecture gate tests **74 passed** (`/tmp/auto-57-0df5-gate-tests.log`). Both injected raw Hive/BrowserClient path rejection tests executed.
- Gates PASS: `check_direct_effects.py` (51 sites, 4 TOOL_EFFECT, all dispositioned), `check-model-egress.py` (20 physical callers, **12 banked reachable escapes awaiting #56**; pass is not a completed cutover), `check-security-inventory.py` (62 paths/23 rows/2 counted claims; prose not fully checked), `check-convergence-matrix.py` (1,462 modules classified), `check-suite-inventory.py` (21 suites; 34,162 unique test identities). Logs `/tmp/auto-57-0df5-<script stem>.log`.
- No production/test/ledger edit is supported by the reported failures: neither reported drift nor unbanked-vulture failure reproduces. Finalize evidence and residual acceptance gaps rather than manufacture a repair.
- Frozen exact starting-head CI: 51 successful + 3 skipped checks, **16 in progress**; `gates-ran` pending (`Required execution evidence is still arriving`). This is not green CI and says nothing about the new local report commit. No remote refresh performed.

## Acceptance review (bounded evidence, not integration approval)

| # | Criterion | Fresh executed evidence / production reachability / limits |
|---|---|---|
| 1 | Consume #55, no second tool executor | `tools/contracts.py:358` calls existing canonical Invocation lifecycle; Hive constructor/adapter and legacy Invocation tests pass. Whole-repository #55 cutover **UNVERIFIED**; model-egress explicitly banks 12 remaining reachable escapes. No scheduler or parallel execution authority introduced in this round. |
| 2 | Canonical authorization and policy-required expected effects | Core `test_governed_tool_persists_expected_evidence_on_canonical_invocation`, Hive `test_governed_tool_records_invocation_with_registry_tier`, legacy Invocation tests pass. Hive ships only read-only/internal contracts; high-impact configured test exercises persistence. Universal production coverage **UNVERIFIED**, not inferred from a reusable class. |
| 3 | Effective tool/capability set before execution | Agent base + strategy/model denial suites pass; `base.py:886` checks Agent identity, host schema and Sentinel before raw dispatch; Hive narrows host exposure and canonical Binding admission. BuildersLearning effects retired and tested. Full Principal/Workspace/Goal/Run envelope equivalence across all integrations **UNVERIFIED**. |
| 4 | Missing/unknown schema refusal | Core unknown/missing/schema type tests and Hive legacy materialized argument tests pass, with backend nonexecution assertions. Host schema snapshot and repaired-data validation covered by Agent schema-boundary tests. |
| 5 | Structured commands across supported backends | Bootstrap command contract plus package argv/option/injection tests pass: `run_command` requires `argv`, routes `run_argv`, rejects raw shell strings/metacharacters. Live container/microVM backend parity **UNVERIFIED** (7 skips); not proved merely by a mocked sandbox. |
| 6 | Host-owned registry reversibility | Core/Hive registry-tier and effect-context policy tests pass. Legacy shared-host-tier test covers all 3 tool names, ignores injected caller strings; registry reclassification test denies backend dispatch with canonical `require_approval` event. `legacy_dag_node.py:409,449` resolves and records the shared registry tier. This repairs the prior checkpoint's evidence gap, not a new source change. |
| 7 | Exact/recomputable evidence identities | Core evidence tests assert capability/provider, materialized argument digest, pre-state digest, expected/observed post-state, policy version and Invocation identity after real SQLite close/reopen. Mutation-during-await tests verify exact admitted inputs at backend/evidence. Deployed PostgreSQL restart and multi-process race behavior **UNVERIFIED**. |
| 8 | Durable mismatch, not ordinary success | Core mismatch and interrupted append/ack reopen tests pass: immutable host verdict, one correlated canonical mismatch event, raises PredictionMismatch on replay and never redispatches. Cross-process races **UNVERIFIED**. |
| 9 | Missing high-impact expected effects detectable | `test_high_impact_contract_without_expected_effect_fails_closed` passes, rejects incomplete contract at registration and accepts complete contract. No claim that every possible mutating integration has been configured as high-impact. |
| 10 | Seven historical TOOL_EFFECT sites migrated/retired/reclassified | Current direct-effect inventory gate passes (51 sites / 4 retained TOOL_EFFECT). Chat paths call governed helpers, legacy missing-identity fallback refuses, BrowserClient calls are provider backend sites. Hive production boot/adapter/legacy tests pass. Complete historical seven-site equivalence **UNVERIFIED**; inventory membership and historical note claims alone are insufficient proof. |
| 11 | Injected raw path rejected | Root gate suite (74 passed) includes `test_a_newly_introduced_raw_hive_tool_call_is_rejected_by_the_audit` and `test_a_newly_introduced_raw_browser_client_call_is_rejected_by_the_audit`; both intentionally introduce forbidden raw call sites and assert audit rejection. |
| 12 | #847 closes first with adversarial tests | **UNMET**: frozen job `dispatch-context.json:75131` starts source `issues/847`; `dispatch-context.json:75234` records `state=open`. Related adversarial suites above passed, but full #847 completion/closure cannot be inferred. No issue closure action allowed or taken. |

## Handoff

- Verdict: **BLOCKED**, not MERGE-READY. Reported source/vulture failures are absent; no actual code repair justified. Remaining external prerequisite and explicitly UNVERIFIED acceptance items prevent an all-criteria completion claim.
- Changed file this round: only `.cursor/context/repair-57-0df5a4ee.md` (this evidence checkpoint). No tests added/changed, so no inventory delta note required; suite inventory remains passing. No ledgers/grants touched.
- All executed validation commands exited 0. Test totals: core 384, Hive 112, bootstrap 255 (+7 skipped), architecture 74 = **825 passed, 7 skipped**. Commands used `uv run` throughout; tests/gates used 1200-second tool timeouts. `git diff --check` passed.
- Test commands: `uv run pytest <13 named core test files> -x -q` (files listed in Results); `uv run pytest packages/hive-conductor/backend/tests/{test_governed_tools,test_legacy_dag_node,test_agent_model_tools,test_maistro_core_adapter}.py -x -q`; `uv run pytest packages/maistro-bootstrap/tests -x -q`; `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q`. Gate commands: `uv run python scripts/<script listed in Results>`; exact vulture command `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`.
- No push, PR, merge, issue mutation, cleanup/discard, or background process. Finish with a local commit and clean worktree.
- Staged whitespace check initially caught an extra blank line at this report's EOF; removed it before committing. No source or test validation failed.
- Progress: checked 1 assigned issue; completed 1 validation/report item; issue completion 0; skipped issues 0; source/test validation errors 0. Next: owner review of unmet #847 prerequisite and unverified production/backend coverage; no additional items started.

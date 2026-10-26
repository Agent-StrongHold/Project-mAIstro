# Issue #57 repair — d41cc5ea

## Frozen scope
- Assigned writer worktree `/home/dev/Git/wt/auto-57`, branch `auto-57`.
- Starting HEAD verified: `8ad07da3dcef924be6261af792ed68feb1404f27`; clean worktree.
- Frozen base: `652cf8e56f382e2b6f6344292ef9d14f6fb78e2c`.
- Process only issue #57 and the supplied dispatch-context.json snapshot; no remote enumeration or mutations.
- Repair scope: actual evidence from exact vulture CI gate, prior SECURITY.md drift finding, and focused acceptance validation of existing #57 production code/tests. Amend only reviewed vulture identities if the exact scan finds debt. Do not expand to implementing/closing dependency #847.
- Relevant files frozen from starting diff: SECURITY.md; core tools/contracts.py, capabilities expected_effect/invocation/governed_invocation/effect_context, agents Base/ReAct/Artificer/builders paths; Hive governed_tools and legacy_dag_node; bootstrap command/sandbox paths; adjacent existing tests; direct-effect inventory and scanner tests; ADR-004 and governing Invocation/security ADRs; quality/vulture-baseline.json if evidence requires; this report.

## Initial evidence and assumptions
- Repository AGENTS.md read. Prior result f805e6b2 read: BLOCKED, mostly passing focused tests but external #847 dependency and live-runtime validation gaps.
- No driver `check-*.log` files exist in supplied job directory (shell glob returned not found); remote CI is not assumed green.
- Snapshot issue #57 has twelve acceptance criteria, including actual closure of #847. Treat external closure separately from branch implementation readiness; never mutate GitHub.
- No preexisting uncommitted work to salvage.
- No unresolved ref or merge conflict observed; no develop sync attempted absent evidence it is necessary.

## Validation (in progress)
- Exact CI vulture scan PASS: 1299 findings vs 1303 reviewed base identities, zero unclassified/unbanked identities. Log: job `repair-vulture.log`. No ledger amendment warranted.
- SECURITY.md:35 already documents constructed host ReversibilityRegistry and distinguishes missing Sentinel tier gating (#346); stale prior finding does not reproduce. No cosmetic repair.
- Frozen dispatch sources confirm #847 state=open and list wider remaining acceptance. External closure criterion is UNMET; no GitHub mutation permitted.
- Governing ADR-081226-6b46, ADR-004 amendment, ADR-050, ADR-073 reviewed. Tool contracts reuse CapabilityEffectContext.invocations; no new scheduler/lifecycle authority.
- Documentation search included nonexistent ADR-177/178/180 globs; these were not used as authority. Resolved the actual canonical ADR by its discovered filename instead.
- `uv run ruff check .` PASS; `uv run ruff format --check .` PASS (3482 files).
- Fresh core tools/capabilities + adjacent Agent/ReAct/BuildersLearning/Artificer/Sentinel tests: **1643 passed, 12 skipped**, one unawaited fake-process coroutine warning (`repair-core.log`).
- Fresh Hive governed tools / legacy DAG / Agent model tools / adapter tests: **112 passed** (`repair-hive.log`).
- Fresh bootstrap package tests: **255 passed, 7 skipped** (`repair-bootstrap.log`): one Windows-only test; six Docker/builders-image-dependent tests unavailable. Live container parity is not proven by this run.
- Direct-effect/model-egress adversarial scanner tests: **74 passed** (`repair-adversarial-gates.log`), including introduced raw Hive dispatcher/BrowserClient path rejections.
- Direct-effect gate PASS: 51 sites, including four TOOL_EFFECT entries; inventory matches code (`repair-direct-effects.log`). This is census/disposition evidence, not universal authorization proof.
- Model-egress gate PASS as a debt ratchet, **not** M1 completion: explicitly reports 12 reachable escapes awaiting #56 migration (`repair-model-egress.log`). Full #55 production cutover remains UNVERIFIED.
- Security inventory gate PASS (62 cited paths, 23 rows; most prose not checked); convergence gate PASS (1457 production modules, 152 attributed unreachable); suite inventory PASS (21 suites, 34055 unique identities). Logs: `repair-security-inventory.log`, `repair-convergence.log`, `repair-suite-inventory.log`.
- `uv run mypy` the exact seven package source paths in AGENTS.md PASS (934 source files, `repair-mypy.log`).
- All checks above used 600–1200 second timeouts. Driver logs absent as recorded above. No new tests added; no inventory delta required. No production/ledger change justified by reproduced findings.

## Acceptance review (frozen issue criteria, in order)
1. **Consume #55, no second tool executor:** inspected `contracts.py:358` delegating to existing `effects.invocations.invoke`; `governed_tools.py:263` composes over the live Container effect context; passing Hive boot/chat/legacy tests prove the exercised wiring. Complete #55 cutover **UNVERIFIED**: model-egress gate still reports reachable #56 debt.
2. **Canonical authorization plus required expected effects:** passing core `test_governed_tool_persists_expected_evidence_on_canonical_invocation` asserts policy/completion events and stored prediction. Hive `test_governed_tool_records_invocation_with_registry_tier` exercises production composition. Universal deployed high-impact coverage **UNVERIFIED**; shipped Hive contracts are read-only.
3. **Agent effective set before provider:** Agent base/strategy allowlist tests, custom-strategy schema-boundary tests, BuildersLearning no-effect tests, and Hive `test_unlisted_and_badly_typed_tools_refuse_before_the_backend` passed. Inspected Agent-owned identity gate in `base.py:901`, then Sentinel validation, then raw dispatch; BuildersLearning has no remaining strategy-authored shell/GitHub effects. Full principal/Workspace/Goal/Run envelope equivalence across every retained path **UNVERIFIED**.
4. **Missing/unknown schemas fail closed:** core `test_agent_allowlist_and_unknown_schema_fail_before_backend`, unsupported-type tests, Agent `test_unknown_tool_is_not_exposed_and_cannot_be_forged_by_strategy`, and legacy raw-tool-without-schema tests passed with no backend effect. Host object-schema checks are explicit, not unrestricted `{}` fallbacks.
5. **Constrained command contract across backends:** bootstrap `test_agent_loop_command_contract.py` and argv/hardening suites passed. Inspected builder exposure and dispatch using structured argv instead of raw cmd. Live container parity **UNVERIFIED** (six integration skips); no claim of live microVM/backend equivalence.
6. **Canonical host reversibility:** Hive registry-tier, legacy shared-registry tier, and legacy host-reclassification tests all passed. `contracts.py:335` and `legacy_dag_node.py:409` read host registry state, not node/caller tier labels. SECURITY.md correctly distinguishes this classification from unimplemented reversibility-driven Sentinel approval gating (#346).
7. **Exact/recomputable expected-effect records:** core SQLite close/reopen tests passed for both interrupted-append cases and assert Invocation/capability/provider identity, exact arguments + digest, pre-state digest, expected/observed state, policy version and evidence digest. Source `expected_effect.py` binds these fields; `invocation.py:519` fills canonical identity before durable admission. Live PostgreSQL/restart and universal deployed mutating-tool coverage **UNVERIFIED**.
8. **Durable mismatch, not silently ordinary success:** passing mismatch/reopen tests assert immutable first observation, correlated durable event, PredictionMismatch on replay, one event after lost append/ack, and no repeated backend effect. Inspected `contracts.py:384` replay append and `invocation.py:953` first-observation settlement. Cross-process race behavior **UNVERIFIED**, and recovery still requires replay.
9. **Missing configured high-impact predictions detectable/policyable:** `test_high_impact_contract_without_expected_effect_fails_closed` passed (ExpectedEffectRequired plus complete-contract positive control); `ToolContract.__post_init__` refuses incomplete prediction contracts before dispatch.
10. **Seven historical TOOL_EFFECT entries controlled/retired:** direct-effect gate matches four current TOOL_EFFECT provider-backend entries; passing boot/chat/legacy tests exercise canonical wrapping and refusal without identity. Full historical seven-site equivalence **UNVERIFIED**: census success alone cannot establish all historical security controls.
11. **Intentional raw path rejected:** `tests/test_check_direct_effects.py:496` and `:519` inject raw Hive dispatcher and BrowserClient calls; both passed within the fresh 74-test gate run.
12. **#847 closes first with adversarial evidence:** **UNMET**. Supplied `dispatch-context.json:73333` records #847 open. Passing relevant adversarial subsets cannot substitute for external prerequisite closure or complete independent #847 acceptance.

## Reproducible commands
All commands ran in this worktree. Logs are under the assigned job directory `/home/dev/maistro/jobs/d41cc5eacda34916b05b842dd0efe2d0`.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
- `uv run pytest packages/maistro-core/tests/tools packages/maistro-core/tests/capabilities packages/maistro-core/tests/agents/test_base.py packages/maistro-core/tests/agents/test_factory.py packages/maistro-core/tests/agents/test_tool_schema_boundary.py packages/maistro-core/tests/agents/spec packages/maistro-core/tests/agents/strategies/test_react.py packages/maistro-core/tests/agents/strategies/test_builders_learning.py packages/maistro-core/tests/agents/artificer/test_strategy.py packages/maistro-core/tests/security/sentinel/test_audit.py -x -q`
- `uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py packages/hive-conductor/backend/tests/test_legacy_dag_node.py packages/hive-conductor/backend/tests/test_agent_model_tools.py packages/hive-conductor/backend/tests/test_maistro_core_adapter.py -x -q`
- `uv run pytest packages/maistro-bootstrap/tests -x -q -rs`
- `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q`
- `uv run ruff check .`; `uv run ruff format --check .`
- `uv run python scripts/check_direct_effects.py`
- `uv run python scripts/check-model-egress.py`
- `uv run python scripts/check-security-inventory.py`
- `uv run python scripts/check-convergence-matrix.py`
- `uv run python scripts/check-suite-inventory.py`
- `uv run mypy packages/maistro-core/src packages/maistro-server/src packages/maistro-turing/src packages/maistro-canvas/src packages/maistro-bootstrap/src packages/maistro-registry/src packages/maistro-ext-sdk/src`

## Handoff
Only this checkpoint changes in this round. Existing source, tests, ledgers, grants, and earlier reports remain preserved. No actual vulture/security-doc repair was warranted by current evidence. No inventory note added because no tests were added, removed, or changed. Local validation is not exact-head remote CI approval (remote CI **UNVERIFIED**, no driver logs supplied).

Progress: checked 1 assigned issue, done 1 focused validation handoff, skipped 0 issues, failed validation commands 0. Verdict **BLOCKED** on external #847 acceptance and the explicitly unverified production/backend/historical criteria. Next: authorized owner/verifier resolves dependency sequencing and missing evidence; never infer closure or merge readiness from passing ratchets. Commit checkpoint locally only; no push or GitHub mutation.

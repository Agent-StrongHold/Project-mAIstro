# Issue #57 repair — 4b2ff8d8

## Frozen scope
- Only issue #57 on assigned worktree `/home/dev/Git/wt/auto-57`, branch `auto-57`.
- Starting HEAD verified `86c1b36d82e2880dd3bf60618f38a12c344c422e`; supplied base `c29e0ea7094198095c107e3583dbfd5e50009a5d` resolves. Worktree initially clean.
- Evidence snapshot: `/home/dev/maistro/jobs/4b2ff8d87d2b48de8c219dc3816d6316/dispatch-context.json`; no re-fetch or GitHub mutation.
- Process one item: focused #57 CI-repair/acceptance validation; modify only evidenced defects and this report. Ledger edits permitted only for actual vulture findings.
- No check-*.log files present in supplied job directory at initial listing. Prior result read: `/home/dev/maistro/jobs/0ed59cc820dd40229a6957bcde730dfb/result.json`, verdict BLOCKED; its verification claims will not be assumed true.

## Recorded ambiguity / assumption
- Dispatch mentions an exhausted launch preflight for a missing external worker instruction file. This worker is already executing with supplied instructions; no repository change is appropriate for that external file.
- Prior finding alleges SECURITY.md drift; prior result says already repaired. Inspect current source before editing.
- Acceptance 12 requires #847 closure; frozen snapshot has #847 open. Cannot satisfy external closure locally; no closure actions permitted.

## Progress
- Snapshot and exact refs verified. No uncommitted salvage was needed.
- Exact vulture gate PASS: 1311 findings vs 1315 reviewed base identities, no unbanked identities. No ledger edit is justified.
- SECURITY.md:35 already documents `ReversibilityRegistry` construction and distinguishes it from Sentinel approval gating. Prior stale-doc finding not reproducible; no wording-only repair.
- Read accepted ADR-004 amendment, ADR-050, ADR-068, ADR-081226-6b46; production core contracts, Hive composition and legacy Invocation adapter reviewed. Registry/exposure does not grant authority or own lifecycle; classification is not approval gating. No reconciliation-driven source change required.
- `uv sync --locked --extra dev` PASS. Focused core tests PASS: 390. Log: job directory `writer-core.log`.
- Fresh Hive tests PASS: 105 (`writer-hive.log`); bootstrap: 243 passed, 7 skipped (`writer-bootstrap.log`); architecture adversarial tests PASS: 74 (`writer-architecture.log`). Skips: one Windows-only regression on Linux, six container tests lacking Docker/image availability.
- `uv run ruff check .`, `uv run ruff format --check .` (3443 files), `git diff --check`: PASS.
- Relevant gates all PASS: direct effects (51 sites / 4 TOOL_EFFECT); model egress (nonexpansion ratchet, explicitly 12 retained reachable escapes); security inventory; convergence (1447 modules); suite inventory (21 suites, 33468 unique identities). Job directory `writer-check*.log` files contain fresh local results, not driver/remote CI results.
- Read expected-effect model and adversarial contract tests, Hive real SQLite Container/Run fixture and boot/chat entry-point tests, bootstrap command-contract tests, and accepted lifecycle ADR-081226-a66b. No test failure reproduced within executed checks. Existing tests exercise real persistence/admission with physical backends patched; they are not live backend parity proof.
- Supplied base ledger inspected with `git show c29e0ea7094198095c107e3583dbfd5e50009a5d:quality/direct-effect-call-sites.json`: six TOOL_EFFECT identities (two chat wrappers, two legacy wrappers, two BrowserClient calls); current census four. Seventh historical identity remains UNRESOLVED. Current census does not establish all historical dispositions; no guessed identity or ledger change.
- Agent base allowlist/Sentinel gate, removed AgentSpec fields, retired BuildersLearning side effects, legacy host reclassification tests and Invocation host-observation code reviewed. One schema limitation recorded: `base.py:941` still returns an empty schema if absent, while shipped Hive provider contracts validate independently. Full strategy-independent missing-schema refusal cannot be claimed from the focused ReAct/contract tests. No speculative redesign of the Agent/provider seam was attempted.

## Exact validation commands and outcomes

All validation commands used `uv run` and 1200-second timeouts (initial ref/source inspection used 1000 seconds). Logs are in the supplied job directory, not tracked source files.

- `uv sync --locked --extra dev`: PASS.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS (1311 findings, 1315 reviewed identities; no unbanked identities).
- `uv run pytest packages/maistro-core/tests/tools/test_governed_contracts.py packages/maistro-core/tests/agents/test_base.py packages/maistro-core/tests/agents/test_factory.py packages/maistro-core/tests/agents/test_tool_call_identity.py packages/maistro-core/tests/agents/spec/test_agent_spec.py packages/maistro-core/tests/agents/spawner/test_spawner.py packages/maistro-core/tests/agents/strategies/test_react.py packages/maistro-core/tests/agents/strategies/test_builders_learning.py packages/maistro-core/tests/agents/artificer/test_strategy.py packages/maistro-core/tests/capabilities/test_effect_context_policy.py packages/maistro-core/tests/security/sentinel/test_audit.py -x -q`: **390 passed**; `writer-core.log`.
- `uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py packages/hive-conductor/backend/tests/test_legacy_dag_node.py packages/hive-conductor/backend/tests/test_agent_model_tools.py packages/hive-conductor/backend/tests/test_maistro_core_adapter.py -x -q`: **105 passed**; `writer-hive.log`.
- `uv run pytest packages/maistro-bootstrap/tests -x -q -rs`: **243 passed, 7 skipped**; `writer-bootstrap.log`.
- `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q`: **74 passed**; `writer-architecture.log`.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3443 files.
- `uv run python scripts/check_direct_effects.py`: PASS, 51 sites / 4 TOOL_EFFECT; `writer-check_direct_effects.log`.
- `uv run python scripts/check-model-egress.py`: PASS as a nonexpansion ratchet, **not** proof of zero escapes; `writer-check-model-egress.log`.
- `uv run python scripts/check-security-inventory.py`: PASS; `writer-check-security-inventory.log`.
- `uv run python scripts/check-convergence-matrix.py`: PASS; `writer-check-convergence-matrix.log`.
- `uv run python scripts/check-suite-inventory.py`: PASS; `writer-check-suite-inventory.log`.
- `git diff --check`: PASS.

## Acceptance review (not integration approval)

| # | Criterion | Executed evidence / limits |
| --- | --- | --- |
| 1 | Consume #55 canonical seam | `contracts.py:355` delegates to the existing Invocation service. Hive real Container/Run/NodeRun/Attempt boot tests pass. Full #55 prerequisite completion **UNVERIFIED**: model-egress ratchet still reports 12 reachable escapes; gate success is not cutover completion. |
| 2 | Authorization and required expected effects | Core `test_governed_tool_persists_expected_evidence_on_canonical_invocation` passes, asserting policy/completion events and attached prediction. Hive `test_governed_tool_records_invocation_with_registry_tier` proves shipped route correlation. Live shipped high-impact effect **UNVERIFIED**: Hive contracts currently expose read-only/internal tools; mutating contract is a library test fixture. |
| 3 | Effective authorized tool set | Agent base, ReAct, artificer and Hive denial tests pass before backend; BuildersLearning side effects retired. `base.py:892` checks Agent identity before Sentinel; `governed_tools.py:281` intersects host exposure. Full principal/Workspace/Goal/Run effective envelope across all consumers **UNVERIFIED**. |
| 4 | Missing/unknown schemas fail closed | Contract/unsupported-type, ReAct and legacy tests pass with backend-call assertions. Hive requires registered host schemas; legacy unknown raw-tool test passes. Full strategy-independent boundary **UNVERIFIED**: Agent `_tool_schema` retains `{}` fallback (`base.py:941`), so these passing subset tests are not evidence of universal refusal. |
| 5 | Structured command contracts across backends | Bootstrap schema/raw-text/metacharacter/argv tests pass; `agent_loop.py:413` calls `run_argv`, not raw shell text. Live all-backend parity **UNVERIFIED** (6 container/image skips; 1 Windows-only test skipped). |
| 6 | Host-owned reversibility | Hive registry and legacy shared-tier/reclassification tests pass, including caller downgrade refusal and policy event `tool.reversibility`. `contracts.py:101` constructs registry, `legacy_dag_node.py:409` resolves it. Classification is not complete Sentinel approval integration; SECURITY.md explicitly distinguishes this. |
| 7 | Recomputable prediction identities | Both SQLite reopen tests pass, asserting capability/provider/arguments/digests/expected and observed states/Invocation id/policy version. `expected_effect.py:66` compares host observations. Actual pre-state retrieval and complete all-consumer high-impact parity **UNVERIFIED**; storing a digest is not retrieval evidence. |
| 8 | Durable mismatch, cannot rewrite as success | Core mismatch and two interrupted-append SQLite reopen tests pass. `invocation.py:965` preserves first host observation; stable correlated event and raised PredictionMismatch survive replay without backend redispatch. Observation/event append are separate durable writes; repair is retry-driven, not proven autonomous atomic recovery. |
| 9 | Missing high-impact expected effects detectable | `test_high_impact_contract_without_expected_effect_fails_closed` passes: incomplete configured contract rejected at registration, complete contract accepted. Future legacy high-impact policy parity **UNVERIFIED**. |
| 10 | Seven shipped inventory entries controlled/retired | Current census passes and retained production-route/legacy no-identity refusal tests pass. Supplied base contains six TOOL_EFFECT entries; exact historical seventh disposition and complete seven-site equivalence **UNVERIFIED**. |
| 11 | Intentionally introduced raw paths rejected | `tests/test_check_direct_effects.py:496` and `:519` inject Hive and BrowserClient raw calls, assert NEW-site audit failures; both pass. Finite curated AST coverage is not a claim against every reflective Python bypass. |
| 12 | #847 closes first from adversarial evidence | **UNMET**: supplied dispatch source `repos/Agent-StrongHold/Project-mAIstro/issues/847` has `state=open`. Local adversarial tests do not prove complete #847 acceptance or external closure. No GitHub mutations permitted. |

Remote exact-head CI is **UNVERIFIED**. No driver `check-*.log` files were present at arrival; new writer logs are local results only. No historical pending/green status is treated as current proof.

## Handoff / changes

Only `.cursor/context/repair-57-4b2ff8d8.md` changed this round. No production code, tests, inventories, ledgers, grants or gates changed: neither the alleged stale SECURITY.md claim nor unbanked vulture debt reproduced. No test delta means no new inventory note is warranted. Existing implementation preserved intact.

Verdict: **BLOCKED**, not merge-ready or integration approval. Owner/verifier must resolve the explicit external prerequisite and missing acceptance evidence, including shared schema admission, historical inventory and backend parity. The missing external launcher file is not a repository repair.

Progress: checked 1 assigned issue; done 1 validation/handoff item; skipped 0 issues; errors 0 validation commands (7 individual tests skipped). Next: authorized owner/verifier review. Finish with a local commit only; no push or issue closure.

# Issue #57 repair disposition — job 2c71a0b6

## Frozen assignment

- Issue #57 only; branch `auto-57`, assigned worktree `/home/dev/Git/wt/auto-57`.
- Verified clean starting HEAD `ec75662f9c1c3e5406c1f58c47697267c6c5686f`; supplied base `161dedc06344b3d9630f3b79be9418088a5bff99`.
- Used the supplied dispatch snapshot and prior result only, without refreshing remote issue/PR lists or mutating GitHub. Prior validation claims were not treated as current proof.
- Writer role assumed from the explicit repair/commit assignment. No driver `check-*.log` files existed in the job directory at initial inspection. The logs below were executed independently this round.
- Scope: reproduce the reported SECURITY.md drift and exact-vulture failure, inspect existing #57 production paths/adjacent tests, validate acceptance, commit an evidence-backed disposition. No unrelated implementation, grants, or ledger expansion.
- Read repository instructions, documentation authority map, accepted ADR-004 (including its #847 amendment), ADR-050, ADR-068, and ADR-081226-6b46. Tool exposure cannot grant authority; reversibility classification does not itself decide approval. Preserve canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` and the existing Binding/Invocation lifecycle. Missing underlying #55/#56 cutover evidence is not a reason to introduce a parallel executor here.

## Repair findings

Neither assigned repair finding reproduces at this HEAD:

1. `SECURITY.md:35` already states that governed contracts construct `ReversibilityRegistry`, consistent with `packages/maistro-core/src/maistro/tools/contracts.py:101`. It explicitly distinguishes classification from unresolved reversibility-based Sentinel approval (#346). No repeat prose correction is justified.
2. Exact vulture CI scan passes: 1298 findings, zero unclassified and zero never_allowlist, versus 1302 reviewed base identities. No unbanked identity or genuinely dead code was reported. The lane permits evidence-backed ledger amendment, but this scan supplies no reason for one.

No failing focused validation justified a production/test repair. Only this evidence note changes; no test inventory delta is required because no tests were added or changed. The inventory gate passes independently. Existing implementation and ledger changes from earlier commits are preserved.

## Executed validation

All commands ran foreground in the assigned worktree; test/gate timeouts were 1200 seconds. Logs live in `/home/dev/maistro/jobs/2c71a0b625fc4f45ab9fe0dcbe26ca6b/`.

| Command | Outcome | Log |
| --- | --- | --- |
| `uv sync --locked --extra dev` | PASS | console |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; zero unclassified | `check-vulture-worker.log` |
| `uv run pytest` core paths below, `-x -q` | 384 passed | `check-core-worker.log` |
| `uv run pytest` Hive paths below, `-x -q` | 112 passed | `check-hive-worker.log` |
| `uv run pytest packages/maistro-bootstrap/tests -x -q` | 255 passed, 7 skipped | `check-bootstrap-worker.log` |
| `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q` | 74 passed | `check-architecture-worker.log` |
| `uv run ruff check .` | PASS | `check-ruff-worker.log` |
| `uv run ruff format --check .` | PASS; 3490 files | `check-format-worker.log` |
| `uv run python scripts/check_direct_effects.py` | PASS; 51 sites, 4 TOOL_EFFECT | `check_direct_effects-worker.log` |
| `uv run python scripts/check-model-egress.py` | PASS as ratchet; retains 12 reachable escapes | `check-model-egress-worker.log` |
| `uv run python scripts/check-security-inventory.py` | PASS; 62 paths, 23 rows, 2 counted claims; not all prose checked | `check-security-inventory-worker.log` |
| `uv run python scripts/check-convergence-matrix.py` | PASS; 1462 modules classified | `check-convergence-matrix-worker.log` |
| `uv run python scripts/check-suite-inventory.py` | PASS; 21 suites, 34162 unique identities | `check-suite-inventory-worker.log` |

Core paths, under `packages/maistro-core/tests/`: `tools/test_governed_contracts.py`; `agents/{test_base,test_factory,test_agent_seam_fail_closed,test_tool_call_identity,test_tool_schema_boundary,test_trust_pipeline_equivalence}.py`; `agents/spec/test_agent_spec.py`; `agents/strategies/{test_react,test_builders_learning}.py`; `agents/artificer/test_strategy.py`; `capabilities/test_effect_context_policy.py`; `security/sentinel/test_audit.py`.

Hive paths, under `packages/hive-conductor/backend/tests/`: `{test_governed_tools,test_legacy_dag_node,test_agent_model_tools,test_maistro_core_adapter}.py`.

Total: **825 passed, 7 skipped**. Mock provider success is not live-backend proof.

## Acceptance review

| # | Criterion | Executed evidence / remaining limits |
| --- | --- | --- |
| 1 | Consume #55 canonical seam | Inspected `contracts.py:358` delegating to existing Invocations and governed wrapper; core persistence and Hive boot/legacy wiring tests PASS. Complete production cutover **UNVERIFIED**: model-egress retains 12 reachable escapes, and bootstrap `agent_loop.py:476` calls `_dispatch_tool` directly. Do not infer zero bypasses from a passing debt ratchet. |
| 2 | Authorization plus required expected-effect evidence | Core `test_governed_tool_persists_expected_evidence_on_canonical_invocation` PASS asserts policy/completion events and correlated prediction. Hive real SQLite Container/Run/NodeRun/Attempt tests PASS with stub backend. Universal high-impact production policy configuration **UNVERIFIED**. |
| 3 | Effective authorized tool/capability set | Agent base/factory/schema/seam/identity/trust, ReAct, artificer, BuildersLearning and Hive refusal tests PASS before backend execution. Hive exposure intersection and existing execution records inspected. Complete principal/Workspace/Goal/Run envelope equivalence across integrations **UNVERIFIED**. |
| 4 | Missing/unknown schemas fail closed | Core unknown-schema and unsupported root/nested type cases, Agent and Hive refusal tests PASS, including no backend dispatch assertions. Bounded schema subset, not arbitrary JSON Schema support. |
| 5 | Constrained command contract across backends | Bootstrap argv-only/raw-command/metacharacter and backend-shape tests PASS; inspected `agent_loop.py:407-419` routing `run_command` to `run_argv`. Seven skipped tests; live supported-backend parity **UNVERIFIED**. |
| 6 | Host-owned reversibility | Inspected registry construction and legacy `legacy_dag_node.py:409,449`; Hive registry-tier, caller-tier rejection and registry reclassification/policy tests PASS. Classification evidence is not a claim that Sentinel.resolve_tier implements #346 approval integration. |
| 7 | Recomputable exact expected-effect binding | Core argument-mutation, canonical persistence and real SQLite close/reopen tests PASS, asserting Invocation/capability/provider/arguments/digests/pre-state digest/expected and observed states/policy version. PostgreSQL and cross-process behavior **UNVERIFIED**. |
| 8 | Durable mismatch cannot silently become success | Core mismatch immutability and both interrupted append/lost-ack SQLite reopen cases PASS: stable correlated event, no redispatch, replay raises PredictionMismatch despite later matching observation. Observation/event writes remain separate; recovery is on replay. Cross-process races **UNVERIFIED**. |
| 9 | Missing required high-impact predictions detectable | `test_high_impact_contract_without_expected_effect_fails_closed` PASS: incomplete registration rejects; complete prediction contract accepted. Universal shipped mutating-action configuration **UNVERIFIED**. |
| 10 | Seven historical TOOL_EFFECT sites migrated/retired | Current direct-effect gate PASS (4 retained TOOL_EFFECT sites), Hive boot/chat/legacy and BuildersLearning retirement tests PASS; retained provider dispositions inspected. Historical seven-site behavior/control equivalence **UNVERIFIED**; census reduction alone is not proof. |
| 11 | Direct/raw path introduction rejected | Both injected raw Hive dispatcher and BrowserClient rejection tests (`tests/test_check_direct_effects.py:496,519`) PASS in architecture run. This proves the curated scanner cases, not every possible Python effect. |
| 12 | #847 closes first with adversarial verification | **UNMET**: frozen `dispatch-context.json:76291` identifies `/issues/847`; line 76394 records `state=open`. Local tests are not authorized issue closure or complete #847 verification. No closure attempted. |

## Handoff

Verdict **BLOCKED**: criterion 12 cannot be repaired by branch code or permitted local actions. Remote final-head CI, complete M1 cutover, skipped/live backends, and broader acceptance limits above remain explicitly UNVERIFIED. No integration approval is implied.

Changed file: `.cursor/context/repair-57-2c71a0b6.md` only. No production/test/inventory/quality-ledger/grant changes. No push, merge, destructive git, discarded work, issue mutation or spawned agents. Local commit and post-commit status are required before returning.

Progress: checked 1 assigned issue; done 1 bounded validation/report; skipped 0 issues; failed validations 0; issue completion 0. Next: authorized owner sequences #847 and supplies missing acceptance evidence. Another documentation/vulture repair dispatch needs new failing evidence; the supplied findings are already absent.

# Issue 57 repair — c3ca23c8

## Frozen scope
- Only issue #57, branch auto-57, assigned worktree /home/dev/Git/wt/auto-57.
- Starting HEAD verified: 8e95585200e2f921275d19fe0dec10f5406f316f; clean index/worktree.
- Dispatch snapshot: /home/dev/maistro/jobs/c3ca23c850fa4b93be80f8b9935d4580/dispatch-context.json. Do not refetch issue/PR lists.
- Assigned repair: inspect prior security claim drift, execute exact vulture gate, repair evidenced dead/retained identities only, validate issue acceptance and commit locally.
- Candidate files: SECURITY.md, quality/vulture-baseline.json (explicit lane exception), evidence-driven related source/tests only, inventory notes if tests added, and this report.
- No check-*.log files present in supplied job directory at initial listing. No external CI success assumed.
- Existing branch work preserved; no uncommitted incoming changes.

## Progress
- Read root AGENTS.md; inspected starting diff summary against supplied develop base.
- Ambiguity: dependency closure cannot be performed in this lane (GitHub mutation prohibited). Treat snapshot status as evidence and report remaining blocker, not alter issue requirements.
- Read prior result and report as evidence only. Extracted all 12 acceptance criteria from primary dispatch issue body.
- Item 1 DONE: fresh `uv sync --locked --extra dev` and exact requested vulture gate PASS: 1,298 findings, 0 unclassified, 0 never_allowlist; 1,302 base reviewed identities. Logs `/tmp/auto-57-c3ca-{sync,vulture}.log`. No unbanked identities exist to repair/amend; leave ledger intact.
- Item 2 DONE: read SECURITY.md:35 directly. It already states governed contracts construct ReversibilityRegistry and explicitly disclaims missing Sentinel registry-based approval gating (#346). Reported claim drift does not reproduce; no cosmetic edit justified.
- Item 3 IN PROGRESS: independent focused acceptance validation and production/ADR review.
- Fresh core tests PASS: 384 passed in 2.99s (`/tmp/auto-57-c3ca-core.log`), covering governed contracts, Agent identity/schema/seam/factory/spec, strategies, effect-context policy and Sentinel audit.
- Read accepted ADR-050 and ADR-068 in full. Reconciliation: registry classification is not an approval authority; tool exposure must only narrow existing canonical Binding permission. Read production contracts.py in full: registry construction at :101 and actual dispatch via existing invocations.invoke at :358 corroborate the current SECURITY claim.
- Snapshot source `repos/Agent-StrongHold/Project-mAIstro/issues/847` independently inspected: state=open. Acceptance 12 remains unmet; no issue closure attempted.
- Read accepted canonical ADR-081226-6b46, production Hive governed_tools.py and adjacent core governed-contract tests in full. Hive derives scope from live Run/NodeRun/Attempt, intersects caller tools with host exposure, and delegates to canonical Invocation; high-impact tests exercise actual canonical lifecycle/SQLite reopen, not just isolated validation helpers. No competing scheduler/event/authorization path introduced by repair (no code changed).
- Fresh Hive focused tests PASS: 112 in 19.15s (`/tmp/auto-57-c3ca-hive.log`). Bootstrap package PASS: 255 passed, 7 skipped in 17.46s (`/tmp/auto-57-c3ca-bootstrap.log`); live-backend parity remains UNVERIFIED due to skipped integrations.
- Fresh root architecture gate tests PASS: 74 in 13.27s (`/tmp/auto-57-c3ca-architecture-tests.log`), including deliberately injected raw Hive/BrowserClient paths. Ruff lint and format PASS (3,490 files), logs `/tmp/auto-57-c3ca-ruff-{check,format}.log`.
- Checkpoint: 825 tests passed, 7 skipped. No source/test failure found, no new tests or inventory delta, no ledger changes justified.
- Relevant gates all PASS, fresh logs `/tmp/auto-57-c3ca-<script>.log`: `check_direct_effects` (51 sites, 4 TOOL_EFFECT), `check-model-egress` (20 callers; explicitly **12 retained reachable escapes awaiting #56**, not proof of completed cutover), `check-security-inventory` (62 paths/23 rows/2 counted claims; prose not fully checked), `check-convergence-matrix` (1,462 modules), `check-suite-inventory` (21 suites/34,162 unique identities).
- Independently inspected Agent base.py:886+ identity/schema/Sentinel gate and host schema snapshot, legacy_dag_node.py:409+ registry-tier resolution and canonical Invocation dispatch, bootstrap agent_loop.py:407+ structured argv dispatch. None of these inspections proves universal integration or live-backend parity; report limits below.
- Item 3 validation DONE. All reproduced checks pass; no evidence justifies modifying production, tests, inventory or retained-debt ledger.

## Acceptance evidence (fresh checks; not integration approval)

| # | Criterion | Evidence and limits |
|---|---|---|
| 1 | Consume #55 seam, not another executor | `contracts.py:358` calls canonical `invocations.invoke`; core persistence and Hive real adapter/legacy tests pass. Complete repository #55/#56 cutover **UNVERIFIED**: model-egress gate reports 12 reachable escapes. |
| 2 | Canonical authorization plus policy-required expected effects | Executed `test_governed_tool_persists_expected_evidence_on_canonical_invocation` verifies actual backend dispatch, canonical record, policy/completion events. Hive real-wiring tests pass. Universal production coverage **UNVERIFIED**; shipped Hive contracts are internal/read-only, not deployed high-impact contracts. |
| 3 | Effective authorized Agent set before provider execution | Agent base/factory/schema/seam/identity/trust and ReAct/artificer/Hive adversarial suites pass with denied-backend nonexecution assertions. `base.py:886+` checks host Agent identity/schema/Sentinel before dispatch. Complete authority-envelope equivalence across all integrations **UNVERIFIED**. |
| 4 | Missing/unknown model-requested schemas fail closed | Executed core unknown/missing/unsupported root/nested schema refusal tests and Hive schema tests. Core tests assert no Binding admission or provider execution for malformed schema types. |
| 5 | One constrained structured command contract | Bootstrap 255 tests pass; tests reject model command strings and injected argv/pytest flags, while `agent_loop.py:407+` uses `run_argv`, not implicit shell execution. Live supported-backend parity **UNVERIFIED** (7 integration skips). |
| 6 | Host-owned reversibility | Core/Hive registry tests and legacy reclassification tests pass. Production `contracts.py:101`, `governed_tools.py:163` and `legacy_dag_node.py:409` resolve registry state, not caller tier strings. This does not establish missing Sentinel approval wiring (#346); ADR-068 forbids a competing approval authority. |
| 7 | Exact/recomputable expected-effect records | Executed core canonical persistence, await-boundary argument mutation, and SQLite reopen tests assert exact capability/provider/arguments/digests/pre-state/expected/observed post-state/policy/Invocation identity. Deployed PostgreSQL and cross-process behavior **UNVERIFIED**. |
| 8 | Durable mismatch, not ordinary success | Executed immutable mismatch and interrupted append/ack recovery tests against real SQLite reopen: stable correlated event, no redispatch, later observation cannot rewrite first mismatch, replay raises PredictionMismatch. Cross-process races **UNVERIFIED**. |
| 9 | Missing expected effects detectable on configured high-impact actions | Executed `test_high_impact_contract_without_expected_effect_fails_closed`: incomplete registration refuses, complete prediction contract accepts. This does not prove all mutating integrations have been configured high-impact. |
| 10 | Historical seven TOOL_EFFECT entries migrated/retired with controls | Fresh direct-effect gate passes (51 sites, four retained TOOL_EFFECT); Hive production/legacy and BuildersLearning retirement tests pass. Complete historical seven-site equivalence **UNVERIFIED**; disposition counts alone do not prove reachable behavior/control coverage. |
| 11 | Intentionally introduced raw paths rejected | Fresh root architecture suite passes 74 tests, including `tests/test_check_direct_effects.py:496,519`, injecting raw Hive/BrowserClient calls and asserting gate rejection. Universal no-bypass claim remains bounded by census scope, not assumed from passing inventory. |
| 12 | #847 closes from adversarial evidence first | **UNMET**: supplied `dispatch-context.json:75595` identifies #847 and `:75698` records issue state=open. Local adversarial tests do not substitute for prerequisite verification/closure. No GitHub mutations allowed or attempted. |

## Commands/outcomes

All validation used 1,200-second timeouts, real uv-managed environment, and foreground commands.

- `uv sync --locked --extra dev` — PASS.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS; zero unclassified/never_allowlist identities. No ledger amendment justified.
- `uv run pytest` with explicit core paths, `-x -q`: `packages/maistro-core/tests/tools/test_governed_contracts.py`; core `tests/agents/{test_base,test_factory,test_agent_seam_fail_closed,test_tool_call_identity,test_tool_schema_boundary,test_trust_pipeline_equivalence}.py`; core `tests/agents/spec/test_agent_spec.py`; core `tests/agents/strategies/{test_react,test_builders_learning}.py`; core `tests/agents/artificer/test_strategy.py`; core `tests/capabilities/test_effect_context_policy.py`; core `tests/security/sentinel/test_audit.py` — **384 passed**.
- `uv run pytest packages/hive-conductor/backend/tests/{test_governed_tools,test_legacy_dag_node,test_agent_model_tools,test_maistro_core_adapter}.py -x -q` (explicit expanded paths) — **112 passed**.
- `uv run pytest packages/maistro-bootstrap/tests -x -q` — **255 passed, 7 skipped**.
- `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q` — **74 passed**.
- `uv run ruff check .` and `uv run ruff format --check .` — PASS.
- `uv run python scripts/<script>.py` for each of `check_direct_effects`, `check-model-egress`, `check-security-inventory`, `check-convergence-matrix`, `check-suite-inventory` — PASS with the qualifications recorded above.
- `git diff --check` — PASS before final report completion; recheck at commit.

## Handoff

- Only changed file: `.cursor/context/repair-57-c3ca23c8.md` (this evidence report). No production/test/inventory/ledger/grant changes; no fabricated repair against absent findings.
- Prior SECURITY drift and vulture failures did not reproduce. No test addition means no inventory delta required; the inventory gate itself passes.
- Driver `check-*.log` files absent from supplied job directory; no remote final-head CI evidence established. Remote CI **UNVERIFIED**, never inferred green.
- Verdict **BLOCKED**: acceptance 12 external prerequisite remains open in snapshot; broader acceptance limits explicitly listed above. Owner must sequence #847 and supply missing production/backend coverage before closure. Do not rerun cosmetic repairs or invent debt rows.
- Progress: {checked: 1 issue, done: 1 bounded repair-validation/report, skipped: 0 issues, errors: 0 failed validations, next: owner prerequisite/coverage follow-up}. No fetch, push, PR mutation, issue closure, merge, destructive git, discarded work, background commands or subagents.
- Finish with local commit; report is a handoff only, never integration approval.

# Issue #57 repair — job 99b09cb5

## Frozen scope
- Assigned issue #57 only, branch auto-57, starting HEAD 97b5ea86ce1c96a86b9a5aa0054861fa7a780c29; base 161dedc06344b3d9630f3b79be9418088a5bff99.
- Clean worktree confirmed before changes. No incoming work to salvage.
- Snapshot: supplied dispatch-context.json only; no GitHub refresh/mutations.
- Repair target: reproduce exact vulture gate and repair actual evidence; inspect SECURITY.md claim versus reachable contracts; focused acceptance validation of existing #57 implementation.
- Candidate files: quality/vulture-baseline.json (explicit CI-repair exception), actual dead identities identified by gate, SECURITY.md only if stale, this progress note, inventory note only if tests added/changed. Do not modify unrelated ledgers.
- Acceptance 12 is externally blocked: frozen snapshot issues/847 state=open. No authority to close it. Remote CI readiness is unverified.
- Job directory contains no check-*.log files at initial inspection; run local checks.

## Progress
- Initial state and complete issue #57 / #847 acceptance text inspected from frozen dispatch.
- Existing branch contains extensive prior implementation; preserve it.
- `uv sync --locked --extra dev` PASS. Exact vulture gate PASS: 1298 findings; zero unclassified/never_allowlist; 1302 base reviewed identities. No evidenced ledger amendment/source repair needed.
- SECURITY.md:35 already documents registry construction and distinguishes classification from missing Sentinel approval gating (#346). Prior stale-claim finding does not reproduce. No cosmetic edit justified.
- Read repository instructions, docs authority hierarchy and prior result/reports as untrusted context.
- Read accepted ADR-050, ADR-068, ADR-081226-6b46 fully. Reconciliation: reversibility is classification, not independent approval authority; ToolExposure must narrow existing Binding authorization, not create another effect lifecycle. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt.
- Read production contracts.py and adjacent test_governed_contracts.py fully. Canonical dispatch is invocations.invoke at contracts.py:358. High-impact predictions are persisted before provider execution; observed mismatch is settled by the canonical Invocation service and correlated durable event, not provider verdict.
- Fresh targeted core validation PASS: 384 tests in 2.67s. Includes real Invocation persistence, SQLite reopen/lost mismatch append acknowledgement recovery, caller input mutation across await boundaries, typed schema refusal, Agent/strategy allowlists and denial auditing. No actual failed test/source finding yet.
- Fresh Hive focused tests PASS: 112 in 18.60s. Bootstrap package PASS: 255, 7 skipped in 16.60s. Root direct-effect/model-egress architecture tests PASS: 74 in 11.99s. Total 825 passed, 7 skipped.
- Read Hive production governed_tools.py and adjacent tests fully, legacy canonical tool admission, Agent base boundary, bootstrap command dispatch. Hive obtains scope from existing Run/NodeRun/Attempt and intersects caller tool names with host exposure; legacy resolves registry tier then delegates to canonical Invocation; Agent validates schema after Sentinel repair. Bootstrap uses structured run_argv for command dispatch but its TurnRunner calls _dispatch_tool directly (agent_loop.py:490): this inspection alone does not prove complete #55 migration/canonical admission for every builder tool. Keep full cutover UNVERIFIED, not infer it from a passing argv test.
- Final gates all PASS: ruff lint, format (3490 files), direct effects (51 sites / 4 TOOL_EFFECT), model-egress (20 callers), security inventory (62 paths / 23 rows / 2 counted claims), convergence (1462 modules), suite inventory (21 suites / 34162 unique identities), git diff --check.
- Important gate limits: model-egress explicitly retains 12 reachable escapes awaiting #56; security gate explicitly does not check all prose. These are passing debt ratchets, not proof of full cutover/security completeness.
- Independent frozen-snapshot check: dispatch-context.json:75827 identifies issues/847; :75930 states open. No external prerequisite closure assumed or attempted.

## Acceptance review

| # | Criterion | Fresh evidence / explicit limits |
|---|---|---|
| 1 | Consume #55 canonical seam | contracts.py:358 delegates to existing invocations.invoke; core and real SQLite Hive wiring tests pass. Complete #55/#56 production cutover UNVERIFIED (12 retained model escapes; bootstrap direct dispatch). |
| 2 | Canonical authorization and policy-required predictions | test_governed_tool_persists_expected_evidence_on_canonical_invocation executed and passed; Hive boot Invocation wiring passed. Universal shipped high-impact configuration UNVERIFIED; current Hive registry exposes internal/read-only tools. |
| 3 | Effective authorized Agent/tool envelope before dispatch | Executed Agent base/factory/schema/seam/identity/trust, ReAct, artificer and Hive adversarial suites; refusals assert no backend calls. Full envelope equivalence across every integration UNVERIFIED. |
| 4 | Missing/unknown schemas fail closed | Core allowlist/unknown schema, unsupported root/nested schema, Agent schema and Hive materialized argument refusal tests passed before Binding/backend dispatch. |
| 5 | Constrained structured command contract | Bootstrap 255 tests passed, including command argv/pytest injection guards; agent_loop.py:407+ dispatches run_argv, not implicit shell text. Seven integration skips mean live supported-backend parity UNVERIFIED. |
| 6 | Host-owned reversibility | contracts.py:101 constructs registry; governed_tools.py:163 and legacy_dag_node.py:409 resolve host registration. Executed Hive registry and legacy reclassification tests passed. Classification is not missing Sentinel approval integration (#346). |
| 7 | Recomputable expected-effect records | Core exact argument/caller-mutation/SQLite reopen tests executed and passed: capability/provider/arguments/digests/pre-state/expected/observed post-state/policy/Invocation identity. Deployed PostgreSQL/cross-process behavior UNVERIFIED. |
| 8 | Durable correlated mismatch, not ordinary success | Executed mismatch immutability and lost append/ack recovery after SQLite reopen; one correlated event, no redispatch, replay raises PredictionMismatch. Cross-process races UNVERIFIED. |
| 9 | Missing configured high-impact predictions detectable | Executed test_high_impact_contract_without_expected_effect_fails_closed: incomplete registration denied, complete contract accepted. All mutating integrations being configured high-impact UNVERIFIED. |
| 10 | Historical seven TOOL_EFFECT sites migrated/retired | Current direct-effect inventory passes (4 retained sites), Hive/legacy wiring and BuildersLearning retirement tests passed. Complete historical seven-site behavioral/control equivalence UNVERIFIED; site counts do not establish it. |
| 11 | Raw path introduction rejected by gate | Executed 74 root architecture tests including deliberately injected raw Hive and BrowserClient calls; audit rejects both. Proof bounded by census scope. |
| 12 | #847 closes from adversarial evidence first | UNMET: frozen dispatch-context.json:75930 records #847 open. Local adversarial tests do not substitute for authorized verification/closure. |

## Commands executed

All commands ran in the assigned worktree, foreground, with uv-managed dependencies; validation timeouts were 1200 seconds.

- `uv sync --locked --extra dev` — PASS.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS; zero unclassified identities, no ledger amendment justified.
- `uv run pytest` with `-x -q` and explicit core paths: `tests/tools/test_governed_contracts.py`; `tests/agents/{test_base,test_factory,test_agent_seam_fail_closed,test_tool_call_identity,test_tool_schema_boundary,test_trust_pipeline_equivalence}.py`; `tests/agents/spec/test_agent_spec.py`; `tests/agents/strategies/{test_react,test_builders_learning}.py`; `tests/agents/artificer/test_strategy.py`; `tests/capabilities/test_effect_context_policy.py`; `tests/security/sentinel/test_audit.py` (all under packages/maistro-core) — 384 passed.
- `uv run pytest packages/hive-conductor/backend/tests/{test_governed_tools,test_legacy_dag_node,test_agent_model_tools,test_maistro_core_adapter}.py -x -q` (explicit expanded paths) — 112 passed.
- `uv run pytest packages/maistro-bootstrap/tests -x -q` — 255 passed, 7 skipped.
- `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q` — 74 passed.
- `uv run ruff check .`; `uv run ruff format --check .` — PASS.
- `uv run python scripts/<script>.py` for `check_direct_effects`, `check-model-egress`, `check-security-inventory`, `check-convergence-matrix`, `check-suite-inventory` — PASS with limits above.
- `git diff --check` — PASS; recheck at commit.

## Handoff

Only changed file: `.cursor/context/repair-57-99b09cb5.md` (this evidence report). No production, test, inventory, ledger or grant changes: reported scanner/doc defects do not reproduce and no actual failure warrants guessed/cosmetic repair. No tests added/changed, so no inventory delta required; inventory gate passes.

Verdict BLOCKED: acceptance 12 external prerequisite remains open; additional full-production/backend coverage remains explicitly UNVERIFIED. Remote final-head CI UNVERIFIED; job directory supplied no check-*.log files. No merge-ready/integration approval or issue closure claim.

Progress: checked 1 assigned issue; done 1 bounded validation/report; skipped 0 issues; errors 0 failed validations. Next: authorized owner sequences #847 and resolves production/backend coverage gaps; do not loop on absent vulture/doc defects. Commit this report locally; never push. No GitHub mutation, fetch/merge, destructive git, discarded work, subagents or background commands.

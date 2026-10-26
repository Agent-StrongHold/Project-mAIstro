# Issue 57 repair snapshot — fca00e9a

- Assigned worktree `/home/dev/Git/wt/auto-57`, branch `auto-57`.
- Exact starting HEAD verified: `22b4151b959ba072806dbdd5c7d155a55dd9f02b`; worktree clean.
- Frozen scope: issue #57 only; repair prior SECURITY.md reversibility claim if still present, evaluate exact vulture per-identity gate and amend only evidenced debt as explicitly authorized, validate existing tool-contract behavior against 12 acceptance criteria. No GitHub mutation or dependency closure.
- Inputs: job `fca00e9ac4d34d01872c7e9164034182/dispatch-context.json`, starting branch changes, supplied previous result if present. Job directory initial listing contains no check-*.log files; driver results unavailable rather than assumed passing.
- Ambiguity: generic verifier wording says do not edit, but lane explicitly assigns writer/repair and requires commit; proceed as writer with focused repairs only.
- Captured issue #847 is open. Acceptance 12 cannot be fulfilled by local code or remote mutation; retain as blocker.
- Plan: inspect instructions/ADRs and current contracts/tests; run exact requested vulture gate; repair actual evidence only; run ruff, package-targeted tests and applicable architecture gates; record results and commit.

## Recorded results

- `uv sync --locked --extra dev`: PASS.
- Exact requested vulture gate: PASS; 1310 findings, 1314 reviewed identities, zero unclassified/never_allowlist. No unbanked identities; ledger changes are not warranted.
- SECURITY.md:35 already says governed contracts construct the registry, and separately notes missing Sentinel approval integration (#346). The reported documentation defect is not reproducible at this HEAD; do not apply a cosmetic repair.
- Read accepted ADR-004, ADR-050, ADR-068 and ADR-081226-6b46. Reconciliation: removed unenforced AgentSpec declarations are documented by ADR-004 amendment; host classification is not approval authority; Invocation remains the fulfillment lifecycle. No new authority introduced.
- Prior result read as historical BLOCKED evidence, not adopted as fresh validation.
- Fresh core focused tests: 336 passed (2.28s). Hive focused tests: 112 passed (18.83s). Bootstrap package tests: 255 passed, 7 skipped (17.45s). Ruff check and format-check both PASS (3472 files formatted).
- Production inspected: Hive `live_tool_context` re-reads Run/NodeRun/Attempt; governed executor intersects host registry exposure and calls canonical Invocation; legacy tool path resolves the shared registry tier and invokes canonical lifecycle. Tests exercise boot Agent/chat wiring and backend-not-called denials. No live backend execution inferred from mocks.
- Expected-effect evidence retains arguments, pre-state digest, expected/observed state, policy/version and Invocation identity. SQLite reopen tests exercise durable mismatch recovery, including append/ack interruption. Original pre-state retention/retrieval is not established by a digest; full criterion 7 remains UNVERIFIED.
- Architecture regression tests: 74 passed (13.17s), including intentionally introduced raw Hive/browser tool path rejection. Total this round: 777 passed, 7 skipped.
- Gates PASS: direct-effects (51 sites, 4 TOOL_EFFECT), model-egress (20 physical callers, explicitly 12 reachable escapes awaiting #56), security-inventory (limited mechanical checks; not all prose), convergence-matrix (1455 production modules), suite-inventory (21 suites, 33776 unique test identities, no duplicates).
- No source/test/ledger amendment justified by reproduced repair findings. No new tests: inventory-delta note not required. Only this evidence checkpoint changed.

## Acceptance against executed evidence

| # | Criterion | Evidence / limitation |
| --- | --- | --- |
| 1 | Consume #55 governed seam, no competing executor | Governed contracts call existing Invocation; Hive boot/chat and legacy tests pass. Full #55 production cutover **UNVERIFIED**: current model-egress gate reports banked reachable escapes. |
| 2 | Canonical authorization and required expected effects | Core persistence and Hive registry-tier Invocation tests pass. Deployed high-impact/mutating tool coverage **UNVERIFIED**; Hive ships internal contracts. |
| 3 | Effective authorized tool set before provider | Core Agent/custom strategy/ReAct/artificer and Hive adversarial refusals pass with backend-not-called assertions; retired BuildersLearning has no shell/GitHub effects. Universal Principal/Workspace/Goal/Run envelope **UNVERIFIED**. |
| 4 | Missing/unknown schemas fail closed | Core unknown/unsupported schema and Agent host-schema boundary tests; Hive materialized argument refusals pass. |
| 5 | Constrained command contract across supported backends | Bootstrap argv/raw-text/metacharacter rejection tests pass in package suite. Live backend parity **UNVERIFIED** (7 skipped tests, no live isolation execution). |
| 6 | Host-owned reversibility | Core registry classification and effect-policy floor tests; Hive/legacy shared registry tier tests pass. SECURITY.md correctly distinguishes this from Sentinel approval-gating debt (#346). |
| 7 | Exact/recomputable expected-effect evidence | SQLite reopen tests assert Invocation/capability/provider, materialized argument digest, pre-state digest, expected/observed state and policy version. Production pre-state retention/retrieval and deployment restart **UNVERIFIED**. |
| 8 | Durable correlated mismatch, not ordinary success | Mismatch and SQLite append/ack interruption/replay tests pass: immutable verdict, one correlated event, no redispatch, PredictionMismatch raised. Cross-process concurrency **UNVERIFIED**. |
| 9 | Missing configured high-impact predictions detectable/policyable | Core high-impact contract registration refusal and complete-contract positive control pass. |
| 10 | Seven historical TOOL_EFFECT entries controlled or retired | Current census matches four retained entries; legacy controls/retirement tests pass. Complete historical seven-site equivalence **UNVERIFIED**; counts alone do not prove it. |
| 11 | Architecture/security gate rejects introduced raw tool path | Both intentionally introduced raw Hive/browser path rejection tests pass in 74-test architecture run. |
| 12 | #847 closes first after adversarial verification | **UNMET**: frozen dispatch source `repos/Agent-StrongHold/Project-mAIstro/issues/847` is open. Local tests do not establish full child acceptance or closure; no remote mutation permitted. |

Exact-head remote CI **UNVERIFIED**. Driver check logs were not supplied. Passing local gates that bank migration debt are not proof that all acceptance criteria hold.

## Commands executed

All validation used 1200-second timeouts in the assigned worktree, exited zero, and was run independently of earlier claims:

```text
uv sync --locked --extra dev
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run pytest packages/maistro-core/tests/tools/test_governed_contracts.py packages/maistro-core/tests/agents/test_tool_schema_boundary.py packages/maistro-core/tests/agents/test_base.py packages/maistro-core/tests/agents/test_factory.py packages/maistro-core/tests/agents/spec/test_agent_spec.py packages/maistro-core/tests/agents/strategies/test_react.py packages/maistro-core/tests/agents/strategies/test_builders_learning.py packages/maistro-core/tests/agents/artificer/test_strategy.py packages/maistro-core/tests/capabilities/test_effect_context_policy.py packages/maistro-core/tests/security/sentinel/test_audit.py -x -q
uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py packages/hive-conductor/backend/tests/test_legacy_dag_node.py packages/hive-conductor/backend/tests/test_agent_model_tools.py packages/hive-conductor/backend/tests/test_maistro_core_adapter.py -x -q
uv run pytest packages/maistro-bootstrap/tests -x -q
uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check_direct_effects.py
uv run python scripts/check-model-egress.py
uv run python scripts/check-security-inventory.py
uv run python scripts/check-convergence-matrix.py
uv run python scripts/check-suite-inventory.py
```

## Handoff

**BLOCKED** by criterion 12 and the explicitly unverified production guarantees above. This is not a source repair or integration approval. Both supplied repair findings were already absent at the assigned starting HEAD; do not manufacture cosmetic or ledger changes to make this round appear productive. An authorized owner must sequence the child prerequisite and provide the remaining acceptance evidence. No GitHub actions performed.

Progress: checked 1 assigned issue; done 1 focused-validation item; skipped 0 issues; failed validation commands 0; issue completion 0. Next: owner review of the external prerequisite and unverified criteria, not another identical stale-doc/vulture repair dispatch. Finish with local commit and confirm clean status.

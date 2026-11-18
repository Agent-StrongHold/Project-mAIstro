# Issue 57 repair — afdf9da2

## Frozen scope
- Assigned worktree `/home/dev/Git/wt/auto-57`, branch `auto-57`.
- Starting HEAD `5dc2b538e9713e4cacbc7d8d15e4b0e6b80f0d7c`; base `b9cd15c608b5cc23ce785b3c80813d7e4d8f678b`.
- Single item: issue #57, from supplied dispatch-context.json; no remote enumeration or mutations.
- Inspect existing governed tool implementation/tests and relevant ADRs. Repair only evidenced #57 defects, SECURITY.md drift if still present, and exact vulture ledger identities if the prescribed scan finds them. Documentation/report path is this file; inventory notes only if tests change.
- Initial worktree clean. Prior result says BLOCKED, not trusted as current validation.
- No check-*.log files were supplied in this job directory (initial find returned no matches).
- Ambiguity: prompt includes verifier and writer instructions; lane explicitly assigns repair, so proceed as writer.

## Results
- Exact vulture command PASS (1310 findings, 1314 reviewed identities; zero unclassified and never_allowlist). Log `/tmp/auto-57-afdf-vulture.log`; no unbanked identities, so no ledger amendment justified.
- SECURITY.md:35 already documents registry construction and distinguishes classification from remaining Sentinel approval debt (#346). Supplied drift finding is not reproduced. No cosmetic repair.
- Frozen dispatch sources #55 and #847 both remain open. Criterion 12 is UNMET; full #55 completion cannot be inferred from local tool tests.
- Read accepted canonical fulfillment ADR-081226-6b46 and complete governed contracts implementation. Adapter delegates dispatch to canonical Binding/Invocation; schema/allowlist admission, argument snapshot, host registry classification, expected-evidence attachment and mismatch-replay append are present.
- External issue closure and remote CI cannot be established through local code; use supplied snapshot, no GitHub mutations.
- `uv sync --locked --extra dev`: PASS.
- Fresh scoped tests: core 336 PASS, Hive 112 PASS, bootstrap 255 PASS / 7 SKIP, architecture gates 74 PASS. Total 777 PASS / 7 SKIP. Logs `/tmp/auto-57-afdf-{core,hive,bootstrap,architecture}.log`. Commands listed below before commit.
- Read accepted ADR-004 amendment, ADR-050, ADR-068 and Hive composition alongside core adversarial tests. Reconcile historical taxonomy with canonical fulfillment ADR: registry classification and expected evidence belong on existing Binding/Invocation; they are not a separate approval authority. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt. No code changes proposed.
- No tests added or removed; no inventory delta note needed.
- Static checks PASS: `uv run ruff check .`; `uv run ruff format --check .` (3472 files); direct-effects, model-egress, security-inventory, convergence, suite-inventory, shipped-surface-truth, ratchet-provenance gates. Logs `/tmp/auto-57-afdf-{ruff,format,gates}.log`.
- Gate limitations recorded, not treated as acceptance proof: model-egress retains 12 reachable escapes; direct-effect census has 51 sites / 4 TOOL_EFFECT; security inventory checks cited paths/counts, not all prose. Suite inventory reports 21 suites / 33776 unique identities / no duplicate evidence. Ratchet provenance has 54 consumers; non-fatal existing SyntaxWarnings.
- Production inspections: canonical `expected_effect.py` retains argument/pre-state digests and policy version; Invocation binds selected identity before admission and preserves first observation. Shared Agent boundary checks declaration then Sentinel and validates materialized repairs. Hive verifies live canonical execution records and intersects caller tools with host exposure. Legacy resolves registry tier and validates materialized backend arguments; it does not use an independent effect authority.

## Acceptance review

| # | Criterion | Fresh executed evidence / limit |
| --- | --- | --- |
| 1 | Consume #55 canonical seam | Core contracts call `effects.invocations.invoke`; 112 Hive tests pass, including boot/chat canonical dispatch. Full #55 prerequisite **UNVERIFIED**: frozen #55 open; model-egress ratchet explicitly retains 12 reachable escapes awaiting #56. |
| 2 | Authorization and policy-required predictions | Core persisted-evidence and Hive Invocation tests pass. Invocation binds selected capability/provider/id before durable admission. Deployed high-impact mutation **UNVERIFIED**: shipped Hive contracts are internal/read-only. |
| 3 | Effective authorized tool set before provider | Shared Agent declaration/Sentinel checks, host-schema snapshots and Hive exposure intersection inspected; model/strategy unlisted-name and widened-schema tests pass. Universal principal/Workspace/Goal/Run envelope for every provider **UNVERIFIED**. |
| 4 | Missing/unknown schema fail closed | Core unknown-schema, unsupported root/nested type, Agent repaired-argument and Hive legacy materialized-argument refusals pass before backend calls. |
| 5 | Constrained commands across backends | All bootstrap tests: 255 pass / 7 skip. Command-contract tests prove raw text refusal, argv dispatch and shell-token denial. Production `_dispatch_tool` uses `sandbox.run_argv`, never implicit `sh -c`. Live backend parity beyond exercised paths **UNVERIFIED**. |
| 6 | Host-owned reversibility | Core policy-floor and Hive/legacy tier tests pass. Core registry is constructed at `contracts.py:101`; legacy resolves it at `legacy_dag_node.py:409`. Caller tier strings do not set these values. Sentinel registry-based approval gating is separate documented debt (#346), not claimed here. |
| 7 | Recomputable exact identities | Core SQLite reopen tests pass for capability/provider/materialized args/digests/pre-state digest/expected and observed post-state/Invocation id/policy version. Underlying production pre-state retention/retrieval and deployed restart **UNVERIFIED**; a digest alone does not preserve source state. |
| 8 | Durable mismatch not silently successful | Core append-absent/ack-lost SQLite recovery passes: replay raises PredictionMismatch, event is unique and correlated, provider ran once, later clean observation cannot replace mismatch. Cross-process adversarial observation concurrency **UNVERIFIED**. |
| 9 | Required high-impact prediction detectable | `test_high_impact_contract_without_expected_effect_fails_closed` passes with positive complete-contract control. |
| 10 | Seven historical TOOL_EFFECT sites hardened or retired | Current direct-effect census passes (51 sites / 4 tool sites); legacy tests and retired BuildersLearning no-effect tests pass. Historical seven-site behavior equivalence **UNVERIFIED**; current inventory count alone is not proof. |
| 11 | Intentionally introduced raw bypass rejected | 74 architecture tests pass, including injected raw Hive/browser tool calls rejected by audit. Gate coverage is finite syntax, not universal static proof. |
| 12 | #847 closes first with adversarial evidence | **UNMET**: supplied dispatch source `repos/Agent-StrongHold/Project-mAIstro/issues/847` says `state=open`. Local passing adversarial subsets cannot close/fully verify #847. |

## Exact test commands

Each used a 1200-second timeout; all were run afresh in the assigned worktree.

```text
uv run pytest packages/maistro-core/tests/tools/test_governed_contracts.py packages/maistro-core/tests/agents/test_tool_schema_boundary.py packages/maistro-core/tests/agents/test_base.py packages/maistro-core/tests/agents/test_factory.py packages/maistro-core/tests/agents/spec/test_agent_spec.py packages/maistro-core/tests/agents/strategies/test_react.py packages/maistro-core/tests/agents/strategies/test_builders_learning.py packages/maistro-core/tests/agents/artificer/test_strategy.py packages/maistro-core/tests/capabilities/test_effect_context_policy.py packages/maistro-core/tests/security/sentinel/test_audit.py -x -q
uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py packages/hive-conductor/backend/tests/test_legacy_dag_node.py packages/hive-conductor/backend/tests/test_agent_model_tools.py packages/hive-conductor/backend/tests/test_maistro_core_adapter.py -x -q
uv run pytest packages/maistro-bootstrap/tests -x -q
uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q
```

Other commands: `uv sync --locked --extra dev`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run python` with each of:

```text
scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
scripts/check_direct_effects.py
scripts/check-model-egress.py
scripts/check-security-inventory.py
scripts/check-convergence-matrix.py
scripts/check-suite-inventory.py
scripts/check-shipped-surface-truth.py
scripts/check-ratchet-provenance.py
```

## Handoff

**BLOCKED**, not integration approval. Only this evidence note changes; no production, test, inventory-count, ledger or grant edits. Fresh checks do not reproduce the reported SECURITY.md drift or vulture failure; speculative source cleanup or ledger banking would not repair actual evidence. No red/green claim is made for this evidence-only round.

No driver check logs were supplied. Remote exact-head CI remains **UNVERIFIED**, and external prerequisite closure is outside this writer's authority. Remaining risks are the explicitly UNVERIFIED acceptance guarantees above. Progress: checked 1 issue, done 1 focused-validation item, skipped 0 issues, failed validation commands 0, issue completion 0. Next: owner sequencing/proof of #55/#847 and remaining production/backend guarantees. Commit this note locally; no push or GitHub mutation.


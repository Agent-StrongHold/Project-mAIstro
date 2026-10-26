# Issue #57 repair — frozen scope

- Worktree: `/home/dev/Git/wt/auto-57`; starting HEAD `22eebbbfdbfcb977c6dedd6793ec8a3756516bf6`; base `b9cd15c608b5cc23ce785b3c80813d7e4d8f678b`.
- Only item: issue #57, from job `85f6efb1f06c4e39a56181eaae749766/dispatch-context.json`. No GitHub mutations or refreshed scope.
- Initial tree clean; no incoming work to salvage.
- Assigned writer repair: inspect instructions/ADRs and existing execution/tests; correct evidenced SECURITY.md drift; execute exact vulture gate and repair only actual findings (ledger exception applies); run focused acceptance and formatting/lint gates; commit locally.
- Ambiguity: prompt combines verifier no-edit instructions with explicit writer repair/commit assignment. Proceed as writer, retaining external blockers in final report.
- Supplied job directory has no `check-*.log` files at initial inspection; driver evidence unavailable here. Will execute relevant checks locally.
- External acceptance: #847 reportedly open in frozen snapshot; cannot close here. No inference that pending remote CI is green.

## Progress
- Snapshot recorded; repository instructions read; starting ref confirmed.
- Exact vulture command PASS: 1310 findings / 1314 reviewed identities; 0 unclassified / never_allowlist. No unbanked identity or ledger amendment justified.
- SECURITY.md:35 already documents registry construction via tools/contracts.py and distinguishes it from unresolved Sentinel approval gating (#346). Supplied drift finding is not reproduced; no cosmetic repair warranted.
- Prior result read (BLOCKED); historical checks are not adopted as fresh evidence. Frozen issue #847 is open, so acceptance 12 is unmet. Starting diff already includes earlier repairs to documentation and legacy classification.
- `uv sync --locked --extra dev` PASS; focused core pytest run PASS (336 tests, 2.68s). Includes binding/policy/allowlist/schema refusals, positive controls, nested argument mutation and SQLite close/reopen mismatch recovery.
- Read accepted ADR-004, ADR-050 and ADR-081226-6b46; contracts/Hive composition and core adversarial tests. Tool exposure is not authority and reversibility classification is distinct from approval. Preserve canonical execution and Invocation ownership.
- Attempted read `docs/adr/ADR-068-authorization-and-elevation.md`: not found; skipped. Resolved actual filename with find: `ADR-068-unified-authorization-and-elevation.md`; no validation command failed.
- Fresh Hive focused suite PASS: 112 tests (18.57s). Bootstrap package suite PASS: 255 tests / 7 skipped (16.90s). Architecture audit regression tests PASS: 74 tests (12.52s). Total fresh test evidence: 777 passed / 7 skipped, not live backend parity proof.
- Production review: GovernedToolExecutor re-resolves canonical Binding and invokes the existing lifecycle; Hive obtains identity from persisted Run/NodeRun/Attempt. Legacy tool admission reads the same registry before Invocation and materialized arguments are validated in tool adapters. ExpectedEffectEvidence stores exact arguments and pre-state digest, not retrievable original pre-state; live production retrieval/recomputation remains UNVERIFIED.
- Read accepted ADR-068 at resolved path. Reconciliation: host-owned classification narrows the existing effect boundary, not a replacement for Sentinel authorization or approval. No competing Goal store, scheduler, execution authority, event authority, or authorization path introduced.
- Fresh `ruff check .` and `ruff format --check .` PASS (3472 files formatted).
- Fresh gates PASS: direct-effects (51 sites, 4 TOOL_EFFECT), model-egress (20 callers; 12 explicitly banked reachable escapes awaiting #56), security-inventory (prose explicitly not fully checked), convergence-matrix (1455 modules), suite-inventory (21 suites / 33776 unique identities / zero duplicates). Passing census/ratchets are not proof that all effects are governed.
- No production/test/ledger changes are supported by reproduced evidence. No new tests, hence no inventory-delta note is required. Only this checkpoint changes.

## Acceptance review

Evidence is from tests executed this round and inspected production wiring, not earlier verification claims. No live provider, container/microVM workload or PostgreSQL deployment was exercised.

| # | Acceptance criterion | Executed evidence and limits |
| --- | --- | --- |
| 1 | Consume #55 seam, no second executor | `contracts.py:358` invokes existing lifecycle; Hive boot/chat and legacy Invocation tests passed. Full #55 production cutover **UNVERIFIED**; model-egress still reports 12 banked escapes awaiting #56. |
| 2 | Canonical authorization plus required expected effects | Core persisted-prediction test and Hive canonical registry-tier/boot/chat tests passed. Shipped Hive contracts are internal/read-only; deployed high-impact/mutating tool behavior **UNVERIFIED**. |
| 3 | Effective authorized tools before provider | Core Agent/ReAct/artificer/custom-strategy and Hive unlisted-tool denials passed with backend-not-called assertions and positive controls; BuildersLearning no-effect tests passed. Universal Principal/Workspace/Goal/Run effective-envelope coverage **UNVERIFIED**. |
| 4 | Missing/unknown schema fail closed | Core unknown-schema, unsupported root/nested types, custom-strategy schema forgery, Sentinel repaired-input tests and Hive materialized-argument denial tests passed. |
| 5 | Constrained structured command contract across backends | Bootstrap suite 255 passed / 7 skipped, including argv dispatch and raw command/metacharacter refusal. Live backend parity **UNVERIFIED**; skips are not acceptance evidence. |
| 6 | Host-owned reversibility | `contracts.py:102` constructs registry; legacy admission `legacy_dag_node.py:409` resolves from same Hive host registry. Core policy-floor and Hive/legacy tier tests passed. Sentinel registry-based approval integration (#346) remains separately documented debt. |
| 7 | Recomputable exact evidence | SQLite close/reopen tests passed for Invocation/capability/provider, exact materialized arguments and digest, pre-state digest, expected/observed post-state and policy version. Production pre-state retention/retrieval and deployed restart **UNVERIFIED**; a digest alone is not retrieval evidence. |
| 8 | Durable correlated mismatch, never ordinary success | Core mismatch test and both SQLite append interruption/replay cases passed: immutable mismatch, exactly one correlated event, no provider redispatch, PredictionMismatch raised. Cross-process concurrency **UNVERIFIED**. |
| 9 | Missing required predictions detectable/policyable | High-impact registration refusal plus complete-contract positive control passed. |
| 10 | Seven historical TOOL_EFFECT entries controlled or retired | Current direct-effect inventory matches code (4 retained TOOL_EFFECT); legacy control and retired BuildersLearning tests passed. Full historical seven-site equivalence **UNVERIFIED**; census counts alone do not establish control equivalence. |
| 11 | Introduced raw/direct tool bypass rejected | 74 architecture regression tests passed, including intentionally introduced raw Hive and browser-client calls rejected by the audit. Finite AST coverage is not a universal bypass proof. |
| 12 | #847 closes first after adversarial verification | **UNMET**: frozen dispatch `repos/Agent-StrongHold/Project-mAIstro/issues/847` has `state=open`. Local adversarial tests do not establish full child acceptance or closure. No GitHub mutations permitted. |

Exact-head remote CI **UNVERIFIED**: no driver check-*.log files were present in this job directory; pending historical checks are not green. Tests intentionally mock provider backends; no live backend or deployment claim is made.

## Executed validation commands

All used the assigned worktree and long validation timeouts (600 seconds for vulture, 1200 seconds for remaining commands); all exited zero:

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

**BLOCKED**, not integration approval. No speculative source, cosmetic documentation, ledger, or grant edits. The stale SECURITY.md/vulture repair requests are not reproducible at the assigned starting head. This committed checkpoint preserves fresh acceptance evidence and its explicit limits.

Progress: checked 1 assigned issue; done 1 focused-validation item; skipped 0 issues; failed validation commands 0; issue completion 0. One unsuccessful filename read was resolved before continuing. Next: authorized owner must sequence #847 and establish the remaining production/backend/control-equivalence guarantees above. No push, PR/issue mutation, ref deletion or destructive Git command performed. Finalize with local commit and clean-status confirmation.

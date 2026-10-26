# Issue #57 repair — frozen scope

- Worktree: /home/dev/Git/wt/auto-57; branch auto-57.
- Starting HEAD: 0d13596e71eb8f2327821066ed02edbf39867f73; base b9cd15c608b5cc23ce785b3c80813d7e4d8f678b. Initial worktree clean.
- Process only issue #57 from supplied dispatch-context.json (no GitHub refresh).
- Fixed repair targets: SECURITY.md claim/behavior drift if still present; actual findings from the mandated exact-argument vulture gate, with quality/vulture-baseline.json amendments permitted only for reviewed retained identities; focused validation and inventory notes only if tests change.
- Read-only acceptance evidence: existing issue #57 implementation and adjacent tests, relevant ADRs, supplied prior result; prerequisite #847 and #55 state from frozen dispatch only. No external mutations.
- Driver check logs: initial job directory listing contains no check-*.log files. Prior result records BLOCKED, not green.
- Assumption: writer role applies (explicit repair assignment and commit requirement); issue closure and exact-head CI cannot be fabricated by local edits.

## Progress

- Snapshot recorded before implementation; no incoming uncommitted work.
- Exact vulture gate executed: PASS, 1310 findings, 1314 reviewed identities, zero unclassified/never_allowlist (`/tmp/auto-57-vulture.log`). No unbanked identities; no ledger change justified.
- SECURITY.md:35 already describes ReversibilityRegistry construction and separately identifies unresolved Sentinel approval integration (#346). Reported stale prose finding is not reproduced.
- Frozen dispatch lists #55 and #847 open. Criterion 12 cannot be met by this worker; no closure actions permitted.
- Prior result/checkpoint read as historical evidence only; its passing test claims will be rerun, not inherited.
- No actual repair target found so far. Continue focused validation, not speculative source or ledger edits.
- Read accepted ADR-004 (including amendment removing unused declaration fields), ADR-050, ADR-068, ADR-081226-6b46 and production contracts/Hive composition plus adjacent adversarial tests. Reconciliation: tool exposure and reversibility narrow the existing Binding/Invocation seam; they do not independently authorize effects or own execution lifecycle. Sentinel approval integration remains explicit separate debt.
- `uv sync --locked --extra dev`: PASS (260 resolved, 218 checked).
- Fresh test runs PASS: core 336; Hive 112; bootstrap 255 / 7 skipped; raw-path architecture regression tests 74. Total 777 passed / 7 skipped, logs `/tmp/auto-57-{core,hive,bootstrap,architecture}.log`. Skips are not evidence of backend parity.
- No source/test/ledger edits warranted by reproduced findings. No added tests means no inventory delta required.
- `uv run ruff check .` and `uv run ruff format --check .`: PASS (3472 formatted files).
- Fresh gates PASS: direct-effects, model-egress, security-inventory, convergence-matrix, suite-inventory, shipped-surface-truth, ratchet-provenance (`/tmp/auto-57-gates.log`). Current census: 51 sites / 4 TOOL_EFFECT. Model-egress explicitly retains 12 reachable escapes; this is not completed #55/#56 migration evidence. Inventory: 21 suites, 33776 unique test identities, no duplicates. Ratchet checker uses locally selected base afffa63094e9; these are local default gate results, not exact-head remote CI certification. Existing nonfatal SyntaxWarnings occurred during provenance checking.

## Acceptance review

All test evidence below was executed this round, not adopted from prior claims. Production paths were inspected; no live external provider or PostgreSQL deployment was exercised.

| # | Criterion | Evidence and residual limit |
| --- | --- | --- |
| 1 | Consume #55 canonical seam, no competing executor | `contracts.py` calls the existing `effects.invocations.invoke`; Hive production composition resolves persisted Run/NodeRun/Attempt. Hive suite 112 passed, including boot/chat Invocation assertions. Full #55 prerequisite **UNVERIFIED**: frozen issue open, banked model escapes remain. |
| 2 | Authorization plus policy-required predictions | Core canonical Invocation/persisted expected-evidence test passed; Hive registry-tier and boot/chat tests passed. Deployed high-impact/mutating behavior **UNVERIFIED**: shipped Hive registry exposes internal/read-only tools. |
| 3 | Effective authorized set before provider execution | Fresh core Agent/ReAct/artificer/custom-strategy denial tests and Hive unlisted-tool tests passed with backend-not-called assertions and positive controls. Universal principal/Workspace/Goal/Run envelope across all providers **UNVERIFIED**. |
| 4 | Missing/unknown schemas fail closed | Core unknown/missing schema, unsupported root/nested type, custom-strategy schema forgery and repaired-argument tests passed. Legacy materialized-argument tests passed. |
| 5 | Consistent constrained command arguments | Bootstrap 255 passed / 7 skipped, including structured argv dispatch and raw command/injection refusal. `agent_loop.py:414` dispatches run_command through `run_argv`. Live backend parity **UNVERIFIED**, and skipped tests are not proof. |
| 6 | Host-owned reversibility | `contracts.py:101` constructs registry; legacy admission `legacy_dag_node.py:409` reads same host registry. Fresh core policy-floor and Hive/legacy tier tests passed. Sentinel reversibility-based approval integration (#346) remains explicit debt, not claimed complete. |
| 7 | Recomputable exact argument/pre-state/effect evidence | SQLite reopen tests passed for Invocation/capability/provider, exact arguments and digest, pre-state digest, expected/observed state and policy version. `ExpectedEffectEvidence` stores a digest, not retrievable original pre-state. Production pre-state retention/retrieval and deployed restart **UNVERIFIED**. |
| 8 | Durable correlated mismatch cannot become success | Both append interruption modes passed after real SQLite close/reopen and repeated replay, asserting one event/provider call and immutable mismatch. Host comparison raises PredictionMismatch. Cross-process concurrent observation **UNVERIFIED**. |
| 9 | Missing required high-impact prediction policy | Registration-refusal test and complete-contract positive control passed. |
| 10 | Seven historical TOOL_EFFECT sites controlled/retired | Current census gate passed (51 sites / 4 TOOL_EFFECT), legacy and retired BuildersLearning tests passed. Full historical seven-site behavioral/control equivalence **UNVERIFIED**: census counts alone do not prove it. |
| 11 | Introduced raw/direct tool path rejected | Architecture regression suite 74 passed, including intentional raw Hive and browser paths rejected by audit (`tests/test_check_direct_effects.py:496,519`). Finite syntax coverage is not universal bypass proof. |
| 12 | #847 closes first from adversarial verification | **UNMET**: frozen dispatch `repos/Agent-StrongHold/Project-mAIstro/issues/847` says `state=open`. Local adversarial tests do not substitute for complete child verification/closure. No GitHub mutation allowed. |

Exact-head remote CI **UNVERIFIED**: no driver check-*.log files supplied. Prior queued/pending checks are not passing evidence. Historical checkpoint prose in `docs/implementation/issue-57-repair-round.md` is not adopted as current behavior: its legacy registry gap predates the current fixed production code.

## Executed validation commands

All ran in assigned worktree, with 1200-second validation timeouts:

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
uv run python scripts/check-shipped-surface-truth.py
uv run python scripts/check-ratchet-provenance.py
```

All exited zero. Supporting read-only commands inspected HEAD/status/diff, repository instructions, accepted ADRs, production code, adjacent tests, frozen dispatch and prior result. No remote fetch, GitHub mutation, ledger/grant edit, service startup, full-tree pytest or destructive Git command was performed.

## Handoff

**BLOCKED**, not integration approval. Only this checkpoint changes; the stale SECURITY.md/vulture findings do not reproduce, so another cosmetic or ledger repair is not justified. No test addition, hence no inventory delta.

Progress: checked 1 issue; done 1 focused-validation item; skipped 0 issues; failed validation commands 0; issue completion 0. Next: authorized owner must sequence/prove #55 and #847 and supply the explicitly unverified production/backend/evidence guarantees above. Re-dispatching unchanged stale findings cannot satisfy the external stop condition.

Finalization: run diff whitespace check, commit this checkpoint locally, and verify clean status; no push.

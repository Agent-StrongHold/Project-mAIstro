# Issue #57 repair — c7e5bd38

## Frozen scope
- Only issue #57, branch `auto-57`, worktree `/home/dev/Git/wt/auto-57`.
- Starting head `ec383d1a187269ed603cc4cd357a81d9d2448e75`; base `652cf8e56f382e2b6f6344292ef9d14f6fb78e2c`.
- Evidence snapshot: `/home/dev/maistro/jobs/c7e5bd385464488a95c8debae9b403b5/dispatch-context.json`; prior result `d41cc5eacda34916b05b842dd0efe2d0/result.json`.
- Initial worktree clean. No driver `check-*.log` files supplied in the job directory.
- Process only the assigned vulture exact-debt-ledger repair and actual acceptance evidence for existing #57 behavior; no GitHub mutations or new work items.
- Planned files: this checkpoint; `quality/vulture-baseline.json` only if the exact scan demonstrates missing retained identities; existing #57 production/test files only if validation demonstrates a concrete defect. Any added tests require inventory notes.

## Initial evidence / assumptions
- Prior result is BLOCKED and reports #847 open, absent remote CI evidence, six live-container skips, and model-egress escapes owned by #56. These are claims to recheck, not assumed passes.
- SECURITY.md drift was reportedly already repaired. Inspect current file before deciding any repair.
- Writer role selected because assignment explicitly requests repair and local commit.

## Validation
- `uv sync --locked --extra dev` PASS (218 installed packages checked).
- Exact requested vulture command PASS: 1299 findings, 1303 reviewed base identities, zero unclassified/unbanked identities (`repair-vulture.log`). No ledger amendment warranted.
- Frozen dispatch confirms #55 and #847 remain open; #57 acceptance criterion 12 explicitly requires #847 closure. Cannot resolve external closure by code or forbidden GitHub mutation.
- SECURITY.md:35 already states registry construction and correctly separates it from Sentinel reversibility-based approval gating. Prior drift claim does not reproduce.
- Reviewed repository AGENTS.md, docs/README.md, accepted ADR-081226-6b46, ADR-004 amendment, and ADR-073. Inspected host contracts, Hive production wiring, bootstrap command exposure, and adjacent adversarial tests. GovernedToolExecutor delegates to existing `effects.invocations.invoke`, not a separate execution authority.
- `uv run ruff check .` PASS; `uv run ruff format --check .` PASS (3482 files).
- Core tools/capabilities + adjacent Agent/schema/spec/ReAct/BuildersLearning/Artificer/audit tests: **1643 passed, 12 skipped**, one unawaited `_FakeProc.communicate` warning (`repair-core.log`).
- Hive governed tool/legacy/Agent model/adapter tests: **112 passed** (`repair-hive.log`).
- Bootstrap package: **255 passed, 7 skipped** (`repair-bootstrap.log`); one Windows-only test and six live Docker/builders-image tests skipped. Live container parity remains UNVERIFIED.
- Architecture-gate adversarial tests: **74 passed** (`repair-adversarial-gates.log`), including introduced raw Hive dispatcher and BrowserClient bypass rejection.
- Direct-effect gate PASS: 51 sites, four TOOL_EFFECT entries; inventory matches source (`repair-check_direct_effects.log`). Census/disposition success is not proof of complete historical seven-site authorization equivalence.
- Model-egress debt gate PASS but explicitly reports **12 reachable escapes awaiting #56 migration** (`repair-check-model-egress.log`); not proof of complete #55 cutover.
- Security inventory PASS (62 cited paths, 23 rows, two counts; not all prose verified); convergence PASS (1457 production modules, 152 attributed unreachable); suite inventory PASS (21 suites, 34055 unique test identities).
- Seven-package `uv run mypy` command from AGENTS.md PASS (934 source files).
- Attempted ADR-050 filename was not found; resolved with one local glob to `docs/adr/ADR-050-tool-reversibility-taxonomy.md` and read the actual accepted ADR. Reconcile its historical convergence prose via canonical front matter and Invocation ADR: classification belongs on Binding -> Invocation; do not assert registry classification proves reversibility-driven approval gating.
- No concrete source/test/ledger failure reproduced; no cosmetic repair or invented ledger debt. No new/changed tests, so no inventory delta note required.

## Acceptance review (all twelve frozen #57 criteria)
1. **Consume #55, no second executor:** inspected `tools/contracts.py:358` calling existing `effects.invocations.invoke` and Hive `governed_tools.py:263` composing over `container.capability_effects`. Passing boot/chat/legacy tests exercise that production wiring. Complete #55 cutover **UNVERIFIED**: debt gate still reports reachable #56 escapes.
2. **Canonical authorization and expected effects:** passing `test_governed_tool_persists_expected_evidence_on_canonical_invocation` asserts actual stored prediction and policy/completion events; Hive production wiring test asserts canonical Invocation with registry tier. Universal deployed coverage **UNVERIFIED**; high-impact example uses a test contract, not a shipped Hive mutating tool.
3. **Effective allowlist before provider:** passing custom-strategy/schema/Agent/ReAct/BuildersLearning tests assert no raw backend call for unknown/unlisted names. `agents/base.py:901` checks Agent identity, then Sentinel; retired BuildersLearning side calls have no effects. Full principal/Workspace/Goal/Run envelope equivalence on every retained path **UNVERIFIED**.
4. **Missing/unknown schema fail closed:** passing core allowlist/schema tests and `test_tool_schema_boundary.py:87,104` assert typed/shared refusal or Agent error before backend effects; unsupported root/nested schema types are also tested.
5. **Constrained command contract:** bootstrap command exposure requires argv, rejects raw cmd and shell-metacharacter tokens; complete bootstrap suite passes applicable argv/hardening tests. Live container parity **UNVERIFIED** (six integration skips); no claim of cross-backend equivalence from fake dispatch alone.
6. **Host-owned reversibility:** passing Hive registry-tier/legacy host-reclassification tests and inspection of `contracts.py:335` prove exercised calls resolve from host registry, not caller labels. Does not establish missing Sentinel tier-driven approval gating (#346).
7. **Recomputable exact prediction records:** passing SQLite reopen tests assert Invocation/capability/provider identity, exact arguments + digest, pre-state digest, expected and observed state, policy version, evidence digest. `expected_effect.py` and `invocation.py:519` implement the canonical binding. Live PostgreSQL restart and all deployed mutating coverage **UNVERIFIED**.
8. **Durable mismatch, not ordinary success:** passing mismatch/reopen tests assert first observation immutable, correlated durable event, no redispatch, replay raises PredictionMismatch, and one event after lost append/ack. `invocation.py:953` settles through existing store; `contracts.py:384` repairs append on replay. Cross-process races **UNVERIFIED**; crash recovery requires replay.
9. **Missing high-impact prediction policyable:** passing incomplete-contract test raises ExpectedEffectRequired before dispatch and includes complete-contract positive control; `ToolContract.__post_init__` enforces configuration.
10. **Historical seven TOOL_EFFECT entries:** current direct-effect inventory gate passes with four TOOL_EFFECT backend sites; passing Hive boot/chat/legacy tests exercise wrapping and refusal without identity. Complete historical seven-site equivalence **UNVERIFIED**; census is not authorization proof.
11. **Introduce raw path and reject:** `tests/test_check_direct_effects.py:496,519` assert NEW audit failures for raw Hive and BrowserClient paths; freshly passed in 74-test adversarial gate suite.
12. **#847 closes first:** **UNMET**. Frozen dispatch source for `/issues/847` records open. Branch tests cannot substitute for prerequisite closure or full independent adversarial #847 verification. No GitHub mutation allowed.

## Commands and outcomes
Executed in this worktree with 1000–1200 second command timeouts. Logs are in `/home/dev/maistro/jobs/c7e5bd385464488a95c8debae9b403b5`.

- `uv sync --locked --extra dev` — PASS.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS.
- `uv run ruff check .`; `uv run ruff format --check .` — PASS.
- `uv run pytest packages/maistro-core/tests/tools packages/maistro-core/tests/capabilities packages/maistro-core/tests/agents/test_base.py packages/maistro-core/tests/agents/test_factory.py packages/maistro-core/tests/agents/test_tool_schema_boundary.py packages/maistro-core/tests/agents/spec packages/maistro-core/tests/agents/strategies/test_react.py packages/maistro-core/tests/agents/strategies/test_builders_learning.py packages/maistro-core/tests/agents/artificer/test_strategy.py packages/maistro-core/tests/security/sentinel/test_audit.py -x -q` — 1643 passed, 12 skipped.
- `uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py packages/hive-conductor/backend/tests/test_legacy_dag_node.py packages/hive-conductor/backend/tests/test_agent_model_tools.py packages/hive-conductor/backend/tests/test_maistro_core_adapter.py -x -q` — 112 passed.
- `uv run pytest packages/maistro-bootstrap/tests -x -q -rs` — 255 passed, 7 skipped.
- `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q` — 74 passed.
- `uv run python scripts/check_direct_effects.py` — PASS.
- `uv run python scripts/check-model-egress.py` — PASS debt ratchet only, 12 reachable escapes.
- `uv run python scripts/check-security-inventory.py` — PASS.
- `uv run python scripts/check-convergence-matrix.py` — PASS.
- `uv run python scripts/check-suite-inventory.py` — PASS.
- `uv run mypy packages/maistro-core/src packages/maistro-server/src packages/maistro-turing/src packages/maistro-canvas/src packages/maistro-bootstrap/src packages/maistro-registry/src packages/maistro-ext-sdk/src` — PASS.
- `git diff --check` — PASS before final notes; recheck before commit.

## Handoff
Changed file: only this durable checkpoint. Source, tests, ledgers, grants and prior work are preserved. No concrete repair warranted by current failures; exact vulture gate and prior SECURITY.md finding already pass. Remote exact-head CI **UNVERIFIED**: no driver check logs supplied; frozen linked-PR checks name older heads, not this starting/final head.

Progress: checked 1 assigned issue; done 1 focused validation handoff; skipped 0 issues; failed validation commands 0 (one nonexistent documentation path resolved). Verdict **BLOCKED** due to unmet #847 prerequisite and explicit production/backend/historical evidence gaps. Next: owner/verifier supplies prerequisite and missing production evidence. Local commit is handoff only, not integration approval. Never push, close issues, or weaken gates to manufacture readiness.



# Issue #57 repair — ae30317b

## Frozen scope

- Worktree `/home/dev/Git/wt/auto-57`, branch `auto-57`.
- Starting HEAD `68b037ae3e08c836e79ce1b29eabf52c6d3b86ef`; base `652cf8e56f382e2b6f6344292ef9d14f6fb78e2c`.
- Only issue #57 from supplied dispatch-context.json; do not re-fetch or expand the issue/PR snapshot.
- Inspect existing governed-tool implementation, adjacent tests, applicable ADRs, SECURITY.md reported drift, exact vulture debt ledger and relevant workflow checks. Edit only evidence-backed defects, permitted vulture ledger reconciliation, and this record (inventory note if tests change).
- Initial worktree clean; no incoming edits to salvage.
- Prior result read: BLOCKED, #847 open, six live-container tests skipped, model-egress migration incomplete. These are claims to revalidate, not acceptance evidence.
- Driver job directory contains no `check-*.log` files at start. Remote CI remains UNVERIFIED; no GitHub mutation or issue closure allowed.

## Assumptions / boundaries

Writer role applies (explicit assigned repair and mandatory local commit). Preserve Goal -> Graph -> Run -> NodeRun -> Attempt and existing Invocation authority. External prerequisite #847 cannot be closed here; record it rather than scope-creeping. No develop sync conflict exists in the starting worktree.

## Results

- `uv sync --locked --extra dev` PASS (218 packages checked).
- Exact requested vulture command PASS: 1299 findings, 1303 reviewed base identities, zero unclassified/unbanked identities. `repair-vulture.log` in the job directory. No ledger amendment is justified.
- Current SECURITY.md:35 already describes registry construction and distinguishes classification from Sentinel approval gating. The stale reported claim does not reproduce; do not make a cosmetic edit.
- Frozen dispatch #57 has twelve acceptance bullets. #55 and #847 remain open in this snapshot. Criterion 12 explicitly requires #847 closure; cannot satisfy it with branch changes or forbidden GitHub mutation.
- Read AGENTS.md, docs/README.md, accepted ADR-081226-6b46, ADR-050, ADR-004 amendment and ADR-073. Reconciliation: tool exposure is not authority; retain canonical Binding -> Invocation. ADR-050 historical convergence prose is not an implementation claim; current front matter is Accepted, not Implemented. Registry classification alone does not prove Sentinel reversibility-based approval gating.
- Inspected `tools/contracts.py`, `capabilities/expected_effect.py`, Hive `services/governed_tools.py`, bootstrap `builders/agent_loop.py`, and core adversarial contract tests. Executor delegates to existing `effects.invocations.invoke`; Hive derives persisted execution identity and intersects allowlists with host registry.
- Focused core tools/capabilities/Agent/spec/schema/strategy/audit command PASS: **1643 passed, 12 skipped**, one unawaited fake-process warning (`repair-core.log`). Skips: four missing Playwright, one real-pool test and seven PostgreSQL contention cases without DSNs. SQLite reopen tests actually execute; these skips are not PostgreSQL evidence.
- Hive governed-tools/legacy DAG/Agent model/adapter tests PASS: **112 passed** (`repair-hive.log`).
- Complete bootstrap package PASS: **255 passed, 7 skipped** (`repair-bootstrap.log`): one Windows-specific case, six Docker/builders-image cases unavailable. Live backend parity remains UNVERIFIED.
- `uv run ruff check .` PASS; `uv run ruff format --check .` PASS (3482 files).
- Architecture gate adversarial tests PASS: **74 passed** (`repair-adversarial-gates.log`).
- `check_direct_effects.py` PASS: 51 sites, four TOOL_EFFECT backend sites. Census/disposition match is not complete historical seven-site authorization-equivalence proof.
- `check-model-egress.py` PASS as a debt gate, explicitly reports **12 reachable escapes awaiting #56 migration**. Do not infer complete #55 cutover.
- `check-security-inventory.py` PASS (62 cited paths, 23 rows, two counts; not all prose checked); `check-convergence-matrix.py` PASS (1457 modules, 152 attributed unreachable); `check-suite-inventory.py` PASS (21 suites, 34055 unique test identities).
- Inspected production Agent allowlist/schema/Sentinel ordering and denial audit, canonical observation/event persistence, Hive real-SQLite Container tests, command-contract tests and intentional raw-tool architecture-gate regressions. Tests assert no backend calls for refusals and actual Invocation persistence; raw gate tests assert NEW audit failures.
- Seven-package mypy command PASS: **934 source files** (`repair-mypy.log`). `git diff --check` PASS.
- No source/test/ledger failure reproduced. No new tests or changed collection counts, so no inventory note/delta required.

## Acceptance (twelve frozen criteria)

1. **Consume #55, no second executor:** inspected `tools/contracts.py:358` delegating to existing `effects.invocations.invoke` and Hive composing over `container.capability_effects`. Fresh core and Hive wiring tests pass. Complete #55 production cutover **UNVERIFIED**: frozen #55 open; current egress gate still reports 12 reachable #56 escapes.
2. **Canonical authorization + required expected effects:** passing `test_governed_tool_persists_expected_evidence_on_canonical_invocation` checks stored prediction and policy/completion events; passing Hive real-Container tests check production tool Invocation persistence. Universal deployed coverage **UNVERIFIED**; the high-impact ticket contract is a test example, not a shipped mutating Hive tool.
3. **Effective allowlist before provider:** fresh custom-strategy/Agent/ReAct/BuildersLearning tests and Hive tests assert unknown/unlisted calls never reach backend. `agents/base.py:901` checks identity then Sentinel; BuildersLearning's formerly unused shell/GitHub effects are retired. Full principal/Workspace/Goal/Run envelope equivalence across every retained path **UNVERIFIED**.
4. **Missing/unknown schema fail closed:** fresh `test_agent_allowlist_and_unknown_schema_fail_before_backend`, custom-strategy/schema tests and unsupported nested/root schema-type tests pass. Assertions check actual no-backend dispatch, not just a string denial.
5. **Constrained command contract:** fresh bootstrap tests pass structured argv exposure, raw cmd refusal, injection token rejection and backend hardening cases. Six live Docker/builders-image tests skip; supported live-backend parity **UNVERIFIED**.
6. **Host-owned reversibility:** fresh Hive registry-tier and legacy host-reclassification tests pass; inspected host registry resolution in `contracts.py:335` and `legacy_dag_node.py:409`. Caller labels do not supply the tier in exercised production paths. This does not prove Sentinel reversibility-driven approval gating (#346).
7. **Recomputable exact prediction:** fresh SQLite reopen tests check Invocation/capability/provider identity, materialized arguments and digest, pre-state digest, expected and observed states, policy version and evidence digest. Caller-mutation tests use synchronized real admission awaits. PostgreSQL restart and deployed high-impact coverage **UNVERIFIED**.
8. **Durable mismatch, not ordinary success:** fresh mismatch/reopen/lost-append-ack tests prove immutable first observation, correlated durable event, replay raises PredictionMismatch, no redispatch and no duplicate event. `invocation.py:953` uses the existing store; `contracts.py:384` repairs append on replay. Cross-process races **UNVERIFIED**; recovery requires replay.
9. **Missing high-impact predictions policyable:** fresh incomplete-contract refusal test raises ExpectedEffectRequired before execution and includes complete-contract positive control. Registration enforces the prediction contract.
10. **Seven historical TOOL_EFFECT sites:** current gate PASS (four retained backend TOOL_EFFECT sites); fresh Hive boot/chat/legacy tests pass same-seam wiring and missing-identity refusal. Complete historical seven-site control/equivalence mapping **UNVERIFIED**; inventory/disposition success alone is insufficient.
11. **Intentionally introduce raw path; reject:** freshly passed `tests/test_check_direct_effects.py:496,519` introduces raw Hive and BrowserClient paths and asserts NEW audit failures in the 74-test architecture suite.
12. **#847 closure first:** **UNMET**. Frozen `dispatch-context.json:73694` issue #847 object explicitly records state=open. Branch tests cannot close the prerequisite or substitute for independent full #847 adversarial verification. No GitHub mutation allowed.

## Commands executed

All validation commands used 1200-second tool timeouts; full outputs are `repair-*.log` in `/home/dev/maistro/jobs/ae30317bc820454f81e0f5c55a149c4d/`.

- `uv sync --locked --extra dev` — PASS.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS.
- `uv run ruff check .`; `uv run ruff format --check .` — PASS.
- `uv run pytest packages/maistro-core/tests/tools packages/maistro-core/tests/capabilities packages/maistro-core/tests/agents/test_base.py packages/maistro-core/tests/agents/test_factory.py packages/maistro-core/tests/agents/test_tool_schema_boundary.py packages/maistro-core/tests/agents/spec packages/maistro-core/tests/agents/strategies/test_react.py packages/maistro-core/tests/agents/strategies/test_builders_learning.py packages/maistro-core/tests/agents/artificer/test_strategy.py packages/maistro-core/tests/security/sentinel/test_audit.py -x -q -rs` — 1643 passed, 12 skipped.
- `uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py packages/hive-conductor/backend/tests/test_legacy_dag_node.py packages/hive-conductor/backend/tests/test_agent_model_tools.py packages/hive-conductor/backend/tests/test_maistro_core_adapter.py -x -q -rs` — 112 passed.
- `uv run pytest packages/maistro-bootstrap/tests -x -q -rs` — 255 passed, 7 skipped.
- `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q` — 74 passed.
- `uv run python scripts/check_direct_effects.py` — PASS.
- `uv run python scripts/check-model-egress.py` — PASS debt ratchet, not complete convergence.
- `uv run python scripts/check-security-inventory.py` — PASS.
- `uv run python scripts/check-convergence-matrix.py` — PASS.
- `uv run python scripts/check-suite-inventory.py` — PASS.
- `uv run mypy packages/maistro-core/src packages/maistro-server/src packages/maistro-turing/src packages/maistro-canvas/src packages/maistro-bootstrap/src packages/maistro-registry/src packages/maistro-ext-sdk/src` — PASS.
- `git diff --check` — PASS.

## Handoff

Only changed file: `.cursor/context/repair-57-ae30317b.md` (this validation checkpoint). Existing source, tests, ledgers, grants and prior work preserved. No actual failure warrants a source/ledger repair; the named Vulture and SECURITY.md findings do not reproduce at assigned HEAD.

Verdict **BLOCKED**, not integration approval: #847 prerequisite remains open; other coverage limitations are explicitly marked above. Exact-head remote CI **UNVERIFIED** because no driver check logs were supplied. No push, PR, issue closure, merge, grant edits or gate weakening performed.

Progress: {checked: 1, done: 1 focused validation handoff, skipped: 0 issues, errors: 0 validation commands, next: prerequisite owner/verifier must supply #847 closure and missing production/backend evidence}. Finish with local checkpoint commit and clean worktree; do not restart another repair cycle or invent a code change to manufacture progress.

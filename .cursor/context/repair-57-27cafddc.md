# Issue #57 — repair job 27cafddc

## Frozen scope
- Item: issue #57 only; assigned worktree `/home/dev/Git/wt/auto-57`, branch `auto-57`.
- Starting HEAD verified: `305b0290b17f6a7b34a7b39a88f426f570f1ae12`; clean worktree. Supplied develop base: `fe733ae4ee27d33f0b0f2912f5cb4ee3b2243e21`.
- Evidence snapshot: `/home/dev/maistro/jobs/27cafddc914349448cb485b65e8f15f8/dispatch-context.json`; no remote enumeration or mutation.
- Process only supplied #57 acceptance criteria, prior SECURITY.md drift, and explicit exact-debt-ledger vulture repair. Inspect adjacent runtime/tests/ADRs before edits. Preserve existing branch changes.
- File scope: SECURITY.md; governed-tool runtime and adjacent tests for inspection/validation; quality/vulture-baseline.json only if exact scan supports amendment; this note; inventory note only if tests added.

## Initial results / assumptions
- `git status --short`: clean; HEAD matches dispatch.
- Job directory contains no `check-*.log` files at inspection; deterministic driver results unavailable rather than assumed passed.
- Large pre-existing branch diff includes unrelated historical changes; not reworking them in this focused round.
- Supplied prior #847 open-state and CI-pending findings are external constraints, not authorization to close issues or change gates. Will record acceptance as blocked/unverified if the frozen evidence still requires that.

## Progress
- Frozen primary issue reviewed: 12 acceptance criteria; prerequisite #847 is open in supplied snapshot. This cannot be resolved by local code or issue-closure actions in this lane.
- `uv sync --locked --extra dev`: PASS.
- Exact requested vulture scan: PASS, 1305 findings, 1309 reviewed identities, unclassified=0, never_allowlist=0 (`repair-vulture.log` in job directory). No evidence warrants ledger/source amendment.
- SECURITY.md:35 already describes registry construction and explicitly disclaims reversibility-based Sentinel approval gating; supplied stale-claim defect does not reproduce. contracts.py:101 confirms registry construction.
- Read prior result and checkpoint as historical evidence, not validation. They also report these two repair targets already satisfied.
- ADR-004 read including accepted #847 amendment removing unused declarations. Attempted ADR-050-execution-model.md path was not found; skipped that nonexistent path, resolved actual ADR filenames from local directory. No execution using unresolved ref/ID occurred.
- Read accepted ADR-050, ADR-051, ADR-081226-6b46, ADR-081426-1f7c and governed runtime/adjacent tests. Tool exposure is not authority or a lifecycle; the existing Invocation service owns effects. No competing execution authority added in this round; classification does not imply approval gating.
- Fresh focused core tests: 336 passed (`repair-core.log`). Fresh shipped Hive Agent/chat/legacy tests: 112 passed (`repair-hive.log`). Fresh bootstrap package suite: 255 passed, 7 skipped (`repair-bootstrap.log`); six Docker/image-unavailable and one Windows-only leg leave live backend parity UNVERIFIED.
- Expected-effect runtime binds exact arguments and pre-state digest; SQLite reopen test proves persisted comparison/replay/event identity. It does not demonstrate original deployed pre-state retrieval or universal production high-impact coverage (Hive registry currently has three internal tools).
- Scope remains one issue. No reproduced defect or failed scanner justifies production/test/ledger changes.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS (3474 files).
- Fresh capabilities/tools package subsets: 1279 passed, 12 skipped, 1 warning (`repair-capabilities-tools.log`). Eight skips need PostgreSQL DSNs; four need optional Playwright. Existing mocked Git failure test warns about unawaited `_FakeProc.communicate`. Counts overlap focused core suite, not a unique total.
- Fresh architecture gate tests: 74 passed (`repair-gate-tests.log`), including intentionally introduced raw tool/BrowserClient bypass detection.
- Fresh direct-effects, model-egress, security-inventory, convergence, suite-inventory checks: PASS. Inventory: 21 suites / 33910 unique identities. Current direct-effect census: 51 sites / four TOOL_EFFECTs. Model-egress explicitly retains 12 reachable escapes; non-expansion is not proof of completed #55/#56 cutover. Security-inventory explicitly does not validate all prose.
- No tests added or changed, so no inventory-delta note or baseline edit needed. No source/ledger change warranted for already-correct reported defects.
- Frozen prerequisite source located at dispatch-context.json:72772, #847 state=open at :72875. No remote check/issue refresh attempted. Exact-head CI remains UNVERIFIED (no driver check logs supplied).
- `git diff --check`: PASS; only this new checkpoint is changed.

## Acceptance review

| # | Criterion | Executed evidence / limit |
|---|---|---|
| 1 | Consume #55 governed Invocation seam, not second executor | Core/Hive integration tests pass; contracts.py:358 uses existing Invocation service. Complete #55 production cutover UNVERIFIED; model-egress ratchet passing with retained escapes cannot establish it. |
| 2 | Canonical authorization plus required expected effects | Core persisted-prediction test and Hive registry-tier/canonical-identity tests pass (336/112-test subsets). Deployed high-impact/mutating coverage UNVERIFIED; Hive exposes internal tools only. |
| 3 | Enforce effective Agent authorized set before dispatch | base.py:901 rejects undeclared calls; schema/Sentinel validation precedes shared callback. Fresh Agent/ReAct/artificer/BuildersLearning/Hive denial tests pass with no backend execution. Universal Principal/Workspace/Goal/Run envelope equivalence UNVERIFIED. |
| 4 | Missing/unknown schemas fail closed | Fresh missing-schema, unknown-name, unsupported-type, repaired/materialized argument and legacy argument denial tests pass. |
| 5 | Constrained structured commands across backends | Bootstrap argv-required/raw-text/metacharacter tests and package suite pass. Supported live backend parity UNVERIFIED: six Docker/image and one Windows leg skipped. |
| 6 | Host-owned reversibility policy | ToolContractRegistry constructs registry (contracts.py:101), Invocation request uses registry classification, Hive/legacy shared-registry tests pass. Not a claim of Sentinel approval-floor completion. |
| 7 | Recomputable exact prediction identities | SQLite reopen tests assert capability/provider, exact args/digest, pre-state digest, expected/observed state, Invocation id and policy version. Original production pre-state retrieval UNVERIFIED; runtime persists only digest (contracts.py:321). PostgreSQL integration legs skipped. |
| 8 | Durable correlated mismatch, no silent success | Fresh mismatch/reopen/append-interruption/lost-ack tests pass; one event, no redispatch, first verdict retained and PredictionMismatch raised. invocation.py:953 uses existing store; :976 builds existing EventStore envelope. Cross-process observation races UNVERIFIED. |
| 9 | Missing required high-impact predictions detectable | Fresh incomplete high-impact registration denial plus complete-contract positive control pass. |
| 10 | Seven historical TOOL_EFFECT entries controlled or retired | Fresh current census matches four TOOL_EFFECT sites; production and retirement tests pass. Full historical seven-site equivalence UNVERIFIED; matching current ledger alone is insufficient. |
| 11 | Architecture gate rejects introduced raw tool bypass | 74 fresh gate tests pass, including tests/test_check_direct_effects.py:496 and :519 deliberately introducing raw Hive/BrowserClient paths and asserting rejection. |
| 12 | #847 closes from adversarial tests before #57 | UNMET: frozen dispatch-context.json:72875 records prerequisite #847 open. Local partial tests do not establish complete child acceptance or authorize closure. |

## Commands executed

Validation used 1200-second timeouts; logs are in the supplied job directory. All validation commands below passed; skips/warning above remain explicit.

- `uv sync --locked --extra dev`
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (verified against vulture-ratchet.yml:82)
- `uv run pytest packages/maistro-core/tests/tools/test_governed_contracts.py packages/maistro-core/tests/agents/test_tool_schema_boundary.py packages/maistro-core/tests/agents/test_base.py packages/maistro-core/tests/agents/test_factory.py packages/maistro-core/tests/agents/spec/test_agent_spec.py packages/maistro-core/tests/agents/strategies/test_react.py packages/maistro-core/tests/agents/strategies/test_builders_learning.py packages/maistro-core/tests/agents/artificer/test_strategy.py packages/maistro-core/tests/capabilities/test_effect_context_policy.py packages/maistro-core/tests/security/sentinel/test_audit.py -x -q`
- `uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py packages/hive-conductor/backend/tests/test_legacy_dag_node.py packages/hive-conductor/backend/tests/test_agent_model_tools.py packages/hive-conductor/backend/tests/test_maistro_core_adapter.py -x -q`
- `uv run pytest packages/maistro-bootstrap/tests -x -q -rs`
- `uv run pytest packages/maistro-core/tests/capabilities packages/maistro-core/tests/tools -x -q -rs`
- `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run python scripts/check_direct_effects.py`
- `uv run python scripts/check-model-egress.py`
- `uv run python scripts/check-security-inventory.py`
- `uv run python scripts/check-convergence-matrix.py`
- `uv run python scripts/check-suite-inventory.py`
- `git diff --check`

## Handoff

**BLOCKED**, not integration approval. Supplied repair targets already pass at starting HEAD; making cosmetic source or ledger changes would not repair an evidenced failure. Only this checkpoint changed. No policy/gate grants, GitHub mutations, discarded work or test additions.

Residual risks: open external prerequisite; full M1 production cutover/effective scoped-envelope proof; deployed high-impact prediction coverage; original pre-state retrieval; cross-process observation races; historical seven-site equivalence; skipped live backend validation; exact-head remote CI unavailable. These are not silently treated as satisfied by passing bounded local tests.

Progress: checked=1 issue, focused validation done=1, issue completion=0, skipped=0 issues, failed validation commands=0; one nonexistent ADR read was recorded/skipped. Next: prerequisite/evidence owners must resolve #847/full acceptance; no new implementation item started. Finish by committing this evidence locally, never pushing.

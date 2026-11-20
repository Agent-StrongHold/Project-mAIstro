# Issue #57 repair — cfab916e

## Frozen scope
- Assigned worktree `/home/dev/Git/wt/auto-57`, branch `auto-57`.
- Starting HEAD e77bdc9b31e97a69f2b411174f06dfa96326ce34; supplied base fe733ae4ee27d33f0b0f2912f5cb4ee3b2243e21.
- Process only issue #57 and supplied dispatch/prior evidence. No remote enumeration or mutations.
- Initial tree clean; existing committed implementation preserved.
- Repair targets: reproduce exact vulture gate; reconcile SECURITY.md reversibility claim only if still stale; verify issue acceptance against production/tests. Existing dependency #847 is outside implementation ownership.
- Candidate files: this note, SECURITY.md (if evidence warrants), quality/vulture-baseline.json (explicit CI repair authorization only), and genuinely dead source identities reported by the exact gate. Tests/inventory only if behavior changes require them. No speculative changes.

## Initial evidence
- HEAD verified exactly matches assignment; no develop sync conflict present.
- Supplied job directory has no check-*.log files in initial listing. Do not infer driver checks passed.
- Supplied prior result exists; not yet reviewed.
- Ambiguity: prompt includes verifier and writer instructions; explicit assigned repair/writer commit requirement governs this round.

## Progress
- Exact vulture command executed successfully: 1305 findings / 1309 reviewed identities; zero unclassified and never_allowlist. No unbanked identity to fix or ledger amendment to justify.
- SECURITY.md:35 already states registry construction and host-owned classification, and distinguishes it from pending Sentinel approval integration. Supplied stale-doc finding does not reproduce; leave it intact.
- Prior result read, not adopted as proof. Frozen #57 has 12 acceptance criteria; frozen #847 remains open. Supplied job directory contains no check-*.log files.
- Read contracts, expected-effect representation and adjacent adversarial/reopen tests. Only pre-state digest is persisted; original production pre-state retrieval remains unverified, not inferred from a matching test fixture.
- No evidence-justified production/test repair identified. Continue bounded fresh validation, then commit this checkpoint rather than manufacture cosmetic source/ledger changes.
- Fresh environment/lint: `uv sync --locked --extra dev`, `uv run ruff check .`, and `uv run ruff format --check .` all passed (3474 files formatted).
- Fresh focused acceptance runs: core 336 passed; Hive production/legacy/boot/adapter 112 passed; bootstrap 255 passed / 7 skipped; architecture/security gate regression tests 74 passed. Logs saved as `repair-{core,hive,bootstrap,gate-tests}.log` in this job directory.
- Bootstrap skips: one Windows-only, six Docker/image unavailable. Do not infer live backend parity.
- Read accepted ADR-081226-6b46, ADR-081226-a66b, ADR-050, ADR-068, ADR-004. Reconciliation: schema/exposure is not authority or lifecycle; reversibility classification is not approval. ADR-004 amendment explicitly removes unused tools_allowed/write_scopes rather than treating declarations as grants.
- Production inspection: Hive constructs GovernedToolExecutor, re-reads canonical Run/NodeRun/Attempt, intersects requested names with host registry; legacy calls the same Invocation service and host reversibility lookup. Agent snapshots schemas and gates both strategy/model-selected tools before dispatch. BuildersLearning side effects are retired. No architecture/lifecycle changes made.
- Additional canonical capabilities/tools validation: 1279 passed / 12 skipped / one mock coroutine warning. Eight skipped PostgreSQL legs lack configured DSNs; four Playwright legs lack its dependency. Warning: `_FakeProc.communicate` unawaited in mocked GitHub failure test. Saved `repair-capabilities-tools.log`; no unrelated repair attempted.
- Direct-effect, model-egress, security-inventory, convergence and suite-inventory gates passed. Census: 51 effects / four TOOL_EFFECT sites; 1455 production modules; 21 suites / 33910 unique test identities. Model-egress explicitly retains 12 reachable escapes; gate PASS is a non-expansion ratchet, not complete #55/#56 cutover. Logs: `repair-architecture.log`, `repair-suite-inventory.log`.

## Commands and outcomes

All validation ran with long (600/1200 second) timeouts in the assigned worktree.
- `uv sync --locked --extra dev`: PASS.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3474 files.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, exact CI arguments confirmed against both workflows.
- `uv run pytest` focused core files with `-x -q`: 336 passed. Files: tools/test_governed_contracts.py; agents/test_tool_schema_boundary.py, test_base.py, test_factory.py; agents/spec/test_agent_spec.py; agents/strategies/test_react.py, test_builders_learning.py; agents/artificer/test_strategy.py; capabilities/test_effect_context_policy.py; security/sentinel/test_audit.py (all under packages/maistro-core/tests).
- `uv run pytest packages/maistro-core/tests/capabilities packages/maistro-core/tests/tools -x -q -rs`: 1279 passed, 12 skipped, one warning. Counts overlap focused core run; not a unique total.
- `uv run pytest` Hive test_governed_tools.py, test_legacy_dag_node.py, test_agent_model_tools.py, test_maistro_core_adapter.py with `-x -q`: 112 passed (under packages/hive-conductor/backend/tests).
- `uv run pytest packages/maistro-bootstrap/tests -x -q -rs`: 255 passed, 7 skipped.
- `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q`: 74 passed.
- `uv run python scripts/check_direct_effects.py`: PASS.
- `uv run python scripts/check-model-egress.py`: PASS as ratchet, 12 banked reachable escapes.
- `uv run python scripts/check-security-inventory.py`: PASS; output explicitly says prose is not comprehensively checked.
- `uv run python scripts/check-convergence-matrix.py`: PASS.
- `uv run python scripts/check-suite-inventory.py`: PASS, all 21 suites.

## Acceptance review (frozen issue #57)

| # | Criterion | Fresh evidence / limit |
|---|---|---|
| 1 | Consume real #55 Invocation seam, no competing executor | contracts.py:358 reaches existing Invocation lifecycle; fresh Hive boot/legacy tests pass. Full #55 completion **UNVERIFIED**; local ALLOW fixtures and ratchet membership are not production authorization proof. |
| 2 | Canonical authorization plus predictions where required | Core persisted high-impact evidence test and Hive registry-tier/Invocation tests pass. Deployed mutating-tool prediction coverage **UNVERIFIED**; Hive's shipped contracts are read-only. |
| 3 | Effective authorized tool set before provider | Fresh Agent, ReAct, artificer, Hive adversarial denial tests assert no provider dispatch; BuildersLearning side-effect retirement tests pass. Universal Principal/Workspace/Goal/Run authority envelope **UNVERIFIED**. |
| 4 | Missing/unknown schema fails closed | Fresh unknown/missing/unsupported-schema and host-schema snapshot tests pass, including legacy materialized arguments. |
| 5 | Constrained command contracts across backends | Bootstrap argv-only, raw-text refusal, injection/backend hardening tests pass. Live Docker and Windows parity **UNVERIFIED** due to seven explicit skips. |
| 6 | Host-owned canonical reversibility | Fresh core effect-floor tests, Hive registry-tier and legacy shared-registry tests pass. SECURITY.md:35 accurately separates classification from Sentinel registry-based approval gating. |
| 7 | Exact recomputable evidence identities | Fresh SQLite reopen test verifies exact materialized args, digests, Invocation, capability/provider, expected/observed post-state, policy version. Original production pre-state retrieval/recomputation **UNVERIFIED**: contracts.py:321 persists only a digest. PostgreSQL legs skipped. |
| 8 | Durable correlated mismatch, never silent success | Fresh mismatch and SQLite append-interruption/ack-recovery tests pass: first verdict immutable on replay, one correlated event, PredictionMismatch, no redispatch. Cross-process observation races **UNVERIFIED**. |
| 9 | Missing required high-impact predictions detectable/policyable | Fresh high-impact contract refusal test passes with complete-contract positive control. |
| 10 | Seven historical TOOL_EFFECT sites controlled/retired | Fresh census matches four current TOOL_EFFECT sites; production/retired-strategy tests pass. Full historical seven-site migration equivalence **UNVERIFIED**; current census alone is insufficient. |
| 11 | Intentional raw tool bypass rejected by gate | Fresh 74-test gate run includes deliberate raw Hive and BrowserClient path rejection regressions. |
| 12 | #847 closes first from adversarial tests | **UNMET**: supplied frozen source `issues/847` at dispatch-context.json:72308 has `state=open` at :72411. No closure or GitHub mutation is authorized; local adversarial subsets are not complete child acceptance. |

## Handoff

Verdict: **BLOCKED**. Only this evidence checkpoint changes. No production, test,
inventory, quality-ledger or grant edits are justified by reproduced evidence;
therefore no inventory-delta note is required. Existing committed work preserved.
No remote CI proof or supplied driver check logs are available; exact-head CI is
**UNVERIFIED**, never inferred from local results.

Residual risks: #847 prerequisite unmet; complete #55 seam, deployed mutating
prediction coverage, original pre-state retrieval, cross-process observation
settlement, live PostgreSQL/Docker/Playwright behavior and historical seven-site
mapping unverified. Next action belongs to authorized prerequisite owners and
production evidence providers, not another speculative documentation/ledger edit.

Progress: checked 1 assigned issue; focused-validation item done 1; issue completion
0; skipped issues 0; failed validation commands 0. Finish with a local checkpoint
commit, no push.

Final pre-commit checks: exact vulture gate re-run after dependency sync PASS
(`repair-vulture.log`); `git diff --check` PASS. Status contains only this new
checkpoint. No ledger changes, tests, or other source changes.

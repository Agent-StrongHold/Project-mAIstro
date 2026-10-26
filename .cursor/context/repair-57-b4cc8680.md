# Issue #57 repair — b4cc8680

## Frozen scope
- Assigned worktree `/home/dev/Git/wt/auto-57`, branch `auto-57`.
- Starting HEAD `4c3503bd10a4b8a9e0987c19922217c5b4684ff8`; supplied develop base `fe733ae4ee27d33f0b0f2912f5cb4ee3b2243e21`.
- Only issue #57 and supplied dispatch snapshot; no remote mutations or re-enumeration.
- Repair targets: reported SECURITY.md reversibility drift; exact vulture identity gate failures if reproduced. Inspect surrounding governed execution code and tests, ADRs; run focused acceptance validation. Do not change unrelated pre-existing branch differences or other ledgers.
- Initial worktree clean; HEAD matches assignment. No `check-*.log` files exist in supplied job directory at initial inspection, so driver checks cannot be assumed.
- Writer role assumed from explicit repair assignment. Criterion #847 closure cannot be performed under no-GitHub-mutations constraint; report its frozen state.

## Progress
- Initial repository instructions read; broad branch diff recorded in tool output (142 files vs supplied base); existing differences are preserved.
- Read frozen #57/#847 acceptance bodies, prior result and report, tool contracts, governed Hive production composition and adjacent contract tests. #847 remains open in the frozen snapshot; no closure proof is available.
- `uv sync --locked --extra dev` PASS. Exact requested vulture scan PASS: 1305 findings, 1309 reviewed identities, zero unclassified/never_allowlist (`repair-vulture.log` in job directory). No source/ledger amendment is justified.
- SECURITY.md:35 already documents construction through tool contracts and explicitly separates host-owned reversibility classification from Sentinel approval integration. The reported stale documentation finding is not reproducible at the assigned head. Preserve wording rather than fabricate a repair.
- Read accepted ADR-081226-6b46, ADR-081226-a66b, ADR-050, ADR-068, ADR-004. Reconciliation: tool exposure is not authority or a lifecycle; reversibility classification is not approval; obsolete AgentSpec authority-looking fields were removed per the ADR-004 amendment. No competing scheduler, store, authority, or lifecycle is introduced in this round.
- Fresh focused tests PASS: core contract/Agent/strategy/policy/audit files 336 passed; Hive governed/legacy/boot/adapter files 112 passed; bootstrap package 255 passed, 7 skipped (one Windows-only, six unavailable Docker/image); deliberately introduced raw-effect/model-egress gate tests 74 passed. Logs: `repair-{core,hive,bootstrap,gate-tests}.log` in job directory.
- Fresh ruff check and format-check PASS (3474 files). Direct-effect, model-egress, security-inventory, convergence and suite-inventory checks PASS. Important limitation: model-egress ratchet explicitly retains 12 reachable escapes awaiting #56; this is not proof of complete M1 cutover. Current census: 51 direct effects, four TOOL_EFFECT sites; 1455 production modules classified; 21 suites / 33910 unique test identities. Gate output inspected directly; suite details saved in `repair-suite-inventory.log`.
- Inspected Agent host schema snapshot/allowlist/Sentinel dispatch, retired BuildersLearning side effects, Hive canonical Run/NodeRun/Attempt re-read and registry intersection, legacy direct canonical Invocation with shared host reversibility registry, and expected-effect digest representation. Full production pre-state retrieval and live backend parity are not demonstrated by these checks.
- Additional canonical capabilities/tools package run PASS: 1279 passed, 12 skipped, one warning (`repair-capabilities-tools.log`). Eight skips require configured real PostgreSQL, four require Playwright. Warning is an unawaited `_FakeProc.communicate` coroutine in the mocked GitHub failure test, not an observed provider bypass. No unrelated repair is attempted.
- Frozen #55 body also remains open and requires real production/approval/quota evidence. Its completion is not inferred from passing local unit/integration tests. No production/test/ledger change is evidence-justified.

## Commands executed

All commands ran locally in the assigned worktree; validation timeouts were 1200 seconds.

| Command | Result |
| --- | --- |
| `uv sync --locked --extra dev` | PASS |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; zero unclassified/never_allowlist; no ledger repair needed |
| `uv run pytest` focused core files below, `-x -q` | 336 passed |
| `uv run pytest packages/maistro-core/tests/capabilities packages/maistro-core/tests/tools -x -q -rs` | 1279 passed, 12 skipped, one mock coroutine warning |
| `uv run pytest` four Hive files below, `-x -q` | 112 passed |
| `uv run pytest packages/maistro-bootstrap/tests -x -q -rs` | 255 passed, 7 skipped |
| `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q` | 74 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3474 files |
| `uv run python scripts/check_direct_effects.py` | PASS; 51 sites / four TOOL_EFFECT |
| `uv run python scripts/check-model-egress.py` | PASS as ratchet; 12 reachable escapes remain |
| `uv run python scripts/check-security-inventory.py` | PASS; prose not comprehensively checked |
| `uv run python scripts/check-convergence-matrix.py` | PASS; 1455 production modules |
| `uv run python scripts/check-suite-inventory.py` | PASS; all 21 suites / 33910 unique identities |
| `git diff --check` | PASS; only this new report is untracked before commit |

Core focused files, under `packages/maistro-core/tests/`:
`tools/test_governed_contracts.py`, `agents/test_tool_schema_boundary.py`,
`agents/test_base.py`, `agents/test_factory.py`, `agents/spec/test_agent_spec.py`,
`agents/strategies/test_react.py`, `agents/strategies/test_builders_learning.py`,
`agents/artificer/test_strategy.py`, `capabilities/test_effect_context_policy.py`,
`security/sentinel/test_audit.py`.

Hive focused files, under `packages/hive-conductor/backend/tests/`:
`test_governed_tools.py`, `test_legacy_dag_node.py`, `test_agent_model_tools.py`,
`test_maistro_core_adapter.py`.

Some core tests overlap the capabilities/tools run; counts are not unique totals.
No new tests or inventory counts changed; no inventory-delta note is required.

## Acceptance review (all twelve frozen criteria)

| # | Criterion | Fresh evidence / remaining limit |
| --- | --- | --- |
| 1 | Consume real #55 seam, no second executor | `tools/contracts.py:358` invokes the existing canonical lifecycle; Hive boot/legacy tests pass with persisted execution identities. Complete #55 prerequisite is **UNVERIFIED**, not established by registry membership or policy-ALLOW fixtures. Frozen #55 is open. |
| 2 | Canonical authorization plus required predictions | Core `test_governed_tool_persists_expected_evidence_on_canonical_invocation` and real SQLite Hive `test_governed_tool_records_invocation_with_registry_tier` pass. Deployed high-impact/mutating-provider coverage is **UNVERIFIED**; shipped Hive contracts are read-only. |
| 3 | Effective authorized tools before provider | Agent/ReAct/artificer/custom-strategy/Hive denial tests pass with no-backend-call assertions. BuildersLearning side effects are retired. Full universal Principal/Workspace/Goal/Run envelope is **UNVERIFIED**; host exposure alone cannot prove it. |
| 4 | Missing/unknown schemas fail closed | Core unknown/missing/unsupported-schema and Agent host-schema-boundary tests pass; Hive legacy materialized-argument refusal tests pass. |
| 5 | Constrained command contract across backends | Bootstrap package passes argv-only, raw-text refusal, injection and backend hardening tests. Live Docker parity **UNVERIFIED**: six unavailable-image/backend tests skipped, plus one Windows-only test. |
| 6 | Host-owned reversibility | Core effect-floor tests, Hive registry-tier and legacy shared-registry tests pass. `legacy_dag_node.py:409` resolves `hive_tool_reversibility` before Invocation. SECURITY.md:35 accurately distinguishes this from unimplemented registry-based Sentinel approval gating. |
| 7 | Exact, recomputable expected-effect identities | Core SQLite close/reopen fault tests pass, binding exact arguments/digest, Invocation/capability/provider, pre-state digest, expected/observed post-state and policy version. Full production retrieval/recomputation of original pre-state is **UNVERIFIED**: `contracts.py:321` stores only its digest; real PostgreSQL legs were skipped. |
| 8 | Durable correlated mismatch, never ordinary success | Core mismatch and both SQLite interrupted-append/ack cases pass: immutable first verdict, one correlated event after replay, PredictionMismatch raised, no provider redispatch. Cross-process high-impact observation races **UNVERIFIED**; recovery tested by replay, not an autonomous recovery worker. |
| 9 | Missing high-impact predictions detectable/policyable | `test_high_impact_contract_without_expected_effect_fails_closed` passes with complete-contract positive control. |
| 10 | Seven historical TOOL_EFFECT sites controlled/retired | Current direct-effect census passes with four retained provider-backend TOOL_EFFECT sites; Hive chat/boot/legacy routing and retired strategy tests pass. Complete historical seven-site mapping is **UNVERIFIED**; a present-day census is not migration equivalence evidence. |
| 11 | Deliberate raw bypass rejected by architecture gate | Both newly introduced raw Hive and raw BrowserClient audit rejection tests pass in the 74-test architecture gate run. |
| 12 | #847 closes first from adversarial tests | **UNMET**: supplied `dispatch-context.json:71982` identifies issue #847; `:72085` has `state=open`. Local adversarial tests are not issue closure or complete child acceptance; no GitHub mutation is authorized. |

## Handoff

Verdict: **BLOCKED**, not merge/integration approval. The supplied stale-doc and
vulture findings do not reproduce. Only this evidence checkpoint changes; all
pre-existing code, tests, quality ledgers and grants are preserved. Do not invent
cosmetic edits or repeat this repair without fresh failure evidence.

Residual risks: #847 closure unmet; #55 completion, deployed mutating-effect
coverage, original pre-state retrieval, cross-process observation races, live
PostgreSQL/Docker/Playwright behavior, and historical seventh-site equivalence
are unverified. Exact-head remote CI is **UNVERIFIED**; no supplied driver logs
exist and no remote pass is inferred.

Progress: checked 1 assigned issue; focused-validation item done 1; issue completion
0; skipped issues 0; failing validation commands 0. Next: authorized owner sequences
#847/#55 and supplies the missing production/backend/historical evidence. Finish
with a local commit only; never push.

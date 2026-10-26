# Issue #57 repair — 2c3ee758

## Frozen scope
- Assigned issue: #57 only; branch auto-57; starting head 0694d4fd507e13862a911288b2799a289a5f8089; base bb9a7fbbc7524be0f63d3b74b76a0edda459b60a.
- Worktree initially clean; no salvage patch needed.
- Evidence snapshot: /home/dev/maistro/jobs/2c3ee758e9b14f6f9915db43fcdd17a8/dispatch-context.json; prior result /home/dev/maistro/jobs/18abbc0491df4f17a3618a70701f54c3/result.json. No re-fetch/re-enumeration of GitHub.
- Frozen inspection targets: issue #57 body/acceptance, linked #847 status in supplied snapshot; branch diff's tool contracts, effect invocation, agent/model seam, host adapter, relevant tests; SECURITY.md; relevant ADRs; exact vulture CI scan and ledger.
- Allowed repairs: evidence-backed #57 security documentation/runtime/test corrections; reviewed exact-debt vulture ledger amendment explicitly permitted by dispatch. No other quality ledger/grant edits.
- Writer role assumed (explicit assigned repair and local commit requirement); supplied verifier no-edit instruction is role-specific and not applicable.
- No check-*.log files present in current job directory at initial inspection. Prior job has writer logs; these are evidence, not proof of current validation.

## Progress
- Initial state and starting ref verified exactly; branch diff inspected; repository AGENTS.md read.
- Read frozen issue #57 acceptance (12 criteria), #847 body/status and prior result/report. #847 remains open in supplied snapshot; criterion 12 cannot be met by local code. Prior result deliberately leaves other integration portions unverified.
- SECURITY.md:35 already states that governed contracts construct ReversibilityRegistry and distinguishes incomplete Sentinel approval integration. Reported prose drift is not reproducible on the assigned head; no cosmetic edit justified.
- Fresh `uv sync --locked --extra dev`: PASS. Fresh exact CI vulture scan: PASS, 1310 findings / 1314 reviewed identities; no unbanked identities. No ledger amendment justified by actual scan.
- Read ToolContractRegistry/GovernedToolExecutor and Hive production composition plus exact expected-evidence model and adjacent adversarial/persistence tests. Consumes existing Binding/Invocation lifecycle, no competing scheduler or event authority.
- Read accepted ADR-004, ADR-050, ADR-068, ADR-081226-6b46 and ADR-081226-a66b. ADR-004 amendment explicitly permits removal of misleading tools_allowed/write_scopes declarations; no replacement authorization path should be introduced.
- Fresh core focused validation: 956 passed (agents, governed contracts, effect policy, Sentinel audit), `/tmp/repair-57-2c3ee758-core.log`.
- Fresh shipped Hive composition validation: 107 passed (governed tools, legacy DAG node, Agent/model tools, core adapter), `/tmp/repair-57-2c3ee758-hive.log`.
- Fresh bootstrap validation: 243 passed, 7 skipped (one Windows-only, six Docker/image unavailable), `/tmp/repair-57-2c3ee758-bootstrap.log`; live cross-backend parity remains UNVERIFIED.
- Fresh whole-tree ruff check and format check PASS (3456 files); adversarial direct-effect/model-egress gate tests 74 passed.
- Fresh gates all PASS: direct effects (51 sites, 4 TOOL_EFFECT), model-egress nonexpansion (still 12 reachable escapes, not #55/#56 completion proof), security inventory (bounded named claims only), convergence (1451 modules), suite inventory (33563 unique identities, all 21 suites match), radon (127 findings / 128 reviewed, 1 nonblocking stale row). No unbanked vulture debt; no other ledger modifications permitted/needed.
- Demonstrated actual scope-confusion defect in Hive live_tool_context: two new production entry-point tests with real SQLite Run/NodeRun/Attempt records and conflicting ambient Workspace/Project each failed `DID NOT RAISE RunIntegrityError`; missing-scope positive control passed. Red log `/tmp/repair-57-2c3ee758-scope-red.log` (2 failed, 1 passed).
- Focused repair: reject nonempty correlation scope inconsistent with persisted Run before any Binding registration or backend effect; always derive ToolInvocationContext scope from canonical Run. Matches the existing AdmittedModelCalls scope rule; no new authorization owner or scheduler.
- Added +3 Hive test cases and required inventory note `docs/testing/inventory-notes/issue-57-admitted-tool-scope.md`. Fresh green production-path suite now 110 passed, `/tmp/repair-57-2c3ee758-hive-green.log`.
- First post-edit ruff run found SIM117 in new negative test (nested context managers); fixed by combining context managers. Final whole-tree ruff check and format check PASS; final vulture/radon/direct-effect/model-egress/security-inventory/convergence/suite-inventory checks PASS; `git diff --check` PASS. Inventory now 3970 Hive / 33566 total unique identities, +3 explained by new note. No gate weakening or ledger changes.
- Final test module after lint adjustment: 12 passed. Broader repaired Hive validation: 110 passed. No new items will be started; finalize acceptance and commit the focused scope repair.

## Acceptance review (fresh executed evidence, not inherited claims)

| # | Criterion | Evidence and remaining limits |
|---|---|---|
| 1 | Consume #55 canonical Invocation seam | Hive real SQLite Container tests pass through `governed_hive_tool` -> `GovernedToolExecutor` -> existing `effects.invocations.invoke`. New scope regressions fail before repair and pass after; no alternate lifecycle/executor authority added. Full #55 prerequisite completion **UNVERIFIED**; nonexpansion gates are not universal cutover proof. |
| 2 | Authorization plus required predictions | Executed core `test_governed_tool_persists_expected_evidence_on_canonical_invocation` asserts policy/completion events and prediction linkage. Hive boot Agent and legacy integration tests assert persisted Invocation. Shipped mutating/high-impact provider composition **UNVERIFIED** (current Hive registry is internal/read-only; prediction test uses library ticket fixture). |
| 3 | Effective allowlist before provider | Executed shared Agent, strategy and Hive adversarial refusals; `Agent._authorize_and_invoke` checks identity.tools, host-schema snapshot and Sentinel before raw callback; Hive intersects requested exposure with host names. New scope cases prove correlation strings cannot widen Run scope. Complete principal/owner envelope across all consumers **UNVERIFIED**. ADR-004 amendment overrides issue language about retaining removed tools_allowed/write_scopes fields. |
| 4 | Missing/unknown schemas fail closed | Executed `test_tool_schema_boundary.py`, unsupported-schema contract tests and strategy adversarial tests: absent/non-object/unknown type schemas, forged/nested mutable exposures and invalid Sentinel repairs refuse backend dispatch. Valid/no-argument controls pass. Standalone consumers outside tested shared seam **UNVERIFIED**. |
| 5 | Constrained command contract | Bootstrap tests pass (243); structured argv/no raw cmd/metacharacter, git/path and shell-free dispatch assertions inspected. Cross-platform/live container parity **UNVERIFIED**: seven skips, including six Docker/image unavailable tests. |
| 6 | Host-owned reversibility | Hive registry/tier tests and `test_legacy_tools_record_the_shared_host_registry_tier`, `test_legacy_registry_reclassification_reaches_canonical_effect_policy` pass; effect policy tests enforce irreversible admission fact. SECURITY.md:35 accurately limits remaining Sentinel integration (#346); no caller-selected tier accepted by governed contracts. |
| 7 | Exact recomputable evidence | Executed SQLite reopen test asserts actual capability/provider, materialized arguments/digest, pre-state digest, expected/observed post-state, Invocation id and policy version. Persisted evidence model inspected. Retrieval of actual pre-state from its digest / complete deployed high-impact integration **UNVERIFIED**. |
| 8 | Durable mismatch not ordinary success | Executed mismatch and interrupted-append/reopen tests (both append-committed states): immutable first verdict, one correlated durable event, no redispatch; raises PredictionMismatch. Autonomous repair without a retry **UNVERIFIED**. |
| 9 | Required predictions detectable | Executed high-impact missing-prediction registration failure and complete positive control; ToolContract.__post_init__ refuses incomplete callbacks/version. Future/legacy high-impact provider parity **UNVERIFIED**. |
| 10 | Seven historical tool sites | Current census passes with 4 TOOL_EFFECT sites; shipped Hive/legacy and rewritten strategy tests pass. Exact historical seven-site equivalence **UNVERIFIED**; current count alone cannot prove it. |
| 11 | No raw bypass regression | Executed 74 adversarial direct-effect/model-egress gate tests, including intentionally introduced raw tool paths rejected by architecture checks; both gates pass. This is bounded static enforcement, not arbitrary reflective-code sandboxing. |
| 12 | #847 closes first | **UNMET**: frozen dispatch source `repos/Agent-StrongHold/Project-mAIstro/issues/847` state=open. Adversarial tests do not substitute for issue closure; no GitHub mutations allowed/performed. |

Exact-head remote CI **UNVERIFIED**; current job supplied no check-*.log files. No prior CI status is inferred green.

## Changed files

- `packages/hive-conductor/backend/services/governed_tools.py`: reject scope conflicts against admitted Run; derive scope only from Run.
- `packages/hive-conductor/backend/tests/test_governed_tools.py`: +2 conflicting-scope denials and +1 missing-correlation-scope positive control, all through shipped entry point and real persistence.
- `docs/testing/inventory-notes/issue-57-admitted-tool-scope.md`: required +3 suite delta and regression intent.
- `.cursor/context/repair-57-2c3ee758.md`: frozen scope, independent evidence and handoff.

## Commands executed

All Python commands used uv; validation timeouts were 1200 seconds.

- `uv sync --locked --extra dev` — PASS.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS before/after; no unbanked identities, ledger unchanged.
- `uv run pytest packages/maistro-core/tests/agents packages/maistro-core/tests/tools/test_governed_contracts.py packages/maistro-core/tests/capabilities/test_effect_context_policy.py packages/maistro-core/tests/security/sentinel/test_audit.py -x -q` — 956 PASS.
- `uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py packages/hive-conductor/backend/tests/test_legacy_dag_node.py packages/hive-conductor/backend/tests/test_agent_model_tools.py packages/hive-conductor/backend/tests/test_maistro_core_adapter.py -x -q` — 107 PASS before added cases, 110 PASS after repair.
- `uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py -k 'scope_conflicting or missing_correlation_scope' -q --tb=short` — expected RED: 2 failed (DID NOT RAISE), 1 passed; original production defect reproduced before editing production code.
- `uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py -x -q` — final 12 PASS.
- `uv run pytest packages/maistro-bootstrap/tests -x -q -rs` — 243 PASS, 7 SKIPPED as above.
- `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q` — 74 PASS.
- `uv run ruff check .`; `uv run ruff format --check .` — final PASS. Intermediate new-test SIM117 corrected without weakening lint.
- `uv run python scripts/check-radon-baseline.py` — PASS, one stale row nonblocking; no edits to radon ledger.
- `uv run python scripts/check_direct_effects.py`; `uv run python scripts/check-model-egress.py`; `uv run python scripts/check-security-inventory.py`; `uv run python scripts/check-convergence-matrix.py`; `uv run python scripts/check-suite-inventory.py` — all PASS before and after repair; limitations above. Final suite collection 33566 unique identities.
- `git diff --check` — PASS.

## Handoff

Verdict **BLOCKED** at issue level: criterion 12 requires #847 closure and several broader acceptance portions remain explicitly unverified. Focused scope repair is locally validated for handoff, not integration approval. No pushes, merges, GitHub mutations, baseline/grant edits or discarded work. A local commit will include exactly the four files above.

Progress: {checked: 1, done: 1, skipped: 0, errors: 0, next: "owner/verifier review of committed repair, #847 prerequisite and explicitly unverified acceptance portions"}. Expected red regression failures and one corrected intermediate lint finding are recorded above, not unresolved validation errors.

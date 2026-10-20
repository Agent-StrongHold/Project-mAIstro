# Issue #57 repair checkpoint

## Frozen scope
- Issue #57 only, branch auto-57, starting HEAD d9cdc558f723bd22a5f222d0c5037e28f84d7056.
- Evidence snapshot: /home/dev/maistro/jobs/f6b720311e8b451596dd6c9d21834313/dispatch-context.json; prior result /home/dev/maistro/jobs/5f1f9fbe83d84a66ac01c3516f988b8c/result.json.
- Tasks: salvage/finish existing merge; reconcile SECURITY.md reversibility claim; execute exact vulture gate and repair observed identities only; validate #57 criteria without GitHub mutation.
- Existing merge parent d32ddff767b00a49870c60e2c3f67f858ca341e5 resolves locally. One conflict: security/sentinel/audit.py imports. Other staged changes are incoming merge work and will be preserved.
- Backups before edits: ../incoming-57.patch and ../incoming-57-index.patch.
- Current job has no check-*.log files. Prior job logs are historical, not evidence for this HEAD.
- Ambiguity: issue closure is external state, not a code acceptance proof. Use frozen dispatch snapshot; do not close issues or infer readiness from prior claims.

## Progress
- Initial worktree and merge state inspected; no work discarded.
- Read accepted ADR-081226-6b46, ADR-050, ADR-073 and adjacent audit/signature tests. Reconciled import conflict by retaining the runtime AuditEntry needed by scoped denials and incoming AuditSigner used by retention. No new execution or authorization authority.
- Corrected SECURITY.md layer 4: registry is constructed by governed contracts; reversibility-driven Sentinel approval remains a limitation, not a shipped claim.
- `uv sync --locked --extra dev`: passed. Exact CI vulture command: passed, 1317 findings / 1321 reviewed identities, zero unclassified or never-allowlist. No ledger repair warranted by actual scan; no ledger edited.
- Frozen acceptance 12 is unmet: dispatch snapshot reports #847 open. Closure sequencing cannot be repaired by local code or GitHub mutation in this lane.
- Focused core regression run: 283 passed, 1 skipped (repair-core.log); lint and format checks passed (3366 files).
- Added one integration regression for the actual merge seam: pre-Sentinel allowlist denial is retained as a signed, org-scoped entry (including runtime AuditEntry construction). Added +1 inventory note; sentinel audit module: 23 passed; core suite inventory: 16716, matches.
- Direct-effect inventory gate passed: 51 sites, four TOOL_EFFECT sites all dispositioned; adversarial gate tests: 36 passed. Security inventory gate passed (prose correction itself is manually verified against contracts.py and Sentinel, not claimed as scanner coverage).
- Bootstrap acceptance run: 10 passed, 6 skipped (Docker-dependent cases); hive production-wiring run: 86 passed using real SQLite Container/Run/NodeRun/Attempt fixtures.
- Regression demonstration: removed `audit.AuditEntry` from the imported module in a disposable Python process (no file edits), ran the new test, and observed the expected failure (missing retained denial; guarded NameError). Normal test passed. This proves the test detects the actual conflicting-import regression rather than only exercising a happy path.
- Capability package tests: 719 passed, 7 skipped (repair-capabilities.log). Exact AGENTS mypy command: success, 907 source files. Final ruff check/format and diff whitespace checks passed.

## Acceptance review (frozen issue body)
1. Canonical seam dependency: production `services/governed_tools.py` constructs GovernedToolExecutor over container.capability_effects; contracts.py calls existing invocations.invoke, no replacement lifecycle. Executed hive real-SQLite production-wiring tests (86 passed).
2. Invocation authorization/prediction attachment: test_governed_contracts persists Invocation and policy/completion events; capabilities tests (719 passed) exercise governed admission. High-impact prediction is library policy, not claimed for read-only hive tools.
3. Effective allowlist: core test_agent_allowlist_and_unknown_schema_fail_before_backend and hive test_unlisted_and_badly_typed_tools_refuse_before_the_backend passed; ReAct adversarial coverage included in core run.
4. Missing/unknown schemas: same core tests plus Agent ReAct tests passed before backend dispatch.
5. Command contract: bootstrap structured-argv tests and container argv-shape hardening tests passed (10 tests total). Live container execution UNVERIFIED here: six tests skipped because builders image/backend unavailable. No claim that fakes prove real sandbox isolation.
6. Host reversibility: hive test_governed_tool_records_invocation_with_registry_tier and test_hive_tool_registry_is_host_owned passed; classification is recorded, not claimed to implement Sentinel approval gating.
7. Exact expected-effect binding: contracts.py plus expected_effect.py bind provider/capability/arguments/digests/policy and Invocation lifecycle attaches id before admission. test_governed_tool_persists_expected_evidence_on_canonical_invocation passed. Durable high-impact restart round-trip was not independently exercised: UNVERIFIED.
8. Mismatch: test_prediction_mismatch_is_durable_evidence_and_not_success passed (canonical event seam, refuses overwrite). This uses in-memory adapters; durable restart behavior UNVERIFIED.
9. Required predictions: test_high_impact_contract_without_expected_effect_fails_closed passed.
10. Seven-site inventory: direct-effect gate passed (four remaining provider backends dispositioned); hive chat routing / boot tool Invocation / legacy no-identity refusal tests passed. Registry implementation and backend reclassification inspected, no ledger edits in this round.
11. Bypass rejection: tests/test_check_direct_effects.py 36 passed including injected raw hive dispatcher and raw BrowserClient call refusals (lines 496 and 519).
12. #847 closure: UNMET, frozen dispatch snapshot says open; no remote mutation performed.

## Residual risks / handoff
- No current-job driver check logs existed at start; all repair-*.log evidence was executed in this round. Prior CI claims are not promoted to current evidence. Remote CI UNVERIFIED.
- PostgreSQL live service tests and builder-container integration skipped; focused in-memory/SQLite/mock-PG checks are not a substitute for those deployments.
- Existing incoming merge files outside the narrow repair are preserved, not silently rewritten. No new scheduler, Goal store, event authority, authorization route, or quality-ledger edits.
- Status: checked one assigned issue; repaired local merge/documentation regression; externally BLOCKED on criterion 12 and noted unverified deployment checks. Next: verifier/integrator evaluates committed repair and separately resolves #847 sequencing.

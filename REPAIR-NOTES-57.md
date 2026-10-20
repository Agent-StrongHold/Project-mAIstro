# Issue #57 repair checkpoint

## Current round (2026-10-20, job c7edbafe530e4df1a2b2cc9f236fb3a1)
- Frozen item: issue #57 only; assigned worktree `/home/dev/Git/wt/auto-57`, branch auto-57; clean starting HEAD edd05e56083666ef137280963b0a97c1728342f5, develop base fad17a87c34193a91c568eb8b0a910e8e6384ccd.
- Frozen evidence: current job dispatch-context.json and prior job f6b720311e8b451596dd6c9d21834313/result.json. No current-job check-*.log files were present at start. Earlier results below are history, not new verification.
- Scope/files: inspect existing #57 production contracts/Invocation, their adjacent tests, accepted ADRs, SECURITY.md, exact vulture scanner/ledger and relevant CI gates. Change only evidence-backed #57 repairs, this checkpoint, and required test inventory notes. No remote mutation or unrelated issue processing.
- Ambiguity: prior requested SECURITY.md repair may already be present; inspect rather than reapply. #847 is an external closure prerequisite; record its captured state, do not attempt closure.
- Initial inspection: clean assigned HEAD confirmed; no uncommitted salvage needed. Current issue body has twelve acceptance criteria, including #847 closing first.
- Current executed checks: `uv sync --locked --extra dev`, exact CI vulture command (1317 findings, zero unclassified/never_allowlist), `uv run ruff check .`, and `uv run ruff format --check .` all passed. No ledger change is warranted. SECURITY.md:35 already contains the earlier correction; no repeat edit needed.
- Read accepted ADR-081226-6b46, ADR-050 and ADR-073, production tool contracts/Invocation composition and adjacent adversarial tests. Found concrete acceptance-8 risk: observation is saved before mismatch append, while replay skips append whenever an observation exists; an append failure permanently suppresses planning/security evidence.
- Reproduced before production edits: `uv run pytest packages/maistro-core/tests/tools/test_governed_contracts.py -k mismatch_event_recovers -x -q` failed with zero mismatch events after real SQLite close/reopen (repair-regression-before.log). Added two parametrized regression cases (+2 inventory note) covering failure before append commit and lost acknowledgement after commit.
- Focused fix: canonical Invocation builds a stable mismatch-event identity; governed tool settlement always retries the canonical EventStore's idempotent append. Existing Invocation/Event stores remain the sole authorities; no outbox, scheduler or policy path added. Database observation/event writes remain separate and recovery is on replay, not an atomic or autonomous recovery claim.
- Post-fix validation: core tools/capabilities and adjacent agent/audit tests 1455 passed, 11 skipped (repair-core.log); full bootstrap package 236 passed, 7 skipped; focused Hive production-wiring tests 86 passed. Adversarial architecture/model-egress gate tests 74 passed. Core inventory matches 16719 collected tests with the +2 note.
- Residual execution evidence: core run emits one pre-existing mock coroutine warning. Live bootstrap container tests skipped for unavailable maistro-builders image; image-inspection command also reports absent. Frozen current dispatch explicitly confirms `/issues/847` state=open, so criterion 12 remains unmet. Initial hyphenated direct-effect script lookup found no file; adjacent tests identify the actual gate as scripts/check_direct_effects.py (use that path below).

### Current acceptance review / final validation
All commands below were executed in this round; logs live under the current job
path above with `repair-` prefix. Earlier round claims are not substituted.

1. Canonical seam dependency: inspected `services/governed_tools.py` composing over Container.capability_effects and contracts.py calling the existing invocations.invoke. Hive production routing/real SQLite identity fixtures: 86 passed (repair-hive.log).
2. Authorization plus required prediction evidence: `test_governed_tool_persists_expected_evidence_on_canonical_invocation`, capabilities admission tests, and new SQLite reopen regression passed (repair-core.log / repair-regression-after.log).
3. Agent effective allowlist: adjacent Agent/ReAct, core contract and Hive refusal-before-backend tests executed in the 1455-test core and 86-test Hive runs; all passed.
4. Unknown/missing schemas: core unknown-schema, ReAct unknown-schema and Hive badly-typed-tool refusals passed in those runs. This is not a claim of full arbitrary JSON Schema support.
5. Structured command contract: bootstrap package 236 passed, 7 skipped (repair-bootstrap.log), including argv-only contract and hardened backend shape tests. Live container tests skipped: image unavailable. Real container execution remains UNVERIFIED, not proven by mocks.
6. Host-owned reversibility: Hive Invocation-tier and registry tests and core effect-context policy tests passed; SECURITY.md:35 accurately distinguishes governed classification from Sentinel.resolve_tier integration.
7. Exact evidence identity: new real SQLite reopen tests assert capability/provider, Invocation id, exact arguments, argument/pre-state digest, expected/observed state, policy version, stable evidence and correlation. Passed both fault cases. PostgreSQL high-impact restart behavior remains UNVERIFIED.
8. Durable mismatch: reproduced dropped event on original code, then both new SQLite fault cases passed (8 total contract tests). A failed append is retried on replay; a committed append with lost acknowledgement is deduplicated. First mismatch cannot be overwritten by a later matching observation; backend executes only once. No autonomous repair without replay is claimed.
9. Configured high-impact missing predictions: registration fails closed in `test_high_impact_contract_without_expected_effect_fails_closed`; executed and passed.
10. Seven-site migration/reclassification: inspected existing provider-backend dispositions and production wiring; `check_direct_effects.py` passed with 51 sites / four remaining TOOL_EFFECT provider sites; Hive boot/chat/legacy refusal tests passed. No new inventory/authority change in this round.
11. Bypass rejection: `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q`: 74 passed, including deliberately injected raw tool calls. Direct-effect and model-egress gates passed; the latter still reports existing #56 model escapes, not zero overall escape debt.
12. Closure sequencing: UNMET: current dispatch-context.json:68104 identifies /issues/847, line 68207 says state=open. Cannot satisfy or alter this external prerequisite locally; no GitHub mutation performed.

Final gates: exact vulture (zero unclassified/never_allowlist; no ledger amendment
needed), direct effects, model egress, convergence matrix, security inventory,
core suite inventory (16719), ruff check/format (3366 files), exact AGENTS mypy
command (907 source files), and git diff --check passed. No quality ledger was
edited in this round; branch-wide ledger differences predate this repair.

Changed files this round: REPAIR-NOTES-57.md, core capabilities/invocation.py,
core tools/contracts.py, core tests/tools/test_governed_contracts.py, and
inventory-notes/issue-57-mismatch-append-recovery.md.

Residual risks: current remote CI UNVERIFIED; absent builder image and skipped
PostgreSQL legs are not promoted to deployment proof. Observation/event writes
remain separate, repaired when the same logical call replays. Old releases used
random mismatch-event ids, so replay of a historical already-emitted mismatch
can append one new stable-id event during upgrade (not another tool dispatch).
Current-round status: checked 1, done 1 focused repair, skipped 0 issues, errors 0
remaining local validation failures; externally BLOCKED by criterion 12. Next:
verifier reviews this committed handoff and separately resolves #847 sequencing.

## Frozen scope (previous round)
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

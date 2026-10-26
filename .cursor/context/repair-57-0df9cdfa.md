# Issue #57 repair — 0df9cdfa

## Frozen snapshot and scope

- Assigned worktree `/home/dev/Git/wt/auto-57`, branch `auto-57`; starting HEAD `4ffd7e10341583ae3ae0a3969ea34d9154292b01`, develop base `2ac9606142162af4727a6c36eb25f635a16522b6`. Initial tree clean; no salvage required.
- Only issue #57 is processed. Source is the supplied `dispatch-context.json`; no refetch or issue enumeration. Its #847 snapshot is open, so acceptance 12 is unmet; no GitHub mutation is authorized.
- Repair snapshot: inspect the existing #57 production/tool controls and adjacent tests, verify the SECURITY.md registry claim, run the explicitly requested exact vulture gate, repair only actual reported retained/dead identities if any, and validate the twelve acceptance criteria. No ordinary quality/grant changes; vulture-only ledger permission applies if actual findings require it.
- Relevant file set: `SECURITY.md`; `packages/maistro-core/src/maistro/{tools/contracts.py,capabilities/{invocation.py,governed_invocation.py,expected_effect.py,effect_context.py},agents/{base.py,strategies/react.py,strategies/builders_learning.py,artificer/strategy.py},security/sentinel/{audit.py,reversibility.py}}`; their adjacent tests; `packages/maistro-bootstrap` command builders/tests; `packages/hive-conductor` governed-tool host/tests; `quality/vulture-baseline.json` only for the assigned exact-debt repair; relevant ADRs, CI gates, existing issue-57 notes, and this report. Additional source locations only as needed to verify those paths, not new issues.
- No `check-*.log` files are present in this job directory at start. Prior result is evidence, not assumed validation: prior writer reported BLOCKED, with criterion 12 unmet and production/pre-state claims unverified.

## Progress

1. Snapshot captured; both assigned refs resolve, initial worktree is clean. Read repository instructions, current #57/#847 bodies, prior result, and branch diff summary. No merge conflict exists.
2. Exact requested vulture command PASS: 1305 findings / 1309 reviewed identities, zero unclassified or never_allowlist. No ledger amendment is justified. SECURITY.md:35 already describes registry construction and separately limits Sentinel approval integration; supplied stale documentation finding is not reproducible. Do not manufacture cosmetic edits.
3. Read accepted ADR-081226-6b46, ADR-050, ADR-068 and ADR-004 and current tool contracts/expected-effect tests. Reconciliation: AgentSpec's unused authority-looking fields were removed per the ADR-004 amendment; reversibility classification is distinct from approval authority; the tool adapter delegates lifecycle to canonical Invocation. Evidence binds provider, materialized arguments, pre-state digest, expected/observed states and policy; SQLite restart test covers append/ack interruption. Original pre-state content is not retained here, so full production pre-state recomputation is not proven.
4. `uv sync --locked --extra dev` PASS. Fresh focused core tests: 336 passed. Fresh Hive boot/chat/legacy/adapter tests: 112 passed. Bootstrap package: 255 passed, 7 skipped (one Windows-only test; six live Docker/image-dependent tests). Architecture/model-egress adversarial tests: 74 passed. Hive/bootstrap/gate logs are in the current job directory as `repair-{hive,bootstrap,gate-tests}.log`. No added tests or inventory count changes.
5. Inspected production wiring: Hive re-reads canonical Run/NodeRun/Attempt identities, intersects its host registry exposure, and builds GovernedToolExecutor over Container.capability_effects; legacy resolves shared registry/schema but calls the existing canonical Invocation service directly. Agent passes model/strategy callbacks through its allowlist/Sentinel boundary. No live container execution is inferred from mocked tests; skipped live-backend checks remain UNVERIFIED.
6. Ruff check and format-check PASS (3474 Python files). Direct-effect, model-egress, security-inventory, convergence-matrix and suite-inventory gates PASS. Exact outcomes: 51 direct-effect sites, four TOOL_EFFECT sites; model-egress explicitly retains 12 reachable escapes awaiting #56; all 1455 production modules classified; all 21 suites match, 33910 unique test identities and no duplicates. These ratchet results are not universal behavior proofs.
7. Additional core capabilities/tools validation PASS: 1279 passed, 12 skipped, one warning. Eight skips require real PostgreSQL environment; four require Playwright. Warning: a mocked `_FakeProc.communicate` coroutine was not awaited in the GitHub failure-path test. No new source/test changes were made or justified by that warning. Log: `repair-core-capabilities-tools.log` in the current job directory.
8. Read lifecycle ADR-081226-a66b and inspected strategy retirement and branch routing changes. Retired BuildersLearning recon/diagnostic calls no longer run independently. All current TOOL_EFFECT inventory entries are existing provider backends below Invocation; historical seven-site equivalence is not established by the census alone. Frozen #55 is open and states its own production evidence requirements; no assumption that green debt ratchets establish that prerequisite.
9. Base-ledger inspection initially failed with TypeError because `sites` is a dict, not a list. Corrected the read-only inspection once: the supplied develop base has six TOOL_EFFECT entries (chat search/browse, legacy search/browse, BrowserClient search/browse). Current branch routes the two chat calls through governed tools; four remain as Invocation provider backends. The issue's historical seventh entry is not resolved by this base comparison; record UNVERIFIED rather than expand the snapshot or fetch history. This was an inspection error, not a gate/test failure.

## Commands and outcomes

All validation was local in the assigned worktree, with 1200-second timeouts.
No supplied `check-*.log` files existed; executed checks are independent of prior jobs.

| Command | Outcome |
| --- | --- |
| `uv sync --locked --extra dev` | PASS |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; zero unclassified/never_allowlist |
| `uv run pytest` focused core files listed below, `-x -q` | 336 passed |
| `uv run pytest packages/maistro-core/tests/capabilities packages/maistro-core/tests/tools -x -q -rs` | 1279 passed, 12 skipped, one warning |
| `uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py packages/hive-conductor/backend/tests/test_legacy_dag_node.py packages/hive-conductor/backend/tests/test_agent_model_tools.py packages/hive-conductor/backend/tests/test_maistro_core_adapter.py -x -q` | 112 passed |
| `uv run pytest packages/maistro-bootstrap/tests -x -q -rs` | 255 passed, 7 skipped |
| `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q` | 74 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3474 files |
| `uv run python scripts/check_direct_effects.py` | PASS; 51 sites / four TOOL_EFFECT |
| `uv run python scripts/check-model-egress.py` | PASS as a debt ratchet; 12 reachable escapes remain |
| `uv run python scripts/check-security-inventory.py` | PASS; prose not fully checked |
| `uv run python scripts/check-convergence-matrix.py` | PASS; 1455 modules |
| `uv run python scripts/check-suite-inventory.py` | PASS; 21 suites / 33910 unique identities |
| `git diff --check` | PASS |

Focused core files, all under `packages/maistro-core/tests/`:
`tools/test_governed_contracts.py`, `agents/test_tool_schema_boundary.py`,
`agents/test_base.py`, `agents/test_factory.py`, `agents/spec/test_agent_spec.py`,
`agents/strategies/test_react.py`, `agents/strategies/test_builders_learning.py`,
`agents/artificer/test_strategy.py`, `capabilities/test_effect_context_policy.py`,
`security/sentinel/test_audit.py`. Some tests overlap the additional capabilities/tools run;
these counts must not be treated as unique evidence totals.

Logs in the job directory: `repair-hive.log`, `repair-bootstrap.log`,
`repair-gate-tests.log`, `repair-core-capabilities-tools.log`,
`repair-ruff-check.log`, `repair-ruff-format.log`, `repair-architecture-gates.log`.
Core focused and initial vulture outputs were inspected directly in the tool transcript.

## Acceptance review (frozen #57 body)

| # | Criterion | Fresh executed evidence / remaining limitation |
| --- | --- | --- |
| 1 | Consume #55, no second executor | `contracts.py:358` delegates to existing canonical Invocation; Hive boot and legacy tests pass. Full M1 dependency/cutover **UNVERIFIED**: frozen #55 remains open and banked model escapes remain. Existing branch moves previously raw calls into Invocation, so prerequisite sequencing cannot be inferred from this branch's tests alone. |
| 2 | Authorization plus required prediction evidence | Core `test_governed_tool_persists_expected_evidence_on_canonical_invocation` and Hive `test_governed_tool_records_invocation_with_registry_tier` pass, with persisted identity assertions and real SQLite Container in Hive. Core high-impact policy is fixture-configured; deployed mutating-provider coverage **UNVERIFIED**. |
| 3 | Effective authorized tools before execution | Agent/ReAct/custom-strategy/artificer and Hive unlisted/schema/scope-confusion tests pass with backend-not-called assertions. BuildersLearning side effects retired and retirement tests pass. Universal Principal/Workspace/Goal/Run authority-envelope proof **UNVERIFIED**; pure registry exposure is not that proof. |
| 4 | Unknown/missing schemas fail closed | Core allowlist/unknown/unsupported-schema tests and Agent host-schema boundary tests pass, as do Hive legacy materialized-argument refusals. |
| 5 | Consistent constrained command contract | Bootstrap argv-only/raw-text/metacharacter tests pass; backend hardening tests pass in the 255-test run. Live Docker backend parity **UNVERIFIED**: six image/backend-dependent tests skipped, plus one Windows-only skip. |
| 6 | Host-owned reversibility | Core effect-floor tests and Hive registry-tier/legacy shared-registry tests pass; legacy resolves `hive_tool_reversibility` before Invocation at `legacy_dag_node.py:409`. SECURITY.md:35 already accurately limits the separate Sentinel approval claim. |
| 7 | Exact/recomputable expected-effect identity | SQLite reopen/fault tests pass and assert Invocation/provider/capability, exact materialized arguments/digests, expected/observed states and policy version. `contracts.py:321` stores a pre-state digest; production retrieval of original pre-state and full deployed recomputation **UNVERIFIED**. Real PostgreSQL legs were skipped. |
| 8 | Durable mismatch, no ordinary success | Core mismatch and both SQLite append/ack-interruption cases pass: immutable first mismatch, one correlated durable event after replay, PredictionMismatch raised, no provider redispatch. Cross-process high-impact observation races **UNVERIFIED**; recovery is replay-driven, not autonomous. |
| 9 | Missing required high-impact prediction is policyable | Core `test_high_impact_contract_without_expected_effect_fails_closed` passes, with complete-contract positive control. |
| 10 | Seven historical TOOL_EFFECT sites controlled/retired | Current census passes; two base chat calls now route through governed tools and four current entries are provider backends; Hive boot/chat/legacy tests and strategy retirement tests pass. Historical seventh-site identity/equivalence **UNVERIFIED**: supplied base contains six, not seven. |
| 11 | Reject deliberately introduced raw bypasses | `tests/test_check_direct_effects.py:496` and `:519` deliberately add raw Hive/browser calls and prove audit rejection; passed in the 74-test gate run. |
| 12 | #847 closes from adversarial proof first | **UNMET**: frozen `dispatch-context.json:72054` names issue #847 and `:72157` records `state=open`. Local adversarial tests do not establish closure or full child acceptance; GitHub mutations prohibited. |

## Handoff

**BLOCKED**, not integration approval. Only this evidence checkpoint changed;
no production code, tests, inventory counts, quality ledgers or grants changed.
No new test-inventory note is required. Both supplied repair findings (old
SECURITY.md claim and unbanked vulture identities) are absent at the assigned
HEAD, so a source/ledger edit would be unsupported cosmetic churn.

Residual risks: prerequisite #847 remains open, #55 production completion is not
proven, live PostgreSQL/container/Playwright checks were skipped, full pre-state
retrieval and cross-process observation stability remain unverified, and the
historical seventh TOOL_EFFECT identity is unresolved. Exact-head remote CI is
**UNVERIFIED**; no remote CI pass is inferred or requested via GitHub mutations.

Progress: checked 1 assigned issue; done 1 focused-validation item; skipped 0
issues; 0 failing test/gate commands; 1 corrected read-only inspection error;
issue completion 0. Next: authorized owner handles #847/#55 sequencing and the
explicit evidence gaps, rather than redispatching the stale-doc/vulture repair.
Finish with a local commit and confirm the worktree is clean; never push.

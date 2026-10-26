# Issue #57 — frozen repair validation d66b462e

## Scope and starting state

Assigned worktree `/home/dev/Git/wt/auto-57`, branch `auto-57`; initial clean HEAD `d2c2cd32a0a4dd2e8efdbaec680269b4e2704543`; supplied develop base `a9fdec4cb40a62ada3e897448eabc81f2410135a`. One item only: issue #57 from supplied dispatch-context.json. No remote enumeration/mutation, no unrelated fixes, no discarded work. Existing accumulated diff is preserved. Writer role assumed because lane explicitly assigns repair and a local commit.

No driver `check-*.log` files existed in this job directory at start. Logs created here are local validation, not remote CI. Prior verification claims are context only.

Edit targets frozen after initial reproduction: this evidence note only unless a locally reproduced #57 defect warrants focused production/test/inventory edits. Explicit ledger permission does not justify changing an already passing ledger.

## Reproduced initial checks

- `uv sync --locked --extra dev`: PASS, 218 packages checked.
- Exact requested `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1310 findings, 1314 reviewed identities, zero unclassified/never-allowlist. Trusted merge base selected by gate: `bb9a7fbbc752`; candidate `d2c2cd32a0a4`. No unbanked identity to repair. Log `check-vulture-local.log` in supplied job directory.
- `SECURITY.md:35` already says governed contracts construct `ReversibilityRegistry`, distinguishes classification from Sentinel approval gating (#346), and matches `tools/contracts.py:101`. Supplied stale-prose finding is not reproducible; no cosmetic edit warranted.
- Supplied frozen issue #847 remains `state=open`; criterion 12 is externally unmet. No issue closure will be attempted.

## Review and additional validation

- Read accepted ADR-050, ADR-068, ADR-081226-6b46 and ADR-004 amendment. Reconciliation: reversibility classification cannot grant authority or replace Sentinel gating; tool exposure must consume canonical Binding/Invocation, never own a second lifecycle. Removed unused AgentSpec declarations follow ADR-004's amendment, not its superseded interface sketch.
- Reviewed core contracts and real SQLite mismatch recovery/evidence tests, Hive production registry and admitted Run scope lookup. Core `GovernedToolExecutor` calls `effects.invocations.invoke`; Hive derives Workspace/Project from Run records, verifies Run/NodeRun/Attempt relationships, intersects caller tools with host registry. All three shipped Hive tools are internal/read-only; configured high-impact predictions are covered by core contracts/tests, not a deployed Hive mutation.
- Fresh core focused tests: **334 passed** (`check-core-tests-local.log`). Command covers governed contracts, shared Agent schema boundary, Agent base/factory/spec, ReAct, BuildersLearning, artificer, effect-context policy, Sentinel audit.
- Fresh Hive tests: **110 passed** (`check-hive-tests-local.log`), covering governed tools, legacy DAG adapter, boot Agent model tools and core adapter.
- Fresh bootstrap package validation: **243 passed, 7 skipped** (`check-bootstrap-tests-local.log`). Live backend parity cannot be inferred from skipped tests.
- Fresh architecture adversarial tests (`tests/test_check_direct_effects.py`, `tests/test_check_model_egress.py`): **74 passed**, including intentionally inserted raw effect paths rejected by actual scanners (`check-architecture-tests-local.log`).
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS, 3456 files formatted. Logs `check-ruff-local.log`, `check-format-local.log`.
- `uv run python scripts/check_direct_effects.py`: PASS, 51 dispositioned sites, including 4 TOOL_EFFECT provider-backend sites. This count alone does not prove equivalence to all seven historical sites.
- `uv run python scripts/check-model-egress.py`: PASS as a ratchet, but explicitly reports **12 reachable escapes awaiting #56 migration**. Passing inventory cannot prove the complete #55 dependency cutover.
- `uv run python scripts/check-suite-inventory.py`: PASS, all 21 suites match (33566 unique collected identities). No tests added; no inventory delta/note changes required.
- Security inventory: PASS (62 cited paths, 23 rows, 2 counted claims; not a general prose audit). Convergence matrix: PASS (1451 production modules classified).
- No production, test, quality ledger, or inventory edits justified. Only this note changes in this round.

## Acceptance review (fresh evidence, not inherited completion claims)

| # | Acceptance criterion | Executed evidence / remaining limitation |
| --- | --- | --- |
| 1 | Consume the real #55 Invocation seam | Production `tools/contracts.py` calls `effects.invocations.invoke`; Hive governed/legacy/boot tests passed. Complete #55 prerequisite **UNVERIFIED**; passing model-egress ratchet explicitly retains reachable escapes. No second scheduler, Goal store, execution lifecycle or authorization authority introduced. |
| 2 | Canonical authorization and required expected effects | Core `test_governed_tool_persists_expected_evidence_on_canonical_invocation` passed; verifies canonical Invocation and policy-decision/completion events. Hive production wiring tests passed. Deployed high-impact mutation **UNVERIFIED**: Hive currently exposes only three internal/read-only tools. |
| 3 | Effective authorized Agent tool set before provider | Shared Agent boundary, ReAct, artificer and Hive unlisted-tool tests passed; BuildersLearning tests pin no strategy-authored shell/GitHub effects. Universal principal/Workspace/Goal/Run authority intersection **UNVERIFIED** by this bounded run; declarations cannot be equated with grants (ADR-068). |
| 4 | Missing/unknown schema fails closed | Agent schema-boundary tests and governed unknown/unsupported-type tests passed; assert no provider/binding execution. Root, nested object/array, missing schema and repaired arguments are exercised, not just a validation helper happy path. |
| 5 | One structured command contract | Full bootstrap suite passed, including command argv contract, raw `cmd` refusal, injection/argument guards. Production `agent_loop.py` dispatches `run_command` through structured argv, not implicit shell text. Live container/microVM parity **UNVERIFIED**, seven bootstrap cases skipped. |
| 6 | Host-owned reversibility | Hive registry/legacy tier tests and independent effect-policy tests passed; contracts resolve `ReversibilityRegistry`, attach `_tool_reversibility` before Invocation. Classification alone is not approval gating; SECURITY.md accurately retains the #346 limitation. |
| 7 | Exact recomputable expected-effect evidence | Real SQLite reopen tests passed: capability/provider, Invocation id, exact arguments + digest, pre-state digest, expected and observed post-state, policy version and evidence digest are asserted. Retrieval of original production pre-state for later independent recomputation **UNVERIFIED**. |
| 8 | Durable correlated mismatch, not ordinary success | Mismatch tests and both interrupted SQLite append/ack recovery cases passed; stored false verdict survives reopen and attempted later clean observation, exactly one correlated mismatch event, no redispatch. Production database deployment/restart **UNVERIFIED** (tests exercise real local SQLite). |
| 9 | Missing high-impact predictions detectable/policyable | `test_high_impact_contract_without_expected_effect_fails_closed` passed: incomplete registration raises ExpectedEffectRequired; complete prediction contract succeeds. |
| 10 | Seven historical TOOL_EFFECT sites controlled or retired | Current census matches 51 sites/4 TOOL_EFFECT; production Hive/legacy/boot and BuildersLearning retirement tests passed. Historical seven-to-current-site equivalence **UNVERIFIED**; prior inventory prose is not independent evidence. |
| 11 | Intentional raw path rejected by architecture gate | 74 architecture tests passed, including `test_a_newly_introduced_raw_hive_tool_call_is_rejected_by_the_audit` and corresponding browser-client test. They introduce new raw calls and assert actual scanner audit returns NEW, rather than asserting a static count. |
| 12 | #847 closes first from adversarial evidence | **UNMET**: frozen dispatch source `repos/Agent-StrongHold/Project-mAIstro/issues/847` is open. Adversarial tests and retirement/removal work exist locally, but tests do not close an issue. No remote mutation/status refresh attempted. |

## Handoff / disposition

**BLOCKED**: no reproduced vulture debt or SECURITY prose defect warrants a source/ledger repair. All additional commands listed above passed; that does not establish every acceptance criterion, live backend parity, dependency closure or remote CI. Exact-head remote CI is **UNVERIFIED**, and no deterministic driver logs were supplied at start. All logs in this job directory ending `-local.log` are this worker's fresh runs.

Owner next: complete #847 acceptance/closure sequencing, resolve remaining production/historical acceptance evidence, and obtain exact-head required CI. No issue/PR closure, push, merge, grant edit or other GitHub mutation performed. This round adds no tests; existing inventory notes unchanged, all 21 suite counts verified. Preserve prior accumulated branch changes.

Progress: checked 1 assigned issue; validation done 1; issue completion 0; skipped issues 0; validation errors 0. Finalize this evidence as a local commit; never integration approval.

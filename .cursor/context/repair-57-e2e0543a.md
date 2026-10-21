# Issue #57 repair checkpoint — e2e0543a

## Frozen scope
- Assigned issue: #57 only; branch auto-57 in /home/dev/Git/wt/auto-57.
- Starting HEAD verified: 60b19de1f66ed5ac81bc6d561c09cd51d46ec863; base: 9cc5d1aca141695d747b23bd06a12cce9d8f850d.
- Initial working tree clean. No salvage patch required.
- Supplied snapshot: /home/dev/maistro/jobs/e2e0543a15e14aa7b42d2a3dd857b022/dispatch-context.json; do not refresh remote issue/PR lists.
- Work items (in order): (1) inspect existing #57 implementation/instructions/ADRs and reproduce exact vulture gate; repair evidenced retained/dead identities only, (2) focused acceptance validation and report external blockers, (3) commit all changes locally.
- File scope: existing #57 production/test files from base diff as validation inputs; quality/vulture-baseline.json only for explicitly authorized exact-debt repair; this checkpoint for results; inventory note only if tests change. No unrelated policy/ledger edits.
- No check-*.log files present in supplied job directory at start; no driver checks inferred.

## Assumptions / ambiguity
- Writer role applies (explicit lane repair + commit requirement).
- Dependency closure is external: cannot close #847 or mutate GitHub. Record snapshot evidence rather than infer closure.

## Progress
- Verified starting ref and clean worktree; extracted all 12 acceptance criteria from supplied snapshot.
- `uv sync --locked --extra dev`: PASS; exact requested vulture gate: PASS (1317 findings, 1321 base reviewed identities; no unbanked identities). No ledger amendment is justified; do not invent debt or weaken gates.
- Supplied prior artifact read: prior repair committed legacy schema/reversibility enforcement in starting HEAD. Independently confirmed SECURITY.md:35 already states registry construction and its approval-gating limitation; stale prose finding not reproducible.
- Frozen dispatch sources issues/55 and issues/847 both say open. #847 criterion 12 is UNMET externally; #55 full cutover cannot be assumed.
- No nested AGENTS.md found under the three affected packages. Relevant ADR paths resolved from disk; reading next, then focused tests. No source/test change yet justified.
- Read accepted ADR-050, ADR-068, ADR-081226-6b46 and ADR-093. Reconciliation: reversibility is host classification, never a separate authorization grant; ToolExposure must consume Binding/Invocation, not own lifecycle. Isolation is distinct from constrained argument validation.
- Read core governed contract implementation/tests and Hive registry/legacy admission/tests. Tests assert no backend on denial, durable SQLite mismatch replay, host registry tier, and live persisted Run identities; starting validation of these production paths. Vulture item completed with no repair needed; next item is focused acceptance validation.

## Fresh executed validation
All Python commands used `uv run`, with 1200-second tool timeouts. No service claims inferred from historical notes.

| Command | Outcome |
| --- | --- |
| `uv sync --locked --extra dev` | PASS |
| `python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1317 findings, no unbanked identities |
| pytest core governed contracts; Agent base/factory/spec/spawner/tool-call identity; ReAct/BuildersLearning/artificer; effect-context policy; Sentinel audit (`-x -q`) | 390 passed; `/tmp/issue57-e2e-core.log` |
| pytest Hive governed tools/legacy DAG node/Agent model tools/core adapter (`-x -q`) | 105 passed; `/tmp/issue57-e2e-hive.log` |
| pytest packages/maistro-bootstrap/tests -x -q | 236 passed, 7 skipped; `/tmp/issue57-e2e-bootstrap.log` |
| pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q | 74 passed |
| ruff check . | PASS |
| ruff format --check . | PASS: 3415 files already formatted |
| python scripts/check_direct_effects.py | PASS: 51 sites, 4 TOOL_EFFECT |
| python scripts/check-model-egress.py | PASS ratchet, **12 reachable escapes awaiting #56 migration**, not completed M1 proof |
| python scripts/check-security-inventory.py | PASS: 61 paths, 23 rows; explicitly does not check all prose |
| python scripts/check-convergence-matrix.py | PASS: 1437 modules classified |
| python scripts/check-suite-inventory.py | PASS: all 21 suites match, 33193 unique test identities |

No test addition/removal or production/ledger changes warranted by these results; no inventory delta note needed. No remote mutations.

## Acceptance review against reachable behavior

1. **Consume #55, not another executor:** `tools/contracts.py:355` delegates to the existing canonical `effects.invocations.invoke`; Hive boot adapter `adapters/maistro_core.py:287` injects the admitted executor. `test_boot_agent_tool_effect_creates_its_own_invocation` and `test_governed_tool_records_invocation_with_registry_tier` executed successfully against a real SQLite Container with persisted Run/NodeRun/Attempt. Legacy Invocation tests also passed. Repository-wide #55 prerequisite completion is **UNVERIFIED**: its snapshot is open and model-egress reports 12 banked escapes. No new execution authority introduced this round.
2. **Canonical authorization plus expected effects:** `test_governed_tool_persists_expected_evidence_on_canonical_invocation` passed, asserting both canonical policy-decision/completed events and persisted required prediction correlated to Invocation. Hive production-path tests assert its own Invocation. No shipped Hive high-impact tool is configured (registry exposes web_search, browse_url, clarify as internal); the required-prediction test uses the public production executor with a host-registered contract, not a live high-impact product operation.
3. **Effective authorized tools before provider:** Agent base/factory, ReAct/artificer and Hive denial tests passed; Agent `base.py:892` checks identity before Sentinel and providers, Hive intersects caller exposure with host registry, and core re-resolves canonical Binding scope. BuildersLearning Frank/Mason no-effect tests passed. Full principal/Workspace/Goal/Run effective-envelope equivalence for all retained legacy consumers is **UNVERIFIED**, not inferred from passing allowlist subsets or Binding registration.
4. **Missing/unknown schema fail closed:** core `test_agent_allowlist_and_unknown_schema_fail_before_backend`, all unsupported-type cases, and Hive `test_a_raw_tool_without_a_host_schema_is_refused` passed with no backend calls. Legacy materialized-argument validation tests passed. Validator supports a documented subset of JSON Schema, not full dialect compliance.
5. **Consistent structured commands:** bootstrap argv schema/dispatch, injection refusal, local Sandbox and mocked ContainerSandbox hardening tests passed within 236 passes. `agent_loop.py:413` dispatches run_argv, Docker `container_sandbox.py:413` passes argv to _exec, local `sandbox.py:261` invokes subprocess without shell. Seven skipped cases mean live Docker/Windows parity is **UNVERIFIED**; hardware-VM backend equivalence also **UNVERIFIED**. Isolation alone is not accepted as an argument grammar proof.
6. **Host-owned reversibility:** `ToolContractRegistry` constructs the registry at `contracts.py:101`; Hive standard tier test and three legacy registry-tier cases passed. Host reclassification test denies before backend and asserts `tool.reversibility` canonical policy evidence despite caller downgrade strings. SECURITY.md:35 already states construction and separately disclaims Sentinel.resolve_tier integration (#346); reported claim drift is absent, not repaired again.
7. **Exact/recomputable prediction identity:** real SQLite reopen test passed in both interrupted-append modes and asserts capability/provider, exact materialized arguments/digest, pre-state digest, expected/observed state, Invocation id, policy version and event evidence digest. Execution uses host comparison (`expected_effect.py:66`). Actual PostgreSQL restart, retrieval of the pre-state behind its digest, and high-impact legacy adapter prediction parity remain **UNVERIFIED**; a digest alone is not claimed to recover unavailable pre-state.
8. **Durable mismatch not ordinary success:** mismatch and interrupted-append/reopen/replay tests passed; raises PredictionMismatch, preserves first false verdict despite later success observation, appends one correlated mismatch event and never redispatches. Recovery requires replay; no atomic outbox/autonomous recovery claim. Provider cannot submit a replacement verdict via the executor API.
9. **Missing high-impact expected effects detectable:** `test_high_impact_contract_without_expected_effect_fails_closed` passed; incomplete host contract is refused at registration and complete one accepted. Legacy future high-impact prediction parity is **UNVERIFIED**, not implied by independent mutation/irreversibility approval tests.
10. **Historical seven TOOL_EFFECT entries:** inspected exact supplied base ledger with git show: only six TOOL_EFFECT entries exist there (two chat wrappers, two legacy helpers, two BrowserClient methods). Current chat routing and production entry-point tests passed; the direct-effect gate matches four retained provider-backend sites. Legacy no-identity/schema/tier tests passed. The issue's historical seventh identity and full historical seven-site control equivalence remain **UNVERIFIED**; do not manufacture an identity or infer parity from inventory membership.
11. **Intentional direct/raw bypass rejected:** 74 gate tests passed, including `tests/test_check_direct_effects.py:496` raw Hive dispatcher injection and `:519` raw BrowserClient injection; both introduce a new site and assert audit rejection. Runtime schema-less extension and missing canonical-identity refusal tests also passed. The finite AST inventory is not proof against arbitrary reflective Python bypasses.
12. **#847 closes first:** **UNMET**. Frozen `dispatch-context.json` source `repos/Agent-StrongHold/Project-mAIstro/issues/847` has `state=open`. Its adversarial test subsets were executed above, but no complete #847 closure proof or external mutation is available/authorized. This alone precludes MERGE-READY.

Remote CI remains **UNVERIFIED**: no driver check-*.log files were present at start; historical statuses are not exact-head green evidence.

## Handoff

Changed only this checkpoint (frozen scope, independent validation, acceptance limitations). No production/test/policy/grant/ledger edits: the exact requested scanner passes and the alleged stale documentation is already corrected. An invented source/ledger repair would not address actual evidence. All twelve criteria checked; external closure and explicit UNVERIFIED items remain blocked rather than being relabeled complete.

Progress: checked 1 issue, done 1 validation item (no new code repair warranted), skipped 0 issues, errors 0 in executed validation. Next: authorized owners sequence #847/#55 and complete the missing historical/backend/effective-envelope evidence; verifier reviews this local handoff. Finish with a local commit, never push.

# Issue #57 salvage and validation — 18abbc04

## Frozen scope

- Sole item: #57; worktree `/home/dev/Git/wt/auto-57`, branch auto-57.
- Verified starting HEAD cb87a0ebce65151c5cff92a98f43f0e1d92829df. Assigned base bb9a7fbbc7524be0f63d3b74b76a0edda459b60a.
- Incoming staged changes (12 files) preserved in `/home/dev/Git/wt/incoming-57-18abbc.patch` including staged additions (`git diff HEAD --binary`). Never discarded.
- Frozen repair files: the 12 incoming paths, this report, and only evidence-backed issue #57 fixes in adjacent governed-tool code/docs; vulture ledger only if exact gate proves unbanked retained identities.
- Evidence: supplied dispatch-context.json; prior incoming report `.cursor/context/repair-57-3a6a7088.md` is untrusted until repeated checks. No re-fetch/re-enumeration of issue/PR lists.
- Job directory initial listing contains no check-*.log files. Driver evidence unavailable. New local logs will be recorded here separately.
- Ambiguity: lane is repair/writer despite generic verifier text. Proceed as writer: preserve, validate, locally commit. No GitHub mutation. #847 prerequisite closure cannot be repaired by local code.

## Progress

- Repository instructions and incoming handoff read. Incoming implementation narrows shared Agent admission and wires Hive schema exposure to its canonical contracts. Read accepted ADR-004 (including amendment), ADR-050, ADR-068, ADR-081226-6b46 and ADR-081226-a66b, incoming production diff and new tests. Repair uses existing Agent/Sentinel admission; Hive exposure is a detached projection, not another policy/execution owner. Goal -> Graph -> Run -> NodeRun -> Attempt remains unchanged.
- SECURITY.md:35 already accurately documents registry construction versus incomplete approval integration; prior prose finding not reproducible. No cosmetic edit warranted.
- Prior result exists and was read; it confirms missing-schema fallback was the unresolved defect on starting HEAD. Supplied snapshot confirms both #55 and #847 state=open. Criterion 12 remains externally blocked, regardless of green local tests.
- New tests include real `Agent.handle()` adversarial custom strategies, two-turn nested schema mutation, repaired-input validation, valid controls and composed Hive persisted Invocation. Existing positive fixture edits reviewed: they explicitly register previously synthetic lookup schemas and retain authorization/trust/identity assertions.
- Fresh `uv sync --locked --extra dev`: PASS. Exact assigned vulture gate: PASS (1311 findings, 1315 reviewed identities, no unbanked identities). No ledger edits justified.
- Fresh core focused suite: **956 passed** (agents, governed contracts, effect policy, Sentinel audit). Fresh Hive production-path suite: **107 passed** (governed tools, legacy node, Agent/model tools, core adapter). Logs: `writer-core.log`, `writer-hive.log`, `writer-vulture.log` in this job directory. These are current local runs, not inherited claims or remote CI.
- Inspected production shared admission and canonical ToolContractRegistry/GovernedToolExecutor plus Hive context/Binding composition. Existing exact high-impact evidence is persisted before provider execution; Hive exposure projection does not execute or authorize by itself.
- Fresh red/green proof: loaded the exact starting-HEAD Agent source **in memory only** and ran the new schema test module: **9 failed, 3 passed**, including actual forbidden backend awaits. Current implementation passes all 12 in the 956-test run. Tree was never reverted or replaced. `writer-schema-red.log` preserves expected failures.
- Fresh whole-tree ruff check and format check PASS (3444 files); focused Agent mypy PASS. Bootstrap tests **243 passed, 7 skipped** (Windows-only plus six unavailable Docker/image cases): live backend parity is not proven. Architecture adversarial tests **74 passed**, including intentionally injected raw/direct tool effects rejected by gates. Logs: `writer-{ruff,format,mypy,bootstrap,architecture}.log`.
- Fresh gates all PASS: radon (127 current blocks/128 reviewed, 0 new/regressed, 1 nonblocking stale identity); direct effects (51 sites, 4 TOOL_EFFECT); model-egress nonexpansion (**12 retained reachable escapes**, not complete architectural cutover); security inventory (explicitly not all prose); convergence (1447 modules); suite inventory (21 suites, 33482 unique tests, +14 explained). `git diff --check` PASS. Logs: `writer-check-*.log` in this job directory. These local log names do not represent supplied driver or remote checks.
- Independently inspected assertions in governed-contract persistence/mismatch/reopen tests, effect policy, command contract and shipped Hive tests; acceptance limits below deliberately retain unproven portions. Updated existing inventory note with current validation provenance; no additional tests or count changes beyond incoming +12 core/+2 Hive.

## Acceptance review

| # | Criterion | Current executed evidence / limits |
|---|---|---|
| 1 | Consume #55 canonical seam | Real SQLite Container/Run/NodeRun/Attempt Hive tests and boot Agent.handle -> ReAct -> correlated canonical tool Invocation PASS. Full #55 prerequisite completion **UNVERIFIED**: snapshot lists #55 open; model-egress gate retains 12 reachable escapes. No new executor/lifecycle authority. |
| 2 | Canonical authorization + predictions | Executed governed-contract tests assert canonical policy/completion events, expected evidence and Invocation correlation. Hive production-route tests assert completed Invocation. Shipped high-impact/mutating tool effect **UNVERIFIED** (prediction case uses library fixture). |
| 3 | Effective allowlist | Agent/strategy and Hive denial tests PASS: undeclared/unknown names cannot dispatch; host-intersection narrows. Complete principal/owner/Workspace/Goal/Run envelope across every consumer **UNVERIFIED**. ADR-004 amendment overrides removed declarative tools_allowed/write_scopes fields. |
| 4 | Missing/unknown schemas fail closed | New strategy-independent Agent.handle tests PASS: absent/non-object/unknown schemas, forged/widened exposure, two-turn mutation, invalid and empty Sentinel repairs do not call raw backend; scoped denial asserted. Valid/no-argument controls PASS. Starting-HEAD in-memory probe has 9 regression failures. Universal standalone integration parity **UNVERIFIED**. |
| 5 | Structured command contract | Bootstrap suite 243 PASS: schema requires argv, raw cmd and metacharacters rejected, structured local/container path assertions. Live supported-backend parity **UNVERIFIED**: six container/image tests and one Windows-only test skipped. |
| 6 | Host-owned reversibility | Executed Hive and legacy tests assert registry tier, reject caller downgrade, enforce host reclassification. SECURITY.md:35 accurately distinguishes classification from still-incomplete Sentinel approval integration. |
| 7 | Recomputable exact evidence | SQLite reopen tests assert capability/provider, exact arguments/digest, pre-state digest, expected/observed outcome, policy version and Invocation id. Actual pre-state retrieval and all-consumer high-impact parity **UNVERIFIED**; digest retention alone is not retrievable evidence. |
| 8 | Durable immutable mismatch | PredictionMismatch, host verdict immutability and interrupted-append (before/after commit) SQLite reopen/retry tests PASS; one correlated event, no redispatch. Autonomous reconciliation without retry **UNVERIFIED**. |
| 9 | Required predictions detectable | High-impact contract with missing callbacks/version raises ExpectedEffectRequired; complete control accepted. Future legacy high-impact policy parity **UNVERIFIED**. |
| 10 | Seven historical TOOL_EFFECT dispositions | Current census and shipped/retired-path tests PASS; exact historical seven-site equivalence **UNVERIFIED** (four current tool sites does not prove historical equivalence). |
| 11 | Raw bypass regression gate | 74 direct-effect/model-egress adversarial tests PASS, intentionally introduced Hive/BrowserClient raw paths rejected. Not proof against arbitrary reflective Python code. |
| 12 | #847 closes first | **UNMET**: frozen dispatch source `repos/Agent-StrongHold/Project-mAIstro/issues/847` has state=open. No local test or code substitutes for closure; no GitHub mutations permitted. |

Remote exact-head CI **UNVERIFIED**; no driver check-*.log files were supplied. Earlier claims/statuses are not inferred green.

## Changed files and validation commands

Preserved incoming production changes:
- `packages/maistro-core/src/maistro/agents/base.py`: omit fabricated unknown exposures; detached host schema snapshot; refuse absent schema; validate exact materialized arguments after Sentinel including empty repairs; existing scoped audit sink.
- `packages/hive-conductor/backend/services/governed_tools.py`: detached exposure projection of canonical ToolContractRegistry.
- `packages/hive-conductor/backend/adapters/maistro_core.py`: pass projection to existing Agent factory.

Preserved tests: core `tests/agents/{test_tool_schema_boundary,test_agent_seam_fail_closed,test_base,test_tool_call_identity,test_trust_pipeline_equivalence}.py`; Hive `backend/tests/{test_governed_tools,test_agent_model_tools}.py`. Preserved prior report `.cursor/context/repair-57-3a6a7088.md`; updated `docs/testing/inventory-notes/issue-57-agent-schema-boundary.md`; added this report.

All validation used 1200-second tool timeouts:

- `uv sync --locked --extra dev` PASS.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` PASS. No ledger/grant amendments warranted or made.
- `uv run pytest packages/maistro-core/tests/agents packages/maistro-core/tests/tools/test_governed_contracts.py packages/maistro-core/tests/capabilities/test_effect_context_policy.py packages/maistro-core/tests/security/sentinel/test_audit.py -x -q` — 956 PASS.
- `uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py packages/hive-conductor/backend/tests/test_legacy_dag_node.py packages/hive-conductor/backend/tests/test_agent_model_tools.py packages/hive-conductor/backend/tests/test_maistro_core_adapter.py -x -q` — 107 PASS.
- `uv run pytest packages/maistro-bootstrap/tests -x -q -rs` — 243 PASS, 7 skips above.
- `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q` — 74 PASS.
- `uv run ruff check .`; `uv run ruff format --check .`; `uv run mypy packages/maistro-core/src/maistro/agents/base.py` — all PASS.
- `uv run python scripts/check-radon-baseline.py`, `check_direct_effects.py`, `check-model-egress.py`, `check-security-inventory.py`, `check-convergence-matrix.py`, `check-suite-inventory.py` (each through uv run python scripts/) — all PASS, qualifications above.
- `git diff --check` PASS.
- In-memory starting-HEAD source regression probe via `uv run python`, then `pytest.main(['packages/maistro-core/tests/agents/test_tool_schema_boundary.py', '-q', '--tb=short'])` — expected exit 1, 9 failed/3 passed. No tree edits for the probe.

## Handoff

**BLOCKED** at issue level: #847 closure and residual acceptance evidence need authorized owner/verifier review. Focused repair is locally validated, not integration approval. No push/merge, issue/PR/comment mutation, baseline/grant change, destructive command, or discarded salvage. Final action: local commit including all incoming changes and this independent evidence.

Progress: {checked: 1, done: 1, skipped: 0, errors: 0, next: "owner/verifier review of prerequisite closure and explicitly unverified acceptance portions"}. Validation skipped seven platform/container-dependent test cases, not the assigned issue. No final unexpected failed commands.

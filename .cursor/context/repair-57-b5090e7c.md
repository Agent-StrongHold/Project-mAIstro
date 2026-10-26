# Issue #57 repair — b5090e7c

## Frozen scope
- Sole item: issue #57; worktree `/home/dev/Git/wt/auto-57`, branch `auto-57`.
- Starting HEAD: `7992ef73d726d4b5c5311ba4b4405d7d9d869e18`; supplied develop base: `161dedc06344b3d9630f3b79be9418088a5bff99`.
- Initial working tree clean; no incoming edits to salvage.
- Evidence: supplied job `dispatch-context.json`, prior job `2c71a0b625fc4f45ab9fe0dcbe26ca6b/result.json`, existing issue-57 implementation/tests, relevant ADRs, SECURITY.md, exact vulture gate. No GitHub refresh or mutations.
- Repair targets: verify alleged security-documentation drift and exact vulture debt; fix only reproduced defects. Acceptance review is limited to this frozen issue and its existing changes.
- No `check-*.log` files were supplied in this job directory at initial inspection. Run fresh validation; do not treat prior claims as evidence.

## Initial evidence
- Prior result reports #847 open and criterion 12 unmet; external closure is prohibited in this lane. Proceed with local validation, not issue closure.
- Prior result says SECURITY.md drift and vulture debt did not reproduce. Recheck independently.

## Validation and outcome
- `uv sync --locked --extra dev`: passed (`check-sync.log`).
- Exact CI vulture scan: passed (`check-vulture.log`): 1298 findings / 1302 reviewed identities, zero unclassified or never_allowlist. No ledger amendment is justified.
- SECURITY.md:35 already states governed contracts construct the registry and distinguishes approval gating (#346). Alleged drift does not reproduce; no cosmetic repeat repair.
- Supplied dispatch explicitly records #847 open; acceptance 12 remains unmet.
- Initial guessed ADR-050 filename did not exist; skipped it, resolved the actual filename from one directory snapshot before continuing.
- Production legacy dispatch now records host registry reversibility in Invocation request. Older handoff claims that it lacks a tier are stale; do not adopt them.
- Read accepted ADR-050, ADR-068, ADR-081226-6b46: tool exposure is not authority, registry classification is not an approval grant, and canonical Invocation owns fulfillment. No architecture reconciliation or new execution authority is needed.
- Core tools/capabilities plus adjacent Agent/schema/ReAct/BuildersLearning/artificer/spec/audit tests: **1583 passed, 12 skipped**, one unawaited fake-process coroutine warning (`check-core-tests.log`).
- Hive production governed-tools/legacy-node/Agent-model/core-adapter tests: **112 passed** (`check-hive-tests.log`).
- Full bootstrap package: **255 passed, 7 skipped** (`check-bootstrap-tests.log`). Live skipped backends are not acceptance proof.
- `uv run ruff check .` and `uv run ruff format --check .`: passed (3490 files).
- Architecture/security adversarial gate tests: **74 passed** (`check-gate-tests.log`), including intentionally introduced raw Hive dispatcher and BrowserClient calls.
- Direct-effect inventory: passed, 51 sites including 4 retained TOOL_EFFECT sites. Model-egress: passed its ratchet but explicitly reports **12 reachable escapes awaiting #56**; not proof of complete M1 cutover. Security inventory (limited prose check), convergence (1462 modules), and all 21 suite inventories passed. No test additions or inventory deltas in this round.
- Repeated bootstrap/tools/capabilities tests with `-rs`: **1541 passed, 19 skipped** (`check-skips.log`). Skips: Windows-only case, six missing Docker/builders-image cases, four missing Playwright cases, eight PostgreSQL cases without configured DSNs. These deployment legs remain UNVERIFIED; no attempt to hide skips.
- Frozen dispatch also records #55 open. Existing production seams are tested, but the prerequisite's completion cannot be certified from ratchet success.
- `git diff --check`: passed. Only this checkpoint is modified; production code, tests, inventory, ledgers and grants remain untouched.

## Acceptance review

These are this round's executed results, not adoption of earlier completion claims.
All logs below are in `/home/dev/maistro/jobs/b5090e7cae8743ef923c378ce193cd95/`.

| # | Criterion | Evidence / limitation |
|---|---|---|
| 1 | Consume #55's canonical seam | `contracts.py:_invoke_admitted` delegates to the existing governed Invocation service; Hive real-SQLite boot and legacy tests pass in `check-hive-tests.log`. No competing lifecycle found. Complete prerequisite cutover **UNVERIFIED**: frozen #55 is open and model-egress reports existing reachable escapes. |
| 2 | Canonical authorization and required expected effects | Core `test_governed_tool_persists_expected_evidence_on_canonical_invocation` passes, asserting policy/completion events and Invocation-bound predictions. Hive `test_governed_tool_records_invocation_with_registry_tier` passes through real Container stores. Configured high-impact coverage is library-level; shipped Hive contracts are read-only. |
| 3 | Effective tool set enforced before provider execution | Core Agent/base/schema-boundary, ReAct, artificer and BuildersLearning tests pass; Hive unlisted-tool/model-tool/strategy-bypass refusals pass. `governed_hive_tool` intersects caller tools with host exposure; canonical Binding/policy remains the authorization ceiling. Full legacy Agent/principal-envelope equivalence **UNVERIFIED** by these focused tests. |
| 4 | Missing/unknown schema fails closed | Core `test_agent_allowlist_and_unknown_schema_fail_before_backend`, unsupported-type parametrizations and Hive `test_a_raw_tool_without_a_host_schema_is_refused` pass. Legacy materialized-argument tests refuse before backend calls. |
| 5 | Constrained structured command contract | Full bootstrap suite passes, including `test_agent_loop_command_contract.py` argv-only/raw-command/metacharacter tests. Six live container tests skip for missing Docker/image; production backend execution parity **UNVERIFIED**, not inferred from mocks. |
| 6 | Host-owned reversibility | Hive registry and Invocation-tier tests pass, including legacy shared registry and reclassification reaching canonical policy. `legacy_dag_node.py:_run_tool_node` now puts registry tier into Invocation request; older handoff gap does not reproduce. Sentinel approval integration remains explicitly out of scope of the SECURITY.md claim. |
| 7 | Exact/recomputable expected-effect binding | Core caller-mutation tests and both real SQLite close/reopen fault cases pass. They assert exact arguments, provider/capability, pre-state/argument digests, Invocation/correlation, expected/observed state and policy version. PostgreSQL restart **UNVERIFIED** (DSNs unset). |
| 8 | Durable mismatch cannot become ordinary success | Core durable mismatch plus two SQLite append/ack-loss recovery tests pass; replay preserves mismatch and emits one correlated canonical event without redispatch. Observation/event writes remain separate; recovery requires replay. Cross-process race behavior **UNVERIFIED** here. |
| 9 | Required high-impact prediction is policyable | `test_high_impact_contract_without_expected_effect_fails_closed` passes: incomplete host contracts cannot register; complete contract is accepted. |
| 10 | Seven historical tool sites migrated/retired/reclassified | Direct-effect gate passes (51 total / 4 retained TOOL_EFFECT provider sites). Base-to-HEAD ledger diff shows two chat sites replaced with governed wrappers and four backend sites reclassified beneath Invocation; chat/boot/legacy tests pass. Historical seventh-site equivalence is **UNVERIFIED**: inventory history says one left with #56, but that statement alone is not executed behavioral proof. |
| 11 | Introduced raw path rejected by architecture gate | `check-gate-tests.log`: 74 passed, including deliberately introduced raw Hive dispatcher and BrowserClient calls rejected by audit. |
| 12 | #847 closes first with adversarial verification | **UNMET**: frozen dispatch records `/issues/847` state=open. Relevant adversarial subsets pass locally, but cannot establish full child-issue closure; no GitHub mutation or refresh performed. |

## Commands

- `uv sync --locked --extra dev`
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
- `uv run pytest packages/maistro-core/tests/tools packages/maistro-core/tests/capabilities packages/maistro-core/tests/agents/test_base.py packages/maistro-core/tests/agents/test_factory.py packages/maistro-core/tests/agents/test_tool_schema_boundary.py packages/maistro-core/tests/agents/strategies/test_react.py packages/maistro-core/tests/agents/strategies/test_builders_learning.py packages/maistro-core/tests/agents/artificer/test_strategy.py packages/maistro-core/tests/agents/spec/test_agent_spec.py packages/maistro-core/tests/security/sentinel/test_audit.py -x -q`
- `uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py packages/hive-conductor/backend/tests/test_legacy_dag_node.py packages/hive-conductor/backend/tests/test_agent_model_tools.py packages/hive-conductor/backend/tests/test_maistro_core_adapter.py -x -q`
- `uv run pytest packages/maistro-bootstrap/tests -x -q`
- `uv run pytest packages/maistro-bootstrap/tests packages/maistro-core/tests/tools packages/maistro-core/tests/capabilities -x -q -rs`
- `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q`
- `uv run ruff check .`; `uv run ruff format --check .`
- `uv run python scripts/check_direct_effects.py`
- `uv run python scripts/check-model-egress.py`
- `uv run python scripts/check-security-inventory.py`
- `uv run python scripts/check-convergence-matrix.py`
- `uv run python scripts/check-suite-inventory.py`
- `git diff --check`

All executed commands above passed. Commands used 1200-second validation timeouts.
No current remote CI status was established: **UNVERIFIED**. No test additions,
so no new inventory-delta note is required. No source, ledger or grant edits were
justified by the actual repair evidence.

## Handoff

Verdict: **BLOCKED**, not merge/integration approval. Only this evidence checkpoint
changed. Do not repeat the already-fixed SECURITY.md wording or amend a clean
vulture ledger to manufacture a repair. Remaining owner work is prerequisite
sequencing (#55/#847), missing acceptance/deployment evidence, and remote CI.

Progress: checked 1 assigned issue; done 1 local validation item; skipped 0 issues;
errors 0 validation failures. Issue completion remains blocked. Next: verifier /
authorized owner reviews this committed evidence and resolves the external
prerequisites. No pushes, PRs, comments, closures or other GitHub mutations.

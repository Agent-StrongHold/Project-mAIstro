# Issue 57 repair — cf70231d

## Frozen scope
- Assigned writer worktree `/home/dev/Git/wt/auto-57`, branch `auto-57`.
- Verified clean start at `93bfd15b8693444e03fd13541d444e2f491f38e7`.
- Frozen develop base `a9fdec4cb40a62ada3e897448eabc81f2410135a` resolves locally.
- Process only issue #57 using supplied `dispatch-context.json`; no remote enumeration or GitHub mutations.
- Files eligible for this repair: governed-tool production/test files already in the issue diff, `SECURITY.md`, relevant inventory notes, `quality/vulture-baseline.json` only if exact scanner evidence requires an amendment, and this evidence note.
- Prior result read: predecessor ended BLOCKED, reporting #847 open and model-egress gate failure; those claims need current verification.
- No `check-*.log` files were supplied in the job directory listing. Current local validation will be recorded separately.

## Assumptions
- Dispatch asks for writer repair; verifier-only no-edit instruction does not apply to this lane.
- No develop-sync conflict exists (clean starting tree); do not perform an unsolicited merge.
- Criterion requiring another issue to close cannot authorize closing it or expanding this assignment.

## Progress
- Initial state and prior-result inspection complete; frozen #57 has 12 criteria and frozen #847 is open (criterion 12 externally unmet).
- `uv sync --locked --extra dev` PASS; exact vulture scan PASS: 1310 findings, 1314 reviewed identities, zero unclassified/never_allowlist. No ledger amendment justified.
- `SECURITY.md:35` already correctly describes registry construction and remaining Sentinel approval limitation; reported drift not reproduced.
- One attempted ADR read used a guessed nonexistent filename (`ADR-050-capability-providers.md`), not found; skipped. Resolved actual ADR paths from local file inventory before further reads.
- Read accepted ADR-050, ADR-068, ADR-081226-6b46 and amended ADR-004 completely. Reconciliation: contracts remain exposure/classification, not a second authority; effective tool authority stays at canonical Binding/Invocation. No lifecycle/scheduler/store changes.
- Inspected core contracts, adjacent adversarial tests, Hive production composition, expected-effect model and canonical Invocation persistence.
- Reproduced actual argument-identity defect: `uv run pytest packages/maistro-core/tests/tools/test_governed_contracts.py -k caller_mutation -q` FAILED (2 failed, 27 deselected). Both Binding-lookup and provider-entry suspensions let the caller replace a string with an integer and append an integer to a string array after schema validation; provider received both invalid changes. Provider-entry case diverges from already-persisted input/evidence.
- Added 2 event-synchronized regression cases with inventory note. Fixed `GovernedToolExecutor.execute` to deep-snapshot arguments before its first await, so schema validation, predictions, effect key and backend share detached input. This is a bounded #57 contract/evidence repair; no authority or lifecycle changes.

## Fresh validation (1200-second command timeouts)
- Focused core governed contracts/Agent schema/base/factory/spec/ReAct/BuildersLearning/artificer/effect policy/Sentinel audit: **336 passed**, including both formerly red regressions.
- Focused Hive governed-tools/legacy DAG/model-tools/core-adapter: **110 passed**.
- Full bootstrap package: **255 passed, 7 skipped**; live substrate parity not proven by skips.
- Architecture direct-effect/model-egress gate adversarial tests: **74 passed**.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3457 files).
- Test total so far: **775 passed, 7 skipped**; initial red run intentionally failed 2 tests against unfixed behavior.

## Post-repair gates
All PASS with `uv run` and 1200-second command timeouts:
- `python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: 1310 findings / 1314 reviewed, zero unclassified/never_allowlist; no ledger changes warranted. Exact arguments confirmed from `.github/workflows/vulture-ratchet.yml:82`.
- `python scripts/check-suite-inventory.py`: all 21 suites match, 33646 unique test identities, zero duplicated evidence. New inventory note accounts for +2 core tests.
- `python scripts/check_direct_effects.py`: all 51 sites dispositioned, 4 TOOL_EFFECT.
- `python scripts/check-model-egress.py`: no candidate expansion; explicitly retains **12 reachable escapes awaiting #56**. This is NOT proof of full #55 cutover.
- `python scripts/check-security-inventory.py`: 62 cited paths, 23 rows, 2 counted claims match. Does not verify all prose.
- `python scripts/check-convergence-matrix.py`: all 1451 production modules classified.
- `git diff --check`: PASS.
- `python scripts/check-ratchet-provenance.py`: PASS (54 quality consumers explicit provenance; all delegated ratchets passed). Existing scanner SyntaxWarnings were non-fatal.
- `python scripts/check-shipped-surface-truth.py`: PASS.

## Acceptance assessment
| # | Criterion | Executed evidence and limits |
| --- | --- | --- |
| 1 | Consume canonical #55 Invocation seam | Inspected Hive production composition and contracts delegation to `effects.invocations.invoke`; 110 Hive integration tests passed. Full #55 prerequisite completion **UNVERIFIED**; model-egress census retains 12 banked reachable escapes. No second executor/authority introduced by this repair. |
| 2 | Canonical authorization plus required expected effects | Core persisted-prediction test and Hive Invocation/registry-tier integration tests passed. Hive's shipped tool registry is internal/read-only; live high-impact production mutation **UNVERIFIED**. |
| 3 | Effective Agent tool/capability set enforced before execution | Core Agent/ReAct/artificer/schema-boundary and Hive denial tests passed, including strategy-originated calls and retired BuildersLearning effects. Complete principal/Workspace/Goal/Run envelope for all providers **UNVERIFIED**. |
| 4 | Missing/unknown schemas fail closed | Core unknown-name/schema, unsupported root/nested types and Agent boundary tests passed. New red/green race regressions ensure the input validated is the input dispatched, even across admission awaits. |
| 5 | Constrained structured command across backends | Full bootstrap suite: 255 passed, 7 skipped, including argv/raw-command/injection controls. Live skipped backend parity **UNVERIFIED**. |
| 6 | Host-owned reversibility | Registry construction and lookup inspected in contracts/Hive composition; core policy-floor and Hive/legacy registry-tier tests passed. SECURITY.md correctly distinguishes classification from still-unwired Sentinel registry-based approval (#346). |
| 7 | Exact recomputable expected-effect identity | Core real SQLite reopen tests passed, asserting Invocation/provider/capability/materialized arguments/pre-state digest/post-state/policy identity. New two-stage race tests red before fix, green after; provider arguments exactly match persisted request/effect key/expected-evidence digest. Independent production pre-state retrieval/live deployment restart **UNVERIFIED**. |
| 8 | Durable mismatch cannot become ordinary success | Both SQLite mismatch append/ack interruption cases passed, preserve first verdict across reopen/replay and emit one correlated event without redispatch; attempted clean overwrite remains false. |
| 9 | Missing high-impact predictions detectable/policyable | High-impact registration without complete prediction contract fails; complete-contract positive control passed. |
| 10 | Seven historical TOOL_EFFECT sites hardened or retired | Current direct-effect census matches 51 sites/4 TOOL_EFFECT, Hive/legacy tests and BuildersLearning no-effect tests passed. Full historical seven-site control-equivalence **UNVERIFIED**; census membership alone cannot prove it. |
| 11 | Intentional raw bypass rejected by architecture gate | 74 architecture tests passed, including injected raw Hive/browser tool paths rejected as new direct effects. |
| 12 | #847 closes from adversarial tests first | **UNMET**: frozen dispatch source `repos/Agent-StrongHold/Project-mAIstro/issues/847` is open. No GitHub mutations; local tests cannot fulfill external closure sequencing. |

## Exact test commands
All use the assigned worktree and 1200-second timeouts:
```text
uv run pytest packages/maistro-core/tests/tools/test_governed_contracts.py -k caller_mutation -q
# Initial RED against unfixed code: 2 failed, 27 deselected (both invalid caller mutations reached provider).
uv run pytest packages/maistro-core/tests/tools/test_governed_contracts.py packages/maistro-core/tests/agents/test_tool_schema_boundary.py packages/maistro-core/tests/agents/test_base.py packages/maistro-core/tests/agents/test_factory.py packages/maistro-core/tests/agents/spec/test_agent_spec.py packages/maistro-core/tests/agents/strategies/test_react.py packages/maistro-core/tests/agents/strategies/test_builders_learning.py packages/maistro-core/tests/agents/artificer/test_strategy.py packages/maistro-core/tests/capabilities/test_effect_context_policy.py packages/maistro-core/tests/security/sentinel/test_audit.py -x -q
# GREEN: 336 passed, including both regressions.
uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py packages/hive-conductor/backend/tests/test_legacy_dag_node.py packages/hive-conductor/backend/tests/test_agent_model_tools.py packages/hive-conductor/backend/tests/test_maistro_core_adapter.py -x -q
# 110 passed.
uv run pytest packages/maistro-bootstrap/tests -x -q
# 255 passed, 7 skipped.
uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q
# 74 passed.
```

## Handoff
Changed files:
- `packages/maistro-core/src/maistro/tools/contracts.py`: snapshot materialized arguments before admission awaits.
- `packages/maistro-core/tests/tools/test_governed_contracts.py`: two red/green async mutation regressions.
- `docs/testing/inventory-notes/issue-57-materialized-argument-snapshot.md`: +2 core tests.
- This evidence note.

**BLOCKED** at issue level despite a verified bounded repair: #847 remains open in frozen evidence; complete production/prerequisite/historical guarantees above remain UNVERIFIED. Remote exact-head CI **UNVERIFIED** (no supplied driver check logs). Owner must sequence #847 and resolve remaining acceptance proof. No source/ledger changes made for stale SECURITY.md/vulture findings because neither reproduced. No push, merge, PR/issue mutation, gate weakening or other authority introduced.

Progress: checked 1 assigned issue; done 1 bounded repair; skipped 0 items; residual failed validations 0 (initial 2-test RED was intentional). Next: commit locally, confirm clean state, and hand off the external blockers. Do not mark issue merge-ready or close it.

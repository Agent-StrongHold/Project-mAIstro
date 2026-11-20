# Issue 57 repair — 5dd573ba

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-57`, branch `auto-57`.
- Starting HEAD `ae9e146ca7d99cc920361573b9b35745a28ed910`; base `afffa63094e9b7ee7506eadb23f6c775a820224a`.
- Single item: issue #57, supplied dispatch-context.json only; no remote enumeration or mutations.
- Focus: exact vulture CI gate repair, reported SECURITY.md drift, and focused verification of existing acceptance behavior. Inspect only related production code, tests, ADRs, gates, and inventory notes.
- Initial worktree clean; no incoming edits to salvage.
- No `check-*.log` files supplied in this job directory. Driver verification cannot be assumed.
- Prior result was BLOCKED: #847 open, full #55 completion and remote exact-head CI unverified. These are evidence to recheck, not proof of current behavior.

## Progress

- Read repository instructions and frozen issue acceptance text.
- Ambiguity: this is a writer repair despite shared verifier/writer wording. Proceed with focused evidence-based edits and a local commit, as explicitly assigned.
- External closure cannot be performed in this lane; criterion 12 will remain unmet if the frozen #847 evidence is still open.
- Exact vulture CI command PASS: 1310 findings, 1314 reviewed identities, zero unclassified / never_allowlist; actual base afffa63094e9. Log `/tmp/auto-57-5dd-vulture.log`. No ledger amendment justified by current findings.
- Reported SECURITY.md:35 drift is not reproduced: it already describes registry construction and distinguishes classification from remaining Sentinel registry-based approval debt (#346). No cosmetic edit warranted.
- Frozen #55 and #847 sources both remain `open`. Full #55 completion cannot be inferred from tool-local tests; #847 closure criterion 12 is unmet.
- Read accepted ADR-081226-6b46 and amended ADR-004. Tool metadata does not grant authority; canonical Binding/Invocation remain the effect authority. Two guessed ADR filenames were not found; skipped those paths, resolve exact names before further reads.
- Inspected complete core contracts: registry-owned schemas/tiers, pre-await argument deepcopy, canonical Binding resolution/Invocation dispatch, durable expected-effect observation and idempotent mismatch event append are present.
- Read accepted ADR-050 and ADR-068 at their resolved filenames. Reconcile with canonical fulfillment ADR: classification and prediction metadata attach to existing Binding/Invocation, never an independent authority; preserve Goal -> Graph -> Run -> NodeRun -> Attempt.
- Read complete Hive governed composition and core adversarial contract tests. Hive re-reads live canonical execution records, derives scope from Run, registers/re-resolves Binding, intersects exposure with caller narrowing, and delegates raw backend only below Invocation. Shipped Hive tools are internal/read-only; this is not proof of deployed high-impact mutation.
- `uv sync --locked --extra dev`: PASS.
- Focused core tests: **336 passed** (`/tmp/auto-57-5dd-core.log`).
- Focused Hive tests: **112 passed** (`/tmp/auto-57-5dd-hive.log`).
- Full bootstrap package: **255 passed, 7 skipped** (`/tmp/auto-57-5dd-bootstrap.log`).
- Architecture adversarial gate tests: **74 passed** (`/tmp/auto-57-5dd-architecture.log`).
- No tests added/removed; no inventory delta note needed.

## Static validation results

All validation ran in the assigned worktree with 1200-second timeouts; no driver claims adopted.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3472 files formatted.
- `git diff --check`: PASS.
- `uv run python scripts/check_direct_effects.py`: PASS, 51 sites / 4 TOOL_EFFECT. This validates current census membership/dispositions, not all historical behavior.
- `uv run python scripts/check-model-egress.py`: PASS as ratchet only; **12 reachable escapes awaiting #56 migration**, 7 unreachable library/diagnostic callers, 1 approved Provider boundary. Full #55 dependency remains UNVERIFIED.
- `uv run python scripts/check-security-inventory.py`: PASS, 62 cited paths / 23 rows / 2 counted claims. This gate does not validate all prose.
- `uv run python scripts/check-convergence-matrix.py`: PASS, 1455 production modules / 156 attributed unreachable modules.
- `uv run python scripts/check-suite-inventory.py`: PASS, 21 suites / 33776 unique test identities / zero duplicated evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- Above gate logs: `/tmp/auto-57-5dd-gates.log`.
- `uv run python scripts/check-ratchet-provenance.py`: PASS, 54 quality JSON consumers, including delegated ratchets; non-fatal scanner SyntaxWarnings. Log `/tmp/auto-57-5dd-provenance.log`.
- Inspected Agent shared allowlist/schema/Sentinel gate, Hive Agent/chat call sites, legacy canonical Invocation and materialized-schema validation, bootstrap structured-command dispatch, canonical expected-effect model, and adversarial gate tests. No new production repair justified by the two supplied findings: both are already corrected at the assigned HEAD.

## Acceptance evidence and limits

| # | Criterion | Executed evidence / limitation |
| --- | --- | --- |
| 1 | Consume #55 canonical seam, no second executor | Core `contracts.py` delegates to canonical `effects.invocations.invoke`; Hive boot/chat and legacy paths inspected, 112 Hive tests PASS. **Full #55 prerequisite UNVERIFIED**: frozen #55 is open; model-egress gate retains 12 reachable escapes. |
| 2 | Canonical authorization and policy-required prediction evidence | Core persisted-prediction and Hive canonical Invocation tests PASS; `invocation.py` binds expected evidence before durable admission. Deployed high-impact mutation **UNVERIFIED** (shipped Hive contracts are internal/read-only). |
| 3 | Effective authorized set before provider | Shared Agent declaration/Sentinel gate and Hive exposure intersection inspected. Core adversarial model/strategy/schema-denial tests PASS; no provider dispatch on refusal. Universal principal/Workspace/Goal/Run envelope for every provider **UNVERIFIED**. |
| 4 | Unknown/missing schemas fail closed | Core contract/schema-boundary and Hive unknown-name/schema tests PASS. Unsupported root/nested types denied; materialized repairs validated; argument mutation tests synchronize at real admission/provider suspension. |
| 5 | Constrained structured command contract | Bootstrap 255 PASS / 7 SKIP, including `test_agent_loop_command_contract.py`: raw command refused, structured argv sent via `run_argv`, shell tokens refused. Dispatch inspected. Live/backend parity beyond local exercised paths **UNVERIFIED**. |
| 6 | Host-owned reversibility | Registry construction/lookup and Hive/legacy registry consumption inspected; policy-floor and legacy tier tests PASS. Separate Sentinel registry-based elevation debt #346 is accurately documented in SECURITY.md:35. |
| 7 | Recomputable exact effect identity | Core SQLite reopen tests PASS: capability/provider/arguments/digests/pre-state digest/post-state/Invocation id/policy version retained. Independent production pre-state retrieval and deployed restart **UNVERIFIED**; digest alone is not underlying state retention. |
| 8 | Durable, non-overwritable mismatch evidence | Real SQLite append-absent and ack-lost recovery tests PASS: replay still raises PredictionMismatch; unique correlated event; backend once; later clean observation cannot replace first mismatch. |
| 9 | Missing high-impact prediction detectable/policyable | Incomplete high-impact registration denied with ExpectedEffectRequired; complete-contract positive control PASS. |
| 10 | Seven historical TOOL_EFFECT entries migrated/retired | Current direct-effects census PASS (51 sites / 4 tool sites); legacy schema/tier and retired BuildersLearning tests PASS. Full historical seven-site behavioral equivalence **UNVERIFIED**; inventory membership alone is insufficient. |
| 11 | Introduced raw bypass rejected by gate | 74 architecture tests PASS, including intentionally injected raw Hive/browser tool calls rejected by inventory audit. This is evidence for the gate's covered syntax, not universal static proof. |
| 12 | #847 closes with adversarial tests first | **UNMET**: frozen dispatch source `repos/Agent-StrongHold/Project-mAIstro/issues/847` has `state=open`. Local tests cannot establish external closure or all #847 acceptance. No GitHub mutations permitted. |

## Exact executed test commands

```text
uv run pytest packages/maistro-core/tests/tools/test_governed_contracts.py packages/maistro-core/tests/agents/test_tool_schema_boundary.py packages/maistro-core/tests/agents/test_base.py packages/maistro-core/tests/agents/test_factory.py packages/maistro-core/tests/agents/spec/test_agent_spec.py packages/maistro-core/tests/agents/strategies/test_react.py packages/maistro-core/tests/agents/strategies/test_builders_learning.py packages/maistro-core/tests/agents/artificer/test_strategy.py packages/maistro-core/tests/capabilities/test_effect_context_policy.py packages/maistro-core/tests/security/sentinel/test_audit.py -x -q
uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py packages/hive-conductor/backend/tests/test_legacy_dag_node.py packages/hive-conductor/backend/tests/test_agent_model_tools.py packages/hive-conductor/backend/tests/test_maistro_core_adapter.py -x -q
uv run pytest packages/maistro-bootstrap/tests -x -q
uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q
```

## Handoff

**BLOCKED** at issue level. **777 passed, 7 skipped** in fresh scoped validation. No production code, tests, inventory counts, ledgers or grants changed in this round; only this evidence note changed. The exact vulture gate is already green and reported SECURITY.md drift is absent. No speculative cleanup or ledger banking is justified. No red/green regression is claimed for an evidence-only repair round.

Remote exact-head CI remains **UNVERIFIED**: no driver check logs supplied, no remote status inferred from local checks. External prerequisite closure, full #55 adoption, historical seven-site proof, and remaining production/backend guarantees require the authorized owning lanes.

Progress: checked 1 assigned issue, done 1 focused validation item, skipped 0 issues, validation failures 0 (two missing ADR path reads corrected using resolved filenames); issue completion 0. Next: hand off unmet prerequisites and production-evidence limits. Commit this note locally; no push, PR, merge or issue action.

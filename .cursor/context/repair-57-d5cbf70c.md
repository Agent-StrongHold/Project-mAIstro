# Issue #57 — d5cbf70c repair checkpoint

## Frozen scope
- Worktree `/home/dev/Git/wt/auto-57`, branch `auto-57`.
- Starting HEAD `20836853d0434810273e9313ceedaf3ec6c85a94`; supplied develop base `1e6b080256026eec0136be31a1acb8abbb3cfc1f`.
- One item: issue #57; frozen evidence is `/home/dev/maistro/jobs/d5cbf70c63254753b11a6aad55993327/dispatch-context.json`. No GitHub refresh/mutations, integration or unrelated fixes.
- Clean incoming worktree; no salvage needed.
- Writer repair round: inspect acceptance evidence and exact vulture gate; change only demonstrated failures. Potential files: issue-57 governed runtime/tests/docs and `quality/vulture-baseline.json` only if exact scan requires it. No other ledger/grant changes.
- Job directory has no `check-*.log` artifacts at initial inspection; driver verification is not available to assume.

## Executed results
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS (1305 findings, 0 unclassified, 0 never_allowlist; tool baseline base 2ac960614216; output `/tmp/auto-57-d5cb-vulture.log`). No unbanked identities; no speculative ledger amendments.

## Inspected evidence
- Frozen issue #57 has twelve acceptance criteria, including prerequisite #847 closure. Its frozen #847 source says `state=open`; criterion 12 is UNMET and cannot be repaired by a local code/ledger edit.
- `SECURITY.md:35` already describes `ReversibilityRegistry` construction and distinguishes classification from Sentinel approval gating. The supplied drift finding does not reproduce; no wording repair justified.
- `contracts.py` and adjacent adversarial tests inspected: host registry, schema/admission, canonical Invocation delegation, expected-effect settlement and SQLite reopen recovery. Hive production composition reads canonical execution records and narrows its exposure before invoking that adapter.
- Prior report read as context only; none of its executed results adopted as this round's evidence.
- Read accepted ADR-050, ADR-068, ADR-081226-6b46 and ADR-081426-1f7c. Reconciliation: exposure is not authorization; reversibility classification does not prove approval gating; Invocation and EventStore retain existing lifecycle/evidence ownership. No architectural change planned.
- Read canonical expected-effect model/observation method, Agent adversarial schema tests, bootstrap command dispatcher and Hive composition. Pre-state is stored as a digest, and first-observation immutability uses a service-local lock; deployed state retrieval and cross-process race guarantees are not inferred.
- `uv sync --locked --extra dev`: PASS. Exact vulture command also matches `.github/workflows/quality.yml:1512`.
- No production repair is justified by the supplied stale doc/scanner findings. Continue focused acceptance validation; explicitly preserve residual gaps.

## Fresh focused validation
- Core governed contracts, Agent schema/base/factory/spec/ReAct/BuildersLearning/artificer, effect-context policy and Sentinel audit: **336 passed** (`/tmp/auto-57-d5cb-core.log`).
- Hive governed tools, legacy DAG node, Agent model tools and core adapter: **112 passed** (`/tmp/auto-57-d5cb-hive.log`).
- Full bootstrap scoped suite: **255 passed, 7 skipped** (`/tmp/auto-57-d5cb-bootstrap.log`). Six skips require unavailable Docker/image; one is Windows-only. Live backend parity remains unverified.
- Direct-effect/model-egress gate regression tests: **74 passed** (`/tmp/auto-57-d5cb-bypass.log`), including deliberate introduced raw paths.
- All commands used `uv run pytest ... -x -q` (bootstrap also `-rs`), 1200-second timeouts. No new tests or inventory-count changes.

- `uv run ruff check .` and `uv run ruff format --check .`: **PASS**; 3474 files already formatted.
- Fresh local gates **PASS** (`/tmp/auto-57-d5cb-gates.log`): direct effects (51 sites, four TOOL_EFFECT), model egress (20 callers; explicitly banks 12 reachable escapes awaiting #56), security inventory (does not check all prose), convergence matrix (1455 production modules), suite inventory (21 suites, 33910 unique identities).
- Inspected Agent shared dispatch at `base.py:901-1019` and legacy canonical Invocation at `legacy_dag_node.py:412-460`. Host allowlist/schema checks and registry classification are reachable; this is not proof of a universal Principal/Workspace/Goal/Run envelope.

## Acceptance review

| # | Criterion | Fresh execution and production evidence / limitation |
|---|---|---|
| 1 | Consume #55 Invocation; no second executor | `contracts.py:358` delegates to existing Invocation. Hive real SQLite Container tests exercise canonical Run/NodeRun/Attempt correlation and boot executor. Complete #55 cutover is **UNVERIFIED**; model-egress non-expansion passing does not prove it. |
| 2 | Canonical authorization and required expected-effect evidence | Core `test_governed_tool_persists_expected_evidence_on_canonical_invocation` passes with policy events and attached evidence; Hive registry-tier Invocation test passes. Deployed mutating/high-impact coverage is **UNVERIFIED** (Hive registry currently read-only/model-backed). |
| 3 | Effective Agent authorization before provider execution | Core Agent/ReAct/artificer/schema and Hive denial tests pass, asserting no backend call for unlisted/invalid requests. BuildersLearning no-effect tests pass; unused AgentSpec fields are removed. Universal Principal/Workspace/Goal/Run effective-envelope enforcement is **UNVERIFIED**; selected allowlist tests are not universal authority proof. |
| 4 | Missing/unknown schema fails closed | Core unknown-schema/custom-strategy/forged-schema/unsupported-type/repaired-data denial tests pass; explicit valid/no-argument positive controls pass. Legacy materialized-argument refusals pass. |
| 5 | One structured command contract across supported backends | Bootstrap suite passes argv/injection/command-contract tests. `agent_loop.py:387-413` validates nonempty string argv and dispatches `run_argv`, not raw shell text. Live supported-backend parity is **UNVERIFIED**: six Docker/image and one Windows test skipped. |
| 6 | Host-owned reversibility | `contracts.py:101` constructs registry; Hive/legacy registry-tier tests pass (legacy lookup at `legacy_dag_node.py:412`). Classification is evidenced, not Sentinel approval gating. |
| 7 | Exact recomputable expected-effect identity | SQLite reopen tests pass for lost append and lost acknowledgement, checking capability/provider, arguments/digest, pre-state digest, expected/observed post-state, Invocation and policy version after reconstructing stores. `contracts.py:321` stores a pre-state digest only; deployed original state retrieval/full recomputation is **UNVERIFIED**. |
| 8 | Durable correlated mismatch, not silent success | PredictionMismatch and real SQLite reopen/replay tests pass; first observation remains unchanged, one Invocation-correlated durable event, no redispatch. `invocation.py:953-1008` uses canonical store/EventStore. Cross-process observation race guarantees are **UNVERIFIED**. |
| 9 | Missing required high-impact prediction detectable | `test_high_impact_contract_without_expected_effect_fails_closed` passes (ExpectedEffectRequired plus complete-contract positive control). |
| 10 | Seven historical TOOL_EFFECT entries hardened or retired | Current direct-effect inventory matches 51 sites, four TOOL_EFFECT; Hive reachable wiring/legacy refusal and BuildersLearning retirement tests pass. Historical seven-site equivalence is **UNVERIFIED**; current inventory count cannot prove migration history. |
| 11 | Deliberate raw path rejected by gate | `test_a_newly_introduced_raw_hive_tool_call_is_rejected_by_the_audit` and `test_a_newly_introduced_raw_browser_client_call_is_rejected_by_the_audit` pass in the 74-test gate suite. |
| 12 | #847 closes first from adversarial verification | **UNMET**: frozen `dispatch-context.json:73220` records #847 `state=open` (source starts :73117). No remote refresh or closure action; local adversarial subsets do not prove child completion. |

## Commands run

All Python validation uses `uv run`, with 1200-second timeouts (initial vulture: 600 seconds).
- `uv sync --locked --extra dev`: PASS.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS.
- `uv run pytest` with these paths under `packages/maistro-core/tests`, plus `-x -q`: `tools/test_governed_contracts.py`, `agents/test_tool_schema_boundary.py`, `agents/test_base.py`, `agents/test_factory.py`, `agents/spec/test_agent_spec.py`, `agents/strategies/test_react.py`, `agents/strategies/test_builders_learning.py`, `agents/artificer/test_strategy.py`, `capabilities/test_effect_context_policy.py`, `security/sentinel/test_audit.py`: PASS, 336.
- `uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py packages/hive-conductor/backend/tests/test_legacy_dag_node.py packages/hive-conductor/backend/tests/test_agent_model_tools.py packages/hive-conductor/backend/tests/test_maistro_core_adapter.py -x -q`: PASS, 112.
- `uv run pytest packages/maistro-bootstrap/tests -x -q -rs`: PASS, 255; seven skipped as above.
- `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q`: PASS, 74.
- `uv run ruff check .`; `uv run ruff format --check .`: PASS.
- `uv run python` with each gate: `scripts/check_direct_effects.py`, `scripts/check-model-egress.py`, `scripts/check-security-inventory.py`, `scripts/check-convergence-matrix.py`, `scripts/check-suite-inventory.py`: PASS with limitations above.
- `git diff --check`: PASS. Only this report changed; `git diff --numstat -- quality/` is empty.

## Handoff

**BLOCKED**, not integration approval. No supplied doc/scanner defect reproduced. Source, tests and ledgers unchanged; no inventory-delta note needed because no tests changed. Only changed file: `.cursor/context/repair-57-d5cbf70c.md`. Finish with a local commit; no push or GitHub mutation.

Remote exact-head CI is **UNVERIFIED** (no supplied driver check logs); fresh local gates are not remote CI evidence. Remaining work requires authorized #847 sequencing and proof/repair of the explicit universal/deployed acceptance gaps, not another speculative scanner/doc edit.

Progress: checked=1 assigned issue, done=1 focused validation/report, skipped=0 issues, errors=0 validation commands; issue completion=0. Next: owner review of unmet #847 and UNVERIFIED criteria 1/2/3/5/7/8/10. Do not infer merge readiness from passing inventory/ratchet checks.

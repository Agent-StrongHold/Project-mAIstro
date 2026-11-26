# Issue #57 repair — frozen scope

- Assigned worktree: `/home/dev/Git/wt/auto-57`, branch `auto-57`.
- Starting HEAD verified: `e32139e4dc4f2cd462d28c67015be603a9730328`; clean on arrival.
- Frozen item list: issue #57 only, supplied dispatch snapshot and prior result; no GitHub mutations or re-enumeration.
- Repair scope: evidence-backed SECURITY.md drift and exact vulture per-identity gate; production/acceptance validation and local commit. Inspect adjacent code/tests before changes.
- Job directory contains no `check-*.log` files at initial inspection; driver validation evidence unavailable.
- Starting diff spans existing issue implementation and prior handoffs; preserve all prior work.
- Assumption: writer role applies (explicit repair assignment); verifier-only no-edit instruction does not apply.

## Progress

- Initial repository instructions and branch state inspected; all 12 acceptance criteria extracted from supplied dispatch.
- SECURITY.md:35 already accurately documents registry construction and distinguishes classification from approval gating. Reported documentation drift is not reproducible; no cosmetic repair warranted.
- Exact vulture gate PASS: 1316 findings, 1320 base reviewed identities, no unbanked identities (`/tmp/issue-57-28e455ee-vulture.log`). No ledger amendment justified.
- Frozen dispatch `issues/847` is open: criterion 12 is externally UNMET. Prior result independently read; its validation claims are not adopted.
- First item complete (reported repair failures not reproduced). Read accepted ADR-004 amendment, ADR-050, ADR-068, and ADR-081226-6b46. Reconciliation: host reversibility classification is not authority; tool adapters must consume the canonical Binding/Invocation lifecycle, never own another scheduler/policy path.
- Fresh focused tests PASS: core governed contracts/Agent base/factory/spec/spawner/identity/ReAct/BuildersLearning/artificer/effect-policy/audit: 390; Hive governed tools/legacy DAG/Agent model tools/core adapter: 105; bootstrap package: 243 passed, 7 skipped; direct-effect/model-egress architecture tests: 74. Logs `/tmp/issue-57-28e455ee-{core,hive,bootstrap,architecture}.log`.
- Production read confirms Hive boot and chat wrappers reach GovernedToolExecutor; legacy path uses canonical Invocation with shared registry tier and materialized schema validation. Core expected-effect tests assert real SQLite reopen, immutable mismatch and interrupted-event replay, not merely mock logging.
- No production/test/ledger change is justified; no inventory delta required.
- `uv sync --locked --extra dev` PASS (218 packages checked). Root `ruff check .` PASS; `ruff format --check .` PASS (3423 files).
- Direct-effect gate PASS: 51 sites, 4 TOOL_EFFECT. Model-egress ratchet PASS **but explicitly reports 12 reachable escapes awaiting #56**; not repository-wide M1 completion proof. Security inventory PASS (61 paths/23 rows; does not verify all prose). Convergence PASS (1440 modules classified).
- Suite inventory PASS: all 21 suites match, 33260 unique identities. Log `/tmp/issue-57-28e455ee-inventory.log`.
- Focused validation complete with no failing commands. Supplied base ledger independently inspected with `git show 7f8683be2da4476390ef9112fb7b6e478be709ee:quality/direct-effect-call-sites.json`: six TOOL_EFFECT identities, not seven (two chat wrappers, two legacy helpers, two BrowserClient backends). Historical seventh remains UNRESOLVED; do not fabricate an identity.

## Executed validation

All validation ran locally in the assigned worktree; long-running commands used 1200-second timeouts. Exact vulture invocation:

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`

Other commands (all PASS):
- `uv sync --locked --extra dev`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest` targeted core files (390 passed): tools/test_governed_contracts.py; agents/test_base.py, test_factory.py, test_tool_call_identity.py, spec/test_agent_spec.py, spawner/test_spawner.py, strategies/test_react.py, strategies/test_builders_learning.py, artificer/test_strategy.py; capabilities/test_effect_context_policy.py; security/sentinel/test_audit.py, all under packages/maistro-core/tests, with `-x -q`.
- `uv run pytest` Hive files (105 passed): test_governed_tools.py, test_legacy_dag_node.py, test_agent_model_tools.py, test_maistro_core_adapter.py under packages/hive-conductor/backend/tests, with `-x -q`.
- `uv run pytest packages/maistro-bootstrap/tests -x -q`: 243 passed, 7 skipped.
- `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q`: 74 passed.
- `uv run python scripts/check_direct_effects.py`
- `uv run python scripts/check-model-egress.py` (passing ratchet, not zero escapes)
- `uv run python scripts/check-security-inventory.py`
- `uv run python scripts/check-convergence-matrix.py`
- `uv run python scripts/check-suite-inventory.py`
- `git diff --check`

## Acceptance review (fresh evidence, not integration approval)

1. **Consume #55 seam:** Hive boot test `test_boot_agent_tool_effect_creates_its_own_invocation` and legacy Invocation tests passed. `tools/contracts.py:355` delegates to existing `effects.invocations.invoke`; no second lifecycle introduced. Full #55 prerequisite completion **UNVERIFIED**: supplied snapshot says open and model-egress reports 12 banked reachable escapes.
2. **Canonical authorization and expected effects:** `test_governed_tool_persists_expected_evidence_on_canonical_invocation` passed, asserting policy/completed events plus exact prediction on Invocation. Hive tests assert persisted Run/NodeRun/Attempt correlation. High-impact coverage uses a host-configured contract through the public production executor; no live shipped Hive mutating operation is claimed.
3. **Effective authorized set:** Agent/ReAct/artificer allowlist and Hive unlisted/refusal tests passed, asserting no backend execution; BuildersLearning no-effect tests passed. Agent `base.py:892` checks identity before Sentinel; Hive intersects registry exposure and caller narrowing. Full principal/Workspace/Goal/Run envelope equivalence across all legacy consumers **UNVERIFIED**.
4. **Unknown/missing schemas:** core unknown-schema and unsupported-schema-type tests, ReAct missing-schema tests, and legacy unregistered-tool tests passed with provider refusal. This is the production validator's supported JSON Schema subset, not full dialect compliance.
5. **Structured command contract:** bootstrap schema/argv/raw-command/metacharacter tests passed; `agent_loop.py:413` dispatches argv; local `sandbox.py:261` uses shell=False; container `container_sandbox.py:452` passes argv through _exec. Live supported-backend parity **UNVERIFIED** (7 skipped tests); local additional path/command checks are not equivalent to container isolation.
6. **Host-owned reversibility:** Hive standard tier test, three legacy tier cases, and legacy host reclassification refusal test passed. `contracts.py:101` constructs registry; legacy `legacy_dag_node.py:409` reads shared registry. Caller strings cannot downgrade it. SECURITY.md:35 already describes this and separately disclaims Sentinel.resolve_tier registry gating (#346), so stale-doc repair is unnecessary.
7. **Recomputable prediction evidence:** SQLite reopen tests passed for both interrupted-append modes, asserting exact capability/provider/arguments/digest, pre-state digest, post-state, Invocation id and policy version. `expected_effect.py:66` computes comparison in host code. Recovery/retrieval of actual pre-state behind its digest, live PostgreSQL restart, and legacy high-impact prediction parity **UNVERIFIED**.
8. **Durable mismatch:** mismatch and interrupted-append/replay tests passed; PredictionMismatch raised, first false verdict preserved against later success observation, exactly one correlated event, backend not redispatched. Recovery requires replay; no atomic outbox or autonomous recovery asserted.
9. **Missing required high-impact evidence:** `test_high_impact_contract_without_expected_effect_fails_closed` passed; incomplete host registration rejected, complete contract accepted. Future legacy high-impact prediction-policy equivalence **UNVERIFIED**, not implied by independent effect-policy denial tests.
10. **Seven historical TOOL_EFFECT sites:** current census matches four retained tool provider-backend sites; chat/boot/legacy production-route tests passed. Supplied base contains six TOOL_EFFECT identities. Exact historical seventh and all-seven control equivalence **UNVERIFIED**; a matching inventory alone is not acceptance proof.
11. **Intentional raw path rejected:** `tests/test_check_direct_effects.py:496` and `:519` introduce raw Hive/BrowserClient sites and assert audit rejection; both passed within 74 gate tests. Finite AST census is not a general reflective-Python security proof.
12. **#847 closes first:** **UNMET**. Supplied dispatch source `repos/Agent-StrongHold/Project-mAIstro/issues/847` says `state=open`. Adversarial subsets above do not establish issue closure; no GitHub refresh or mutation performed.

Remote CI **UNVERIFIED**: no driver check-*.log files supplied; historical status/check records are not exact-head green evidence.

## Handoff

Changed only this checkpoint. No production, tests, inventories, ledgers, grants or gates changed. No failing source/scanner evidence warrants an invented repair. No inventory note required because no tests changed. Preserve existing implementation and prior notes.

Verdict: **BLOCKED**, not MERGE-READY. Remaining work is explicit missing evidence and authorized prerequisite sequencing (#55/#847), not an instruction to close anything. This writer cannot satisfy external closure under the no-GitHub-mutation rule.

Progress: checked 1 assigned issue; done 1 validation/handoff item; skipped 0; errors 0. Next: owner/verifier reviews UNVERIFIED criteria and external prerequisites. Finish with a local commit only, never push.

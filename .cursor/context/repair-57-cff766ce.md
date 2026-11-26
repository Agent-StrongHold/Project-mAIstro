# Issue 57 repair — cff766ce

## Frozen scope
- Assigned issue: #57 only; branch `auto-57`, worktree `/home/dev/Git/wt/auto-57`.
- Verified starting HEAD: `9400946d14161690b75c13833700165a46a40ac9`; clean worktree.
- Evidence snapshot: `/home/dev/maistro/jobs/cff766ce6f2d4ec4accd4f917993ed8d/dispatch-context.json`; do not refresh GitHub lists.
- Repair targets: reported SECURITY.md reversibility drift (if still present), actual exact-debt-ledger findings, focused production/tool acceptance validation. Inspect associated implementation, ADRs, tests and inventory notes only as needed.
- No `check-*.log` files present in supplied job directory at initial inspection. Driver execution claims cannot be verified from absent logs.
- Assumption: writer lane (explicit assigned repair and commit requirement); no external mutations. #847 closure cannot be performed by this worker.

## Initial evidence
- Existing branch includes substantial implementation and repeated prior repair notes; preserve all of it.
- No sync conflict or uncommitted incoming work found; no fetch/merge needed.

## Validation and disposition
- Exact vulture scan passed: 1298 findings, 1302 reviewed identities, zero unclassified/never_allowlist; log `/tmp/auto-57-cff766-vulture.log`. No ledger amendment justified.
- SECURITY.md:35 already reflects registry construction and explicitly distinguishes classification from Sentinel approval gating. Reported drift is not reproducible; no cosmetic repair warranted.
- Prior result read as BLOCKED; no prior test claims adopted. Contracts and Hive production wiring inspected: host registry, canonical Binding re-resolution and Invocation delegation, live Run/NodeRun/Attempt correlation.
- One attempted ADR read used a nonexistent filename (`ADR-050-integration-architecture.md`): not found; skipped. Actual ADR filename resolved from directory listing before further reading.
- Read accepted ADR-050, ADR-068, ADR-081226-6b46: classification is not authority or approval; exposure must consume canonical Binding/Invocation. No competing lifecycle introduced by this round.
- Fresh core tools/capabilities and adjacent Agent/spec/strategy/Sentinel subset: 1583 passed, 12 skipped, 1 unawaited fake-process coroutine warning. Skips: 4 missing Playwright and 8 PostgreSQL DSN-dependent tests. Log `/tmp/auto-57-cff766-core.log`.
- Fresh Hive governed tools/legacy DAG/Agent model tools/core adapter subset: 112 passed (`/tmp/auto-57-cff766-hive.log`).
- Fresh full bootstrap package: 255 passed, 7 skipped (Windows-only test and six unavailable Docker/builders-image tests); live container parity remains UNVERIFIED (`/tmp/auto-57-cff766-bootstrap.log`).
- Fresh architecture gate tests: 74 passed, including deliberately introduced raw Hive and BrowserClient tool paths (`/tmp/auto-57-cff766-gate-tests.log`).
- `uv run ruff check .` and `uv run ruff format --check .` passed (3490 formatted files); `git diff --check` passed.
- Direct-effects, model-egress, security-inventory, convergence-matrix, suite-inventory gates all exited 0. Direct census: 51 sites, 4 TOOL_EFFECT; model-egress explicitly reports 12 reachable escapes awaiting #56 (not proof of M1 completion); convergence classifies 1462 modules; all 21 suite counts match. Logs `/tmp/auto-57-cff766-check*.log`.
- Inspected actual new core assertions: before-backend schema/allowlist refusals, deep argument snapshot at awaited admission/provider boundaries, required high-impact contract, durable SQLite mismatch recovery after lost append/ack and immutable verdict. Hive tests use a real SQLite Container with only provider effects substituted.
- Independently extracted frozen dispatch `/issues/55` and `/issues/847`: both `state=open`. Criterion 12 remains unmet; remote CI remains UNVERIFIED.
- Legacy production path records shared host-registry reversibility in canonical Invocation and refuses missing NodeContext; no source repair justified by the supplied targets. Historical inventory completeness is not established solely by the current census.

## Acceptance disposition

| # | Criterion | Fresh evidence and limits |
|---|---|---|
| 1 | Consume #55's production seam, no second executor | `contracts.py:_invoke_admitted` delegates to canonical Invocation; Hive real-Container tests pass. Full #55 completion UNVERIFIED (frozen prerequisite open; model-egress lists 12 retained escapes). |
| 2 | Canonical authorization and required prediction evidence | Core `test_governed_tool_persists_expected_evidence_on_canonical_invocation` asserts policy/completed events and Invocation-bound evidence; Hive boot tool Invocation tests pass. High-impact predictions tested in library composition; shipped Hive contracts are read-only. |
| 3 | Effective tool/capability set enforced before provider | Agent base/schema/ReAct/artificer and Hive unlisted-tool/allowlist narrowing tests pass. `base.py:540` propagates identity.tools; Hive intersects caller names with registry exposure. Full legacy Agent/principal-envelope equivalence UNVERIFIED. |
| 4 | Missing/unknown schemas fail closed | Core unknown-schema and unsupported-type tests, Agent boundary tests and Hive legacy materialized-argument tests pass with no backend calls. |
| 5 | Constrained structured command contract across backends | Bootstrap command schema/raw-command/metacharacter and sandbox argv tests pass. Six live Docker/image cases skip; live backend parity UNVERIFIED. |
| 6 | Host-owned reversibility | `contracts.py:101` constructs registry; legacy `_run_tool_node` records same registry tier, not caller tier. Hive registry and legacy host reclassification tests pass. Classification is not approval gating; SECURITY.md:35 correctly distinguishes it. |
| 7 | Exact recomputable evidence identity | Core argument-mutation and SQLite reopen tests assert arguments, digests, capability/provider, pre-state digest, expected/observed post-state, Invocation and policy version. PostgreSQL restart UNVERIFIED (DSNs unset). |
| 8 | Durable mismatch cannot become ordinary success | Core mismatch and lost-append/lost-ack SQLite reopen cases pass: immutable host verdict, one correlated event, replay without redispatch. Cross-process observation race UNVERIFIED; separate event append requires retry/replay recovery. |
| 9 | Missing expected effects detectable/policyable | `test_high_impact_contract_without_expected_effect_fails_closed` passes with complete-contract positive control. |
| 10 | Seven historical TOOL_EFFECT entries controlled or retired | Current inventory and Hive boot/chat/legacy tests pass; current census has four retained provider sites. Historical seven-site completeness/equivalence UNVERIFIED; inventory counts alone are not proof. |
| 11 | Introduced raw tool path rejected by gate | 74 gate tests pass including intentional raw Hive dispatcher and BrowserClient additions. |
| 12 | #847 closes first with adversarial verification | UNMET: frozen dispatch source `/issues/847` state=open. Adversarial subsets pass locally, but no full child verification or closure may be inferred. No GitHub mutation permitted. |

## Commands executed

Validation commands used 1200-second timeouts and logs under `/tmp/auto-57-cff766-`.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
- `uv run pytest packages/maistro-core/tests/tools packages/maistro-core/tests/capabilities packages/maistro-core/tests/agents/test_base.py packages/maistro-core/tests/agents/test_factory.py packages/maistro-core/tests/agents/test_tool_schema_boundary.py packages/maistro-core/tests/agents/strategies/test_react.py packages/maistro-core/tests/agents/strategies/test_builders_learning.py packages/maistro-core/tests/agents/artificer/test_strategy.py packages/maistro-core/tests/agents/spec/test_agent_spec.py packages/maistro-core/tests/security/sentinel/test_audit.py -x -q -rs`
- `uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py packages/hive-conductor/backend/tests/test_legacy_dag_node.py packages/hive-conductor/backend/tests/test_agent_model_tools.py packages/hive-conductor/backend/tests/test_maistro_core_adapter.py -x -q`
- `uv run pytest packages/maistro-bootstrap/tests -x -q -rs`
- `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run python scripts/check_direct_effects.py`
- `uv run python scripts/check-model-egress.py`
- `uv run python scripts/check-security-inventory.py`
- `uv run python scripts/check-convergence-matrix.py`
- `uv run python scripts/check-suite-inventory.py`
- `git diff --check`
- Local Python extraction of frozen dispatch states for #55 and #847; no network requests.

## Handoff

Only this checkpoint changed. No production/test/quality-ledger edits are justified by the reproduced repair targets, and no tests were added, so no test inventory delta is required. Preserve the already corrected SECURITY.md and passing exact-debt ledger rather than manufacturing a cosmetic repair. No execution lifecycle, grants, authorization path or event authority changed.

Verdict: BLOCKED, not integration approval. Next: authorized owner must sequence #847 and provide missing M1/historical-site/live-backend evidence. Remote CI remains UNVERIFIED; there are no supplied driver check logs. Progress: checked 1 assigned issue; done 1 local validation item; skipped 0 issues; errors 0 failed validation commands (one nonexistent ADR read noted above). Finish with local evidence commit only; no push or GitHub mutation.

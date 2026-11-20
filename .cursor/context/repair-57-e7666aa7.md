# Issue #57 repair — e7666aa7

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-57`, branch `auto-57`.
- Starting HEAD `83a29b6875c22e0114bf111d76d15183bdae506d`; supplied base `a9fdec4cb40a62ada3e897448eabc81f2410135a`. Working tree initially clean.
- Process only issue #57 and supplied dispatch snapshot. No GitHub mutations or re-enumeration.
- Explicit task: exact vulture per-identity CI repair; review actual scanner findings, remove genuinely dead code or bank retained identities as authorized for this round. Inspect relevant contracts/tests/ADRs and run focused acceptance validation.
- Candidate edit scope: actual vulture-reported source identities, `quality/vulture-baseline.json`, focused tests/inventory note only if warranted, this handoff. No unrelated synchronization or gate changes.

## Initial evidence / ambiguity

- Job directory contains no `check-*.log` files at start. Driver deterministic logs unavailable; run checks locally.
- Supplied prior result is BLOCKED; it reports repaired Hive admitted-scope handling but is not independent verification.
- Supplied dispatch has #847 open, so acceptance criterion 12 is not satisfiable by local code alone. No issue closure action will be attempted.
- Starting branch already changes 121 files versus supplied develop base, including unrelated install/sync differences. Preserve all existing work; do not expand this round into unrelated repairs.
- Instructions distinguish writer/verifier; assigned repair + mandatory commit means proceed as writer. Prior SECURITY drift must be checked against current files, not assumed present.

## Results

- `uv sync --locked --extra dev`: exit 0 (218 installed packages checked).
- Exact requested vulture scan: exit 0, 1310 findings, 0 unclassified, 0 never-allowlist, 1314 reviewed baseline identities. Log: job `check-vulture-local-initial.log`. No unbanked identities or source repair justified; do not make speculative ledger edits.
- Current SECURITY.md:35 already documents registry construction through governed contracts and distinguishes classification from Sentinel approval gating. The supplied stale-prose finding is not reproducible.
- Inspected host contracts and Hive production wiring, including admitted Run scope re-read. Read accepted ADR-050, ADR-068, ADR-081226-6b46: classification/exposure cannot grant authority; Invocation owns effect lifecycle. No architecture changes planned.
- One read used a guessed ADR-050 path and failed ENOENT; recorded not found, resolved the actual filename from the directory and read that instead. No command executed against an unresolved git ref or issue ID.
- The vulture tool selected local merge base `bb9a7fbbc752`, not supplied develop base; review gate CLI/base handling before interpreting provenance. A clean local gate is not remote CI proof.

## Focused validation (fresh, not inherited)

All local logs are in the assigned job directory; command timeouts are 1200 seconds.

- Core governed contracts + Agent schema boundary/base/factory/spec + ReAct/BuildersLearning/artificer + effect policy + audit: **334 passed** (`check-core-tests-local.log`).
- Hive governed tools + legacy DAG + Agent model tools + core adapter: **110 passed** (`check-hive-tests-local.log`). Includes the previous round's admitted-scope regressions.
- `uv run pytest packages/maistro-bootstrap/tests -x -q`: **243 passed, 7 skipped** (`check-bootstrap-tests-local.log`). Live backend parity cannot be inferred from skipped tests.
- `uv run ruff check .`: exit 0. `uv run ruff format --check .`: exit 0, 3456 files already formatted.
- Inspected meaningful durable tests: real SQLite close/reopen, interrupted mismatch event append/ack, immutable mismatch replay, exact Invocation/provider/arguments/policy/digest assertions. These are not just mocked log checks.
- Current legacy implementation resolves `hive_tool_reversibility()` before canonical Invocation and attaches `_tool_reversibility`; older checkpoint claims of missing legacy classification no longer apply. High-impact expected-effect evidence remains exercised via configured core contracts, not a shipped Hive mutating tool.

- `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q`: **74 passed**. Includes intentionally introduced raw Hive/browser effect rejection.
- `uv run python scripts/check_direct_effects.py`: exit 0; 51 inventoried sites including 4 TOOL_EFFECT. Inventory is not proof of full historical seven-site parity.
- `uv run python scripts/check-model-egress.py`: exit 0, but explicitly reports **12 reachable escapes awaiting #56 migration**. A passing ratchet must not be represented as completed M1 cutover.
- `uv run python scripts/check-suite-inventory.py`: exit 0, all 21 suites match; no test additions and no inventory delta required.
- `uv run python scripts/check-security-inventory.py`: exit 0; only paths/selected counted claims checked, not all prose.
- `uv run python scripts/check-convergence-matrix.py`: exit 0; 1451 modules classified.
- Validated supplied base resolves to a commit, then reran exact vulture command with `RATCHET_BASE_REV=a9fdec4cb40a62ada3e897448eabc81f2410135a`: exit 0, same 1310 findings. Gate reports trusted merge base `bb9a7fbbc752`; this is tool-selected merge-base provenance, not evidence of CI running on the supplied develop tip. No unbanked identities, stale candidate rows, or unauthorized new debt reported.

## Acceptance review

| # | Criterion | Fresh executed evidence / limitation |
| --- | --- | --- |
| 1 | Consume #55 canonical seam | Core contracts invoke `effects.invocations.invoke`; Hive boot/chat/legacy integration tests pass. Full #55 dependency completion **UNVERIFIED**, not inferred from banked model-egress escapes or a passing inventory gate. |
| 2 | Canonical authorization plus required predictions | `test_governed_tool_persists_expected_evidence_on_canonical_invocation` and Hive `test_governed_tool_records_invocation_with_registry_tier` passed. Production Hive registry has three internal/read-only tools, no configured mutating high-impact deployment; deployed high-impact behavior **UNVERIFIED**. |
| 3 | Effective Agent authority before provider | Core Agent/ReAct/artificer/custom-strategy and Hive unlisted-tool denial tests passed; BuildersLearning no-effect retirement tests passed. Universal current principal/Workspace/Goal/Run authority intersection **UNVERIFIED** by these focused tests. |
| 4 | Missing/unknown schema fail closed | Shared Agent missing/unknown schema, immutable nested-schema and materialized repaired-argument denial tests passed; governed unknown/unsupported schema tests prove no binding/provider execution. |
| 5 | Consistent constrained commands | Full bootstrap suite includes argv contract/no `cmd`, shell metacharacter, backend argument/grammar tests. Seven skipped tests; live container/microVM parity **UNVERIFIED**. |
| 6 | Host-owned reversibility | Hive registry-tier, legacy shared-registry-tier and registry reclassification reaching independent effect policy tests passed; production code resolves registry tier, not caller tier metadata. Classification does not itself prove approval gating (ADR-068; SECURITY.md:35). |
| 7 | Exact recomputable expected-effect identities | SQLite reopen tests assert capability/provider, exact arguments + digest, pre-state digest, expected/observed state, Invocation id, policy version and evidence digest. Retrieval of actual production pre-state behind the digest for independent recomputation **UNVERIFIED**. |
| 8 | Durable correlated mismatch cannot become success | Mismatch exception + immutable observation tests and both SQLite append-interruption/reopen cases passed; one correlated durable mismatch event, no redispatch, replay still fails. Deployed database restart **UNVERIFIED**. |
| 9 | Detect/policy missing required expected effects | High-impact incomplete-contract registration fails with ExpectedEffectRequired; complete-contract positive case passes. Exercised in fresh core test run. |
| 10 | Seven historical TOOL_EFFECT controls/retirement | Current direct-effect census matches; Hive/legacy controls and BuildersLearning retirement tests pass. Complete historical seven-site equivalence remains **UNVERIFIED**; do not substitute a count of four current sites for historical acceptance proof. |
| 11 | Introduced raw path rejected by architecture gate | 74 adversarial audit tests passed, including newly introduced raw Hive tool and browser client paths rejected by the actual scanner. |
| 12 | #847 closes first with adversarial evidence | **UNMET**: supplied frozen dispatch source `repos/Agent-StrongHold/Project-mAIstro/issues/847` has `state=open`. Local adversarial tests do not close this dependency. No remote mutation or status refresh attempted. |

## Handoff

No supplied deterministic driver logs existed at start. All `check-*-local.log` files in this job directory were generated by this worker; do not misattribute them to a driver or remote CI. Exact-head remote CI is **UNVERIFIED**.

Only this evidence handoff is changed in this round. No reproducible vulture failure or stale SECURITY claim warrants a production, test, quality ledger or inventory-note edit. Explicit permission to amend the vulture ledger does not justify fabricating a delta when the exact gate passes. Preserve previous branch work unchanged. No scheduler/store/event/authorization authority added; accepted ADR semantics remain intact.

Disposition: **BLOCKED**, not integration approval. Owner must sequence #847, complete missing production/backend acceptance evidence, and verify exact-head CI. Checked 1 assigned issue; focused validation done 1; issue completion 0; skipped issues 0; validation errors 0. Next: owner review of unmet/UNVERIFIED criteria. Finish with local evidence commit; never push.

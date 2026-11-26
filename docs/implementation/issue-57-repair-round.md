# Issue 57 repair checkpoint

Frozen scope: issue #57, branch `auto-57`, starting HEAD
`4a8680c224c342359d7f92fc9b209aa153902e1b`, supplied develop base
`ac1e2f9556f178fe2597927021d6218d78663101`.

This writer round will review the existing governed-tool seam and adjacent tests,
repair the reported SECURITY.md reachability claim if reproduced, and execute the
exact vulture CI command. Only actual scan findings will justify source or
`quality/vulture-baseline.json` changes (explicitly permitted by this lane).
Expected edit scope: this checkpoint, SECURITY.md, and the vulture ledger if
needed. No other issues, remote mutations, policy grants, or execution authorities.

Initial state: clean worktree; HEAD matched the assignment. Supplied job directory
contains no check-*.log files. The supplied prior result reports BLOCKED, not
acceptance proof. Assumption: this is the writer role, because the assignment
explicitly requests repair and a local commit. #847 closure and remote CI are
external prerequisites; do not infer completion or close anything.

## Reproduced results

- `uv sync --locked --extra dev`: exit 0.
- Exact CI vulture scan: exit 0 (`/tmp/issue-57-vulture-initial.log`). No
  unbanked identities were reported; no ledger amendment is justified.
- SECURITY.md layer 4 already documents registry construction through
  `tools/contracts.py` and explicitly distinguishes classification from approval
  gating. The supplied stale-doc finding is not reproducible at starting HEAD;
  do not apply another wording-only repair.
- Frozen dispatch source `issues/847` remains `state=open`. Acceptance criterion
  12 is not met in the supplied evidence; no remote mutation is permitted.
- Architecture reviewed: ADR-050, ADR-068, ADR-081226-6b46. Tool exposure is
  not authority; classification is distinct from approval. Canonical Invocation
  remains the effect lifecycle; no competing execution authority is introduced.
- Production wiring reviewed: Agent bridge passes `admitted_tool_executor`;
  Hive registry reaches `GovernedToolExecutor` and canonical Invocations.
  Legacy `_run_tool_node` uses canonical Invocation directly, not the governed
  contract executor. Its request contains task/config and its Binding contains
  `effect`, but it does not resolve/record registry reversibility. Full
  acceptance 6/10 parity remains unproven and must not be claimed from schema
  tests alone. This round will not expand into an unassigned legacy redesign.
- An inspection command referenced nonexistent `scripts/check-direct-effects.py`;
  it was not executed. Resolved the actual gate to
  `scripts/check_direct_effects.py` before running validation.

## Fresh focused validation

All commands below executed in the assigned worktree with `uv run`; test/gate
commands had 1200-second timeouts. Logs are `/tmp/issue-57-<name>.log`.

| Command | Outcome | Log name |
| --- | --- | --- |
| `pytest` core governed contracts, Agent base/factory/spec, ReAct, BuildersLearning, artificer, effect-context policy, Sentinel audit files | 303 passed | core-tests |
| `pytest` Hive governed tools, legacy DAG node, Agent model tools, core adapter files | 92 passed | hive-tests |
| `pytest packages/maistro-bootstrap/tests -x -q` | 236 passed, 7 skipped | bootstrap-tests |
| `pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q` | 74 passed | gate-tests |
| `ruff check .` | exit 0 | ruff-check |
| `ruff format --check .` | exit 0; 3385 files formatted | ruff-format |
| `python scripts/check_direct_effects.py` | exit 0; 51 sites, 4 TOOL_EFFECT | direct-effects |
| `python scripts/check-model-egress.py` | exit 0; explicitly reports 12 reachable escapes awaiting #56 migration | model-egress |
| `python scripts/check-security-inventory.py` | exit 0; prose is explicitly not fully checked | security-inventory |
| `python scripts/check-convergence-matrix.py` | exit 0; 1426 production modules classified | convergence |
| `python scripts/check-suite-inventory.py` | exit 0; all 21 suites match | suite-inventory |

No test/source/ledger changes were warranted by these checks, so no test inventory
delta note is needed. Passing ratchets are not proof that all acceptance criteria
are met: some gates intentionally bank unresolved escapes and count inventory.

## Acceptance evidence (not integration approval)

| # | Criterion | Executed evidence and limitations |
| --- | --- | --- |
| 1 | Consume the #55 seam, no second executor | Hive boot and legacy Invocation tests pass; `contracts.py:355` calls the existing Invocation service. Repository-wide M1 completion **UNVERIFIED**: model-egress reports banked reachable escapes, not completed cutover. |
| 2 | Canonical authorization and required predictions | Core `test_governed_tool_persists_expected_evidence_on_canonical_invocation` and Hive `test_governed_tool_records_invocation_with_registry_tier` pass. Core evidence is configured high-impact; shipped Hive registry exposes read-only tools. |
| 3 | Effective authorized tool set before dispatch | Agent base, ReAct, artificer denial tests and Hive `test_unlisted_and_badly_typed_tools_refuse_before_the_backend` pass. BuildersLearning Frank/Mason no-effect tests pass. Full legacy effective-envelope equivalence **UNVERIFIED**. |
| 4 | Missing/unknown schemas fail closed | Core `test_agent_allowlist_and_unknown_schema_fail_before_backend` and Hive materialized legacy argument refusal tests pass. These test denial before backend calls, not just error formatting. |
| 5 | One constrained command contract across supported backends | Bootstrap command contract/argv/injection tests pass within the 236-test suite. Seven tests skipped; live container/microVM backend equivalence **UNVERIFIED**. |
| 6 | Host-owned registry reversibility | Hive production seam registry-tier test passes; caller arguments cannot inject extra tier fields under its schemas. Legacy parity **UNVERIFIED**: `legacy_dag_node.py:437` invokes directly with task/config and no registry tier, unlike `contracts.py:335`. |
| 7 | Exact/recomputable expected-effect identities | Core SQLite reopen test passes for both append interruption modes; asserts Invocation/capability/provider/argument/pre-state digests, post-state and policy version after rebuilding durable stores. Live PostgreSQL restart **UNVERIFIED**. |
| 8 | Durable correlated mismatch, not ordinary success | Core mismatch and SQLite reopen/replay tests pass; mismatch remains immutable, raises PredictionMismatch, appends one correlated event without redispatch. |
| 9 | Detect missing required high-impact predictions | Core `test_high_impact_contract_without_expected_effect_fails_closed` passes, including the complete-contract positive case. |
| 10 | Seven historical TOOL_EFFECT sites controlled or retired | Current direct-effect inventory matches 51 sites including 4 retained TOOL_EFFECT sites; architecture tests reject newly introduced raw sites. Full historical seven-site control equivalence **UNVERIFIED**, particularly legacy reversibility/effective-envelope parity. Inventory membership alone is insufficient proof. |
| 11 | Gate rejects introduced direct/raw tool paths | Both `test_a_newly_introduced_raw_hive_tool_call_is_rejected_by_the_audit` and `test_a_newly_introduced_raw_browser_client_call_is_rejected_by_the_audit` pass in the 74-test gate run. |
| 12 | #847 closes first from adversarial evidence | **UNMET**: frozen dispatch source `issues/847` says open. This writer neither refreshes nor changes GitHub state. Its adversarial subsets were run above, but no closure/complete #847 verification is inferred. |

Remote head CI is **UNVERIFIED**. No check-*.log files were supplied in this job
directory; local checks were run independently. Earlier job success claims and
historical inventory-note completion claims are not adopted.

## Handoff

Only this evidence checkpoint changed. No production behavior, tests, quality
ledgers, or grants changed; the reported doc drift and unbanked-vulture failure
were already absent at starting HEAD. This is a blocked handoff, not a claim of
repair or merge readiness. Remaining work: independently prove/repair legacy
control parity without creating another authority, validate missing backend/M1
evidence, and have the authorized owner sequence the #847 prerequisite.

Progress: checked 1 assigned issue; validation item done 1; issue completion 0;
skipped issues 0; validation errors 0. Next: owner review of the explicit unmet
and UNVERIFIED criteria above. Finish with a local commit only; never push.

# Issue 57 — fresh validation handoff (abb2e4d6)

## Frozen scope and disposition

- Assigned issue #57 only, branch `auto-57`, clean starting HEAD
  `16a6bb93b2737769efb87443d092f7c5bd572021`; supplied develop base
  `161dedc06344b3d9630f3b79be9418088a5bff99`.
- Frozen evidence: `/home/dev/maistro/jobs/abb2e4d629b64d9a96a6d1ca00e83787/dispatch-context.json`.
  No re-fetch, GitHub mutation, or dependency closure performed.
- Writer role follows the explicit repair/local-commit assignment. Initial job
  directory contained no driver `check-*.log` files. Logs named below were
  generated independently in this round, not adopted from earlier claims.
- Reported SECURITY.md drift does not reproduce: line 35 already documents
  `ReversibilityRegistry` construction through governed tool contracts and
  distinguishes classification from Sentinel approval gating (#346).
- Exact vulture gate passes: 1299 findings, zero unclassified/unbanked identities,
  trusted comparison base `652cf8e56f38`. No ledger amendment is warranted.
- Only this handoff file changed. No production, test, inventory, ledger, or
  grant changes are justified by the reported defects. No inventory-delta note
  is needed because no tests were added or removed.

## Architecture and inspection

Read repository instructions, documentation authority hierarchy, accepted
ADR-004 (including the declaration-removal amendment), ADR-050, ADR-068 and
ADR-081226-6b46. Tool contracts narrow the existing Binding/Invocation seam;
ToolExposure is not authority, and classification is not approval. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt` and existing event/store/policy
ownership; no new executor authority or scheduler was introduced.

Re-read production `tools/contracts.py`, Agent shared authorization/schema
boundary, Hive governed/legacy wiring, expected-effect model and canonical
observation/event code, retired BuildersLearning side effects, bootstrap argv
dispatch, and adjacent adversarial tests. Three initial ADR reads used wrong
descriptive filenames (ENOENT; skipped); actual filenames were resolved once
and read successfully. No unresolved command ref was executed.

## Fresh executed validation

All validation used `uv run` in the assigned worktree with 1200-second command
timeouts. Logs live in the job directory above.

| Command | Result | Log |
| --- | --- | --- |
| `uv sync --locked --extra dev` | PASS | `check-sync.log` |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS | `check-vulture.log` |
| `uv run ruff check .` | PASS | `check-ruff.log` |
| `uv run ruff format --check .` | PASS; 3482 files | `check-format.log` |
| Core focused pytest selection below | 1643 passed, 12 skipped | `check-core.log` |
| Hive focused pytest selection below | 112 passed | `check-hive.log` |
| `uv run pytest packages/maistro-bootstrap/tests -x -q -rs` | 255 passed, 7 skipped | `check-bootstrap.log` |
| `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -x -q` | 74 passed | `check-adversarial-gates.log` |
| `uv run python scripts/check_direct_effects.py` | PASS; 51 sites, 4 TOOL_EFFECT | `check-direct-effects.log` |
| `uv run python scripts/check-model-egress.py` | PASS as ratchet; retains 12 reachable escapes awaiting #56 | `check-model-egress.log` |
| `uv run python scripts/check-security-inventory.py` | PASS; not a general prose proof | `check-security-inventory.log` |
| `uv run python scripts/check-convergence-matrix.py` | PASS; 1457 production modules classified | `check-convergence.log` |
| `uv run python scripts/check-suite-inventory.py` | PASS; 21 suites, 34055 unique identities | `check-suite-inventory.log` |

Core selection (all paths verified present):

```sh
uv run pytest packages/maistro-core/tests/tools packages/maistro-core/tests/capabilities packages/maistro-core/tests/agents/test_base.py packages/maistro-core/tests/agents/test_factory.py packages/maistro-core/tests/agents/test_tool_schema_boundary.py packages/maistro-core/tests/agents/spec packages/maistro-core/tests/agents/strategies/test_react.py packages/maistro-core/tests/agents/strategies/test_builders_learning.py packages/maistro-core/tests/agents/artificer/test_strategy.py packages/maistro-core/tests/security/sentinel/test_audit.py -x -q -rs
uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py packages/hive-conductor/backend/tests/test_legacy_dag_node.py packages/hive-conductor/backend/tests/test_agent_model_tools.py packages/hive-conductor/backend/tests/test_maistro_core_adapter.py -x -q -rs
```

Core skips: four Playwright transport tests, one real database pool test, seven
PostgreSQL contention cases. One unawaited `_FakeProc.communicate` warning.
Bootstrap skips: Windows-only escape test and six unavailable Docker/builders
image tests. Live backend parity is not inferred from mock/subprocess tests.
Workflow exact vulture arguments confirmed at `vulture-ratchet.yml:82` and
`quality.yml:1526`; model-egress and inventory use workflow default arguments.

## Acceptance — executed evidence and explicit limits

| # | Evidence / limits |
| --- | --- |
| 1 | `tools/contracts.py:358` delegates to canonical Invocation. Core and real-Container Hive tests passed. Complete #55 production cutover **UNVERIFIED**; a passing model-egress ratchet explicitly retains reachable #56 escapes. |
| 2 | Core persisted-prediction test checks authorization/completion events and evidence on Invocation; Hive boot tests assert real Invocation identity. Universal production policy coverage **UNVERIFIED**; current Hive contracts are read-only. |
| 3 | Agent boundary (`agents/base.py:900`) checks declared tools before Sentinel/backend; custom-strategy, ReAct, artificer and Hive denial tests passed. Full principal/Workspace/Goal/Run authority-envelope equivalence **UNVERIFIED**. |
| 4 | Missing/unknown/root/nested unsupported schema tests and host-schema mutation/repair tests passed, asserting no backend dispatch. |
| 5 | Bootstrap raw-command/argv/metacharacter and sandbox hardening tests passed; `agent_loop.py:413` dispatches `run_argv`. Live supported-backend equivalence **UNVERIFIED** (six live cases skipped). |
| 6 | Registry/Hive/legacy host-reclassification tests passed. `legacy_dag_node.py:409` resolves common host registry; `SECURITY.md:35` accurately limits approval-gating claims. |
| 7 | SQLite reopen and argument-mutation tests passed: exact capability/provider, arguments/digest, pre-state digest, expected/observed state, Invocation and policy version survive recovery. Deployed high-impact/PostgreSQL restart coverage **UNVERIFIED**. |
| 8 | Immutable mismatch and interrupted append/ack SQLite reopen tests passed, preserving correlated mismatch and refusing ordinary success without redispatch or duplicate event. Cross-process observation races **UNVERIFIED**; append recovery requires replay. |
| 9 | Incomplete high-impact contract test raises `ExpectedEffectRequired`; complete-contract positive case passed. |
| 10 | Current direct-effect inventory and legacy/retired-strategy tests passed; four TOOL_EFFECT sites remain. Historical seven-site control-equivalence mapping **UNVERIFIED**; ledger disposition alone is not completion proof. |
| 11 | Executed `tests/test_check_direct_effects.py:496,519` deliberately introduce raw Hive/BrowserClient paths; both are rejected by the architecture audit. |
| 12 | **UNMET**: frozen dispatch source `issues/847` (source starts at `dispatch-context.json:74899`) records `state=open`. Adversarial subsets passed locally but do not close the prerequisite or prove all its acceptance. |

## Handoff

**BLOCKED**, not integration approval. Reported doc and exact-debt defects are
absent at this HEAD; no evidence-backed code repair was reproduced. Remote
exact-head CI is **UNVERIFIED**. Next: prerequisite-owner review/verification of
#847 and the explicit production/backend coverage gaps, not another speculative
ledger or cosmetic source repair. No issue closure actions are authorized.

Progress: checked 1 assigned issue; done 1 validation handoff; skipped issues 0;
validation failures 0; three corrected read-path errors documented above. Commit
this note locally, then confirm clean status. No push.

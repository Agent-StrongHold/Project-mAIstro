---
inventory-delta:
  packages/hive-conductor/backend/tests: 3
---
# Issue 1154: Hive execution refuses a missing spine

`test_dag_agents.py` adds three missing-dependency cases (Container, RunStore,
graph projection), proving refusal before configuration, resolver construction,
or physical execution. Its positive execution test now checks the canonical
Attempt and accepted NodeRun evidence, not just a nonempty aggregate.

Existing registered-DAG and metrics tests explicitly request a real in-memory
canonical RunStore plus CanonicalDurableRunStore. Scheduler cursor fixtures map
their historical synthetic scopes to real Projects before canonical execution;
HTTP/WebSocket parity fixtures share the admission Project authority. HITL and
Attention document-seeding fixtures are explicitly projection-only test seams,
not production execution fallbacks. No additional executor or authority is added.

## ADR reconciliation / unresolved acceptance

ADR-082826-d9f5 decision 4 mandates retirement of Hive's module-level document
store: this repair removes it and makes both graph-store accessors fail closed.
ADR-082526-3ca6 AC-5 preserves standalone *node resolution*, which remains intact.
However ADR-082826-d9f5 AC-1 explicitly permits library callers without a RunStore
to execute on the pre-convergence path. The issue's blanket no-spine prohibition
conflicts with that accepted criterion. This repair does not silently override
it: `test_canonical_identity.py` and the core compatibility path remain unchanged.
Thus issue acceptance 2 cannot be claimed globally without an ADR reconciliation.

## Executed validation (repair starting at `2a93d1ad732a`)

All commands ran in the assigned worktree with `uv run`; logs are under
`/home/dev/maistro/jobs/9a43b5c650dd41949f7d8c0f91aaabe0/`.
No driver `check-*.log` files existed there at start. Prior verification claims
were not used as acceptance evidence.

- `ruff check .`, `ruff format --check .`: pass.
- `pytest packages/maistro-core/tests/graph packages/maistro-core/tests/testing
  packages/maistro-core/tests/orchestrator/waves packages/maistro-core/tests/builders
  packages/maistro-core/tests/integration/test_chat_to_graph_e2e.py
  packages/maistro-core/tests/resilience packages/maistro-core/tests/codebase -x -q`:
  **1735 passed, 97 skipped, 1 xfailed** (`core-validation.log`). This includes
  public API retirement, canonical identity, durable traversal/frontier/parity,
  and retained policy/helper tests. PostgreSQL cases were not proven here.
- Hive `pytest -x -q` on `test_dag_agents`, `test_node_metrics_are_measured`,
  `test_scheduler`, `test_attention_projection`, `test_dag_execution_transport_parity`,
  `test_hitl_door`, `test_hitl_timeout_cancel`, `test_registered_dag_recovery`, and
  `test_graph_runner` (all `.py` under `packages/hive-conductor/backend/tests/`):
  **203 passed** (`hive-repair-final.log`). Intermediate fixture failures were
  repaired and re-run; they are preserved in `hive-repair.log`.
- Adjacent Hive `pytest -q --tb=short` on `test_canonical_dag_runner`,
  `test_graph_runner_injection`, `test_evolution_canonical_graph`,
  `test_dag_recovery`, `test_dag_condition_trust`: **74 passed**.
- `python scripts/check-{retired-guidance,execution-lifecycles,convergence-matrix,
  merge-markers,wiring-reads,reachability,reachability-dispositions}.py` (each
  separately): pass. Retired guidance checks 438 governed files; the convergence
  matrix explicitly classifies `run_graph` / `GraphRun` as RETIRED.
- `python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests`
  and the same with `packages/maistro-core/tests`: pass. Hive inventory is 2817.
- `git diff --check`: pass.

## Exact-debt repair and blocker

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` exits **1**: 14 retained identities lack trusted-base
authorization (the fifteenth added identity, `parallel_generations`, is authorized).
The candidate ledger already has the exact current multiset: the 16 stale rows
printed by the gate belong to the **trusted base**, not this candidate. Running
that same command with `--update` succeeds and produces **no identity changes**.
The permitted ledger amendment adds per-identity rationale for the 14 reviewed
retained identities: serialized result/parser fields, compatibility configuration,
and tested policy/adapter helpers, without pretending they have shipped callers.
No gates, category matchers, authorization grants or accepted ADRs were changed.
Candidate bookkeeping cannot supply the separately landed grant the gate demands.

Acceptance 1, 3, 4, 5 and traversal preservation (6) have the executed evidence
above. Acceptance 2 remains **UNVERIFIED globally / contradicted by the retained
core compatibility tests** under accepted ADR-082826-d9f5 AC-1, despite the repaired
Hive boundary. Next owner must reconcile that ADR and authorize or separately
retire the reviewed retained debt before claiming merge readiness. This is a
partial writer handoff, not integration approval.

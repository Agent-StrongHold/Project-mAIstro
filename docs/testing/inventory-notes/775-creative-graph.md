---
inventory-delta:
  packages/maistro-design/tests: +13
---

# 775-creative-graph — issue #775: the creative Graph for multi-artifact fan-out and targeted regeneration

Thirteen maistro-design node IDs, all additive, in one new suite. No other
suite moved. The suite executes the reference creative-production Graph
end to end through the **canonical** durable executor
(`maistro.graph.durable_runs.run_durable_graph` / `resume_durable_graph`) —
the same Run/NodeRun/Attempt machinery every other graph consumer uses — so
every claim below is checked against the real execution spine, not a test
double. No model calls: the stage kinds are deterministic registered node
kinds (`maistro_design/creative_nodes.py`), the same pattern as the
`daily-status` DAG seed.

Production code under test (`packages/maistro-design/src/maistro_design/`):

- `creative_graph.py` — `plan_creative_graph` (one canonical
  `GraphTemplate` per CreativeBrief version: shared upstream decision
  stages → one parallel branch per requested artifact → cross-artifact
  critique → targeted refinement → acceptance → publish/export),
  `instantiate_creative_graph` / `creative_run_provenance` (the exact Goal
  identity/revision, brief lineage/version and accountable/delegated Agent
  provenance bound into the instantiated Graph metadata and the canonical
  Run provenance), `run_creative_graph` (canonical launch only — no private
  scheduler), `invalidated_requests` (pure invalidation arithmetic over two
  brief versions), and `artifact_provenance` (per-artifact lineage read
  from persisted canonical state alone).
- `creative_nodes.py` — eleven deterministic stage kinds. Shared decisions
  are persisted once on the run blackboard (canonical
  `GraphExecutionState` state) and cited by every branch; per-branch
  artifact records travel as blackboard annotations (`dict[str, str]`
  contract: one canonical-JSON record per branch, merged per key across
  parallel siblings) so fan-in stages read real persisted state.

`test_creative_graph.py` (+13), by acceptance criterion:

1. **One template plans/executes ≥3 branches** — template spine + one
   branch per request; a canonical Run walks all three to completion.
2. **Graph/Run retain Goal revision + Agent provenance** — instantiated
   Graph metadata and `Run.provenance` carry goal_id/goal_revision/brief
   version/owner/delegation; the owner is the Run's `actor_principal_id`;
   the template itself stays a reusable plan (no run identity).
3. **Branches run concurrently when ready** — two branches synchronized on
   `asyncio.Event`s (a sequential walker deadlocks into a loud timeout);
   both complete in one frontier wave via the executor's `asyncio.gather`.
4. **Shared decisions persisted once, referenced by descendants** — exactly
   one `message.architecture` / `visual.direction` NodeRun; every branch's
   durable record cites the same consumed decision identities.
5. **Failure isolation** — planted first-try failure: only that branch
   retries (fail NodeRun + succeed NodeRun), siblings visited exactly once
   and accepted; beyond-budget failure fails only its Run, accepted
   siblings stay accepted, and canonical resume refuses the terminal Run.
6. **Invalidation follows the dependency shape** — audience change
   invalidates every descendant; a poster-dimension-only change invalidates
   only the poster branch (website/deck unchanged); channel families
   specialize branches.
7. **Goal revision change** — explicit invalidation naming the revision
   move; historical brief/Run/artifact provenance verified byte-identical
   after the change (`store.get` round-trip).
8. **Every try is Attempt evidence** — per-branch Attempt counts (2/1/1 for
   fail-then-succeed), executor ids set, the failed try's envelope
   (`attempt.result.success is False` + `error_message`) and the failed
   NodeRun error carry the planted failure.
9. **Refresh reconstructs real state** — SqliteDurableRunStore process-loss:
   a fresh store instance reconstructs accepted/failed branch state and
   full provenance from disk; re-fulfillment is a NEW Run that never
   mutates the historical record.
10. **Inspection explains lineage** — each artifact names its Goal
    revision, brief version, consumed shared-decision identities, owner
    agent and delegation ref, status and attempt count, read only from the
    persisted record.

Two canonical behaviors the tests document rather than work around: a
canonical retry visit receives static inputs only (immediate-predecessor
outputs are not re-selected for a revisit), so shared decisions fall back
to the once-persisted blackboard record; and a FAILED Run is terminal
(`resume_durable_graph` refuses it) — new Goal work is a new Run.

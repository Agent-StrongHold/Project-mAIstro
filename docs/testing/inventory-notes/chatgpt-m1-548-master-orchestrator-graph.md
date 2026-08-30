---
inventory-delta:
  packages/maistro-core/tests: +8
---
# chatgpt-m1-548-master-orchestrator-graph

MasterOrchestrator no longer owns a competing execution lifecycle. Its legacy
WorkItem API is projected from canonical Graph -> Run -> NodeRun -> Attempt
execution (#548, #44).

**`tests/orchestrator/test_master_canonical.py` (+7)** proves the convergence
contract at the physical boundary:

- standalone Master durable state is assembled by `CanonicalDurableRunStore`
  over the same canonical `RunStore`, rather than a process-local second record;
- one successful WorkItem is one canonical NodeRun with one canonical Attempt;
- an explicitly retryable failure uses the canonical node policy and creates a
  new NodeRun visit with its own Attempt, matching the retry spine merged in
  #573;
- a completed parallel sibling keeps its routing decision and output while a
  neighbouring sibling consumes a retry, so later dependency input is not lost;
- a failed dependency blocks only the dependent handler while independent work
  in the next canonical Graph frontier still executes;
- configured wave parallelism is declared on the Graph and enforced by the
  canonical `PythonExecutionRuntime` rather than a private Master semaphore;
- a security-gate rejection remains failed physical Attempt evidence while its
  exhausted NodeRun is accepted as a completed logical domain outcome.

**`tests/graph/durable_runs/test_continue_on_failure.py` (+1)** pins the generic
physical/logical split used by that projection: retry budget is still canonical
NodeRun visitation, and only the exhausted logical disposition is softened.
The final `AttemptResult` retains the failed `NodeResult` unchanged.

`WorkItemStatus` remains compatibility/domain vocabulary only. Canonical Run,
NodeRun, Attempt, and Graph continuation records are the execution authority,
and the execution-lifecycle ledger entry for MasterOrchestrator is retired by
this change.

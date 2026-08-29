# PR #548 test inventory

This slice replaces MasterOrchestrator's private execution lifecycle with canonical durable Graph execution.

Focused evidence added/changed in `packages/maistro-core/tests/orchestrator/test_orchestrator.py` covers:

- one WorkItem producing a canonical NodeRun and physical Attempt;
- failure projected from canonical NodeRun terminal state;
- same-frontier concurrency owned by Graph rather than a Master semaphore;
- dependency sequencing represented by Graph edges;
- failed dependencies projected as blocked work;
- retries represented as new NodeRun visits, each with one Attempt;
- progress projected from canonical terminal state;
- missing-handler failure;
- security-gate failure.

The existing SuperPlanner topology tests remain in the same file.

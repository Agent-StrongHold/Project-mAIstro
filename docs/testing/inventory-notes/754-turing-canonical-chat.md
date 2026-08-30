---
inventory-delta:
  packages/maistro-turing/backend/tests: +3
---

# PR #754 Turing canonical chat coverage

PR #754 adds three net behavioral cases to the existing Turing backend chat suite and strengthens the existing success/failure cases. The suite now proves that a reachable chat request is filed in a canonical Workspace Root Project, produces one canonical Run with one chat NodeRun and physical Attempt evidence, exposes the producing `run_id`, records provider failure as a failed canonical Run before projecting HTTP 503, creates a new Run for each turn while retaining the same user Workspace/Project scope, rejects malformed canonical NodeRun result projection, and fails closed if canonical execution asks the Turing-local resolver for an unexpected node.

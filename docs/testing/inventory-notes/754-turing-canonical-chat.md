---
inventory-delta:
  packages/maistro-turing/backend/tests: +1
---

# PR #754 Turing canonical chat coverage

PR #754 adds one net behavioral case to the existing Turing backend chat suite and strengthens the existing success/failure cases. The suite now proves that a reachable chat request is filed in a canonical Workspace Root Project, produces one canonical Run with one chat NodeRun and physical Attempt evidence, exposes the producing `run_id`, records provider failure as a failed canonical Run before projecting HTTP 503, and creates a new Run for each turn while retaining the same user Workspace/Project scope.

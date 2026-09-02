---
inventory-delta:
  packages/maistro-turing/backend/tests: +8
---

# PR #754 Turing canonical chat coverage

PR #754 adds eight net behavioral cases to the existing Turing backend chat suite and
strengthens the existing success/failure cases. The suite now proves that a reachable chat
request is filed in a canonical Workspace Root Project, produces one canonical Run with one
chat NodeRun and physical Attempt evidence, exposes the producing `run_id`, records provider
failure as a failed canonical Run before projecting a fixed public HTTP 503 detail, and never
returns provider exception text to the caller. It proves cancellation terminalizes Run,
NodeRun, and Attempt evidence; Turing uses the canonical chat admission source, durable
retention deadline, and bounded per-process chat window; a failed Run creation does not make
chat unavailable; and a failed initial graph checkpoint compensates the partially admitted Run
before executing the turn once without a `run_id`. Existing coverage also proves each turn gets
a new Run while retaining the same user Workspace/Project scope, malformed canonical NodeRun
result projection is rejected, and an unexpected Turing-local node fails closed rather than
being replayed outside canonical execution.

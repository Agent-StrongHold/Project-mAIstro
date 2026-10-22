---
inventory-delta:
  packages/maistro-core/tests: +5
---
# Recovery refusal and frontier coverage

Add five core cases, with no removed tests or changed production code.
Collection moves from 12,074 to 12,079.

- Two new cases exercise Container recovery over real memory and SQLite
  stores. A persisted physical completion followed by logical cancellation
  produces a real reconciliation integrity error. Recovery records the
  refusal, does not count it as recovered work, and preserves all three
  Run/NodeRun/Attempt records. Both Containers close in `finally`.
- Three cases extend the canonical recovery contract with a persisted
  Attempt lease just before, exactly at, and just after expiry. A live lease
  cannot requeue the frontier; expiry makes its continuation due exactly
  once while preserving canonical execution evidence.

These cases cover the unexecuted integrity-refusal and attempt-bearing
frontier branches reported by PR #1846's diff-coverage gate on `a639c03a`.
Changing the handled exception or counting a refusal as success fails both
Container cases. Always-live and never-live frontier predicate mutants fail
the expiry and live cases respectively. No floor, grant, inventory baseline,
source semantics, or existing assertion changes; the separate no-op replay
starvation bug is neither changed nor asserted as desired behavior.

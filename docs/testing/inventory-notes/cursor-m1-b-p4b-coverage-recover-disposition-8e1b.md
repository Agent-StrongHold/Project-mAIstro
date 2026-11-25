---
inventory-delta:
  packages/maistro-core/tests: +11
  packages/maistro-canvas/tests: +2
---

# cursor-m1-b-p4b-coverage-recover-disposition-8e1b

Coverage gate repair for #2425 / P4b tip: six pure lifecycle refusal/happy
cases for ``recover_leaseless_orphaned_attempt``, five durable
``DurableRunExecutionStore`` recover/disposition cases (skip-loop + missing
Attempt/NodeRun + wired RunStore mirror), and two Canvas reclaim race-path
cases (``_race_or_require_terminal`` + reclaim raise/None fallback).

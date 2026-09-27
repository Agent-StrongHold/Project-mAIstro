---
inventory-delta:
  packages/maistro-core/tests: +3
---
# feat-lane-m1-hitl

`test_a_parent_cannot_complete_while_a_human_node_run_is_paused` is one new
test, collected three times (memory, sqlite, postgres). It pins that a PAUSED
human NodeRun blocks parent `COMPLETED` on every RunStore backend, and that
the parent may complete once that NodeRun itself reaches `COMPLETED`.

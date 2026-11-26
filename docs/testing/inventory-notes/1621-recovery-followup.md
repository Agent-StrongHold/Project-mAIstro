---
inventory-delta:
  packages/maistro-core/tests: -10
---
# 1621 recovery follow-up inventory reconciliation

At the supplied develop base, recollection of the core suite found 18,439 test
node IDs versus the inventory sum of 18,457. The server's prior -10 drift was
the recovery suite absent from the reconstructed branch; restoring its ten
meaningful lifecycle tests brings that suite back to its recorded 680. The
core adjustment reconciles accumulated inventory arithmetic; the repair round
added one durable-store fence regression test
(`test_a_stale_park_replay_cannot_move_the_node_run`), netting -17. Recovery
test coverage is also documented in `1621-abandoned-attempt-recovery.md`.

Follow-up repair round: two spine-conformance pins for the terminal-parent
fork carve-out (#1621) — `test_a_durable_fork_child_is_accepted_under_a_terminal_parent`
and `test_a_fork_fact_naming_another_parent_is_refused_under_a_terminal_parent`,
each parametrized over the memory/sqlite/postgres spine fixture (+6 node IDs) —
plus one replay-selection race pin
(`test_replay_selection_answers_none_for_a_purged_node_run`, +1), netting -10.

---
inventory-delta:
  packages/maistro-core/tests: -17
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

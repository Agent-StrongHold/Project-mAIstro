---
inventory-delta:
  packages/maistro-core/tests: +1
---
# issue-48-hitl-workspace-scope

Adds workspace-scoped pending-work enforcement plus a SQLite continuation-store
race regression proving two stale writers cannot both settle one continuation.

Three regressions were authored in this lane: the workspace-scoped routes test,
the terminal-continuation crash repair, and the stale-writer settlement race.
The first two landed identically on develop through the upstream HITL lineage
(`test_hitl_routes_are_scoped_to_the_callers_workspaces` in
`test_hitl_door.py`, `test_reconcile_repairs_crash_after_terminal_continuation_persistence`
in `test_hitl_settlement.py`), so the merge resolves to one copy of each and
they move no count here; only the stale-writer test is a net addition of this
branch. The scoped pending queue and answer/cancel mutations remain covered by
the develop copies.

---
inventory-delta:
  tests/: +2
---

# #1572: preserve landed HITL revision 061

The assigned develop snapshot `66f3cea9e98980f146a12cf3142d66e30986d276`
landed `061_hitl_pause_kind_index`. The Goal branch also claimed `061`.
Preserve develop's file byte-for-byte and append the unmerged Goal migration
as `062`, parent `061`. No merged migration is renumbered.

`tests/migrations/test_goal_installed_base_upgrade.py` adds one live installed-base
case built with that actual develop snapshot. It checks the original 061 stamp,
absence of Goal tables, forward upgrade without stamping/resetting, survival of
the HITL index and existing user-model/Run data, all Goal tables and planner
artifacts, and durable Goal/revision/bound-Run close/reopen readback.

The existing durable-composition upgrade test now runs from both historical
056 and 057 snapshots (one additional parameterized case). Static identity and
byte-identity tests also pin landed HITL 061. No tests were removed. Core suite
counts are unchanged. Validation and environment limitations are recorded in
`docs/testing/goal-1572-repair-b571.md`.

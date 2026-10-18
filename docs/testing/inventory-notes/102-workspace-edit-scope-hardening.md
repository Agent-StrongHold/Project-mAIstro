---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---

# Backlog edit-scope hardening in the canonical service (#102 follow-up)

One body added to the existing
`packages/hive-conductor/backend/tests/test_backlog_routes.py` suite (+1 node
ID): `test_workspace_id_is_not_generic_editable` proves an editor of one
workspace cannot republish an item into another workspace through the generic
PATCH edit path — the attempt is refused with 422 (`workspace_id` is
deliberately absent from `_EDITABLE_FIELDS`) and the item's workspace scope is
unchanged afterwards.

Two behavior fixes in `services/backlog.py` are covered by the existing bodies
(no new node IDs): `get_detail` now filters dependencies/dependents/children
through the same `_resolve_role` visibility rule as the main item, so private
and cross-workspace related items no longer leak even their id/title/status;
and `update_item` stages the edit on a deep copy, so a refused patch (unknown
field, archived-item guard, validation failure) no longer leaks partial field
writes or a version/provenance bump into subsequent reads. No existing test
was removed or renamed.

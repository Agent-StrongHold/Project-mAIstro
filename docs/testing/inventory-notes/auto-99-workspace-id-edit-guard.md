---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# auto-99 backlog edit-surface hardening (#99 fail-closed authorization)

Adds three node IDs to `packages/hive-conductor/backend/tests/test_backlog_routes.py`
and two matching service changes in
`packages/hive-conductor/backend/services/backlog.py`:

- `test_workspace_id_is_not_generic_editable`, with `workspace_id` removed
  from `_EDITABLE_FIELDS`. The gap: generic edits authorize the caller
  against the item's *current* scope only, so a workspace editor could
  `PATCH` `workspace_id` and publish the item into any workspace whose id
  they know — an authorization bypass on the "unauthorized edits fail
  closed" criterion. Scope is now creation-time only (create checks
  destination membership); moving an item between workspaces needs an
  explicit destination-authorized path, not a field edit. The test proves an
  editor member's attempt to move another workspace's item into their own is
  refused with 422 (`field is not editable`) and the item's scope is
  unchanged afterward.
- `test_create_refuses_a_status_outside_the_legend`, covering the reject arc
  of `BacklogItem._status_is_a_legend_value` (`models/backlog.py`): the
  service pre-validates `status` on the PATCH path, so creation is the only
  route that reaches the model validator's ValueError — the branch the
  diff-coverage gate measured at 50%. Proves `POST /v1/backlog` with an
  off-legend status is a 422 naming the legend, and stores nothing.
- `test_refused_patches_leave_stored_state_untouched`, with `update_item`
  changed to stage the whole edit on a deep copy and publish only after
  every check passes. Previously `_get()` handed back the store's own row,
  so a patch refused by a later check (archived-item guard, park-evidence
  guard, invalid field after a valid one) had already mutated the live item:
  a follow-up GET showed the new title at the old version with no
  provenance. The staged-row rule also closes the supply-then-refuse park
  leak (a `status: blocked` change whose reason failed validation could
  leave `blocked` set on the live row). Both leak shapes are pinned by the
  test: refusal leaves title, priority, version and provenance exactly as
  they were.

No existing test was removed or renamed.

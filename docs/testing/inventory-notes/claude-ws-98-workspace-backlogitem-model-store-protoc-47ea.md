---
inventory-delta:
  packages/maistro-core/tests: +4
  packages/maistro-server/tests: +1
---
# claude-ws-98-workspace-backlogitem-model-store-protoc-47ea

Codex review on PR #1596 (#98) found two BacklogItem store/API bugs; the fixes
each got a regression test.

- `packages/maistro-core/tests`: **+4**. One new store-conformance test
  (`test_version_conflict_payload_is_a_detached_copy`) pins that
  `BacklogVersionConflict.current_item` is a detached copy, not the store's
  live object, and one new test
  (`test_set_parent_checks_version_before_the_requested_parent`) pins that
  `set_parent` checks `expected_version` before validating the parent. Both
  run against the `backend` fixture (in-memory and SQLite), so 2 tests × 2
  backends = +4 collected node IDs.
- `packages/maistro-server/tests`: **+1**. One new API test
  (`test_set_parent_reports_stale_version_over_a_bad_parent`) pins that a
  stale `expected_version` combined with a missing `parent_item_id` returns
  409 (version conflict), not 404 (bad parent), on `PUT
  /workspaces/{workspace_id}/backlog/{item_id}/parent`.

No test was removed, renamed, or skipped; nothing else changed shape.

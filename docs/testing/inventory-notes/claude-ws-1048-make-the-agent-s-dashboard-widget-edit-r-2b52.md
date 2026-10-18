---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
---
# claude-ws-1048-make-the-agent-s-dashboard-widget-edit-r-2b52

+7 in `test_dashboard_layout.py`, all additions, nothing removed or moved (#1048):
two tests drive the chat `create_dashboard_widget` tool against a real UI
`PUT /v1/dashboard/layout` landing between its read and its write (once: both
widgets kept, revision +2; repeatedly: the tool reports `created: false` and the
UI's layout survives), and two pin the pure `dashboard_layouts.with_widget`
insertion helper the retry re-applies (including an `activeTab` that names no tab).

Three SQLite-backed cases repeat the race through real State/PersistedStore/JsonStore
and the authenticated API (one successful retry, two conflicts, and a retry whose
backing-store write fails), assert full widget config/tab/layout preservation and
the exact two-attempt bound, then reopen the database and compare the served state.

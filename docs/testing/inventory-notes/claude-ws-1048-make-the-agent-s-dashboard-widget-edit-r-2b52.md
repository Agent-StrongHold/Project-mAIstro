---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# claude-ws-1048-make-the-agent-s-dashboard-widget-edit-r-2b52

+3 in `test_dashboard_layout.py`, all additions, nothing removed or moved (#1048):
two tests drive the chat `create_dashboard_widget` tool against a real UI
`PUT /v1/dashboard/layout` landing between its read and its write (once: both
widgets kept, revision +2; repeatedly: the tool reports `created: false` and the
UI's layout survives), and one pins the pure `dashboard_layouts.with_widget`
insertion helper the retry re-applies.

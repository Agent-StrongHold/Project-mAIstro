---
inventory-delta:
  packages/hive-conductor/backend/tests: -1
---
# cursor-workspace-retirement-dashboard-8aa9-99fa

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

`packages/hive-conductor/backend/tests` −1:
`test_dashboard_layout_durability.py::test_the_dashboard_page_reads_the_save_response`
was removed in commit 7b888170b9 alongside the page it asserted on. The test
read `frontend/src/pages/Dashboard.tsx` as a text fixture, and PR #2460 deletes
that page (`/dashboard` redirects to Workspace Home), so the test raised
`FileNotFoundError` before it could assert anything. The other 32 durability
tests in the file do not read the page source and still pass (32 passed in
check-3). No compensating additions: the removed node was a source-text
characterization of a surface this PR retires, not coverage of surviving
behavior.

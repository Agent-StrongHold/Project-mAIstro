---
inventory-delta:
  packages/hive-conductor/backend/tests: +13
---
# claude-ws-1201-bind-schedule-owner-and-canonical-worksp-f743

`packages/hive-conductor/backend/tests` gains 13 node IDs, all from the new
`test_schedule_workspace_scope.py` (#1201): two non-admin principals in two
canonical Workspaces exercising schedule create binding (1), refused
selections (3 parametrized + 1 foreign Project), list filtering (1), foreign
get/put/delete/run 404s (1), ownerless legacy rows (1), in-scope owner CRUD
(1), refused ownership/scope transfer (1), membership revocation (1), manual run refused in an archived
Workspace (1), and a delete/update racing a concurrent delete (1).
No test was removed or renamed; the existing `/v1/schedules` route tests in
`test_scheduler.py` and the manual-fire e2e only gained a Workspace fixture.

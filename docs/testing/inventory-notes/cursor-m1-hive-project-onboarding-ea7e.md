---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# cursor-m1-hive-project-onboarding-ea7e

CONNECT for `@flat/hive-conductor/routes.projects` via `main.py` route
registration (disposition root).

Adds two tests in `test_projects_onboarding_connect.py`:

- the live app mounts `/v1/projects` and `/v1/projects/{project_id}/scan`;
- `TestTheProjectsScanActuallyScans` proves the scan route schedules
  `repo_scanner.scan_repo` (scan-contract behavioral coverage).

Also updates `EXPECTED_SCAN_ROUTES` / coverage map in `test_scan_contract.py`.
Reachability drops the projects route plus newly rooted
`onboard_db` / `pipeline_orchestrator` / `repo_scanner`; prunes those from
`hive-unwired-services` and removes the `hive-project-onboarding` group.
Agent Conductor HTTP surface unreachable → `none`. Declares `/v1/projects`
with `projects.write` in the route-permissions registry.

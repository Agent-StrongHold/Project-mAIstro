---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
---

# auto-65 repair: Goal inspection under the declared /v1/workspaces prefix

Repair round for the blocking `check-route-permissions.py` failure: the branch
had mounted Goal inspection on a brand-new `/v1/goals` prefix declared as
`exempt_reason: authenticated-only`, and the gate refuses a new exemption
without an already-landed `exempt::/v1/goals` grant (two-merge rule,
`scripts/ratchet_provenance.py`); no such grant exists on the branch or on
`origin/develop`, and it cannot be landed from this branch.

The repair follows the maintainer's own M3 pattern instead of fighting the
provenance rule: Home (#1048) and Attention (#1049) mount their member-facing
reads under the already-declared `/v1/workspaces` prefix — "no new
route-permissions prefix". Goal inspection now does the same:

- `routes/goals.py` serves `GET /v1/workspaces/{workspace_id}/goals[/{goal_id}]`
  with home.py's fail-closed membership door (`visible_view` → 404 for both
  not-a-member and no-such-Workspace, no existence oracle);
- `services/goal_inspection.py` gained an optional `workspace_id` filter on
  `list_goal_views`/`goal_view` (universe scoping underneath unchanged);
- `quality/route-permissions.json` drops the unauthorized `/v1/goals` entry
  and states the prefix's authenticated-only GET reads in the
  `/v1/workspaces` entry's reason;
- the frontend Goals page inspects the active Workspace tab (or the `?ws=`
  a run's Goal back-link now carries from the run's own `workspace_id`),
  and `types.gen.ts` is regenerated from the live OpenAPI document.

Four new backend tests (17 → 21 in the suite, none removed):

- `test_goal_route_prefix_lives_under_the_declared_workspaces_mount` — the
  old top-level `/v1/goals` paths are 404s (the pre-repair tree's own test
  asserted 200 there, so this pin fails against the ungated mount it names);
- `test_goal_routes_refuse_non_members_without_an_existence_oracle` —
  non-member, sub-resource, and never-existed Workspace all answer the same
  404 `workspace not found`;
- `test_goal_routes_stay_in_the_requested_workspace` — a Goal recorded in
  workspace A is absent from a member's workspace B list and 404s by id
  under B (no silent cross-Workspace merge);
- `test_viewer_members_can_read_goal_inspection` — inspection is a member
  read like Home: a viewer member reads 200.

`test_goals_routes_are_scoped_and_read_only` was rewritten for the new paths
(read-only verb refusal kept); the 16 service-level tests are unchanged —
the projection itself did not move.

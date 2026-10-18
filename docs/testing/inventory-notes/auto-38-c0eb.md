---
inventory-delta:
  packages/maistro-server/tests: +2
---
# auto-38-c0eb

+2 tests in `packages/maistro-server/tests/api/test_projects_api.py`, both
closing the L38 verify finding against `POST /{workspace_id}/projects/{project_id}/memberships`
(#38 / #1148 membership lifecycle):

- `test_a_non_owner_delegated_regrant_preserves_owner_issued_authority` — a
  non-owner's delegated POST previously upserted the whole canonical
  membership row, so owner-issued `grants`/`delegable_grants` (reproduced:
  `['publish']`/`['publish']`) and `role` were silently replaced by the
  requester's narrower re-grant (`['read']`/`[]`) without any owner
  revocation. The route now merges for non-admin requesters: existing
  denies/grants/delegable grants/role survive; the request may only add
  actions the requester can themselves delegate (each checked via
  `require_delegable_grant`).
- `test_a_non_owner_delegated_post_cannot_grant_beyond_own_delegation` —
  guards that the merge is not an escalation path: an action absent from the
  stored row still requires the requester to hold it as delegable (403, row
  unchanged).

No test was removed or weakened; the pre-existing
`test_a_non_owner_delegated_regrant_cannot_clear_an_existing_deny` still
passes unchanged (its subject had no stored grants, so merge and replace
agree there).

Environment observation (not a product defect, no code change): re-running
the core projects/workspaces conformance suites twice against the same
PostgreSQL database can fail postgres legs with leftover deterministic
workspace rows, because `workspaces` is not in `_PG_SCRATCH_TABLES`
(`packages/maistro-core/tests/conftest.py`). Two recovery details, confirmed
in the repair round at eec05d0e2:

1. A stale database (alembic 036) cannot simply be migrated forward:
   `042_manual_fire_occurrence_identity` builds a unique index over
   `canonical_runs` provenance, and leftover scratch rows from earlier
   conformance runs (e.g. `sched-1`/`manual:retry-token-1` written by
   `test_a_retried_manual_fire_is_one_occurrence`) violate it, so the upgrade
   aborts with UniqueViolation. Reset the scratch schema
   (`DROP SCHEMA public CASCADE; CREATE SCHEMA public;`) before
   `alembic upgrade head`.
2. After the reset + fresh migration to 042, the combined targeted run is
   green in one shot: 579 passed / 3 skipped (projects + workspaces +
   `runs/test_spine_conformance.py`, PG legs via `MAISTRO_REQUIRE_PG_LEGS=1`),
   and 66 passed (server projects API incl. the two regression tests above +
   core container wiring), with `ruff check`/`format --check`, the
   `packages/*/src` vulture baseline, and both suite inventories green.

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
(`packages/maistro-core/tests/conftest.py`). On a freshly migrated database
(`alembic upgrade head` → 042) the combined targeted run is green in one
shot: 1003 passed, 3 skipped (core projects/workspaces + spine + retention
conformance + server API suite), with `MAISTRO_REQUIRE_PG_LEGS=1`.

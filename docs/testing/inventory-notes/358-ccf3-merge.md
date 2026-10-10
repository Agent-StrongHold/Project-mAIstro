---
inventory-delta:
  tests/: 0
---
# #358: preserve backlog migrations while resolving the develop merge

Resolve the existing migration-test conflicts without dropping ancestor or
transactional-downgrade assertions. The incoming develop revisions 059/060 stay
unchanged; only this lane's unlanded audit-index revision moves to 061 on 060.

Existing offline migration tests now assert the unique 061 head, exact parents,
and filenames of the incoming backlog pair. The live audit-index round trip
starts/ends at 060 and additionally checks that all five backlog tables remain
alongside the audit row and prior execution/learning structures. No test IDs
added or removed. Both sides of the Vulture whitelist conflict are retained.

Before renumbering, the updated chain test fails (cannot locate revision 061;
Alembic also warns that revision 059 is duplicated). Fresh validation results
are recorded in `docs/testing/358-repair-handoff.md`; PostgreSQL-only assertions
are not claimed when the service is unavailable.

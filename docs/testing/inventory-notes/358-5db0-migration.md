---
inventory-delta:
  tests/: 0
---
# #358: salvage develop merge and preserve landed HITL migration

No collected test count change. Resolve the chain-test conflict retaining
landed develop's removal of superseded 043/045 and the lane's parent/file
identity assertions. Require landed HITL revision 061 followed by audit
revision 062 and exactly one head. Update the existing audit DDL contract
for that parent without changing any index definition. The existing live
round-trip now upgrades from/downgrades to 061 and asserts the HITL column and
index survive rolling back the audit indexes.

Regression evidence: before renumbering the audit migration, the chain test
fails with heads `['061', '061']` instead of `['062']` and Alembic reports a
duplicate revision. See job `5db0f385`'s `worker-migration-red.log` and
`docs/testing/358-5db0-repair.md` for validation and merge provenance.

---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
---
# Issue #65 — physical evidence follows the Run's Workspace

Strengthens both existing parametrizations of
`test_cross_workspace_run_link_cannot_relocate_a_goal`; no collected tests are
added or removed. The real HTTP routes, canonical stores and scoped readers
now receive a NodeRun and Attempt under the linked Run. A corrupt projection
must not attach those children in a different Workspace, including when the
caller belongs to both. The legitimate projection and canonical-id detail
must still return the exact physical identities to a member and refuse a
non-member. No network-edge stubs or new authorization mechanism.

Red/green validation is recorded in `docs/testing/auto-65-ci-repair.md`.

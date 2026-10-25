---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# Issue #65 — Goal evidence cannot cross a projection's Workspace boundary

Two parametrized HTTP cases use real canonical Workspace, Goal and Run stores
and the production scoped readers. A retained projection is deliberately linked
to a canonical Run in another Workspace:

- When the caller belongs to both, canonical Goal facts must still not appear
  under the incorrect Workspace; legitimate Goal history remains readable.
- When the canonical Workspace is foreign, both the canonical evidence and its
  Goal remain undisclosed. The legacy projection retains its scoped read.

The member-of-both case must fail before the fix on the wrongly populated Goal
list. The foreign case pins the existing fail-closed boundary. These tests do not
prove canonical discovery, reconciliation inspection, or restart/reconnect.

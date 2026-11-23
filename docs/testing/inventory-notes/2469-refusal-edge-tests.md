---
inventory-delta:
  packages/hive-conductor/backend/tests: +12
---
# Inventory note — #2469 optimizer target-gate refusal edges

Twelve node IDs added in the new
`packages/hive-conductor/backend/tests/test_optimizer_scope_refusal_edges.py`;
nothing removed or renamed. These pin the fail-closed refusal edges of
`services/optimizer_scope` that the single-threaded ASGI authorization suite
cannot reach: blank ids, an unreadable or tenant-less template version,
garbage/blank projection rows, one template registered under two Workspaces,
a row contradicting the precomputed DAG tenancy, `_member_role` blank
identities, decision-filtered paging, an unclaimed DAG's empty list, a
decision on a blank-DAG / deleted-DAG / scope-less proposal row, and
`record_decision`'s defense-in-depth refusal when a caller-authorized tenant
contradicts the stored recording. Every case also asserts zero writes (no
decision fields, no audit rows).

Provenance: the coverage gate's diff-coverage floor (per-file 90% lines /
80% branch arcs) flagged these arcs as partial on the #2469 branch once the
root-suite cascade was repaired; this suite is the evidence that closes them.

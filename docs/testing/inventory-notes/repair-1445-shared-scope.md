---
inventory-delta:
  packages/maistro-core/tests: +3
---
# repair-1445-shared-scope

+3 in packages/maistro-core/tests/persistence/test_backend_conformance.py: one
conformance test parametrized over all three learning backends (memory,
sqlite, postgres — hence three collected node IDs) pinning that a scoped
learning read still sees the org's shared rows. An empty value on a requested
axis (team/user/agent) is the shared-within-org bucket, so narrowing to one
agent must not hide shared learnings from the system prompt; org itself stays
exact. Restores the visibility rule the develop-era `agent_id = ''` widening
carried and the migration suite pins for the pg similarity read, now enforced
uniformly through `learning_scope_predicate` / `matches_learning_scope` and
`similarity_query`.

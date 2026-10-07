---
inventory-delta:
  packages/maistro-core/tests: +3
---
# #1156 User scope on produced learnings

The conformance suite adds the exact-org-mutation node (one per backend
parameter). Existing agent learning and RCA extraction tests were strengthened
to assert that the authenticated `user_id` is persisted in both traced and
untraced paths — assertion changes only, no new node IDs. This protects the
user scope axis that prompt reads already enforce.

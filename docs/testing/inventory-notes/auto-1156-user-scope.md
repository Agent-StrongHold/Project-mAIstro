---
inventory-delta:
  packages/maistro-core/tests: +4
---
# #1156 User scope on produced learnings

Agent learning and RCA extraction tests now assert that the authenticated
`user_id` is persisted in both traced and untraced paths. This protects the
user scope axis that prompt reads already enforce.

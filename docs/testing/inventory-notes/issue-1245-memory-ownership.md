---
inventory-delta:
  packages/hive-conductor/backend/tests: +9
---
# Issue #1245 memory ownership

Adds one route regression test covering authenticated ownership stamping and
cross-user list, read, update, delete, reinforce, decay, contradict, and stats
behavior for memory entries.

Adds eight direct tests for the chat-completion memory tools
(`_tool_memory_add/search/delete/edit`), which are non-HTTP callers of the
owned store: owner stamping on create, scoped search with and without a query,
scoped delete (own, foreign, missing, missing-id), scoped edit 404 (foreign and
missing hit the same answer), argument validation, and value/key/tag update
with the owner boundary preserved.

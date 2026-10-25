---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# cursor-m1-sessions-search-connect-ea7e

CONNECT proof for `maistro.sessions.search` via hive
`conversation_sessions.list_for` (ADR-048 / disposition root).

Adds one test in `test_conversation_sessions.py`:

- `list_for(..., query=...)` filters title + transcript body through
  `search_sessions` and returns only the matching Workspace session.

Reachability baseline drops `maistro.sessions.search`; the
`sessions-search` CONNECT group is pruned. Vulture still banks
`search_sessions` under `core-public-api-surface` — the product
caller is hive `conversation_sessions` (outside `packages/*/src`),
so the packages scan cannot see the use. Convergence: Sessions
unreachable `some` → `none`.

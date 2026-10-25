---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
  packages/maistro-core/tests: +8
---
# cursor-m1-sessions-search-connect-ea7e

CONNECT proof for `maistro.sessions.search` via hive
`conversation_sessions.list_for` (ADR-048 / disposition root).

Hive (+2):

- `list_for(..., query=...)` filters title + transcript through
  `search_sessions`;
- follow-up coverage that search reads the full retained transcript
  (not only the context window).

Core (+8): `SessionStore` / PG / SQLite retained-transcript search
surface added beside the CONNECT wire (`test_store`,
`test_pg_sessions`, `test_sqlite_sessions`).

Reachability baseline drops `maistro.sessions.search`; the
`sessions-search` CONNECT group is pruned. Vulture still banks
`search_sessions` under `core-public-api-surface` — the product
caller is hive `conversation_sessions` (outside `packages/*/src`),
so the packages scan cannot see the use. Convergence: Sessions
unreachable `some` → `none`.

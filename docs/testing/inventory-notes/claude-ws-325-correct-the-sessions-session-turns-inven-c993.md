---
inventory-delta:
  packages/maistro-core/tests: +2
---
# claude-ws-325-correct-the-sessions-session-turns-inven-c993

`packages/maistro-core/tests/persistence/test_session_ttl_purge.py` gains one
test, parametrized over SQLite and PostgreSQL (two node IDs; the PostgreSQL one
skips without `MAISTRO_TEST_PG_DSN`). It ages real `sessions` and
`session_turns` rows past the store TTL and proves the next `append_messages`
deletes them, backing the retention inventory's `ttl_purge` entries for both
tables (#325). Nothing was removed or moved.

---
inventory-delta:
  packages/maistro-core/tests: +20
---
# claude-issue-328-serialize-prompt-versions-c391

+20 net, and the number hides a deliberate replacement rather than a plain
addition — which is exactly the case these notes exist for.

**+26**, `test_prompt_store_conformance.py`: SPEC-083026-427c's AC-1..AC-8
against stores that enforce their keys. Most cases are parametrized over both
backends, so the count is higher than the eight criteria; only AC-6 (per-name
lock granularity, which SQLite does not have) and AC-8 (the two backends agree)
are PostgreSQL-requiring.

**-13 / +7**, `test_pg_prompts.py`: the thirteen there drove `PgPromptManager`
through a fake connection and asserted the sequence of SQL strings it emitted.
Six broke on this change *because the SQL changed*, which is all they were ever
able to notice — and while they were green, two unconditional failures sat in
the code they covered (`ON CONFLICT` naming a partial index it cannot infer,
and the primary-key collision behind it). A fake enforces no keys, so no test
built on one is evidence about a key. What remains is the seven cases that are
genuinely about pure functions: `_parse_config`, and `_lock_key`'s range,
stability and collision rate.

`test_sqlite_prompts.py` is unchanged and all ten still pass, which is the
check that the behaviour callers depend on survived the schema change rather
than being redefined to whatever the new code does.

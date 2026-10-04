---
inventory-delta:
  packages/maistro-core/tests: +9
---
# #121 CI repair — the durable anti-pattern path was untested at every tier

The merge-queue coverage gate failed this branch on diff coverage: the #121
durable write path (`list_ineffective`, `mark_anti_pattern`) had in-memory and
promoter-level tests but no test at the durable tiers the capture sweep
actually runs against in production, and the twins' decode helpers had
untolerated shapes. New test nodes (+9):

- `packages/maistro-core/tests/memory/learnings/test_durable_hybrid.py` (+2) —
  the `DurableHybridLearningStore` delegation of `list_ineffective` (forwards
  the threshold, returns the twin's rows) and `mark_anti_pattern` (forwards id,
  floor and the binding `org_id`). Same spelled-out-forwarding contract as the
  eight delegations already pinned in that file: a hand-written delegation is
  exactly where a dropped keyword hides.
- `packages/maistro-core/tests/persistence/test_pg_learnings.py` (+5) — the
  PostgreSQL store's `list_ineffective` (SQL predicate pinned: recorded-outcome
  floor, failures strictly dominating) and `mark_anti_pattern` (GREATEST
  confidence lift, org in the WHERE, miss reported as `False`); the
  `_load_applicability` decode shapes a pool can hand back (dict via a
  custom-JSON-codec pool, text via asyncpg's default, malformed text, non-dict
  JSON, non-string types); and one `@requires_postgres` leg binding the read
  and the write against the migrated chain, because a typo in either statement
  would fail every production capture sweep while the fake-verified strings
  stayed green.
- `packages/maistro-core/tests/persistence/test_sqlite_learning_lifecycle.py`
  (+2) — a row whose instant columns hold unparseable text reads back with the
  defaults (`validated_at`/`last_confirmed_at` empty, `created_at` at read
  time) instead of crashing every read that touches it; and the SQLite twins'
  `_load_applicability` / `_load_moment` / `_utc_text` decoder contracts,
  mirroring the pg decoders the same way the stores mirror each other.

Discriminating against the pre-change tree: the durable-hybrid and pg
fake-connection tests fail with `AttributeError`/`TypeError` (the delegations
and methods under test did not exist), and the sqlite decoder tests fail on
the missing tolerance branches. The real-PostgreSQL leg skips without a server
by design, as every other leg in that file does.

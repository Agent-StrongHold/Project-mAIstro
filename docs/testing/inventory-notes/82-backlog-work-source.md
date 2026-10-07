---
inventory-delta:
  packages/maistro-core/tests: +54
---
# 82-backlog-work-source

Epic M3-C (#82) starts its DB-backed Workspace BacklogItem service (#98, with
the model-level parts of #100 claims/leases and #101 history) as a new
`maistro.backlog` package in maistro-core. The +54 node IDs are two new files
in `packages/maistro-core/tests/backlog/`, and the split matters:

- **9 model nodes** (`test_backlog_model.py`): pure pydantic invariants —
  closure evidence required exactly at terminal status, non-blank identity
  fields, naive datetimes normalized to UTC, self-parenting refused,
  optimistic-concurrency version floor.
- **45 conformance nodes** (`test_backlog_store_conformance.py`): one body per
  behavior, parametrized over the `memory`/`sqlite`/`postgres` backends so all
  three store implementations are held to the same contract (the
  `PgStrikeTracker` lesson, #134). The durable-SQLite leg reads through a
  second connection the writer never used, so durability is observed, not
  asserted. The PostgreSQL leg skips without `MAISTRO_TEST_PG_DSN` (16 of the
  45 here) and runs in CI against a migrated Postgres, where alembic `048`
  owns the schema; setting `MAISTRO_REQUIRE_PG_LEGS=1` turns a silent skip
  into an error.

The conformance bodies cover what the epic's first slice promises: workspace
isolation, version-conflict refusal (never merge), UNSET-vs-None clearing
semantics, terminal-status unreachability through ordinary edits, closure
evidence requirements, close/reopen event cycles, decomposition guards,
list filters, and the atomic claim/lease lifecycle including concurrent-claim
admission of exactly one winner.

Until #102 performs the authority cutover, root `BACKLOG.md` stays canonical;
these tests pin the structured service that cutover will migrate into, not a
replacement authority.

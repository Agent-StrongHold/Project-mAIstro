---
inventory-delta:
  packages/maistro-core/tests: -1
---
# auto-448-develop-sync-252950bdb

Lane L448 (issue #448, M2 initiative) — develop sync at `252950bdb`
("WIP: [EPIC M1-B] One execution universe"). The merge conflict was real and
semantic, not textual: both sides changed `PgAuditLog.ensure_schema`.

The branch's CI repair (`c2e7c2cba`) had reverted runtime DDL to a
probe-and-return no-op because `34379a166`'s bootstrap declared `org_id`
without the server default migration 036 gives it. Develop `252950bdb` fixed
that objection in the bootstrap's `CREATE TABLE` (it now declares
`org_id TEXT NOT NULL DEFAULT ''`) and re-introduced the table creation the
durable-events CI leg needs: its fresh PostgreSQL server runs no migration
chain, so a no-op `ensure_schema` leaves `audit_log` absent and the container
wiring still dies.

Resolution: keep develop's bootstrap (merge commit `fbb703825`). Its two
witnesses replace the branch's two now-contradictory tests:

- removed `test_ensure_schema_never_fabricates_the_migrated_audit_table`
  (asserted `to_regclass('audit_log') is None` after `ensure_schema`),
- removed `test_ensure_schema_on_unmigrated_database_is_a_no_op`
  (asserted a `to_regclass` probe emitted no DDL),
- added `test_ensure_schema_takes_the_bootstrap_lock`
  (asserts `pg_advisory_xact_lock` precedes `CREATE TABLE IF NOT EXISTS`).

Net: two tests removed, one added. Nothing was silently dropped: the removed
witnesses asserted the opposite contract from the adopted implementation.

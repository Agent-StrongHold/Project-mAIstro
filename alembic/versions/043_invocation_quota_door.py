"""Quota admission tables and canonical Invocation usage evidence.

Revision ID: 043_invocation_quota_door
Revises: 056
Create Date: 2026-09-27

The effect door's budget reservations (#1196) and the at-most-once provider
usage evidence (#718) attach to the canonical Invocation. They follow the
current chain tip so they do not reuse revision ids 033/035/036, which
develop already assigned. Re-parented onto each new develop head as this
branch has stayed open -- 046, then 047, 048, 050, 051, 052, 053, 054,
055, now 056, #863's planner-stability revision: a migration must append
after the deployed head, never fork beside it, or `alembic upgrade head`
refuses with multiple heads.

Every table here is created only when missing, and every column added
only when absent, because the store bootstraps these same tables itself:
`PgInvocationQuota.ensure_schema` runs its own `CREATE TABLE IF NOT
EXISTS` block, and the SQLite store bootstraps `capability_approvals`.
A live database that ran the store before this migration must therefore
be adopted, not assumed empty -- and the chain's own stamp-back repair
path re-walks these revisions over a schema that already exists. Plain
`CREATE TABLE` fails that re-application with `DuplicateTable` even
though the schema it would build is the schema already there.

The unique constraints are added through a `pg_constraint` guard rather
than a bare `ADD CONSTRAINT`, which PostgreSQL offers no `IF NOT EXISTS`
for. A NOT NULL column with no default still cannot be added to a
populated adopted table: such a database fails the upgrade loudly rather
than being given an invented value, exactly as 044 states.

Revision identifiers stay within Alembic's 32-character version_num column.
"""

from __future__ import annotations

from alembic import op

revision = "043_invocation_quota_door"
down_revision = "056"
branch_labels = None
depends_on = None


#: Every column this migration adds, as whole literal statements. Written out
#: rather than built from an f-string over a (table, column) table: the run-id
#: retention scanner reads migration DDL statically, and an interpolated table
#: name leaves it unable to verify that the statement introduces no `run_id`
#: column it would then have to see in the purge inventory. `IF NOT EXISTS`
#: because the store bootstraps these tables itself, so a live database must be
#: adopted rather than assumed empty.
_ADDED_COLUMNS = (
    "ALTER TABLE invocation_quota_reservations ADD COLUMN IF NOT EXISTS identity JSONB NOT NULL",
    "ALTER TABLE invocation_quota_reservations ADD COLUMN IF NOT EXISTS state TEXT NOT NULL",
    "ALTER TABLE invocation_quota_reservations ADD COLUMN IF NOT EXISTS reason TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE invocation_quota_reservations ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT -1",
    "ALTER TABLE invocation_quota_allocations ADD COLUMN IF NOT EXISTS maximum BIGINT NOT NULL",
    "ALTER TABLE invocation_quota_allocations ADD COLUMN IF NOT EXISTS held BIGINT NOT NULL",
    "ALTER TABLE invocation_quota_allocations ADD COLUMN IF NOT EXISTS spent BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE invocation_quota_allocations ADD COLUMN IF NOT EXISTS measured BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE invocation_quota_evidence ADD COLUMN IF NOT EXISTS evidence_id TEXT NOT NULL",
    "ALTER TABLE invocation_quota_evidence ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL",
    "ALTER TABLE capability_approvals ADD COLUMN IF NOT EXISTS run_id TEXT NOT NULL",
    "ALTER TABLE capability_approvals ADD COLUMN IF NOT EXISTS node_run_id TEXT NOT NULL",
    "ALTER TABLE capability_approvals ADD COLUMN IF NOT EXISTS binding_id TEXT NOT NULL",
    "ALTER TABLE capability_approvals ADD COLUMN IF NOT EXISTS effect_key TEXT NOT NULL",
    "ALTER TABLE capability_approvals ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL",
)


#: PostgreSQL has no `ADD CONSTRAINT IF NOT EXISTS`, and an adopted table the
#: store's own bootstrap created already carries these. Written out as whole
#: literal statements rather than built from an f-string: the run-id retention
#: scanner reads migration DDL statically and cannot verify an interpolated
#: table name does not introduce a `run_id` column.
_UNIQUE_CONSTRAINTS = (
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'uq_invocation_quota_evidence_id'
              AND conrelid = 'invocation_quota_evidence'::regclass
        ) THEN
            ALTER TABLE invocation_quota_evidence
                ADD CONSTRAINT uq_invocation_quota_evidence_id
                UNIQUE (invocation_id, evidence_id);
        END IF;
    END
    $$
    """,
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'uq_capability_approval_effect'
              AND conrelid = 'capability_approvals'::regclass
        ) THEN
            ALTER TABLE capability_approvals
                ADD CONSTRAINT uq_capability_approval_effect
                UNIQUE (run_id, node_run_id, binding_id, effect_key);
        END IF;
    END
    $$
    """,
)


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS invocation_quota_budgets ("
        "budget_id TEXT PRIMARY KEY, definition JSONB NOT NULL)"
    )

    op.execute(
        "CREATE TABLE IF NOT EXISTS invocation_quota_reservations (invocation_id TEXT PRIMARY KEY)"
    )

    op.execute(
        "CREATE TABLE IF NOT EXISTS invocation_quota_allocations ("
        "invocation_id TEXT NOT NULL"
        " REFERENCES invocation_quota_reservations(invocation_id),"
        "budget_id TEXT NOT NULL REFERENCES invocation_quota_budgets(budget_id),"
        "PRIMARY KEY (invocation_id, budget_id))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_invocation_quota_alloc_budget"
        " ON invocation_quota_allocations (budget_id)"
    )

    op.execute(
        "CREATE TABLE IF NOT EXISTS invocation_quota_evidence ("
        "invocation_id TEXT NOT NULL"
        " REFERENCES invocation_quota_reservations(invocation_id),"
        "revision INTEGER NOT NULL,"
        "PRIMARY KEY (invocation_id, revision))"
    )

    op.execute("CREATE TABLE IF NOT EXISTS capability_approvals (request_id TEXT PRIMARY KEY)")

    # Every table exists by now, so the column adds run in one pass; each is
    # `IF NOT EXISTS` and order-independent within its own table.
    for statement in _ADDED_COLUMNS:
        op.execute(statement)
    for statement in _UNIQUE_CONSTRAINTS:
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("capability_approvals")
    op.drop_table("invocation_quota_evidence")
    op.drop_index("idx_invocation_quota_alloc_budget", table_name="invocation_quota_allocations")
    op.drop_table("invocation_quota_allocations")
    op.drop_table("invocation_quota_reservations")
    op.drop_table("invocation_quota_budgets")

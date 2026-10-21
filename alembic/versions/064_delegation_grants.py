"""Persist host-authorized delegation grants in the canonical database.

`delegation_grants` (#845) is the durable backing for the host delegation
authority: the authority a Sentinel consults before any agent-to-agent
handoff is honored. The runtime store's `ensure_schema` bootstraps the table
on standalone pools and at container startup, but per the chain's ownership
rule (stated on `pg_audit` and exercised by the coverage PostgreSQL leg)
the migration chain owns `CREATE TABLE` for every canonical durable table:
the pg_pool test fixture truncates a *migrated* database before each test,
so a table that only runtime DDL would create breaks every PostgreSQL-leg
suite at setup with `UndefinedTableError` — the same shape #231 documented
for scheduling stores.

The DDL is guarded (`CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT
EXISTS`) and byte-identical to `POSTGRES_DELEGATION_SCHEMA` in
`delegation_durable.py`, so a database that already carries the runtime
bootstrap is adopted untouched and a fresh one is built to exactly the
definition the store reads.
"""

from __future__ import annotations

from alembic import op

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS delegation_grants (
            id SERIAL PRIMARY KEY,
            grant_id TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            delegating_agent_id TEXT NOT NULL,
            target_agent_id TEXT NOT NULL,
            goal_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            invocation_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            action TEXT NOT NULL,
            actions TEXT NOT NULL,
            artifact TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            granted_by TEXT NOT NULL,
            provenance TEXT NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_delegation_grants_lookup "
        "ON delegation_grants (principal_id, expires_at)"
    )


def downgrade() -> None:
    op.drop_index("idx_delegation_grants_lookup", table_name="delegation_grants")
    op.drop_table("delegation_grants")

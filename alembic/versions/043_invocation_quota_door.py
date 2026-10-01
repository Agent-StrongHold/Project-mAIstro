"""Quota admission tables and canonical Invocation usage evidence.

Revision ID: 043_invocation_quota_door
Revises: 047
Create Date: 2026-09-27

The effect door's budget reservations (#1196) and the at-most-once provider
usage evidence (#718) attach to the canonical Invocation. They follow the
current chain tip so they do not reuse revision ids 033/035/036, which
develop already assigned. Re-parented onto each new develop head as this
branch has stayed open -- 046, now 047: a migration must append after the
deployed head, never fork beside it, or `alembic upgrade head` refuses with
multiple heads.

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
down_revision = "047"
branch_labels = None
depends_on = None


_EVIDENCE_COLUMNS = (
    ("provider", "TEXT NOT NULL"),
    ("cycle_key", "TEXT NOT NULL"),
    ("input_tokens", "BIGINT NOT NULL DEFAULT 0"),
    ("output_tokens", "BIGINT NOT NULL DEFAULT 0"),
    ("usage_reported", "BOOLEAN NOT NULL"),
)
_RESERVATION_COLUMNS = (
    ("identity", "JSONB NOT NULL"),
    ("state", "TEXT NOT NULL"),
    ("reason", "TEXT NOT NULL DEFAULT ''"),
    ("revision", "INTEGER NOT NULL DEFAULT -1"),
)
_ALLOCATION_COLUMNS = (
    ("maximum", "BIGINT NOT NULL"),
    ("held", "BIGINT NOT NULL"),
    ("spent", "BIGINT NOT NULL DEFAULT 0"),
    ("measured", "BOOLEAN NOT NULL DEFAULT FALSE"),
)
_APPROVAL_COLUMNS = (
    ("run_id", "TEXT NOT NULL"),
    ("node_run_id", "TEXT NOT NULL"),
    ("binding_id", "TEXT NOT NULL"),
    ("effect_key", "TEXT NOT NULL"),
    ("payload", "JSONB NOT NULL"),
)


def _add_columns(table: str, columns: tuple[tuple[str, str], ...]) -> None:
    for name, spec in columns:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {spec}")


def _add_unique(table: str, name: str, columns: str) -> None:
    """Add a named unique constraint only when it is not already there.

    PostgreSQL has no `ADD CONSTRAINT IF NOT EXISTS`, and an adopted table
    created by the store's own bootstrap already carries this constraint.
    """

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = '{name}'
                  AND conrelid = '{table}'::regclass
            ) THEN
                ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE ({columns});
            END IF;
        END
        $$
        """
    )


def upgrade() -> None:
    op.execute(
        "ALTER TABLE quota_usage ADD COLUMN IF NOT EXISTS "
        "unreported_count BIGINT NOT NULL DEFAULT 0"
    )

    op.execute(
        "CREATE TABLE IF NOT EXISTS quota_invocation_evidence (invocation_id TEXT PRIMARY KEY)"
    )
    _add_columns("quota_invocation_evidence", _EVIDENCE_COLUMNS)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_quota_invocation_evidence_provider_cycle"
        " ON quota_invocation_evidence (provider, cycle_key)"
    )

    op.execute(
        "CREATE TABLE IF NOT EXISTS invocation_quota_budgets ("
        "budget_id TEXT PRIMARY KEY, definition JSONB NOT NULL)"
    )

    op.execute(
        "CREATE TABLE IF NOT EXISTS invocation_quota_reservations (invocation_id TEXT PRIMARY KEY)"
    )
    _add_columns("invocation_quota_reservations", _RESERVATION_COLUMNS)

    op.execute(
        "CREATE TABLE IF NOT EXISTS invocation_quota_allocations ("
        "invocation_id TEXT NOT NULL"
        " REFERENCES invocation_quota_reservations(invocation_id),"
        "budget_id TEXT NOT NULL REFERENCES invocation_quota_budgets(budget_id),"
        "PRIMARY KEY (invocation_id, budget_id))"
    )
    _add_columns("invocation_quota_allocations", _ALLOCATION_COLUMNS)
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
    _add_columns(
        "invocation_quota_evidence",
        (("evidence_id", "TEXT NOT NULL"), ("payload", "JSONB NOT NULL")),
    )
    _add_unique(
        "invocation_quota_evidence",
        "uq_invocation_quota_evidence_id",
        "invocation_id, evidence_id",
    )

    op.execute("CREATE TABLE IF NOT EXISTS capability_approvals (request_id TEXT PRIMARY KEY)")
    _add_columns("capability_approvals", _APPROVAL_COLUMNS)
    _add_unique(
        "capability_approvals",
        "uq_capability_approval_effect",
        "run_id, node_run_id, binding_id, effect_key",
    )


def downgrade() -> None:
    op.drop_table("capability_approvals")
    op.drop_table("invocation_quota_evidence")
    op.drop_index("idx_invocation_quota_alloc_budget", table_name="invocation_quota_allocations")
    op.drop_table("invocation_quota_allocations")
    op.drop_table("invocation_quota_reservations")
    op.drop_table("invocation_quota_budgets")
    op.drop_index(
        "ix_quota_invocation_evidence_provider_cycle",
        table_name="quota_invocation_evidence",
    )
    op.drop_table("quota_invocation_evidence")
    op.drop_column("quota_usage", "unreported_count")

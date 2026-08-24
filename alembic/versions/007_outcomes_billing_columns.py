"""Columns `PgOutcomeStore.record` writes that the outcomes table lacks (#122).

The `outcomes` table came from migration 001 and has not moved since. The store
that writes it has: `record()` inserts `charged_microchips` and
`pricing_version`, and PostgreSQL answers `UndefinedColumnError` for both — so
recording an outcome, the store's primary operation, could not succeed.

The SQLite twin (`persistence/sqlite_outcomes.py`) has carried both columns for
some time, which is what makes this drift rather than an unimplemented feature:
the two implementations that claim the same protocol disagreed about the table
they read, and only the untested one was wrong.

Types follow the SQLite schema and the `Outcome` dataclass: both fields are
non-null with zero/empty defaults, so existing rows need no backfill.

Revision ID: 007
Revises: 006
Create Date: 2026-08-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outcomes",
        sa.Column("charged_microchips", sa.BigInteger, nullable=False, server_default="0"),
    )
    op.add_column(
        "outcomes",
        sa.Column("pricing_version", sa.Text, nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("outcomes", "pricing_version")
    op.drop_column("outcomes", "charged_microchips")

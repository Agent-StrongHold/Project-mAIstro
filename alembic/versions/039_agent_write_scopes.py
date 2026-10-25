"""Persist Agent write-scope declarations at the registry boundary (#847)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("write_scopes", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "write_scopes")

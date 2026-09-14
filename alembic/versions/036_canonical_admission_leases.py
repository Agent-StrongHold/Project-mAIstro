"""Durable canonical Run and Attempt admission leases (#1182)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_admission_leases",
        sa.Column("lease_id", sa.Text, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("resource_id", sa.Text, nullable=False),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("principal_id", sa.Text, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kind", "resource_id", name="uq_canonical_admission_resource"),
    )
    op.create_index(
        "ix_canonical_admission_expiry",
        "canonical_admission_leases",
        ["expires_at"],
    )
    op.create_index(
        "ix_canonical_admission_scope",
        "canonical_admission_leases",
        ["kind", "workspace_id", "principal_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_canonical_admission_scope", table_name="canonical_admission_leases")
    op.drop_index("ix_canonical_admission_expiry", table_name="canonical_admission_leases")
    op.drop_table("canonical_admission_leases")

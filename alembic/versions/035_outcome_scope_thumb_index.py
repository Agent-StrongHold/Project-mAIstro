"""Index project-scoped Outcome feedback reads (#844)."""

from __future__ import annotations

from alembic import op

revision = "035_outcome_scope_thumb_index"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_outcomes_scope_thumb_time",
        "outcomes",
        ["org_id", "project_id", "thumb", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outcomes_scope_thumb_time", table_name="outcomes")

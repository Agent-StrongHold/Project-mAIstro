"""Enforce one canonical Run per logical effect (#1194).

The effect key is the stable identity used by node replay and A2A receiver
admission. A unique partial index makes the claim atomic across workers; the
payload remains the source of the effect metadata.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_canonical_runs_effect",
        "canonical_runs",
        [sa.text("((payload->'provenance'->>'effect_key'))")],
        unique=True,
        postgresql_where=sa.text("payload->'provenance'->>'effect_key' IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_canonical_runs_effect", table_name="canonical_runs")

"""Make canonical delegation admission identities unique (#1090).

Revision ID: 033
Revises: 032
"""

from __future__ import annotations

from alembic import op

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None

_INDEX = "ix_canonical_runs_delegation_key"
_KEY = "(payload -> 'provenance' ->> 'delegation_key')"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX}
            ON canonical_runs ({_KEY})
            WHERE {_KEY} IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")

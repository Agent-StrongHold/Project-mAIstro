"""Durable Binding revocation tombstones (#1133, #846).

A tombstone table rather than a column on ``capability_bindings``. Revoking
a Binding *deletes* its row -- that deletion is what makes the identity
unrecoverable -- so a ``revoked_at`` column would be removed along with the
thing it forbids, and an actor that still remembered the id could register
it again. #846 exists because a withdrawn capability that can be re-granted
is not withdrawn.

Until now only ``InMemoryBindingStore`` could revoke, so revocation did not
survive a restart and hive-conductor disabled self_repair and the harness
route whenever the store was durable rather than offer a revoke surface that
could not revoke.

Revision ID: 047
Revises: 046
Create Date: 2026-09-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capability_binding_revocations",
        sa.Column("binding_id", sa.Text(), primary_key=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    # Dropping this loses the record of which identities are forbidden, which
    # is a downgrade that re-grants capabilities. Kept for chain symmetry; an
    # operator running it is choosing that.
    op.drop_table("capability_binding_revocations")

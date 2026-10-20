"""Preserve Sentinel decision signatures and verification material (#69)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "036_sentinel_decision_integrity"
down_revision = "035_outcome_scope_thumb_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Only public verification material is persisted. The Ed25519 private key
    # remains in the signing service/key vault and is never an audit column.
    op.add_column("audit_log", sa.Column("action", sa.Text, nullable=False, server_default=""))
    op.add_column("audit_log", sa.Column("org_id", sa.Text, nullable=False, server_default=""))
    op.add_column(
        "audit_log", sa.Column("principal_id", sa.Text, nullable=False, server_default="")
    )
    op.add_column(
        "audit_log", sa.Column("policy_snapshot", sa.Text, nullable=False, server_default="")
    )
    op.add_column("audit_log", sa.Column("payload", sa.Text, nullable=False, server_default=""))
    op.add_column("audit_log", sa.Column("inputs_hash", sa.Text, nullable=False, server_default=""))
    op.add_column("audit_log", sa.Column("signature", sa.Text, nullable=True))
    op.add_column("audit_log", sa.Column("signature_key_id", sa.Text, nullable=True))
    op.add_column("audit_log", sa.Column("signature_algorithm", sa.Text, nullable=True))
    op.add_column("audit_log", sa.Column("signature_public_key", sa.Text, nullable=True))
    op.add_column(
        "audit_log", sa.Column("violations", sa.Text, nullable=False, server_default="[]")
    )


def downgrade() -> None:
    for name in (
        "signature_public_key",
        "signature_algorithm",
        "signature_key_id",
        "signature",
        "payload",
        "inputs_hash",
        "policy_snapshot",
        "principal_id",
        "org_id",
        "action",
        "violations",
    ):
        op.drop_column("audit_log", name)

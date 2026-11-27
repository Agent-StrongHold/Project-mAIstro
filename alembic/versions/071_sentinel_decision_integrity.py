"""Preserve Sentinel decision signatures and verification material (#69).

Stamp-back and re-upgrade is a live repair path (the adoption contract
063/064/069/070 state and tests/migrations/test_migration_chain.py drives at
the chain level): re-applying this revision over the schema it already built
is adoption, not an error, so every ADD COLUMN is guarded by a catalog probe
instead of relying on the revision stamp alone.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "071"
down_revision = "070"
branch_labels = None
depends_on = None


def _existing_audit_columns() -> set[str]:
    """The audit_log columns the live catalog already carries.

    Probed rather than trusted to the revision stamp: the stamp-back repair
    path re-walks this revision over a schema that already has the columns,
    and a bare ADD COLUMN dies there with DuplicateColumn even though the
    schema it would build is the schema that exists (068 carries the same
    guarded probe for a column an installed base may predate).
    """

    rows = op.get_bind().execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = current_schema() AND table_name = 'audit_log'"
        )
    )
    return {str(row[0]) for row in rows}


def upgrade() -> None:
    # Only public verification material is persisted. The Ed25519 private key
    # remains in the signing service/key vault and is never an audit column.
    # `signature` already holds the store-level audit proof. Never overwrite
    # it; the decision proof is stored separately, in `decision_signature`.
    present = _existing_audit_columns()
    for column in (
        sa.Column("action", sa.Text, nullable=False, server_default=""),
        sa.Column("principal_id", sa.Text, nullable=False, server_default=""),
        sa.Column("policy_snapshot", sa.Text, nullable=False, server_default=""),
        sa.Column("payload", sa.Text, nullable=False, server_default=""),
        sa.Column("inputs_hash", sa.Text, nullable=False, server_default=""),
        sa.Column("decision_signature", sa.Text, nullable=True),
        sa.Column("signature_key_id", sa.Text, nullable=True),
        sa.Column("signature_algorithm", sa.Text, nullable=True),
        sa.Column("signature_public_key", sa.Text, nullable=True),
        sa.Column("violations", sa.Text, nullable=False, server_default="[]"),
    ):
        if column.name not in present:
            op.add_column("audit_log", column)


def downgrade() -> None:
    for name in (
        "signature_public_key",
        "signature_algorithm",
        "signature_key_id",
        "decision_signature",
        "payload",
        "inputs_hash",
        "policy_snapshot",
        "principal_id",
        "action",
        "violations",
    ):
        op.drop_column("audit_log", name)

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

from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS, like 046: stamp-back and re-upgrade is a live repair path,
    # and the chain's contract is that re-applying a revision over the schema
    # it already built is adoption, not an error (tests/migrations,
    # test_reapplying_the_chain_over_an_already_migrated_schema_is_adopted).
    # A bare create_table failed that with DuplicateTable.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS capability_binding_revocations (
            binding_id TEXT PRIMARY KEY,
            revoked_at TIMESTAMPTZ NOT NULL
        )
        """
    )


def downgrade() -> None:
    # Dropping this loses the record of which identities are forbidden, which
    # is a downgrade that re-grants capabilities. Kept for chain symmetry; an
    # operator running it is choosing that.
    op.execute("DROP TABLE IF EXISTS capability_binding_revocations")

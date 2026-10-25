"""Ordered exact-scope audit cursor indexes (#358).

Revision ID: 062
Revises: 061

Re-parented onto develop's HITL pause-kind tip to keep one linear chain:
develop owns `061`, so only this branch's unlanded audit indexes move past
it as `062`. Existing deployed revisions are unchanged.

Each equality-filter shape needs an ordered seek, including timestamp ties.
Build at migration time, not on the first audit request. Eight indexes trade
write amplification for bounded filtered reads. No second audit store.
"""

from itertools import combinations

from alembic import op

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None

# Freeze the migration definition rather than import mutable runtime metadata.
_FIELDS = ("user_id", "boundary", "(verdict = 'denied')")
_INDEXES = [fields for size in range(4) for fields in combinations(_FIELDS, size)]


def upgrade() -> None:
    for index, fields in enumerate(_INDEXES):
        columns = ", ".join(("org_id", *fields, "timestamp DESC", "id DESC"))
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_audit_page_{index} ON audit_log ({columns})")


def downgrade() -> None:
    for index in reversed(range(len(_INDEXES))):
        op.execute(f"DROP INDEX IF EXISTS ix_audit_page_{index}")

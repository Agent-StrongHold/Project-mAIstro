"""Ordered exact-scope audit cursor indexes (#358).

Revision ID: 059
Revises: 058

Re-parented onto develop's Gauntlet-validation-provenance tip to keep one
linear chain: develop claimed `058` while this branch's audit revision was
open, so the audit indexes move past it as `059`. The audit-index revision
has not landed; existing revisions are unchanged.

Each equality-filter shape needs an ordered seek, including timestamp ties.
Build at migration time, not on the first audit request. Eight indexes trade
write amplification for bounded filtered reads. No second audit store.
"""

from itertools import combinations

from alembic import op

revision = "059"
down_revision = "058"
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

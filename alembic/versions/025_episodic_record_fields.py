"""The four `EpisodicMemory` fields `episodic_memories` never had.

Revision ID: 025
Revises: 024
Create Date: 2026-08-30

Migration 001 created `episodic_memories` and nothing has written to it since:
the only `EpisodicStore` was `InMemoryEpisodicStore`, and the container wired it
whatever the database URL said. So the table drifted from the record without
anyone noticing, and four fields the dataclass has always carried have no column
at all -- `project_id`, which `list_by_scope` filters on, `decay_rate`, which
`tick_decay` scales by, and `shared` and `flagged_for_review`, which are
ADR-080 parts C and B.

ADR-083026-a322 makes the store durable, and a store cannot write a field the
table cannot hold. All four land with defaults rather than a backfill because
there is nothing to backfill: the table has never held a row.

The revision id is the bare number, like 023 and 024 before it. The docker
smoke in `ci.yml` asserts the head `version_num` matches `^[0-9a-f]+$`, so a
descriptive suffix -- `025_episodic_record_fields`, the shape 010 and 011
use -- fails that grep the moment it becomes head.

The index is for the read `list_by_scope` performs -- scope, then a weight
floor, ordered by weight. `ix_episodic_org_scope` from 001 covers the first two
columns and stops there, so the weight bound and the ordering were both work
the server had to do after the scan.
"""

from __future__ import annotations

from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None

#: `maistro.types.memory.DEFAULT_DECAY_RATE` at this revision. A literal, not an
#: import: a migration describes the schema at its own point in history, and a
#: constant a later release changes would make this file mean something
#: different depending on when it runs -- the rule migration 011 states for its
#: embedding dimension.
_DEFAULT_DECAY_RATE = "0.01"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE episodic_memories ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE episodic_memories ADD COLUMN IF NOT EXISTS decay_rate DOUBLE PRECISION "
        f"NOT NULL DEFAULT {_DEFAULT_DECAY_RATE}"
    )
    op.execute(
        "ALTER TABLE episodic_memories "
        "ADD COLUMN IF NOT EXISTS shared BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE episodic_memories "
        "ADD COLUMN IF NOT EXISTS flagged_for_review BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_episodic_scope_weight "
        "ON episodic_memories (org_id, scope, weight DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_episodic_scope_weight")
    for column in ("flagged_for_review", "shared", "decay_rate", "project_id"):
        op.execute(f"ALTER TABLE episodic_memories DROP COLUMN IF EXISTS {column}")

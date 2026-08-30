"""How many of a turn's provider calls reported usage.

Revision ID: 025
Revises: 024
Create Date: 2026-08-30

`outcomes.input_tokens` and `output_tokens` are a sum over the provider calls
of one turn, and the strategies producing them spelled
`usage.get("prompt_tokens", 0)` — so a provider that reported no `usage` object
and one that reported zero both landed as `0`. The column beside the value says
which happened, the shape ADR-083026-a91e chose for node metrics
(`tokens_measured` beside the value, rather than a nullable value).

Nullable with no default and no backfill. Every existing row was written by a
producer that did not count, and `0` there would claim it counted and found
none — the exact conflation this column exists to end. `NULL` says "not
recorded", which is what is true of them.

The revision id is the bare number, like 023 and 024 before it: the docker
smoke in `ci.yml` asserts the head `version_num` matches `^[0-9a-f]+$`, so a
descriptive suffix fails that grep the moment it becomes head.
"""

from __future__ import annotations

from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE outcomes ADD COLUMN IF NOT EXISTS usage_reported_calls INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE outcomes DROP COLUMN IF EXISTS usage_reported_calls")

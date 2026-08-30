"""A prompt label becomes a row of its own (#328, ADR-083026-427c).

`prompts` held a version and the label pointing at it in one row, with `label`
a nullable column carrying a partial unique index. Two facts of different arity
shared a row: a version has one identity, a label has one target, and a version
may be the target of several labels.

That last case is the first write of every prompt -- version 1 is both `latest`
and `production` -- and with one label per row the manager wrote a *second row
at the same version*, which `prompts_pkey` forbids. On PostgreSQL that path
raised unconditionally; SQLite's twin, which declares no key over
(name, version), stored the duplicate instead.

Splitting the two gives each its own key, and neither key is partial, so both
are usable as `ON CONFLICT` arbiters -- which the old partial index was not.

Revision ID: 022
Revises: 021
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_labels",
        sa.Column("name", sa.Text, primary_key=True),
        sa.Column("label", sa.Text, primary_key=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.ForeignKeyConstraint(
            ["name", "version"],
            ["prompts.name", "prompts.version"],
            name="fk_prompt_labels_version",
            ondelete="CASCADE",
        ),
    )

    # Carry the existing pointers across before the column they live in goes.
    # DISTINCT ON keeps the highest version per (name, label): the old shape
    # could not hold two rows for one label, so this collapses nothing in a
    # database the old code wrote -- it is here so the migration is total
    # against a database some other writer left in a state the index allowed.
    op.execute(
        sa.text(
            """
            INSERT INTO prompt_labels (name, label, version)
            SELECT DISTINCT ON (name, label) name, label, version
            FROM prompts
            WHERE label IS NOT NULL
            ORDER BY name, label, version DESC
            """
        )
    )

    op.drop_index("ix_prompts_name_label", table_name="prompts")
    op.drop_column("prompts", "label")


def downgrade() -> None:
    op.add_column("prompts", sa.Column("label", sa.Text, nullable=True))

    # A version may now carry several labels and the old shape cannot express
    # that, so the reverse is lossy by construction. It restores one label per
    # version -- the alphabetically first, deterministically rather than
    # whichever the planner happened to reach -- and drops the rest. Recorded
    # here rather than left for a reader to discover from a row count.
    op.execute(
        sa.text(
            """
            UPDATE prompts p
            SET label = l.label
            FROM (
                SELECT DISTINCT ON (name, version) name, version, label
                FROM prompt_labels
                ORDER BY name, version, label
            ) AS l
            WHERE p.name = l.name AND p.version = l.version
            """
        )
    )

    op.create_index(
        "ix_prompts_name_label",
        "prompts",
        ["name", "label"],
        unique=True,
        postgresql_where=sa.text("label IS NOT NULL"),
    )
    op.drop_table("prompt_labels")

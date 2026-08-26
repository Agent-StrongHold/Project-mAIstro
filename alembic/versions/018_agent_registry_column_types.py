"""The `agents` table takes the values the registry actually writes (#297).

`PgAgentRegistry.upsert` has never succeeded against this schema. Three columns
in migration 005 were given types that do not match the domain the registry
serializes, and the first of them fails before the row is ever offered to
PostgreSQL:

    priority_tier  Integer  ->  Text
    rules          JSONB    ->  Text
    provenance     JSONB    ->  Text

**`priority_tier`** is `Literal["P0", "P1", "P2", "P3", "P4", "P5"]` on
`AgentIdentity`, and `_to_params` defaults it to the string `"P2"`. asyncpg
rejects it at bind time: *invalid input for query argument $12: 'P2' ('str'
object cannot be interpreted as an integer)*. No agent, built-in or otherwise,
could reach the table. `trust_tier` — the same kind of value, a tier label —
was already Text, which is what makes this a transcription slip rather than a
decision.

**`rules`** is joined into a newline-separated string by `_to_params` and split
back on read. **`provenance`** is `str` on `AgentIdentity` (`"builtin"`,
`"user"`). Both were declared JSONB, so PostgreSQL answers *invalid input
syntax for type json* for any value that is not itself JSON — which neither of
these ever is.

Measured against a real PostgreSQL 18: with the three types corrected, an
identity upserts, `count()` and `souls()` answer, and `get()` returns every
field unchanged. Before them, the upsert raises on the first bind.

`USING x::text` is exact in both directions here. The JSONB columns hold no
rows to convert (nothing was ever written), and `priority_tier` likewise; the
casts are written for completeness rather than for data that exists.

The downgrade restores the declared types rather than the working ones, because
a migration must reverse to the state it found. It is a return to a schema the
registry cannot write to -- which is the point of reversing it.

Revision ID: 018
Revises: 017
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "agents",
        "priority_tier",
        type_=sa.Text(),
        existing_type=sa.Integer(),
        existing_nullable=True,
        postgresql_using="priority_tier::text",
    )
    op.alter_column(
        "agents",
        "rules",
        type_=sa.Text(),
        existing_type=postgresql.JSONB(),
        existing_nullable=True,
        postgresql_using="rules::text",
    )
    op.alter_column(
        "agents",
        "provenance",
        type_=sa.Text(),
        existing_type=postgresql.JSONB(),
        existing_nullable=True,
        postgresql_using="provenance::text",
    )


def downgrade() -> None:
    op.alter_column(
        "agents",
        "provenance",
        type_=postgresql.JSONB(),
        existing_type=sa.Text(),
        existing_nullable=True,
        postgresql_using="to_jsonb(provenance)",
    )
    op.alter_column(
        "agents",
        "rules",
        type_=postgresql.JSONB(),
        existing_type=sa.Text(),
        existing_nullable=True,
        postgresql_using="to_jsonb(rules)",
    )
    op.alter_column(
        "agents",
        "priority_tier",
        type_=sa.Integer(),
        existing_type=sa.Text(),
        existing_nullable=True,
        postgresql_using="NULLIF(regexp_replace(priority_tier, '\\D', '', 'g'), '')::integer",
    )

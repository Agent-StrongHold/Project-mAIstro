"""A learning, an outcome and a design output name the execution that produced them (#709).

Three tables that record what the system learned, measured or made, and not one
of them could answer "which execution produced this".

`learnings` had no producer field at all — its closest thing was `source_query`,
the text of the request. A learning is a correction the system applies to future
work, so a bad one changing behaviour could not be traced back to the run that
taught it.

`outcomes` was the near miss. 010 gave it `dag_id`, `dag_run_id` and `node_id` —
the Conductor's product-specific DAG identity, which ADR-019 puts on the product
side of the split. The canonical Run/NodeRun/Attempt those DAG runs execute as
(#143, #223, #697) went unnamed, and outcomes are what the router's scoring and
the optimizer's fitness read. Those three columns stay: they name a real object
the Conductor UI reads. The canonical ids sit alongside them.

`design_outputs` — the engine's one persisted artifact table — shipped an
artifact to a user with no record of what made it.

Nullable, and deliberately: rows written before this are legitimate, and so is a
write with no execution in scope. A `NOT NULL DEFAULT ''` would have made every
such row claim a Run whose id is the empty string, which is the over-claim
#698 removed from node metrics in a different subsystem.

`episodic_memories` is not touched. Nothing outside `alembic/` references that
table and its only store implementation holds a dict, so columns here would be a
durability claim with nothing behind it (#710).

Revision ID: 025
Revises: 024
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None

#: The tables gaining producer provenance, and the index each gets on `run_id`.
#: An index only on the Run: "what did this execution produce" is the question
#: this change exists to answer, and it is asked across all three. Indexing the
#: NodeRun and Attempt as well would cost three writes per row to serve a
#: narrowing a `run_id` lookup already makes cheap.
_TABLES = ("learnings", "outcomes", "design_outputs")

_COLUMNS = ("run_id", "node_run_id", "attempt_id")


def upgrade() -> None:
    for table in _TABLES:
        for column in _COLUMNS:
            op.add_column(table, sa.Column(column, sa.Text, nullable=True))
        op.create_index(f"idx_{table}_run_id", table, ["run_id"])


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"idx_{table}_run_id", table_name=table)
        for column in _COLUMNS:
            op.drop_column(table, column)

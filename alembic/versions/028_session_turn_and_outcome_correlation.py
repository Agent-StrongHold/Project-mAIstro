"""A session turn names its producing Run, and an outcome names its session (#748).

Two records in the same neighbourhood as 026's three, left out for reasons that
no longer hold.

`session_turns` (023) recorded that a turn had been appended, and nothing about
what produced it. `container.py` passes `run.run_id` as the `turn_id`, but that
column is contractually an opaque idempotency key -- `reject_blank_turn_id` is
its whole definition, and the SQLite twin declares it `TEXT NOT NULL` with no
semantics -- so the value is a Run id by accident of one call site. The three
columns added here name the execution in fields that mean it; `turn_id` keeps
the meaning it has (ADR-083026-56ee).

`outcomes` gains `session_id`. `agents/base.py` was writing the session id into
`request_id`, beside the three canonical columns 026 added that do say what they
mean. Nothing filters on `outcomes.request_id`, which is why this was invisible
rather than harmful.

**`request_id` is not backfilled and not rewritten.** Rows written before this
revision may hold a session id under that name; rows after hold a request id or
nothing. Moving the old values would have to assume every historical row came
from the one call site that wrote a session there, which is exactly the
assumption this change exists to stop making. The ambiguity is recorded here
instead of erased.

`canonical_runs` already records the session at
`payload -> 'provenance' ->> 'session_id'` (chat_admission.py), with no index --
so "the Runs of this session" was a sequential scan of a table that a retention
sweeper and an archive sweeper both walk. The partial expression index follows
015, which did the same thing in this same table for `schedule_id`. Partial
because only chat Runs carry a session, and indexing the NULLs of every other
Run would be most of the table for none of the queries.

Nullable throughout, and deliberately: a turn appended with no execution in
scope, and an outcome recorded outside a session, are both legitimate. A
`NOT NULL DEFAULT ''` would make every such row claim a Run or a session whose
id is the empty string -- the over-claim ADR-083026-a91e removed from node
metrics in a different subsystem.

Revision ID: 028
Revises: 027
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None

_TURN_COLUMNS = ("run_id", "node_run_id", "attempt_id")

#: `payload` is JSONB on `canonical_runs` (005) and the provenance dict the chat
#: admitter writes lives inside it, so the expression matches 015's exactly.
_SESSION_PROVENANCE = "(payload -> 'provenance' ->> 'session_id')"
_RUN_SESSION_INDEX = "ix_canonical_runs_session"


def upgrade() -> None:
    for column in _TURN_COLUMNS:
        op.add_column("session_turns", sa.Column(column, sa.Text, nullable=True))
    # Only the Run, for the reason 026 gave: "what did this execution produce"
    # is the question asked of all of these, and a `run_id` lookup already
    # narrows enough that indexing the NodeRun and Attempt too would cost three
    # writes per row to serve nothing.
    op.create_index("idx_session_turns_run_id", "session_turns", ["run_id"])

    op.add_column("outcomes", sa.Column("session_id", sa.Text, nullable=True))
    op.create_index("idx_outcomes_session_id", "outcomes", ["session_id"])

    op.execute(
        f"""
        CREATE INDEX {_RUN_SESSION_INDEX}
            ON canonical_runs ({_SESSION_PROVENANCE})
            WHERE {_SESSION_PROVENANCE} IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_RUN_SESSION_INDEX}")

    op.drop_index("idx_outcomes_session_id", table_name="outcomes")
    op.drop_column("outcomes", "session_id")

    op.drop_index("idx_session_turns_run_id", table_name="session_turns")
    for column in _TURN_COLUMNS:
        op.drop_column("session_turns", column)

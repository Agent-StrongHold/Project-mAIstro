"""Task admission idempotency claims (#1176).

Task submission had no identity of its own: every arriving HTTP call minted a
fresh receipt and a fresh canonical Run, so a client retrying after a timeout
duplicated logical work. `maistro.tasks.idempotency` gives admission a stable
key — supplied or payload-derived, scoped to the principal and the effective
Workspace — and this table is where the claim lives.

The table follows the spine's own backend split (#132): PostgreSQL when the
deployment has one, SQLite (`SqliteTaskIdempotencyStore.ensure_schema`)
otherwise. One row per admission claim:

- `scope_key` — the SHA-256 of (domain, principal, workspace, action, key),
  length-prefixed per part. The primary key IS the claim: two concurrent
  identical submissions meet at one INSERT, and the database refuses the
  second rather than trusting a check-then-set in the caller. The principal
  inside the digest is also why the key cannot collide across principals or
  Workspaces, and why another caller cannot resolve a claim it did not make.
- `fingerprint` — SHA-256 of the client-meaningful payload. A replay inside
  the window with a different fingerprint is a visible 409, never somebody
  else's (or a stale) Run.
- `request` — the canonical TaskCreate JSON as admitted (owner and explicit
  key filled in), so a replay after a restart reconstructs the original
  receipt — including one submitted with a header-only key. A plain text
  column rather than `jsonb`: it is written and read back verbatim, never
  queried by content, and text has no codec to disagree about (see
  `evidence_json` on the two pool-building styles).
- `claim_token` — a random per-claimant fence. Every claimant-owned write
  (`begin`, `complete`, `release`) is guarded on it, so a claimant superseded
  past the pending lease cannot stamp its outcome onto (or release) the
  winner's row.
- `task_id`, `run_id` — the announced receipt and, once minted, the Run
  behind it. `task_id` is written by `begin` BEFORE the Run is minted, so a
  claimant that dies mid-admission leaves the handle the retry's discovery
  resolves the minted Run by (the Run's provenance names the receipt);
  `run_id` is written by `complete`/`resolve_run`. `completed_at` — stamped
  once by `complete`, its presence (nonzero) is what makes the outcome final
  and replayable, and the `completed_at = 0` guard keeps any claimant from
  rewriting an outcome that already landed.
- `created_at`, `expires_at`, `lease_expires_at` — integer microseconds since
  the epoch, deliberately not timestamptz: the takeover guard and the purge
  query compare and bound these values on both backends, and one integer
  spelling cannot drift the way two drivers' timestamp parsing can.
  `expires_at` is the replay window (24h default); `lease_expires_at` bounds
  how long a pending claim blocks a second submitter before that submitter
  takes the claim over.

The upgrade needs no backfill: claims begin with this convergence, and every
submission before it is defined to have no admission identity to migrate.

Revision ID: 033
Revises: 032
Create Date: 2026-09-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_idempotency",
        sa.Column("scope_key", sa.Text, nullable=False),
        sa.Column("claim_token", sa.Text, nullable=False),
        sa.Column("fingerprint", sa.Text, nullable=False),
        sa.Column("request", sa.Text, nullable=False),
        sa.Column("task_id", sa.Text, nullable=True),
        sa.Column("run_id", sa.Text, nullable=True),
        sa.Column("completed_at", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("created_at", sa.BigInteger, nullable=False),
        sa.Column("expires_at", sa.BigInteger, nullable=False),
        sa.Column("lease_expires_at", sa.BigInteger, nullable=False),
        sa.PrimaryKeyConstraint("scope_key", name="pk_task_idempotency"),
    )
    # The purge query's scan bound: expired claims are the only deletable
    # population, and without an index every sweep walks the whole table.
    op.create_index("ix_task_idempotency_expires", "task_idempotency", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_task_idempotency_expires", table_name="task_idempotency")
    op.drop_table("task_idempotency")

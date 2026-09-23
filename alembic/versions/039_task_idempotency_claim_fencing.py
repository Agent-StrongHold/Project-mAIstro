"""Fence the task-idempotency claim table (#1176 repair rounds).

Migration 038 created ``task_idempotency`` as the stable admission identity
for task submission: one row per admission scope, carrying the request and
the admitted outcome, replayable for 24h. What it could not do is tell *who*
owns a claim. Two submitters racing on one scope both wrote the same row with
no fence between them, an admission that died mid-flight left a pending row
nobody could safely take over, and a restart-retry had no way to discover the
Run a half-finished admission had already minted.

This revision evolves the table to the fenced shape the runtime now writes:

- ``claim_token`` — a random per-claimant fence. Every claimant-owned write
  (``begin``, ``complete``, ``release``) is guarded on it, so a claimant
  superseded past the pending lease cannot stamp its outcome onto (or
  release) the winner's row.
- ``completed_at`` — stamped once by ``complete``; its presence (nonzero) is
  what makes an outcome final and replayable, and the ``completed_at = 0``
  guard keeps any claimant from rewriting an outcome that already landed.

``task_id`` changes meaning without changing shape: it is now written by
``begin`` BEFORE the Run is minted, so a claimant that dies mid-admission
leaves the handle a retry's discovery resolves the minted Run by (the Run's
provenance names the receipt — see ``PgRunStore.find_run_by_task_receipt``).

One reconciliation: the runtime does not wait for this chain. A deployment
whose pool is spine-ready but not yet migrated provisions this very table at
wire time (``PgTaskIdempotencyStore.ensure_schema``) in the fenced shape
directly — claims are durable from the first submission — and ``alembic
upgrade head`` then meets a table that already has both columns. Rather than
die there (a chain that could never reach head on exactly the deployments
that provisioned early), the upgrade inspects what is standing:

- the migration-038 shape (both new columns absent) is evolved in place, with
  every surviving row backfilled a fence token;
- the runtime-provisioned fenced shape is adopted (primary key and purge
  index verified, reconstructed where an early provisioning skipped them);
- anything else under this name is a shape the store cannot read, and
  failing loudly beats stamping head over a schema nobody checked.

The upgrade needs no data migration beyond the token backfill: claims are
transient (24h replay window), rows completed under 038 replay by
``task_id``/``run_id`` alone, and pending 038 rows expire by their own lease
into the takeover path the fence exists to arbitrate.

Revision ID: 039
Revises: 038
Create Date: 2026-09-20
"""

from __future__ import annotations

from typing import Final

import sqlalchemy as sa
from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None

#: The columns the fenced claim table owns, spelled once so the create, the
#: evolve, and the runtime-provisioning adoption check cannot drift apart.
#: Mirrors ``PgTaskIdempotencyStore.ensure_schema``'s DDL exactly.
CLAIM_COLUMNS: Final[tuple[sa.Column, ...]] = (
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
)

#: The two columns this revision adds to the migration-038 shape, and the
#: only two a 038-era table can be missing while still being this table.
FENCING_COLUMNS: Final[frozenset[str]] = frozenset({"claim_token", "completed_at"})

CLAIM_COLUMN_NAMES: Final[frozenset[str]] = frozenset(col.name for col in CLAIM_COLUMNS)

PURGE_INDEX: Final = "ix_task_idempotency_expires"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("task_idempotency"):
        # Not the chain path (038 creates the table three revisions of story
        # ago on any database that walked here) — this is the deployment that
        # dropped the table while provisioned and is rebuilding. Same shape
        # the runtime would have made, because there is exactly one owner.
        op.create_table(
            "task_idempotency",
            *CLAIM_COLUMNS,
            sa.PrimaryKeyConstraint("scope_key", name="pk_task_idempotency"),
        )
        op.create_index(PURGE_INDEX, "task_idempotency", ["expires_at"])
        return

    columns = {col["name"] for col in inspector.get_columns("task_idempotency")}
    missing = CLAIM_COLUMN_NAMES - columns
    if missing == FENCING_COLUMNS:
        _evolve_pre_fencing_table()
    elif missing:
        raise RuntimeError(
            "task_idempotency already exists without the columns migration 039 "
            f"owns (missing: {sorted(missing)}); it is not the migration-038 "
            "claim table nor the runtime-provisioned fenced one, and the "
            "migration will not stamp over it"
        )
    # else: the fenced shape is already standing — a wire-time provisioning
    # that raced ahead of the chain. Fall through to the shared invariants.

    _ensure_claim_table_invariants(inspector)


def _evolve_pre_fencing_table() -> None:
    """Add the fencing columns to a migration-038 claims table.

    ``claim_token`` is added nullable, backfilled per row, then enforced —
    a NOT NULL add with no default would refuse every table that ever
    admitted anything, and a shared constant default would be a fence
    everybody holds. ``completed_at`` carries its permanent ``0`` server
    default from birth, exactly as the runtime's DDL spells it.
    """
    op.add_column("task_idempotency", sa.Column("claim_token", sa.Text, nullable=True))
    if op.get_bind().dialect.name == "sqlite":
        # The SQLite tier's schema owner is the runtime's ensure_schema, not
        # this chain; the backfill only has to be honest if one ever walks in.
        op.execute("UPDATE task_idempotency SET claim_token = hex(randomblob(16))")
    else:
        op.execute(
            "UPDATE task_idempotency "
            "SET claim_token = md5(random()::text || clock_timestamp()::text)"
        )
    with op.batch_alter_table("task_idempotency") as batch:
        batch.alter_column("claim_token", existing_type=sa.Text, nullable=False)
    op.add_column(
        "task_idempotency",
        sa.Column("completed_at", sa.BigInteger, nullable=False, server_default="0"),
    )


def _ensure_claim_table_invariants(inspector: sa.Inspector) -> None:
    """The two invariants the claim protocol writes through: the PK the
    INSERT ... ON CONFLICT / UPDATE ... WHERE guards rest on, and the purge
    index that keeps the expiry sweep off a full scan. A wire-time
    provisioning that predates either gets it reconstructed here rather than
    stamped over; a duplicate ``scope_key`` fails the CREATE, loudly, exactly
    as it should."""
    pk = inspector.get_pk_constraint("task_idempotency")
    pk_columns = set(pk.get("constrained_columns", []))
    if "scope_key" not in pk_columns:
        if pk.get("name"):
            op.drop_constraint(pk["name"], "task_idempotency", type_="primary")
        op.create_primary_key("pk_task_idempotency", "task_idempotency", ["scope_key"])
    index_names = {ix["name"] for ix in inspector.get_indexes("task_idempotency")}
    if PURGE_INDEX not in index_names:
        op.create_index(PURGE_INDEX, "task_idempotency", ["expires_at"])


def downgrade() -> None:
    """Back to the migration-038 shape: unfenced claims, outcome presence on
    ``task_id``/``run_id`` alone. Completed claims keep their receipts; the
    fences are dropped, which is exactly the pre-038 arbitration story."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("task_idempotency"):
        return
    columns = {col["name"] for col in inspector.get_columns("task_idempotency")}
    for name in sorted(FENCING_COLUMNS):
        if name in columns:
            op.drop_column("task_idempotency", name)

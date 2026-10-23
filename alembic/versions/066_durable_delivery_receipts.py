"""Durable delivery receipts — replay-truthful handler_invocations (#1060).

The (trigger_id, event_id) row alone never proved that a remote handler did
not commit before the local SUCCESS was saved. This revision carries the
reviewed remote-commit contract (#1060) into PostgreSQL:

- ``trigger_definitions`` gains the recipient enrollment columns
  (``replay_safety``, ``contract_ref``); legacy rows upgrade fail-closed to
  ``unproven`` — an old row is never silently upgraded to a safety assertion
  its recipient never made.
- ``handler_invocations`` gains the frozen delivery identity (``delivery_key``
  allocated exactly once on first prepared claim, ``handler_url``,
  ``request_digest``, ``replay_safety``, ``contract_ref``), the fencing
  columns (``claim_token``, ``revision``), the durable dispatch marker
  (``dispatch_started_at``), the current call's evidence (``last_outcome``,
  ``last_error_code``) and cumulative uncertainty
  (``uncertain_prior_dispatch``).
- Attempted legacy rows are reclassified fail-closed: historical SUCCESS is
  preserved as settled acknowledgment; legacy non-success rows with attempts,
  lease/send evidence or a pre-contract hold, and existing FAILED rows (which
  do not prove not_applied), become ``unknown`` with explicit evidence codes
  (``legacy_unkeyed_attempt`` / ``legacy_failed_unproven``). No historical
  delivery keys are invented, attempts are never reset, and no full Events
  are copied into receipts.

Revision ID: 066
Revises: 065
Create Date: 2026-10-18
"""

from __future__ import annotations

from alembic import op

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None

#: Statement-for-statement twin of `pg_stores._SCHEMA_UPGRADES`; the
#: schema-agreement test holds the two catalogues equal. `ADD COLUMN IF NOT
#: EXISTS`, not bare `op.add_column`: the chain is re-applied over
#: already-migrated schemas (stamp-back, #286), and a bare ADD COLUMN fails
#: that re-application with DuplicateColumn.
_COLUMNS = (
    "ALTER TABLE trigger_definitions ADD COLUMN IF NOT EXISTS "
    "replay_safety TEXT NOT NULL DEFAULT 'unproven'",
    "ALTER TABLE trigger_definitions ADD COLUMN IF NOT EXISTS "
    "contract_ref TEXT NOT NULL DEFAULT ''",
    # delivery_key stays nullable: legacy rows never received one, and the
    # claim path is the only place a key may be allocated (exactly once).
    "ALTER TABLE handler_invocations ADD COLUMN IF NOT EXISTS delivery_key TEXT",
    "ALTER TABLE handler_invocations ADD COLUMN IF NOT EXISTS handler_url TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE handler_invocations ADD COLUMN IF NOT EXISTS "
    "request_digest TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE handler_invocations ADD COLUMN IF NOT EXISTS "
    "replay_safety TEXT NOT NULL DEFAULT 'unproven'",
    "ALTER TABLE handler_invocations ADD COLUMN IF NOT EXISTS "
    "contract_ref TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE handler_invocations ADD COLUMN IF NOT EXISTS claim_token TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE handler_invocations ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE handler_invocations ADD COLUMN IF NOT EXISTS dispatch_started_at DOUBLE PRECISION",
    "ALTER TABLE handler_invocations ADD COLUMN IF NOT EXISTS last_outcome TEXT",
    "ALTER TABLE handler_invocations ADD COLUMN IF NOT EXISTS "
    "uncertain_prior_dispatch BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE handler_invocations ADD COLUMN IF NOT EXISTS "
    "last_error_code TEXT NOT NULL DEFAULT ''",
)


def upgrade() -> None:
    for statement in _COLUMNS:
        op.execute(statement)

    # Fail-closed reclassification of attempted legacy rows: only rows that
    # never received a delivery key are touched (every receipt written by the
    # claim/begin/settle protocol carries one). Historical SUCCESS rows are
    # preserved untouched as settled acknowledgment, and truly unattempted
    # pending rows keep their state — the first claim gives them a key and
    # context atomically before their first send.
    op.execute(
        """
        UPDATE handler_invocations SET status = 'unknown',
               uncertain_prior_dispatch = attempts > 0,
               last_error_code = 'legacy_failed_unproven'
         WHERE delivery_key IS NULL AND status = 'failed' AND last_error_code = ''
        """
    )
    op.execute(
        """
        UPDATE handler_invocations SET status = 'unknown',
               uncertain_prior_dispatch = TRUE,
               last_error_code = 'legacy_unkeyed_attempt'
         WHERE delivery_key IS NULL AND last_error_code = ''
           AND (status NOT IN ('pending', 'success', 'failed')
                OR (status = 'pending'
                    AND (attempts > 0 OR lease_expires_at <> 0)))
        """
    )


def downgrade() -> None:
    # Revision-063's InvocationStatus has no UNKNOWN member, so its row
    # decoder (`InvocationStatus(row['status'])`) raises ValueError on any
    # leftover 'unknown' receipt and the rolled-back runtime can neither read
    # nor claim those rows. Reclassify them to 063-era terminal FAILED — the
    # previous release's own outcome for ambiguous transports — so they are
    # never re-dispatched by a runtime that cannot represent uncertainty, and
    # tag last_error for operators. A later re-upgrade reclassifies these
    # rows fail-closed back to UNKNOWN (the legacy_failed_unproven path,
    # whose `last_error_code = ''` guard matches the column default), so no
    # evidence is lost across the round-trip.
    op.execute(
        """
        UPDATE handler_invocations SET status = 'failed',
               last_error = COALESCE(NULLIF(last_error, ''),
                                     'unknown_receipt_downgraded')
         WHERE status = 'unknown'
        """
    )
    op.execute("ALTER TABLE handler_invocations DROP COLUMN IF EXISTS last_error_code")
    op.execute("ALTER TABLE handler_invocations DROP COLUMN IF EXISTS uncertain_prior_dispatch")
    op.execute("ALTER TABLE handler_invocations DROP COLUMN IF EXISTS last_outcome")
    op.execute("ALTER TABLE handler_invocations DROP COLUMN IF EXISTS dispatch_started_at")
    op.execute("ALTER TABLE handler_invocations DROP COLUMN IF EXISTS revision")
    op.execute("ALTER TABLE handler_invocations DROP COLUMN IF EXISTS claim_token")
    op.execute("ALTER TABLE handler_invocations DROP COLUMN IF EXISTS contract_ref")
    op.execute("ALTER TABLE handler_invocations DROP COLUMN IF EXISTS replay_safety")
    op.execute("ALTER TABLE handler_invocations DROP COLUMN IF EXISTS request_digest")
    op.execute("ALTER TABLE handler_invocations DROP COLUMN IF EXISTS handler_url")
    op.execute("ALTER TABLE handler_invocations DROP COLUMN IF EXISTS delivery_key")
    op.execute("ALTER TABLE trigger_definitions DROP COLUMN IF EXISTS contract_ref")
    op.execute("ALTER TABLE trigger_definitions DROP COLUMN IF EXISTS replay_safety")

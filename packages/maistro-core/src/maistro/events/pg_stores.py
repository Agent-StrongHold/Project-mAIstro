"""PostgreSQL-backed durable event stores (#135).

ADR-086's durable-event stores existed in two flavours, in-memory and SQLite.
The container selects on `db_pool is not None`, and `db_pool` is a *SQLite*
connection — so a deployment on PostgreSQL, the durable system of record per
ADR-082226-5104, got **in-memory** durable events. The event log, the trigger
registry and the invocation history were all lost on restart. "Durable events
that are not durable" is #122's shape, one layer up.

The consequence that outlives a restart is idempotency. `InvocationStore` is
what makes a redelivered event recognisable as already handled; in-memory that
guarantee holds within one process, for one process. Any deployment with more
than one worker did not have it at all — and multi-worker is the only reason to
reach for PostgreSQL here in the first place.

So the interesting store is `PgInvocationStore`, and the interesting property is
the one SQLite never had to answer: two workers racing on the same
`(trigger_id, event_id)` must produce **one** invocation. That is a database
guarantee, not application logic — `ON CONFLICT DO NOTHING` against a composite
primary key — and `tests/events/test_durable_store_conformance.py` runs
concurrent writers against a real server rather than asserting it in a comment.

`PgConsumerCursorStore` (#1163) answers the analogous question for the
legacy-bridge replay cursor: `Container.durable_event_cursor` used to be a
plain process-local `int`, so a restart always replayed the whole retained
log. See `events.consumer_cursor` for the full rationale; this module only
adds the PostgreSQL twin, sharing the same schema-bootstrap/advisory-lock
path as the other two stores.

All four take an `asyncpg.Pool` rather than opening their own, matching
`persistence/pg_*` and letting the container own connection lifetime.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import TYPE_CHECKING, Any

from maistro.events.consumer_cursor import DEFAULT_LEASE_SECONDS as CURSOR_DEFAULT_LEASE_SECONDS
from maistro.events.consumer_cursor import CursorLease
from maistro.events.durable_log import LoggedEvent, require_json_encodable_payload
from maistro.events.invocations import (
    DEFAULT_LEASE_SECONDS,
    MAX_ATTEMPTS,
    DeliveryAlreadyStarted,
    DeliveryAttemptLimitReached,
    DeliveryIdentity,
    DeliveryIdentityMismatch,
    HandlerCallOutcome,
    HandlerInvocation,
    InvocationStatus,
    ReplaySafety,
    _disposition_or_none,
    _float_or_zero,
    _int_or_zero,
    _optional_float,
    _optional_str,
    _text,
    identity_matches,
    settle_fields,
    validate_settle,
    validated_outcome,
)
from maistro.events.trigger_store import TriggerDefinition

if TYPE_CHECKING:
    import asyncpg

#: `BIGSERIAL` rather than SQLite's implicit rowid, and `DOUBLE PRECISION` for
#: `created_at` so the float epoch the dataclasses carry survives the round trip
#: unchanged. A `TIMESTAMPTZ` column would be the better schema and a worse
#: match: it would make the PostgreSQL store return values the other two cannot,
#: which is exactly the divergence one conformance suite exists to prevent.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS event_log (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    source TEXT NOT NULL DEFAULT '',
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_log_type_id ON event_log(event_type, id);
CREATE INDEX IF NOT EXISTS idx_event_log_created_at ON event_log(created_at);

CREATE TABLE IF NOT EXISTS trigger_definitions (
    trigger_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    event_pattern TEXT NOT NULL DEFAULT '',
    handler_url TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    replay_safety TEXT NOT NULL DEFAULT 'unproven',
    contract_ref TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_trigger_enabled ON trigger_definitions(enabled);

CREATE TABLE IF NOT EXISTS handler_invocations (
    trigger_id TEXT NOT NULL,
    event_id BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at DOUBLE PRECISION NOT NULL,
    -- The dispatch lease. The primary key below makes racing workers converge
    -- on one *row*; it does not stop both of them calling the handler, because
    -- both read that row back in a non-terminal status. `claim` is what settles
    -- ownership, and this column is where it is recorded.
    lease_expires_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    -- Frozen delivery identity (#1060): the key is allocated exactly once on
    -- the first prepared claim; url/digest/safety/ref are immutable after.
    delivery_key TEXT,
    handler_url TEXT NOT NULL DEFAULT '',
    request_digest TEXT NOT NULL DEFAULT '',
    replay_safety TEXT NOT NULL DEFAULT 'unproven',
    contract_ref TEXT NOT NULL DEFAULT '',
    -- Current-claim fencing and dispatch marker.
    claim_token TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 0,
    dispatch_started_at DOUBLE PRECISION,
    last_outcome TEXT,
    uncertain_prior_dispatch BOOLEAN NOT NULL DEFAULT FALSE,
    last_error_code TEXT NOT NULL DEFAULT '',
    -- The idempotency key, enforced by the database rather than by the caller.
    -- This is what `ON CONFLICT` in `get_or_create` and `claim` relies on, and
    -- what makes two racing workers converge on one row.
    PRIMARY KEY (trigger_id, event_id)
);
CREATE INDEX IF NOT EXISTS idx_invocations_event ON handler_invocations(event_id);

CREATE TABLE IF NOT EXISTS consumer_cursors (
    consumer_id TEXT PRIMARY KEY,
    position BIGINT NOT NULL DEFAULT 0,
    holder TEXT NOT NULL DEFAULT '',
    fencing_token TEXT NOT NULL DEFAULT '',
    lease_expires_at DOUBLE PRECISION NOT NULL DEFAULT 0
);
"""


#: Namespace for the bootstrap advisory lock. Arbitrary but fixed: any two
#: processes running `ensure_event_schema` must pick the same number, and no
#: unrelated advisory lock in this database should pick it too.
_SCHEMA_LOCK_KEY = 0x6D61_6973  # "mais"

#: Legacy-column upgrades plus the fail-closed reclassification of attempted
#: pre-contract rows (#1060 §5), applied idempotently for dev/test bootstrap.
#: Only rows that never received a delivery key are touched; every receipt
#: written by the claim/begin/settle protocol carries one, and historical
#: SUCCESS rows stay untouched as settled historical acknowledgment.
_SCHEMA_UPGRADES = (
    "ALTER TABLE trigger_definitions ADD COLUMN IF NOT EXISTS "
    "replay_safety TEXT NOT NULL DEFAULT 'unproven'",
    "ALTER TABLE trigger_definitions ADD COLUMN IF NOT EXISTS "
    "contract_ref TEXT NOT NULL DEFAULT ''",
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
    """UPDATE handler_invocations SET status = 'unknown',
          uncertain_prior_dispatch = attempts > 0,
          last_error_code = 'legacy_failed_unproven'
       WHERE delivery_key IS NULL AND status = 'failed' AND last_error_code = ''""",
    """UPDATE handler_invocations SET status = 'unknown',
          uncertain_prior_dispatch = TRUE,
          last_error_code = 'legacy_unkeyed_attempt'
       WHERE delivery_key IS NULL AND last_error_code = ''
         AND (status NOT IN ('pending', 'success', 'failed')
              OR (status = 'pending'
                  AND (attempts > 0 OR lease_expires_at <> 0)))""",
)


async def ensure_event_schema(pool: asyncpg.Pool) -> None:
    """Create all four tables. Idempotent, and safe to call concurrently.

    `CREATE TABLE IF NOT EXISTS` is idempotent but **not** serialised: two
    workers that both observe the table as absent can both run the DDL, and one
    loses with `duplicate key value violates unique constraint
    "pg_type_typname_nsp_index"` rather than a clean no-op. That is the failure
    of a bootstrap path in the deployment shape it exists for — several workers
    starting at once is the reason to be on PostgreSQL at all.

    A transaction-scoped advisory lock serialises them. It is released when the
    transaction ends, including by crash, so a worker killed mid-bootstrap does
    not lock the rest out.

    Migrations 004 + 065 remain the real path for a managed deployment; this is
    what lets tests and single-command dev runs work without one. The upgrade
    statements mirror migration 065 (see `tests/migrations/…agreement`).
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock($1)", _SCHEMA_LOCK_KEY)
        await conn.execute(_SCHEMA)
        for statement in _SCHEMA_UPGRADES:
            await conn.execute(statement)


class PgEventLog:
    """PostgreSQL-backed `EventLogStore`."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        await ensure_event_schema(self._pool)

    async def append(
        self,
        event_type: str,
        *,
        entity_type: str = "",
        entity_id: str = "",
        payload: dict[str, Any] | None = None,
        source: str = "",
    ) -> LoggedEvent:
        created_at = time.time()
        require_json_encodable_payload(payload or {})
        row = await self._pool.fetchrow(
            """INSERT INTO event_log
               (event_type, entity_type, entity_id, payload, source, created_at)
               VALUES ($1,$2,$3,$4::jsonb,$5,$6) RETURNING id""",
            event_type,
            entity_type,
            entity_id,
            json.dumps(payload or {}),
            source,
            created_at,
        )
        return LoggedEvent(
            id=row["id"],
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=dict(payload or {}),
            source=source,
            created_at=created_at,
        )

    async def get(self, event_id: int) -> LoggedEvent | None:
        row = await self._pool.fetchrow(
            "SELECT id, event_type, entity_type, entity_id, payload, source, created_at "
            "FROM event_log WHERE id = $1",
            event_id,
        )
        return _row_to_event(row) if row is not None else None

    async def query(
        self,
        *,
        event_type: str | None = None,
        since: float | None = None,
        until: float | None = None,
        after_id: int = 0,
        limit: int = 100,
    ) -> list[LoggedEvent]:
        # Numbered placeholders built alongside the params, so the two cannot
        # drift out of step the way a hand-maintained `$3` would.
        # (column, operator, value) spelled out. An earlier version derived the
        # operator with `value is since`, which is wrong the moment `since` and
        # `until` hold equal floats — CPython interns them, so `until` would be
        # emitted as `>=` and the upper bound would silently become a second
        # lower bound. Placeholders are numbered from `len(params)` so the SQL
        # and the arguments cannot drift apart.
        conditions = ["id > $1"]
        params: list[Any] = [after_id]
        for column, operator, value in (
            ("event_type", "=", event_type),
            ("created_at", ">=", since),
            ("created_at", "<=", until),
        ):
            if value is None:
                continue
            params.append(value)
            conditions.append(f"{column} {operator} ${len(params)}")
        params.append(limit)
        query = (
            "SELECT id, event_type, entity_type, entity_id, payload, source, created_at "
            "FROM event_log WHERE "
            + " AND ".join(conditions)
            + f" ORDER BY id ASC LIMIT ${len(params)}"
        )
        rows = await self._pool.fetch(query, *params)
        return [_row_to_event(r) for r in rows]


class PgTriggerStore:
    """PostgreSQL-backed `TriggerStore`."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        await ensure_event_schema(self._pool)

    async def add(self, trigger: TriggerDefinition) -> None:
        await self._pool.execute(
            """INSERT INTO trigger_definitions
               (trigger_id, name, event_pattern, handler_url, enabled, replay_safety, contract_ref)
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT (trigger_id) DO UPDATE SET
                 name=EXCLUDED.name, event_pattern=EXCLUDED.event_pattern,
                 handler_url=EXCLUDED.handler_url, enabled=EXCLUDED.enabled,
                 replay_safety=EXCLUDED.replay_safety,
                 contract_ref=EXCLUDED.contract_ref""",
            trigger.trigger_id,
            trigger.name,
            trigger.event_pattern,
            trigger.handler_url,
            trigger.enabled,
            trigger.replay_safety.value,
            trigger.contract_ref,
        )

    async def get(self, trigger_id: str) -> TriggerDefinition | None:
        row = await self._pool.fetchrow(
            "SELECT trigger_id, name, event_pattern, handler_url, enabled, "
            "replay_safety, contract_ref FROM trigger_definitions WHERE trigger_id = $1",
            trigger_id,
        )
        return _row_to_trigger(row) if row is not None else None

    async def remove(self, trigger_id: str) -> None:
        await self._pool.execute(
            "DELETE FROM trigger_definitions WHERE trigger_id = $1", trigger_id
        )

    async def list_triggers(self) -> list[TriggerDefinition]:
        rows = await self._pool.fetch(
            "SELECT trigger_id, name, event_pattern, handler_url, enabled, "
            "replay_safety, contract_ref FROM trigger_definitions"
        )
        return [_row_to_trigger(r) for r in rows]

    async def get_matching(self, event_type: str) -> list[TriggerDefinition]:
        # Filtered in Python, as the SQLite store does: the glob semantics in
        # `pattern_matches` are per-segment and not expressible in portable SQL.
        # Doing it differently here would make "the same trigger matches" a
        # per-backend question.
        rows = await self._pool.fetch(
            "SELECT trigger_id, name, event_pattern, handler_url, enabled, "
            "replay_safety, contract_ref FROM trigger_definitions WHERE enabled = TRUE"
        )
        return [t for t in (_row_to_trigger(r) for r in rows) if t.matches(event_type)]

    async def set_enabled(self, trigger_id: str, enabled: bool) -> None:
        await self._pool.execute(
            "UPDATE trigger_definitions SET enabled = $1 WHERE trigger_id = $2",
            enabled,
            trigger_id,
        )


class PgInvocationStore:
    """PostgreSQL-backed `InvocationStore` — the delivery-receipt authority.

    The composite primary key `(trigger_id, event_id)` is the receipt
    identity, and single fenced upserts make two workers racing on the same
    redelivered event converge on one row — never a read-then-write window.
    `claim` prepares/allocates the delivery key, `begin_dispatch` is the sole
    budget-consuming permission to send, and `settle` is revision-fenced.
    """

    _RECEIPT_COLUMNS = (
        "trigger_id, event_id, status, attempts, last_error, created_at, lease_expires_at, "
        "delivery_key, handler_url, request_digest, replay_safety, contract_ref, claim_token, "
        "revision, dispatch_started_at, last_outcome, uncertain_prior_dispatch, last_error_code"
    )

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        await ensure_event_schema(self._pool)

    async def get(self, trigger_id: str, event_id: int) -> HandlerInvocation | None:
        row = await self._pool.fetchrow(
            f"SELECT {self._RECEIPT_COLUMNS} FROM handler_invocations "
            "WHERE trigger_id = $1 AND event_id = $2",
            trigger_id,
            event_id,
        )
        return _row_to_invocation(row) if row is not None else None

    async def get_or_create(self, trigger_id: str, event_id: int) -> HandlerInvocation:
        # One statement. `RETURNING` fires only for the inserting caller, so a
        # NULL row means somebody else won the race — and the follow-up SELECT
        # returns *their* row, which is the whole point: both callers see one
        # receipt with one `created_at`. Bookkeeping only: no key, no claim.
        row = await self._pool.fetchrow(
            """INSERT INTO handler_invocations
               (trigger_id, event_id, status, attempts, last_error, created_at, lease_expires_at)
               VALUES ($1,$2,$3,0,'',$4,0)
               ON CONFLICT (trigger_id, event_id) DO NOTHING
               RETURNING """
            + self._RECEIPT_COLUMNS,
            trigger_id,
            event_id,
            InvocationStatus.PENDING.value,
            time.time(),
        )
        if row is not None:
            return _row_to_invocation(row)
        existing = await self.get(trigger_id, event_id)
        if existing is None:  # pragma: no cover - the conflict proves a row exists
            msg = f"handler_invocations row for ({trigger_id!r}, {event_id}) vanished"
            raise RuntimeError(msg)
        return existing

    async def claim(
        self,
        trigger_id: str,
        event_id: int,
        *,
        delivery: DeliveryIdentity,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
    ) -> HandlerInvocation | None:
        """Prepare one winning receipt/key, or take over an expired lease.

        One upsert: the `WHERE` on the `DO UPDATE` refuses settled or leased
        rows (they match nothing, update nothing, return nothing), the frozen
        identity columns are written only when no key exists yet, and any old
        dispatch marker without a proven not-applied outcome folds into
        `uncertain_prior_dispatch`. Attempts are not consumed here.
        """
        now = time.time()
        row = await self._pool.fetchrow(
            """INSERT INTO handler_invocations
               (trigger_id, event_id, status, attempts, last_error, created_at, lease_expires_at,
                delivery_key, handler_url, request_digest, replay_safety, contract_ref,
                claim_token, revision, dispatch_started_at, last_outcome,
                uncertain_prior_dispatch, last_error_code)
               VALUES ($1,$2,$3,0,'',$4,$5,$6,$7,$8,$9,$10,$11,1,NULL,NULL,FALSE,'')
               ON CONFLICT (trigger_id, event_id) DO UPDATE SET
                 delivery_key = COALESCE(handler_invocations.delivery_key, EXCLUDED.delivery_key),
                 handler_url = CASE WHEN handler_invocations.delivery_key IS NULL
                     THEN EXCLUDED.handler_url ELSE handler_invocations.handler_url END,
                 request_digest = CASE WHEN handler_invocations.delivery_key IS NULL
                     THEN EXCLUDED.request_digest ELSE handler_invocations.request_digest END,
                 replay_safety = CASE WHEN handler_invocations.delivery_key IS NULL
                     THEN EXCLUDED.replay_safety ELSE handler_invocations.replay_safety END,
                 contract_ref = CASE WHEN handler_invocations.delivery_key IS NULL
                     THEN EXCLUDED.contract_ref ELSE handler_invocations.contract_ref END,
                 uncertain_prior_dispatch = handler_invocations.uncertain_prior_dispatch OR (
                     handler_invocations.dispatch_started_at IS NOT NULL
                     AND (handler_invocations.last_outcome IS NULL
                          OR handler_invocations.last_outcome = 'indeterminate')),
                 claim_token = EXCLUDED.claim_token,
                 revision = handler_invocations.revision + 1,
                 lease_expires_at = EXCLUDED.lease_expires_at,
                 dispatch_started_at = NULL,
                 last_outcome = NULL
               WHERE handler_invocations.status <> ALL($12::text[])
                 AND handler_invocations.lease_expires_at <= $4
               RETURNING """
            + self._RECEIPT_COLUMNS,
            trigger_id,
            event_id,
            InvocationStatus.PENDING.value,
            now,
            now + lease_seconds,
            uuid.uuid4().hex,
            delivery.handler_url,
            delivery.request_digest,
            delivery.replay_safety.value,
            delivery.contract_ref,
            uuid.uuid4().hex,
            [
                s.value
                for s in (
                    InvocationStatus.SUCCESS,
                    InvocationStatus.FAILED,
                    InvocationStatus.UNKNOWN,
                )
            ],
        )
        return _row_to_invocation(row) if row is not None else None

    async def begin_dispatch(
        self,
        trigger_id: str,
        event_id: int,
        *,
        claim_token: str,
        expected_revision: int,
        delivery: DeliveryIdentity,
    ) -> HandlerInvocation | None:
        if not claim_token or expected_revision < 0:
            raise ValueError("claim_token must be nonempty and revision non-negative")
        now = time.time()
        row = await self._pool.fetchrow(
            f"""UPDATE handler_invocations SET
                 attempts = attempts + 1, revision = revision + 1, status = 'pending',
                 last_outcome = NULL, dispatch_started_at = $1,
                 last_error = '', last_error_code = ''
               WHERE trigger_id = $2 AND event_id = $3 AND claim_token = $4 AND revision = $5
                 AND lease_expires_at > $1 AND status <> ALL($6::text[])
                 AND dispatch_started_at IS NULL AND attempts < {MAX_ATTEMPTS}
                 AND handler_url = $7 AND request_digest = $8
                 AND replay_safety = $9 AND contract_ref = $10
               RETURNING """
            + self._RECEIPT_COLUMNS,
            now,
            trigger_id,
            event_id,
            claim_token,
            expected_revision,
            [
                s.value
                for s in (
                    InvocationStatus.SUCCESS,
                    InvocationStatus.FAILED,
                    InvocationStatus.UNKNOWN,
                )
            ],
            delivery.handler_url,
            delivery.request_digest,
            delivery.replay_safety.value,
            delivery.contract_ref,
        )
        if row is not None:
            return _row_to_invocation(row)
        return await self._diagnose_refusal(
            trigger_id, event_id, claim_token, expected_revision, delivery
        )

    async def _diagnose_refusal(
        self,
        trigger_id: str,
        event_id: int,
        claim_token: str,
        expected_revision: int,
        delivery: DeliveryIdentity,
    ) -> HandlerInvocation | None:
        """Classify a refused begin as a pre-send fact, or `None` when stale.

        Staleness is reported first: a lost claim is never misread as an
        identity or budget fact about the current owner's receipt.
        """
        receipt = await self.get(trigger_id, event_id)
        if (
            receipt is None
            or receipt.claim_token != claim_token
            or receipt.revision != expected_revision
        ):
            return None
        if not identity_matches(receipt, delivery):
            raise DeliveryIdentityMismatch(
                "receipt destination context differs from the supplied delivery"
            )
        if receipt.attempts >= MAX_ATTEMPTS:
            raise DeliveryAttemptLimitReached(f"attempt cap of {MAX_ATTEMPTS} already consumed")
        if receipt.dispatch_started_at is not None:
            raise DeliveryAlreadyStarted("this claim already began its dispatch")
        return None

    async def settle(
        self,
        trigger_id: str,
        event_id: int,
        *,
        claim_token: str,
        expected_revision: int,
        status: InvocationStatus,
        outcome: HandlerCallOutcome,
    ) -> HandlerInvocation | None:
        if not claim_token or expected_revision < 0:
            raise ValueError("claim_token must be nonempty and revision non-negative")
        evidence = validated_outcome(outcome)
        receipt = await self.get(trigger_id, event_id)
        if (
            receipt is None
            or receipt.claim_token != claim_token
            or receipt.revision != expected_revision
        ):
            return None
        validate_settle(receipt, status, evidence)
        fields = settle_fields(receipt, status, evidence)
        row = await self._pool.fetchrow(
            """UPDATE handler_invocations SET
                 status = $1, last_error = $2, last_error_code = $3, last_outcome = $4,
                 uncertain_prior_dispatch = $5, dispatch_started_at = NULL,
                 revision = revision + 1, lease_expires_at = 0
               WHERE trigger_id = $6 AND event_id = $7 AND claim_token = $8 AND revision = $9
               RETURNING """
            + self._RECEIPT_COLUMNS,
            status.value,
            str(fields["last_error"]),
            str(fields["last_error_code"]),
            evidence.disposition.value,
            bool(fields["uncertain_prior_dispatch"]),
            trigger_id,
            event_id,
            claim_token,
            expected_revision,
        )
        return _row_to_invocation(row) if row is not None else None

    async def save(self, invocation: HandlerInvocation) -> None:
        await self._pool.execute(
            """INSERT INTO handler_invocations
               (trigger_id, event_id, status, attempts, last_error, created_at, lease_expires_at,
                delivery_key, handler_url, request_digest, replay_safety, contract_ref,
                claim_token, revision, dispatch_started_at, last_outcome,
                uncertain_prior_dispatch, last_error_code)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
               ON CONFLICT (trigger_id, event_id) DO UPDATE SET
                 status=EXCLUDED.status, attempts=EXCLUDED.attempts,
                 last_error=EXCLUDED.last_error,
                 lease_expires_at=EXCLUDED.lease_expires_at,
                 delivery_key=EXCLUDED.delivery_key, handler_url=EXCLUDED.handler_url,
                 request_digest=EXCLUDED.request_digest,
                 replay_safety=EXCLUDED.replay_safety, contract_ref=EXCLUDED.contract_ref,
                 claim_token=EXCLUDED.claim_token, revision=EXCLUDED.revision,
                 dispatch_started_at=EXCLUDED.dispatch_started_at,
                 last_outcome=EXCLUDED.last_outcome,
                 uncertain_prior_dispatch=EXCLUDED.uncertain_prior_dispatch,
                 last_error_code=EXCLUDED.last_error_code""",
            invocation.trigger_id,
            invocation.event_id,
            invocation.status.value,
            invocation.attempts,
            invocation.last_error,
            invocation.created_at,
            invocation.lease_expires_at,
            invocation.delivery_key,
            invocation.handler_url,
            invocation.request_digest,
            invocation.replay_safety.value,
            invocation.contract_ref,
            invocation.claim_token,
            invocation.revision,
            invocation.dispatch_started_at,
            invocation.last_outcome.value if invocation.last_outcome else None,
            invocation.uncertain_prior_dispatch,
            invocation.last_error_code,
        )

    async def list_for_event(self, event_id: int) -> list[HandlerInvocation]:
        rows = await self._pool.fetch(
            f"SELECT {self._RECEIPT_COLUMNS} FROM handler_invocations WHERE event_id = $1",
            event_id,
        )
        return [_row_to_invocation(r) for r in rows]


class PgConsumerCursorStore:
    """PostgreSQL-backed `ConsumerCursorStore` (#1163).

    Same claim/advance shape as `PgInvocationStore.claim`: `claim` is one
    upsert whose `WHERE` clause is the exclusion test (a row held by a
    still-live different holder matches nothing and returns nothing), and
    the `CASE` on `fencing_token` keeps a same-holder renewal's token stable.
    `advance` is a plain update guarded by that token, with `GREATEST` as a
    second, independent defence against a stale write moving the position
    backwards.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        await ensure_event_schema(self._pool)

    async def claim(
        self,
        consumer_id: str,
        *,
        holder: str,
        lease_seconds: float = CURSOR_DEFAULT_LEASE_SECONDS,
    ) -> CursorLease | None:
        now = time.time()
        new_token = uuid.uuid4().hex
        row = await self._pool.fetchrow(
            """INSERT INTO consumer_cursors
               (consumer_id, position, holder, fencing_token, lease_expires_at)
               VALUES ($1, 0, $2, $3, $4)
               ON CONFLICT (consumer_id) DO UPDATE SET
                 holder = EXCLUDED.holder,
                 fencing_token = CASE WHEN consumer_cursors.holder = EXCLUDED.holder
                                       THEN consumer_cursors.fencing_token
                                       ELSE EXCLUDED.fencing_token END,
                 lease_expires_at = EXCLUDED.lease_expires_at
               WHERE consumer_cursors.lease_expires_at <= $5
                  OR consumer_cursors.holder = $2
               RETURNING consumer_id, position, fencing_token, lease_expires_at""",
            consumer_id,
            holder,
            new_token,
            now + lease_seconds,
            now,
        )
        return _row_to_cursor_lease(row) if row is not None else None

    async def advance(self, consumer_id: str, *, fencing_token: str, position: int) -> bool:
        row = await self._pool.fetchrow(
            """UPDATE consumer_cursors SET position = GREATEST(position, $1)
               WHERE consumer_id = $2 AND fencing_token = $3
               RETURNING consumer_id""",
            position,
            consumer_id,
            fencing_token,
        )
        return row is not None


def _row_to_event(row: Any) -> LoggedEvent:
    payload = row["payload"]
    return LoggedEvent(
        id=row["id"],
        event_type=row["event_type"],
        entity_type=row["entity_type"] or "",
        entity_id=row["entity_id"] or "",
        # asyncpg returns JSONB as a string unless a codec is registered, so
        # both shapes are accepted rather than depending on pool configuration
        # the store does not own.
        payload=json.loads(payload) if isinstance(payload, str) else dict(payload or {}),
        source=row["source"] or "",
        created_at=row["created_at"],
    )


def _row_to_trigger(row: Any) -> TriggerDefinition:
    return TriggerDefinition(
        trigger_id=row["trigger_id"],
        name=row["name"] or "",
        event_pattern=row["event_pattern"] or "",
        handler_url=row["handler_url"] or "",
        enabled=bool(row["enabled"]),
        replay_safety=ReplaySafety(row["replay_safety"] or "unproven"),
        contract_ref=row["contract_ref"] or "",
    )


def _row_to_invocation(row: Any) -> HandlerInvocation:
    return HandlerInvocation(
        trigger_id=row["trigger_id"],
        event_id=int(row["event_id"]),
        status=InvocationStatus(row["status"]),
        attempts=int(row["attempts"]),
        last_error=_text(row["last_error"]),
        created_at=float(row["created_at"]),
        lease_expires_at=_float_or_zero(row["lease_expires_at"]),
        delivery_key=_optional_str(row["delivery_key"]),
        handler_url=_text(row["handler_url"]),
        request_digest=_text(row["request_digest"]),
        replay_safety=ReplaySafety(str(row["replay_safety"] or "unproven")),
        contract_ref=_text(row["contract_ref"]),
        claim_token=_text(row["claim_token"]),
        revision=_int_or_zero(row["revision"]),
        dispatch_started_at=_optional_float(row["dispatch_started_at"]),
        last_outcome=_disposition_or_none(row["last_outcome"]),
        uncertain_prior_dispatch=bool(row["uncertain_prior_dispatch"]),
        last_error_code=_text(row["last_error_code"]),
    )


def _row_to_cursor_lease(row: Any) -> CursorLease:
    return CursorLease(
        position=int(row["position"]),
        fencing_token=row["fencing_token"],
        expires_at=float(row["lease_expires_at"] or 0),
    )

"""Durable delivery receipts for the at-least-once Event contract (#1060).

The ``((trigger_id, event_id)`` primary key and its lease deduplicate MAIstro
*dispatch only*: they never prove that a remote handler did not commit before
the local SUCCESS was saved. This module therefore separates two authorities
the old row conflated:

- **Delivery identity** — ``DeliveryIdentity`` (handler_url, request digest,
  replay safety, contract ref), frozen on the receipt the first time a key is
  allocated, and immutable thereafter.
- **Delivery evidence** — ``HandlerCallOutcome`` (acknowledged / not_applied /
  indeterminate), the *current call's* evidence only. A local lease, an HTTP
  status or a header never proves an arbitrary remote effect did not occur;
  ``not_applied`` requires an explicit trusted reason.

The writer protocol is ``claim`` / ``begin_dispatch`` / ``settle``:

- ``claim`` prepares exactly one winning receipt (allocating the delivery key
  once) or takes over an expired/unowned row, folding any unreconciled prior
  dispatch marker into ``uncertain_prior_dispatch``. It never consumes budget.
- ``begin_dispatch`` is the sole budget-consuming permission to call. Repeated
  worker death and lease takeover cannot evade ``MAX_ATTEMPTS``.
- ``settle`` records the current call's outcome under revision fencing and
  validates the structural/evidence invariants below. Stale ownership returns
  ``None`` and changes nothing.

Statuses: ``pending``/``retrying`` hold the cursor; ``success``/``failed``/
``unknown`` are settled-for-cursor. ``unknown`` is the truthful state for a
possibly-applied-but-unproven effect: visible, never automatically replayed.
Cumulative uncertainty never clears merely because a later individual call did
not apply. In-memory, SQLite and PostgreSQL implement identical semantics;
a conformance suite runs the same body over all three.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import uuid4

from maistro.sqlite_schema import serialized_schema_upgrade

if TYPE_CHECKING:
    import aiosqlite

    from maistro.events.durable_log import LoggedEvent

MAX_ATTEMPTS = 3
"""Total physical sends permitted per (trigger, event) receipt, ever."""

DEFAULT_LEASE_SECONDS = 300.0
"""How long a claimed receipt stays owned before another worker may take over."""


class InvocationStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    UNKNOWN = "unknown"


#: Statuses that release the processing cursor. ``unknown`` is settled: the
#: receipt stays visible for reconciliation, but the log must be able to move
#: on — an unproven effect must not wedge every later event forever.
SETTLED_FOR_CURSOR_STATUSES = frozenset(
    {InvocationStatus.SUCCESS, InvocationStatus.FAILED, InvocationStatus.UNKNOWN}
)


class ReplaySafety(StrEnum):
    """What the recipient can prove about redelivery of one delivery key.

    ``unproven`` — the recipient cannot deduplicate or query; it may receive a
    one-shot attempt but never automatic redelivery after an uncertain send.
    ``idempotent`` — the recipient atomically binds key+effect at its commit
    boundary (V1: atomic key+digest+commit with durable deduplication).
    ``read_only`` — the handler applies no external effect.
    """

    UNPROVEN = "unproven"
    IDEMPOTENT = "idempotent"
    READ_ONLY = "read_only"


class DeliveryDisposition(StrEnum):
    """What the current call's evidence proves about the remote effect."""

    ACKNOWLEDGED = "acknowledged"
    NOT_APPLIED = "not_applied"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class DeliveryIdentity:
    """The immutable destination context of one receipt.

    Frozen when the delivery key is allocated; every later dispatch of the same
    ``(trigger, event)`` must match it exactly or refuse to send.
    """

    handler_url: str
    request_digest: str
    replay_safety: ReplaySafety = ReplaySafety.UNPROVEN
    contract_ref: str = ""


@dataclass(frozen=True)
class HandlerCallOutcome:
    """Evidence about *one* handler call. Not an effect lifecycle.

    ``reason_code`` (when present) is at most 64 chars of ``[a-z][a-z0-9_]*``;
    ``detail`` is at most 2048 chars. ``NOT_APPLIED`` requires a nonempty
    explicit ``reason_code`` from the trusted caller or a local pre-send
    branch. A malformed outcome classifies indeterminate — never acknowledgment.
    """

    disposition: DeliveryDisposition
    reason_code: str = ""
    detail: str = ""


_REASON_CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_MAX_DETAIL_CHARS = 2048


class DeliveryIdentityMismatch(Exception):
    """The receipt's frozen destination context differs from the supplied one."""


class DeliveryAttemptLimitReached(Exception):
    """``MAX_ATTEMPTS`` physical sends were already consumed; no call permitted."""


class DeliveryAlreadyStarted(Exception):
    """A dispatch marker already exists for this claim; one begin per claim."""


def validated_outcome(outcome: HandlerCallOutcome | None) -> HandlerCallOutcome:
    """Normalise caller evidence: ``None`` is acknowledgment; malformed is indeterminate.

    The injected-caller ``None`` return retains its documented acknowledgment
    meaning. Anything structurally invalid — a bad ``reason_code`` pattern, an
    over-long detail, a ``NOT_APPLIED`` without an explicit reason — classifies
    as ``indeterminate`` and can never become an acknowledgment.
    """
    if outcome is None:
        return HandlerCallOutcome(DeliveryDisposition.ACKNOWLEDGED)
    reason_ok = outcome.reason_code == "" or _REASON_CODE_RE.fullmatch(outcome.reason_code)
    detail_ok = len(outcome.detail) <= _MAX_DETAIL_CHARS
    explicit_reason_ok = outcome.disposition is not DeliveryDisposition.NOT_APPLIED or (
        outcome.reason_code != ""
    )
    if reason_ok and detail_ok and explicit_reason_ok:
        return outcome
    return HandlerCallOutcome(DeliveryDisposition.INDETERMINATE, "malformed_outcome")


def request_digest_v1(handler_url: str, event: LoggedEvent) -> str:
    """Digest v1 of the exact destination and Event body this delivery sends.

    ``v1:`` plus the SHA-256 hex of the UTF-8 JSON of
    ``{version: 1, handler_url: <exact string>, event: Event.to_dict()}`` with
    sorted keys, compact separators, ``ensure_ascii=False`` and
    ``allow_nan=False``. The destination is not normalised and the canonical
    Event identity is never replaced; a digest version change must not be
    silently applied to old receipts.
    """
    body = json.dumps(
        {"version": 1, "handler_url": handler_url, "event": event.to_dict()},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return "v1:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass
class HandlerInvocation:
    """One trigger firing for one event. Keyed by (trigger_id, event_id).

    All stored fields are primitives or enums; every read returns a detached
    snapshot and no backend-owned mutable object escapes the store.
    """

    trigger_id: str
    event_id: int
    status: InvocationStatus = InvocationStatus.PENDING
    attempts: int = 0
    last_error: str = ""
    created_at: float = field(default_factory=time.time)
    lease_expires_at: float = 0.0
    """When the current claim's lease lapses; 0 means nobody holds one."""

    # --- Frozen delivery identity (immutable once the key is allocated) ---
    delivery_key: str | None = None
    """Full uuid4.hex allocated exactly once, on the first prepared claim."""
    handler_url: str = ""
    request_digest: str = ""
    replay_safety: ReplaySafety = ReplaySafety.UNPROVEN
    contract_ref: str = ""

    # --- Current-claim state (rotates with each claim; never proves absence) ---
    claim_token: str = ""
    revision: int = 0
    dispatch_started_at: float | None = None
    """Durable dispatch marker: set by ``begin_dispatch``, cleared by settle/claim."""
    last_outcome: DeliveryDisposition | None = None
    """Evidence of the *current* claim's call, if it completed."""
    uncertain_prior_dispatch: bool = False
    """A possibly-applied prior call was never reconciled. Never self-clears."""
    last_error_code: str = ""

    @property
    def settled_for_cursor(self) -> bool:
        """Whether the processing cursor may advance past this receipt."""
        return self.status in SETTLED_FOR_CURSOR_STATUSES

    @property
    def is_successful_delivery(self) -> bool:
        """Whether the handler acknowledged this delivery. SUCCESS only."""
        return self.status is InvocationStatus.SUCCESS

    @property
    def is_terminal(self) -> bool:
        """Compatibility alias for :attr:`settled_for_cursor`."""
        return self.settled_for_cursor

    def is_leased_at(self, now: float) -> bool:
        """Whether another worker's dispatch lease is still live at ``now``."""
        return self.lease_expires_at > now


@runtime_checkable
class InvocationStore(Protocol):
    """Durable store of delivery receipts, unique on (trigger_id, event_id)."""

    async def get(self, trigger_id: str, event_id: int) -> HandlerInvocation | None: ...

    async def get_or_create(self, trigger_id: str, event_id: int) -> HandlerInvocation:
        """Return the existing receipt for the key, or create a pending one.

        Bookkeeping only: it never grants permission to send, allocates a
        delivery key, or settles anything.
        """
        ...

    async def claim(
        self,
        trigger_id: str,
        event_id: int,
        *,
        delivery: DeliveryIdentity,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
    ) -> HandlerInvocation | None:
        """Atomically prepare one winning receipt/key, or take over an expired one.

        Returns ``None`` for a live lease or a cursor-settled row: the caller
        rereads and never sends on a ``None``. An existing prepared identity is
        returned unchanged even when the supplied one differs — the owning
        processor visibly settles the mismatch without unsafe HTTP. Takeover
        rotates the claim token, increments the revision, sets the lease,
        resets the current-claim marker/outcome, and folds any old dispatch
        marker with absent/indeterminate outcome into
        ``uncertain_prior_dispatch``. Attempts are *not* consumed here.
        """
        ...

    async def begin_dispatch(
        self,
        trigger_id: str,
        event_id: int,
        *,
        claim_token: str,
        expected_revision: int,
        delivery: DeliveryIdentity,
    ) -> HandlerInvocation | None:
        """Atomically consume one attempt and mark the receipt in-dispatch.

        Requires a matching token/revision, a live lease, a nonterminal
        status, no marker for this claim, the exact frozen
        :class:`DeliveryIdentity`, and ``attempts < MAX_ATTEMPTS``. Raises
        :class:`DeliveryIdentityMismatch`, :class:`DeliveryAttemptLimitReached`
        or :class:`DeliveryAlreadyStarted` — pre-send facts about this claim,
        never proof that an earlier send was absent. ``None`` means stale
        ownership (CAS/lease loss), not a retryable transport error.
        """
        ...

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
        """Record the current call's evidence and (maybe) resolve the receipt.

        Token/revision fenced: a still-current owner may settle after lease
        expiry, but a takeover or intervening resolution makes this ``None``
        with no changes. Validates target status in
        success/failed/retrying/unknown and the structural evidence invariants
        (SUCCESS requires acknowledgment; FAILED requires no inherited
        uncertainty plus explicit absence; RETRYING respects the attempt cap
        and is uncertainty-bearing only for idempotent/read_only receipts;
        UNKNOWN carries explicit uncertainty/refusal). Indeterminate evidence
        sets cumulative uncertainty; ``not_applied`` never clears it.
        """
        ...

    async def save(self, invocation: HandlerInvocation) -> None:
        """Low-level unconditional writer. Tests and migrations only.

        Production dispatch never calls this: it bypasses claim/begin/settle
        fencing and evidence validation (#1060).
        """
        ...

    async def list_for_event(self, event_id: int) -> list[HandlerInvocation]: ...


def _identity_frozen_fields(receipt: HandlerInvocation) -> tuple[str, str, ReplaySafety, str]:
    return (
        receipt.handler_url,
        receipt.request_digest,
        receipt.replay_safety,
        receipt.contract_ref,
    )


def identity_matches(receipt: HandlerInvocation, delivery: DeliveryIdentity) -> bool:
    """Whether a receipt's frozen context equals the supplied delivery context."""
    return _identity_frozen_fields(receipt) == (
        delivery.handler_url,
        delivery.request_digest,
        delivery.replay_safety,
        delivery.contract_ref,
    )


_SETTLE_TARGET_STATUSES = frozenset(
    {
        InvocationStatus.SUCCESS,
        InvocationStatus.FAILED,
        InvocationStatus.RETRYING,
        InvocationStatus.UNKNOWN,
    }
)


def _is_uncertainty_bearing(receipt: HandlerInvocation, disposition: DeliveryDisposition) -> bool:
    """Whether this settlement would carry unresolved possibly-applied evidence."""
    return receipt.uncertain_prior_dispatch or disposition is DeliveryDisposition.INDETERMINATE


def _validate_success(disposition: DeliveryDisposition) -> None:
    if disposition is not DeliveryDisposition.ACKNOWLEDGED:
        raise ValueError("SUCCESS requires acknowledged evidence")


def _validate_failed(
    receipt: HandlerInvocation, disposition: DeliveryDisposition, reason_code: str
) -> None:
    # A cap, a status code or an error string never proves absence.
    if disposition is not DeliveryDisposition.NOT_APPLIED or reason_code == "":
        raise ValueError("FAILED requires explicit not_applied evidence with a reason")
    if _is_uncertainty_bearing(receipt, disposition):
        raise ValueError("FAILED requires no unresolved possibly-applied call")


def _validate_retrying(receipt: HandlerInvocation, disposition: DeliveryDisposition) -> None:
    if receipt.attempts >= MAX_ATTEMPTS:
        raise ValueError("RETRYING rejected at the attempt cap")
    if _is_uncertainty_bearing(receipt, disposition) and receipt.replay_safety not in (
        ReplaySafety.IDEMPOTENT,
        ReplaySafety.READ_ONLY,
    ):
        raise ValueError("uncertainty-bearing RETRYING requires an idempotent/read_only contract")


def validate_settle(
    receipt: HandlerInvocation, status: InvocationStatus, outcome: HandlerCallOutcome
) -> None:
    """Structural/evidence invariants for one settlement (#1060 §3).

    Raises ``ValueError`` on a target status the evidence does not support.
    The processor classifies remote evidence; this only validates structure.
    """
    if status not in _SETTLE_TARGET_STATUSES:
        raise ValueError(f"settle target status {status!r} is not a delivery status")
    disposition = outcome.disposition
    if status is InvocationStatus.SUCCESS:
        _validate_success(disposition)
        return
    if disposition is DeliveryDisposition.ACKNOWLEDGED:
        raise ValueError(f"acknowledged evidence cannot settle {status!r}")
    if status is InvocationStatus.FAILED:
        _validate_failed(receipt, disposition, outcome.reason_code)
    elif status is InvocationStatus.RETRYING:
        _validate_retrying(receipt, disposition)
    elif disposition is DeliveryDisposition.NOT_APPLIED and outcome.reason_code == "":
        # UNKNOWN: explicit uncertainty or refusal is required (the check
        # above already ruled out acknowledgment).
        raise ValueError("UNKNOWN refusal requires an explicit reason")


def settle_fields(
    receipt: HandlerInvocation, status: InvocationStatus, outcome: HandlerCallOutcome
) -> dict[str, object]:
    """The column values one settlement writes (validation already passed)."""
    return {
        "status": status,
        "last_error": outcome.detail or outcome.reason_code,
        "last_error_code": outcome.reason_code,
        "last_outcome": outcome.disposition,
        "uncertain_prior_dispatch": receipt.uncertain_prior_dispatch
        or outcome.disposition is DeliveryDisposition.INDETERMINATE,
        "dispatch_started_at": None,
    }


class InMemoryInvocationStore:
    """In-memory :class:`InvocationStore`."""

    def __init__(self) -> None:
        self._invocations: dict[tuple[str, int], HandlerInvocation] = {}
        self._lock = asyncio.Lock()

    async def get(self, trigger_id: str, event_id: int) -> HandlerInvocation | None:
        invocation = self._invocations.get((trigger_id, event_id))
        return _copy_invocation(invocation) if invocation is not None else None

    async def get_or_create(self, trigger_id: str, event_id: int) -> HandlerInvocation:
        async with self._lock:
            key = (trigger_id, event_id)
            existing = self._invocations.get(key)
            if existing is not None:
                return _copy_invocation(existing)
            invocation = HandlerInvocation(trigger_id=trigger_id, event_id=event_id)
            self._invocations[key] = invocation
            return _copy_invocation(invocation)

    async def claim(
        self,
        trigger_id: str,
        event_id: int,
        *,
        delivery: DeliveryIdentity,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
    ) -> HandlerInvocation | None:
        async with self._lock:
            now = time.time()
            key = (trigger_id, event_id)
            receipt = self._invocations.get(key)
            if receipt is None:
                receipt = HandlerInvocation(
                    trigger_id=trigger_id,
                    event_id=event_id,
                    delivery_key=uuid4().hex,
                    handler_url=delivery.handler_url,
                    request_digest=delivery.request_digest,
                    replay_safety=delivery.replay_safety,
                    contract_ref=delivery.contract_ref,
                    revision=1,
                    claim_token=uuid4().hex,
                    lease_expires_at=now + lease_seconds,
                )
                self._invocations[key] = receipt
                return _copy_invocation(receipt)
            if receipt.settled_for_cursor or receipt.is_leased_at(now):
                return None
            # Frozen identity is written exactly once: only a receipt that was
            # never keyed (a truly unattempted legacy row) adopts one now.
            if receipt.delivery_key is None:
                receipt.delivery_key = uuid4().hex
                receipt.handler_url = delivery.handler_url
                receipt.request_digest = delivery.request_digest
                receipt.replay_safety = delivery.replay_safety
                receipt.contract_ref = delivery.contract_ref
            if receipt.dispatch_started_at is not None and receipt.last_outcome not in (
                DeliveryDisposition.NOT_APPLIED,
            ):
                # An in-flight marker whose call was never proven absent.
                receipt.uncertain_prior_dispatch = True
            receipt.claim_token = uuid4().hex
            receipt.revision += 1
            receipt.lease_expires_at = now + lease_seconds
            receipt.dispatch_started_at = None
            receipt.last_outcome = None
            return _copy_invocation(receipt)

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
        async with self._lock:
            receipt = self._invocations.get((trigger_id, event_id))
            if receipt is None:
                return None
            if receipt.claim_token != claim_token or receipt.revision != expected_revision:
                return None
            if not identity_matches(receipt, delivery):
                raise DeliveryIdentityMismatch(
                    "receipt destination context differs from the supplied delivery"
                )
            if receipt.attempts >= MAX_ATTEMPTS:
                raise DeliveryAttemptLimitReached(f"attempt cap of {MAX_ATTEMPTS} already consumed")
            if receipt.dispatch_started_at is not None:
                raise DeliveryAlreadyStarted("this claim already began its dispatch")
            if receipt.settled_for_cursor or not receipt.is_leased_at(time.time()):
                return None
            receipt.attempts += 1
            receipt.revision += 1
            receipt.status = InvocationStatus.PENDING
            receipt.last_outcome = None
            receipt.dispatch_started_at = time.time()
            receipt.last_error = ""
            receipt.last_error_code = ""
            return _copy_invocation(receipt)

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
        async with self._lock:
            receipt = self._invocations.get((trigger_id, event_id))
            if receipt is None:
                return None
            if receipt.claim_token != claim_token or receipt.revision != expected_revision:
                return None
            validate_settle(receipt, status, evidence)
            fields = settle_fields(receipt, status, evidence)
            receipt.status = status
            receipt.last_error = str(fields["last_error"])
            receipt.last_error_code = str(fields["last_error_code"])
            receipt.last_outcome = evidence.disposition
            receipt.uncertain_prior_dispatch = bool(fields["uncertain_prior_dispatch"])
            receipt.dispatch_started_at = None
            receipt.revision += 1
            receipt.lease_expires_at = 0.0
            return _copy_invocation(receipt)

    async def save(self, invocation: HandlerInvocation) -> None:
        async with self._lock:
            self._invocations[(invocation.trigger_id, invocation.event_id)] = _copy_invocation(
                invocation
            )

    async def list_for_event(self, event_id: int) -> list[HandlerInvocation]:
        return [_copy_invocation(i) for i in self._invocations.values() if i.event_id == event_id]


def _copy_invocation(invocation: HandlerInvocation) -> HandlerInvocation:
    """Keep in-memory reads snapshot-like, as durable stores are."""

    return HandlerInvocation(
        trigger_id=invocation.trigger_id,
        event_id=invocation.event_id,
        status=invocation.status,
        attempts=invocation.attempts,
        last_error=invocation.last_error,
        created_at=invocation.created_at,
        lease_expires_at=invocation.lease_expires_at,
        delivery_key=invocation.delivery_key,
        handler_url=invocation.handler_url,
        request_digest=invocation.request_digest,
        replay_safety=invocation.replay_safety,
        contract_ref=invocation.contract_ref,
        claim_token=invocation.claim_token,
        revision=invocation.revision,
        dispatch_started_at=invocation.dispatch_started_at,
        last_outcome=invocation.last_outcome,
        uncertain_prior_dispatch=invocation.uncertain_prior_dispatch,
        last_error_code=invocation.last_error_code,
    )


_RECEIPT_COLUMNS = (
    "trigger_id, event_id, status, attempts, last_error, created_at, lease_expires_at, "
    "delivery_key, handler_url, request_digest, replay_safety, contract_ref, claim_token, "
    "revision, dispatch_started_at, last_outcome, uncertain_prior_dispatch, last_error_code"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS handler_invocations (
    trigger_id TEXT NOT NULL,
    event_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    lease_expires_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (trigger_id, event_id)
)
"""

# Legacy-column upgrades and the fail-closed reclassification of attempted
# pre-contract rows (#1060 §5). The reclassification is idempotent and only
# ever touches rows that never received a delivery key: every receipt written
# by the claim/begin/settle protocol carries one, and historical SUCCESS rows
# are preserved untouched as settled historical acknowledgment.
_RECEIPT_UPGRADES = (
    "ALTER TABLE handler_invocations ADD COLUMN delivery_key TEXT",
    "ALTER TABLE handler_invocations ADD COLUMN handler_url TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE handler_invocations ADD COLUMN request_digest TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE handler_invocations ADD COLUMN replay_safety TEXT NOT NULL DEFAULT 'unproven'",
    "ALTER TABLE handler_invocations ADD COLUMN contract_ref TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE handler_invocations ADD COLUMN claim_token TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE handler_invocations ADD COLUMN revision INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE handler_invocations ADD COLUMN dispatch_started_at REAL",
    "ALTER TABLE handler_invocations ADD COLUMN last_outcome TEXT",
    "ALTER TABLE handler_invocations ADD COLUMN uncertain_prior_dispatch INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE handler_invocations ADD COLUMN last_error_code TEXT NOT NULL DEFAULT ''",
    # Existing FAILED rows do not prove not_applied; preserve as UNKNOWN.
    """UPDATE handler_invocations
       SET status = 'unknown',
           uncertain_prior_dispatch = CASE WHEN attempts > 0 THEN 1 ELSE 0 END,
           last_error_code = 'legacy_failed_unproven'
       WHERE delivery_key IS NULL AND status = 'failed' AND last_error_code = ''""",
    # Any other attempted legacy row without a key is UNKNOWN with evidence.
    """UPDATE handler_invocations
       SET status = 'unknown', uncertain_prior_dispatch = 1,
           last_error_code = 'legacy_unkeyed_attempt'
       WHERE delivery_key IS NULL AND last_error_code = ''
         AND (status NOT IN ('pending', 'success', 'failed')
              OR (status = 'pending'
                  AND (attempts > 0 OR lease_expires_at <> 0)))""",
)


def _upgrade_column(upgrade: str) -> str | None:
    """The column an `ALTER TABLE ... ADD COLUMN <name>` upgrade adds, if any."""
    if not upgrade.startswith("ALTER TABLE"):
        return None
    parts = upgrade.split()
    if len(parts) >= 6 and parts[3] == "ADD" and parts[4] == "COLUMN":
        return parts[5]
    return None


def _row_to_invocation(row: tuple[object, ...]) -> HandlerInvocation:
    outcome = row[15]
    return HandlerInvocation(
        trigger_id=str(row[0]),
        event_id=int(row[1]),  # type: ignore[call-overload]
        status=InvocationStatus(str(row[2])),
        attempts=int(row[3]),  # type: ignore[call-overload]
        last_error=str(row[4] or ""),
        created_at=float(row[5]),  # type: ignore[arg-type]
        lease_expires_at=float(row[6] or 0),  # type: ignore[arg-type]
        delivery_key=str(row[7]) if row[7] is not None else None,
        handler_url=str(row[8] or ""),
        request_digest=str(row[9] or ""),
        replay_safety=ReplaySafety(str(row[10] or "unproven")),
        contract_ref=str(row[11] or ""),
        claim_token=str(row[12] or ""),
        revision=int(row[13] or 0),  # type: ignore[call-overload]
        dispatch_started_at=float(row[14]) if row[14] is not None else None,  # type: ignore[arg-type]
        last_outcome=DeliveryDisposition(str(outcome)) if outcome else None,
        uncertain_prior_dispatch=bool(row[16]),
        last_error_code=str(row[17] or ""),
    )


class SqliteInvocationStore:
    """SQLite-backed :class:`InvocationStore`.

    The composite primary key enforces the (trigger_id, event_id) identity at
    the storage layer; ``claim`` is a single upsert whose ``WHERE`` clause is
    the exclusion test, so racing claimants converge on one winning row.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        async with serialized_schema_upgrade(self._conn):
            await self._conn.execute(_SCHEMA)
            columns = await self._conn.execute("PRAGMA table_info(handler_invocations)")
            names = {str(row[1]) for row in await columns.fetchall()}
            for upgrade in _RECEIPT_UPGRADES:
                added = _upgrade_column(upgrade)
                if added is not None and added in names:
                    continue  # column already present
                await self._conn.execute(upgrade)

    async def get(self, trigger_id: str, event_id: int) -> HandlerInvocation | None:
        cursor = await self._conn.execute(
            f"SELECT {_RECEIPT_COLUMNS} FROM handler_invocations "
            "WHERE trigger_id = ? AND event_id = ?",
            (trigger_id, event_id),
        )
        row = await cursor.fetchone()
        return _row_to_invocation(tuple(row)) if row is not None else None

    async def get_or_create(self, trigger_id: str, event_id: int) -> HandlerInvocation:
        await self._conn.execute(
            """INSERT OR IGNORE INTO handler_invocations
               (trigger_id, event_id, status, attempts, last_error, created_at, lease_expires_at)
               VALUES (?,?,?,0,'',?,0)""",
            (trigger_id, event_id, InvocationStatus.PENDING.value, time.time()),
        )
        await self._conn.commit()
        invocation = await self.get(trigger_id, event_id)
        assert invocation is not None  # nosec B101 - row was just upserted
        return invocation

    async def claim(
        self,
        trigger_id: str,
        event_id: int,
        *,
        delivery: DeliveryIdentity,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
    ) -> HandlerInvocation | None:
        # One statement: `RETURNING` on the upsert, and the `WHERE` on the
        # DO UPDATE is the claim — a terminal or still-leased row matches
        # nothing, updates nothing and returns nothing. Identity columns are
        # frozen once keyed; a never-keyed (truly unattempted legacy) row
        # adopts the supplied identity and its one allocated key.
        now = time.time()
        cursor = await self._conn.execute(
            f"""INSERT INTO handler_invocations
               (trigger_id, event_id, status, attempts, last_error, created_at, lease_expires_at,
                delivery_key, handler_url, request_digest, replay_safety, contract_ref,
                claim_token, revision, dispatch_started_at, last_outcome,
                uncertain_prior_dispatch, last_error_code)
               VALUES (?,?,?,0,'',?,?,?,?,?,?,?,?,1,NULL,NULL,0,'')
               ON CONFLICT(trigger_id, event_id) DO UPDATE SET
                 delivery_key = COALESCE(handler_invocations.delivery_key, excluded.delivery_key),
                 handler_url = CASE WHEN handler_invocations.delivery_key IS NULL
                     THEN excluded.handler_url ELSE handler_invocations.handler_url END,
                 request_digest = CASE WHEN handler_invocations.delivery_key IS NULL
                     THEN excluded.request_digest ELSE handler_invocations.request_digest END,
                 replay_safety = CASE WHEN handler_invocations.delivery_key IS NULL
                     THEN excluded.replay_safety ELSE handler_invocations.replay_safety END,
                 contract_ref = CASE WHEN handler_invocations.delivery_key IS NULL
                     THEN excluded.contract_ref ELSE handler_invocations.contract_ref END,
                 uncertain_prior_dispatch = handler_invocations.uncertain_prior_dispatch OR (
                     handler_invocations.dispatch_started_at IS NOT NULL
                     AND (handler_invocations.last_outcome IS NULL
                          OR handler_invocations.last_outcome = 'indeterminate')),
                 claim_token = excluded.claim_token,
                 revision = handler_invocations.revision + 1,
                 lease_expires_at = excluded.lease_expires_at,
                 dispatch_started_at = NULL,
                 last_outcome = NULL
               WHERE handler_invocations.status NOT IN ('success','failed','unknown')
                 AND handler_invocations.lease_expires_at <= excluded.created_at
               RETURNING {_RECEIPT_COLUMNS}""",
            (
                trigger_id,
                event_id,
                InvocationStatus.PENDING.value,
                now,
                now + lease_seconds,
                uuid4().hex,
                delivery.handler_url,
                delivery.request_digest,
                delivery.replay_safety.value,
                delivery.contract_ref,
                uuid4().hex,
            ),
        )
        row = await cursor.fetchone()
        await self._conn.commit()
        return _row_to_invocation(tuple(row)) if row is not None else None

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
        cursor = await self._conn.execute(
            f"""UPDATE handler_invocations SET
                 attempts = attempts + 1, revision = revision + 1, status = 'pending',
                 last_outcome = NULL, dispatch_started_at = ?, last_error = '', last_error_code = ''
               WHERE trigger_id = ? AND event_id = ? AND claim_token = ? AND revision = ?
                 AND lease_expires_at > ? AND status NOT IN ('success','failed','unknown')
                 AND dispatch_started_at IS NULL AND attempts < 3
                 AND handler_url = ? AND request_digest = ?
                 AND replay_safety = ? AND contract_ref = ?
               RETURNING {_RECEIPT_COLUMNS}""",
            (
                time.time(),
                trigger_id,
                event_id,
                claim_token,
                expected_revision,
                time.time(),
                delivery.handler_url,
                delivery.request_digest,
                delivery.replay_safety.value,
                delivery.contract_ref,
            ),
        )
        row = await cursor.fetchone()
        await self._conn.commit()
        if row is not None:
            return _row_to_invocation(tuple(row))
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

        Diagnosis runs after the fenced UPDATE refused: the error types are
        best-effort pre-send facts, while the UPDATE itself was the atomic
        gate. Staleness (token/revision changed) is reported first — a lost
        claim is never misread as an identity or budget fact.
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
        cursor = await self._conn.execute(
            """UPDATE handler_invocations SET
                 status = ?, last_error = ?, last_error_code = ?, last_outcome = ?,
                 uncertain_prior_dispatch = ?, dispatch_started_at = NULL,
                 revision = revision + 1, lease_expires_at = 0
               WHERE trigger_id = ? AND event_id = ? AND claim_token = ? AND revision = ?
               RETURNING """
            + _RECEIPT_COLUMNS,
            (
                status.value,
                str(fields["last_error"]),
                str(fields["last_error_code"]),
                evidence.disposition.value,
                1 if fields["uncertain_prior_dispatch"] else 0,
                trigger_id,
                event_id,
                claim_token,
                expected_revision,
            ),
        )
        row = await cursor.fetchone()
        await self._conn.commit()
        return _row_to_invocation(tuple(row)) if row is not None else None

    async def save(self, invocation: HandlerInvocation) -> None:
        await self._conn.execute(
            f"""INSERT INTO handler_invocations
               ({_RECEIPT_COLUMNS})
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(trigger_id, event_id) DO UPDATE SET
                 status=excluded.status, attempts=excluded.attempts,
                 last_error=excluded.last_error,
                 lease_expires_at=excluded.lease_expires_at,
                 delivery_key=excluded.delivery_key, handler_url=excluded.handler_url,
                 request_digest=excluded.request_digest,
                 replay_safety=excluded.replay_safety, contract_ref=excluded.contract_ref,
                 claim_token=excluded.claim_token, revision=excluded.revision,
                 dispatch_started_at=excluded.dispatch_started_at,
                 last_outcome=excluded.last_outcome,
                 uncertain_prior_dispatch=excluded.uncertain_prior_dispatch,
                 last_error_code=excluded.last_error_code""",
            (
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
                1 if invocation.uncertain_prior_dispatch else 0,
                invocation.last_error_code,
            ),
        )
        await self._conn.commit()

    async def list_for_event(self, event_id: int) -> list[HandlerInvocation]:
        cursor = await self._conn.execute(
            f"SELECT {_RECEIPT_COLUMNS} FROM handler_invocations WHERE event_id = ?",
            (event_id,),
        )
        rows = await cursor.fetchall()
        return [_row_to_invocation(tuple(r)) for r in rows]

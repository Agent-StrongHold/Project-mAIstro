"""Stable admission identity for task submission (#1176).

Before a Run exists, a submission is identified by nobody: every HTTP call that
arrived minted a fresh receipt and, with an admitter wired, a fresh canonical
Run. A client retrying after a timeout — the response lost, not the work —
duplicated logical work, and nothing in the admission layer could tell a retry
from a second task. This module is the admission-layer contract that makes one
logical submission reconcilable with itself:

**The key.** A submission carries an idempotency/request key, supplied
explicitly (``Idempotency-Key``, or ``TaskCreate.idempotency_key``) or derived
from the request itself. The derived key is the payload fingerprint, so a
byte-identical resubmission is a replay even when the caller never heard of
keys — and two *different* payloads can never collide on it. A client that
legitimately submits identical payloads as distinct work within the replay
window must therefore send distinct explicit keys; derivation cannot
distinguish intentions that are indistinguishable on the wire.

**The scope.** The textual key is hashed together with the authenticated
principal, the effective Workspace, and the admission action
(``admission_scope_key``). The digest is length-prefixed per part, so no two
distinct tuples can produce one scope: a key cannot collide across principals
or Workspaces, and a caller resolving a key computes a scope that only ever
names claims made under the same principal — another caller's Run is not
merely forbidden, it is unaddressable.

**The fingerprint.** Every claim records a fingerprint of the client-meaningful
payload (everything except ``user_id``, which authentication owns, and the key
itself, which would make the derived key circular). A replay under an explicit
key with a different fingerprint raises :class:`IdempotencyKeyMismatch` — the
caller asked to reconcile "submit X" against a claim that admitted Y, and the
honest answer is a visible 409, not somebody else's (or a stale) Run.

**The replay window.** A claim answers replays until ``created_at +
replay_window`` (:data:`DEFAULT_REPLAY_WINDOW`, 24 hours). Inside the window a
repeat resolves to the recorded admission — same task receipt, same ``run_id``,
no second Run. After expiry the key is free: a new submission mints a new Run,
the old Run keeps standing (it is the identity of work that really happened),
and the expired record is deletable by ``purge_expired``. The window is a
documented, deliberate bound: idempotency reconciles retries, which happen in
minutes, not a lifetime deduplication ledger.

**Concurrency.** The claim is an INSERT against a primary key, not a
check-then-set: two identical submissions racing — two tabs, two replicas —
meet at one durable row, and the loser replays the winner's outcome or waits
for it (:class:`Pending`) rather than minting a second Run. A claim that is
still pending holds a short lease (:data:`PENDING_LEASE`); a claim whose owner
died before admitting is taken over once the lease lapses, so a crash mid-
admission stays retryable. That lease is a bounded-stall assumption: admission
is a couple of store round trips, so a claim pending longer than the lease
means its owner is gone.

**Failure ordering.** ``claim -> admit -> complete``, and ``release`` on any
admission failure, keep the two honest cases honest: failing before the Run
exists releases the claim, so the retry mints fresh; failing ambiguously
*after* the Run exists (process death between ``admit`` and ``complete``)
leaves a replayable claim only if ``complete`` landed — the milliseconds
between the two commits are the same two-commit window
``TaskRunAdmitter.admit`` already documents for the Run/receipt pair, and
orphaned Runs from that window are #1114's recovery to find, not this
contract's to hide.

**Not a process-local cache** (the issue's stop condition). The durable
backends — :class:`PgTaskIdempotencyStore` for a replica-shareable deployment,
:class:`SqliteTaskIdempotencyStore` for the single-conductor homelab — put the
claim in the same database tier the Run spine itself selected, so a restart or
a replica handoff resolves retries identically. The in-memory store exists for
the no-database deployment, exactly as the in-memory Run store does; there it
is the deployment's durability tier, not a cache in front of a durable one.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, Protocol

from maistro.tasks.models import TaskCreate

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg

logger = logging.getLogger(__name__)

#: Domain separation for the scope digest. Versioned: a change to the scope
#: tuple's meaning must not silently reinterpret claims recorded before it.
IDEMPOTENCY_SCOPE_DOMAIN = "maistro-task-admission:v1"

#: The admission action every task submission claims under. Part of the scope
#: so a future second admission action (chat, webhooks with their own keys)
#: cannot alias a task claim even for the same principal, Workspace and key.
TASK_SUBMIT_ACTION = "tasks.submit"

#: Prefix marking a key the admission layer derived rather than one a caller
#: supplied. Visible in logs so an operator can tell a client's key from a
#: fingerprint we derived for it.
DERIVED_KEY_PREFIX = "derived:"

#: How long a claim answers replays. Documented in the module docstring: long
#: enough that any realistic retry lands inside it, short enough that an
#: abandoned key is reusable within a day.
DEFAULT_REPLAY_WINDOW = timedelta(hours=24)

#: How long a *pending* (not yet admitted) claim blocks a second submitter
#: before that submitter may take the claim over. Bounds the wait a loser
#: spends on a winner that died mid-admission; admission itself is two store
#: round trips, so anything this side of half a minute is a corpse.
PENDING_LEASE = timedelta(seconds=30)

#: How often a submitter waiting on a pending claim re-asks. One cheap
#: primary-key read per tick; a winner completes in milliseconds, so the usual
#: loser wait is one tick.
PENDING_POLL = 0.05

#: Longest an explicit key may be. The key is hashed before storage, so this
#: bounds admission work and log noise, not a database column.
MAX_IDEMPOTENCY_KEY_LENGTH = 200

#: Upper bound on how many poll ticks the queue spends waiting on a pending
#: claim before reporting the wait as failed. Sized past ``PENDING_LEASE`` so
#: the takeover path is reachable well before the caller gives up.
MAX_PENDING_POLLS = int(PENDING_LEASE.total_seconds() / PENDING_POLL) + 8

#: Provenance key carrying the caller's explicit key on the admitted Run.
IDEMPOTENCY_KEY_PROVENANCE = "idempotency_key"

# Every SQL statement below is a plain literal with zero interpolation —
# inlined at its call site, values bound as parameters — so the statements read
# as what they are rather than as injection surface. The SQLite and PostgreSQL
# dialects differ only in parameter spelling. Each takeover statement carries
# the write-side twin of the read-side decision in ``_assess``: the two must
# stay in agreement, because an assessed-takeover the guard refuses is merely a
# wasted round trip (the flow re-reads and re-classifies), but a guard that
# would take over a claim ``_assess`` calls a replay would mint a second Run
# for an admitted submission. The behavioral tests exercise both sides on
# every backend.


class InvalidIdempotencyKey(ValueError):
    """A key the admission layer refuses to carry: conflicting sources, or one
    over the length bound. Visible at the API as 422, never a silent rename."""


class IdempotencyKeyMismatch(ValueError):
    """A replay under an explicit key whose payload differs from the claim's.

    The issue's fourth acceptance box: the caller must not be handed an
    unrelated prior Run because a key got reused. Surfaces as HTTP 409.
    """


class IdempotencyPendingTimeout(RuntimeError):
    """A concurrent twin held the pending claim past every bounded wait.

    Not the takeover path — that fires at ``PENDING_LEASE`` — but a twin that
    kept re-claiming through it. Raising is the honest answer; the caller's
    retry reconciles against whatever the twin actually admitted.
    """


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)


def _to_us(moment: datetime) -> int:
    """An aware datetime as microseconds since the epoch, exactly.

    Integer microseconds, not float seconds: claim comparison is the purge
    query's WHERE clause and the takeover guard, and a value that rounds is a
    window that drifts. Naive datetimes are refused rather than assumed UTC —
    assuming is how a server-local midnight becomes a different day.
    """
    if moment.tzinfo is None:
        raise ValueError("idempotency timestamps must be timezone-aware")
    return (moment - _EPOCH) // _MICROSECOND


def _from_us(micros: int) -> datetime:
    return _EPOCH + timedelta(microseconds=micros)


def from_epoch_us(micros: int) -> datetime:
    """The inverse of :func:`_to_us`, public because replays need it: a stored
    claim's ``created_at`` is what a reconstructed receipt reports."""
    return _EPOCH + timedelta(microseconds=micros)


def request_fingerprint(request: TaskCreate) -> str:
    """The SHA-256 of the client-meaningful payload, canonicalized.

    ``user_id`` is excluded because authentication owns it — the scope already
    carries the principal, and the API overwrites whatever a client sent.
    ``idempotency_key`` is excluded because a derived key must not depend on
    the key slot, or supplying an explicit key would change the fingerprint
    that explicit keys are checked against.
    """
    payload: dict[str, Any] = request.model_dump(mode="json")
    payload.pop("user_id", None)
    payload.pop("idempotency_key", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def admission_scope_key(*, principal: str, workspace_id: str, action: str, key: str) -> str:
    """The storage key one submission claims under, and the collision answer.

    Every scope component is length-prefixed before the join, so the tuple ->
    digest mapping is injective: no choice of principal, Workspace, action or
    key can produce another tuple's digest, which is what makes cross-tenant
    collision structurally impossible rather than merely unlikely. The
    principal inside the digest is also what keeps another caller from
    *resolving* a claim it did not make — it computes a different scope and
    finds nothing, and the Run behind someone else's claim is reachable only
    through its owner-scoped read paths.
    """
    parts = (IDEMPOTENCY_SCOPE_DOMAIN, principal, workspace_id, action, key)
    framed = "\x1f".join(f"{len(part)}:{part}" for part in parts)
    return hashlib.sha256(framed.encode("utf-8")).hexdigest()


def normalize_idempotency_key(*candidates: str | None) -> str | None:
    """Resolve the supplied key from possibly-several spellings, or refuse.

    Sources that agree (including several ``None``) collapse to the key; two
    *different* non-empty sources is a request carrying two answers to one
    identity question, and is refused rather than resolved by precedence —
    which source wins would otherwise be an implementation detail a retry
    through a different client could flip. Whitespace-only means absent, not
    "a key made of spaces".
    """
    resolved: str | None = None
    for candidate in candidates:
        if candidate is None:
            continue
        stripped = candidate.strip()
        if not stripped:
            continue
        if resolved is not None and resolved != stripped:
            raise InvalidIdempotencyKey(
                "conflicting idempotency keys: the header and the request body "
                "carry different values"
            )
        if len(stripped) > MAX_IDEMPOTENCY_KEY_LENGTH:
            raise InvalidIdempotencyKey(
                f"idempotency key exceeds {MAX_IDEMPOTENCY_KEY_LENGTH} characters"
            )
        resolved = stripped
    return resolved


@dataclass(frozen=True)
class AdmissionRecord:
    """One durable claim: who admitted what, under which outcome, until when.

    ``request`` is the canonical TaskCreate JSON as admitted (owner filled
    in), which is what lets a replay reconstruct the original receipt after a
    restart has emptied the queue's in-memory tasks.
    """

    fingerprint: str
    request: str
    task_id: str | None
    run_id: str | None
    created_at_us: int
    expires_at_us: int
    lease_expires_at_us: int

    @property
    def admitted(self) -> bool:
        """Whether the admission this claim reserves has produced its receipt.

        ``task_id`` is written only by ``complete``, so its presence is the
        claim's own record that the Run exists and the outcome is replayable.
        """
        return self.task_id is not None


@dataclass(frozen=True)
class Claimed:
    """This caller owns the admission: proceed, then ``complete`` or ``release``."""


@dataclass(frozen=True)
class Replayed:
    """A prior identical admission exists inside the window; return its outcome."""

    record: AdmissionRecord


@dataclass(frozen=True)
class Pending:
    """Another caller's claim is mid-admission; wait, then ask again."""

    record: AdmissionRecord


_AssessmentKind = Literal["mismatch", "replayed", "pending", "takeover"]


def _assess(record: AdmissionRecord, *, fingerprint: str, now_us: int) -> _AssessmentKind:
    """Classify an existing claim for one arriving submission.

    Takes a record, never None: the caller reads the row first and answers the
    absent case by inserting. The read-side half of the claim protocol; the
    takeover statements are its write-side twins, and every branch here has a
    mirrored one there. Order matters: the fingerprint contract is checked
    *before* expiry, because a mismatch inside the window must stay a visible
    409 even when the window is one microsecond from closing.
    """
    expired = record.expires_at_us <= now_us
    if record.fingerprint != fingerprint:
        # A reused key with a different payload: the issue's visible failure —
        # unless the window is over, in which case the key is simply free.
        return "takeover" if expired else "mismatch"
    if expired:
        return "takeover"
    if record.admitted:
        return "replayed"
    if record.lease_expires_at_us <= now_us:
        return "takeover"
    return "pending"


def _takeover_guard_holds(record: AdmissionRecord, now_us: int) -> bool:
    """The in-memory twin of the takeover statements' WHERE clause — one
    predicate, spelled twice because one runs in SQL and one in Python. The
    behavioral tests exercise both; a divergence shows up as a backend that
    replays where the other takes over."""
    return record.expires_at_us <= now_us or (
        record.task_id is None and record.lease_expires_at_us <= now_us
    )


class TaskIdempotencyStore(Protocol):
    """Where admission claims live. Protocol, like ``RunStore``: the queue
    wires whichever tier the deployment selected and cannot see the difference."""

    async def claim(
        self,
        scope_key: str,
        *,
        fingerprint: str,
        request: str,
        now: datetime,
        replay_window: timedelta = DEFAULT_REPLAY_WINDOW,
    ) -> Claimed | Replayed | Pending:
        """Reserve the admission named by ``scope_key``.

        Raises :class:`IdempotencyKeyMismatch` when an unexpired claim under
        this scope names a different payload.
        """
        ...

    async def complete(self, scope_key: str, *, task_id: str, run_id: str | None) -> bool:
        """Record the admitted outcome on this caller's own pending claim."""
        ...

    async def release(self, scope_key: str) -> bool:
        """Give a failed admission's claim back: the submission stays retryable."""
        ...

    async def get(self, scope_key: str) -> AdmissionRecord | None: ...

    async def purge_expired(self, *, now: datetime, limit: int = 500) -> int:
        """Delete up to ``limit`` expired claims; the window's garbage collector."""
        ...


class _ClaimFlow:
    """The claim protocol every backend shares, over four storage primitives.

    Subclasses provide insert/read/take-over/complete/release/purge for their
    dialect; this class owns the check-conflict-classify-take-over loop so the
    three backends cannot drift on what a racing retry does. The loop is
    bounded because a guard the ``_assess`` twin disagrees with would
    otherwise spin forever: every refusal to take over is followed by a fresh
    read, and a bounded number of those is enough for any correct guard.
    """

    #: Read-modify-write rounds before giving up and reporting Pending.
    _RACE_ROUNDS = 4

    async def claim(
        self,
        scope_key: str,
        *,
        fingerprint: str,
        request: str,
        now: datetime,
        replay_window: timedelta = DEFAULT_REPLAY_WINDOW,
    ) -> Claimed | Replayed | Pending:
        now_us = _to_us(now)
        fresh = AdmissionRecord(
            fingerprint=fingerprint,
            request=request,
            task_id=None,
            run_id=None,
            created_at_us=now_us,
            expires_at_us=_to_us(now + replay_window),
            lease_expires_at_us=_to_us(now + PENDING_LEASE),
        )
        if await self._insert(scope_key, fresh):
            return Claimed()
        for _ in range(self._RACE_ROUNDS):
            record = await self._read(scope_key)
            if record is None:
                # Released (or taken over) between our refused insert and this
                # read. The slot is free again; try to win it.
                if await self._insert(scope_key, fresh):
                    return Claimed()
                continue
            kind = _assess(record, fingerprint=fingerprint, now_us=now_us)
            if kind == "mismatch":
                raise IdempotencyKeyMismatch(
                    "this idempotency key already admitted a different request payload; "
                    "a replay must repeat the original payload or use a new key"
                )
            if kind == "replayed":
                return Replayed(record)
            if kind == "pending":
                return Pending(record)
            if await self._take_over(scope_key, fresh, now_us):
                return Claimed()
        # The guard kept refusing, which for a correct backend means the row
        # moved under us every round. Report what is there now; a pending
        # answer keeps the caller's own retry loop (and its takeover) armed.
        record = await self._read(scope_key)
        return Pending(record) if record is not None else Pending(fresh)

    async def _insert(self, scope_key: str, record: AdmissionRecord) -> bool:
        raise NotImplementedError

    async def _read(self, scope_key: str) -> AdmissionRecord | None:
        raise NotImplementedError

    async def _take_over(self, scope_key: str, record: AdmissionRecord, now_us: int) -> bool:
        raise NotImplementedError

    async def complete(self, scope_key: str, *, task_id: str, run_id: str | None) -> bool:
        raise NotImplementedError

    async def release(self, scope_key: str) -> bool:
        raise NotImplementedError

    async def get(self, scope_key: str) -> AdmissionRecord | None:
        raise NotImplementedError

    async def purge_expired(self, *, now: datetime, limit: int = 500) -> int:
        raise NotImplementedError


class InMemoryTaskIdempotencyStore(_ClaimFlow):
    """Claims in one process's memory — the no-database deployment's tier.

    The lowest tier, and honest about it: when the Run spine beside it is also
    in memory, a restart loses claims and Runs together, which is the
    deployment's existing durability, unchanged. Bounded like every in-memory
    store here: past :data:`_MAX_ENTRIES` expired claims go first, then the
    oldest — evicting an expired claim is merely early window expiry, and
    evicting the oldest is the same bound the in-memory Run store applies.
    """

    _MAX_ENTRIES = 10_000

    def __init__(self) -> None:
        self._rows: dict[str, AdmissionRecord] = {}
        # One event loop, check-then-act under one lock: the claim protocol's
        # cross-process half comes from the primary key on the durable tiers;
        # this tier's callers are coroutines, which the lock serializes.
        self._lock = asyncio.Lock()

    async def _insert(self, scope_key: str, record: AdmissionRecord) -> bool:
        async with self._lock:
            if scope_key in self._rows:
                return False
            self._rows[scope_key] = record
            self._enforce_bound()
            return True

    def _enforce_bound(self) -> None:
        if len(self._rows) <= self._MAX_ENTRIES:
            return
        now_us = _to_us(datetime.now(UTC))
        expired = sorted(
            (key for key, row in self._rows.items() if row.expires_at_us <= now_us),
            key=lambda key: self._rows[key].created_at_us,
        )
        for key in expired:
            del self._rows[key]
            if len(self._rows) <= self._MAX_ENTRIES:
                return
        oldest = sorted(self._rows, key=lambda key: self._rows[key].created_at_us)
        for key in oldest:
            del self._rows[key]
            if len(self._rows) <= self._MAX_ENTRIES:
                return

    async def _read(self, scope_key: str) -> AdmissionRecord | None:
        async with self._lock:
            return self._rows.get(scope_key)

    async def _take_over(self, scope_key: str, record: AdmissionRecord, now_us: int) -> bool:
        async with self._lock:
            existing = self._rows.get(scope_key)
            if existing is None or not _takeover_guard_holds(existing, now_us):
                return False
            self._rows[scope_key] = record
            return True

    async def complete(self, scope_key: str, *, task_id: str, run_id: str | None) -> bool:
        async with self._lock:
            record = self._rows.get(scope_key)
            if record is None or record.task_id is not None:
                return False
            self._rows[scope_key] = replace(record, task_id=task_id, run_id=run_id)
            return True

    async def release(self, scope_key: str) -> bool:
        async with self._lock:
            record = self._rows.get(scope_key)
            if record is None or record.task_id is not None:
                return False
            del self._rows[scope_key]
            return True

    async def get(self, scope_key: str) -> AdmissionRecord | None:
        async with self._lock:
            return self._rows.get(scope_key)

    async def purge_expired(self, *, now: datetime, limit: int = 500) -> int:
        now_us = _to_us(now)
        async with self._lock:
            doomed = sorted(
                (key for key, row in self._rows.items() if row.expires_at_us <= now_us),
                key=lambda key: self._rows[key].created_at_us,
            )[:limit]
            for key in doomed:
                del self._rows[key]
            return len(doomed)


class SqliteTaskIdempotencyStore(_ClaimFlow):
    """Claims beside the SQLite Run spine: they survive a restart of one
    conductor, which is the durability the homelab tier signs up for.

    One aiosqlite connection, so — exactly as ``SqliteRunStore`` documents —
    every check-then-act pair is serialized on a lock rather than trusting
    interleaving. Cross-*process* safety needs no lock: the primary key on
    ``scope_key`` refuses the second claimant's INSERT at the file, and the
    loser falls into the shared read-and-classify path.
    """

    def __init__(self, conn: Any) -> None:
        # `Any` rather than aiosqlite.Connection: the import is TYPE_CHECKING
        # in every store that takes a connection, and the container hands this
        # one over untyped the same way it hands `db_pool` to the spine.
        self._conn = conn
        self._write_lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS task_idempotency (
                scope_key TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                request TEXT NOT NULL,
                task_id TEXT,
                run_id TEXT,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                lease_expires_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS ix_task_idempotency_expires
                ON task_idempotency(expires_at);
            """
        )
        await self._conn.commit()

    async def _insert(self, scope_key: str, record: AdmissionRecord) -> bool:
        async with self._write_lock:
            try:
                await self._conn.execute(
                    """
                    INSERT INTO task_idempotency
                        (scope_key, fingerprint, request, task_id, run_id,
                         created_at, expires_at, lease_expires_at)
                    VALUES (?, ?, ?, NULL, NULL, ?, ?, ?)
                    """,
                    (
                        scope_key,
                        record.fingerprint,
                        record.request,
                        record.created_at_us,
                        record.expires_at_us,
                        record.lease_expires_at_us,
                    ),
                )
            except sqlite3.IntegrityError:
                # Rolled back before returning: the refused INSERT opened a
                # transaction, and leaving it for the next caller would commit
                # an unrelated write inside it (the trap `SqliteRunStore`
                # documents on the same kind of conflict).
                await self._conn.rollback()
                return False
            await self._conn.commit()
            return True

    async def _read(self, scope_key: str) -> AdmissionRecord | None:
        async with self._conn.execute(
            """
            SELECT scope_key, fingerprint, request, task_id, run_id,
                   created_at, expires_at, lease_expires_at
            FROM task_idempotency WHERE scope_key = ?
            """,
            (scope_key,),
        ) as cursor:
            row = await cursor.fetchone()
        return _row_of(row) if row is not None else None

    async def _take_over(self, scope_key: str, record: AdmissionRecord, now_us: int) -> bool:
        # Guard = expired window, or a pending claim whose lease lapsed.
        async with self._write_lock:
            cursor = await self._conn.execute(
                """
                UPDATE task_idempotency
                SET fingerprint = ?, request = ?, task_id = NULL, run_id = NULL,
                    created_at = ?, expires_at = ?, lease_expires_at = ?
                WHERE scope_key = ?
                  AND (expires_at <= ? OR (task_id IS NULL AND lease_expires_at <= ?))
                """,
                (
                    record.fingerprint,
                    record.request,
                    record.created_at_us,
                    record.expires_at_us,
                    record.lease_expires_at_us,
                    scope_key,
                    now_us,
                    now_us,
                ),
            )
            changed = bool(cursor.rowcount == 1)
            await self._conn.commit()
            return changed

    async def complete(self, scope_key: str, *, task_id: str, run_id: str | None) -> bool:
        async with self._write_lock:
            cursor = await self._conn.execute(
                """
                UPDATE task_idempotency SET task_id = ?, run_id = ?
                WHERE scope_key = ? AND task_id IS NULL
                """,
                (task_id, run_id, scope_key),
            )
            changed = bool(cursor.rowcount == 1)
            await self._conn.commit()
            return changed

    async def release(self, scope_key: str) -> bool:
        async with self._write_lock:
            cursor = await self._conn.execute(
                """
                DELETE FROM task_idempotency
                WHERE scope_key = ? AND task_id IS NULL
                """,
                (scope_key,),
            )
            changed = bool(cursor.rowcount == 1)
            await self._conn.commit()
            return changed

    async def get(self, scope_key: str) -> AdmissionRecord | None:
        return await self._read(scope_key)

    async def purge_expired(self, *, now: datetime, limit: int = 500) -> int:
        async with self._write_lock:
            cursor = await self._conn.execute(
                """
                DELETE FROM task_idempotency WHERE scope_key IN (
                    SELECT scope_key FROM task_idempotency WHERE expires_at <= ?
                    ORDER BY created_at
                    LIMIT ?
                )
                """,
                (_to_us(now), limit),
            )
            changed = int(cursor.rowcount)
            await self._conn.commit()
            return changed


def _row_of(row: Any) -> AdmissionRecord:
    """One positional row — the columns in each SELECT's order, ``scope_key``
    first — as its record. Indexed, not mapped: both drivers hand positionals
    here, and the select spells its column order directly above the call."""
    return AdmissionRecord(
        fingerprint=row[1],
        request=row[2],
        task_id=row[3],
        run_id=row[4],
        created_at_us=row[5],
        expires_at_us=row[6],
        lease_expires_at_us=row[7],
    )


class PgTaskIdempotencyStore(_ClaimFlow):
    """Claims in PostgreSQL beside the PG spine: the tier that makes a retry
    reconcilable across replicas, which is the shape of ambiguous failure the
    issue is actually about — one replica times out on a client, another
    answers the retry."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def _insert(self, scope_key: str, record: AdmissionRecord) -> bool:
        conn: asyncpg.Connection
        async with self._pool.acquire() as conn:
            tag: str = await conn.execute(  # nosec B608 — literal SQL, bound params
                """
                INSERT INTO task_idempotency
                    (scope_key, fingerprint, request, task_id, run_id,
                     created_at, expires_at, lease_expires_at)
                VALUES ($1, $2, $3, NULL, NULL, $4, $5, $6)
                ON CONFLICT (scope_key) DO NOTHING
                """,
                scope_key,
                record.fingerprint,
                record.request,
                record.created_at_us,
                record.expires_at_us,
                record.lease_expires_at_us,
            )
        # asyncpg reports a command tag ("INSERT 0 1"), not a rowcount — the
        # same parse `PgScheduleStore.delete` makes.
        return tag.rsplit(" ", 1)[-1] == "1"

    async def _read(self, scope_key: str) -> AdmissionRecord | None:
        conn: asyncpg.Connection
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT scope_key, fingerprint, request, task_id, run_id,
                       created_at, expires_at, lease_expires_at
                FROM task_idempotency WHERE scope_key = $1
                """,
                scope_key,
            )
        return _row_of(row) if row is not None else None

    async def _take_over(self, scope_key: str, record: AdmissionRecord, now_us: int) -> bool:
        conn: asyncpg.Connection
        async with self._pool.acquire() as conn:
            tag: str = await conn.execute(  # nosec B608 — literal SQL, bound params
                # Guard = expired window, or a pending claim whose lease lapsed.
                """
                UPDATE task_idempotency
                SET fingerprint = $2, request = $3, task_id = NULL, run_id = NULL,
                    created_at = $4, expires_at = $5, lease_expires_at = $6
                WHERE scope_key = $1
                  AND (expires_at <= $7 OR (task_id IS NULL AND lease_expires_at <= $7))
                """,
                scope_key,
                record.fingerprint,
                record.request,
                record.created_at_us,
                record.expires_at_us,
                record.lease_expires_at_us,
                now_us,
            )
        return tag.rsplit(" ", 1)[-1] == "1"

    async def complete(self, scope_key: str, *, task_id: str, run_id: str | None) -> bool:
        conn: asyncpg.Connection
        async with self._pool.acquire() as conn:
            tag: str = await conn.execute(  # nosec B608 — literal SQL, bound params
                """
                UPDATE task_idempotency SET task_id = $2, run_id = $3
                WHERE scope_key = $1 AND task_id IS NULL
                """,
                scope_key,
                task_id,
                run_id,
            )
        return tag.rsplit(" ", 1)[-1] == "1"

    async def release(self, scope_key: str) -> bool:
        conn: asyncpg.Connection
        async with self._pool.acquire() as conn:
            tag: str = await conn.execute(  # nosec B608 — literal SQL, bound params
                """
                DELETE FROM task_idempotency
                WHERE scope_key = $1 AND task_id IS NULL
                """,
                scope_key,
            )
        return tag.rsplit(" ", 1)[-1] == "1"

    async def get(self, scope_key: str) -> AdmissionRecord | None:
        return await self._read(scope_key)

    async def purge_expired(self, *, now: datetime, limit: int = 500) -> int:
        conn: asyncpg.Connection
        async with self._pool.acquire() as conn:
            tag: str = await conn.execute(  # nosec B608 — literal SQL, bound params
                """
                DELETE FROM task_idempotency WHERE scope_key IN (
                    SELECT scope_key FROM task_idempotency WHERE expires_at <= $1
                    ORDER BY created_at
                    LIMIT $2
                )
                """,
                _to_us(now),
                limit,
            )
        return int(tag.rsplit(" ", 1)[-1])


async def wire_task_idempotency(conn: Any, *, pg_pool: Any = None) -> TaskIdempotencyStore:
    """The claim store on the backend the Run spine chose.

    Probed separately from the spine's own table set, for the reason
    ``_pg_schedule_store`` records: a pool migrated to ``032`` but not ``033``
    has a perfectly good durable spine, and dropping its idempotency to
    in-memory over a table it has not grown yet — warned, not silent — beats
    an ``UndefinedTableError`` on somebody's first retry.
    """
    if pg_pool is not None:
        if await pg_pool.fetchval("SELECT to_regclass($1) IS NOT NULL", "public.task_idempotency"):
            return PgTaskIdempotencyStore(pg_pool)
        logger.warning(
            "PostgreSQL pool has no task_idempotency table, so task admission "
            "idempotency is in-process and lost on restart: a retry after a "
            "restart mints a second Run. Run `alembic upgrade head` to make it "
            "durable (#1176)."
        )
        return InMemoryTaskIdempotencyStore()
    if conn is not None:
        store = SqliteTaskIdempotencyStore(conn)
        await store.ensure_schema()
        return store
    return InMemoryTaskIdempotencyStore()


__all__ = [
    "DEFAULT_REPLAY_WINDOW",
    "DERIVED_KEY_PREFIX",
    "IDEMPOTENCY_KEY_PROVENANCE",
    "IDEMPOTENCY_SCOPE_DOMAIN",
    "MAX_IDEMPOTENCY_KEY_LENGTH",
    "MAX_PENDING_POLLS",
    "PENDING_LEASE",
    "PENDING_POLL",
    "TASK_SUBMIT_ACTION",
    "AdmissionRecord",
    "Claimed",
    "IdempotencyKeyMismatch",
    "IdempotencyPendingTimeout",
    "InMemoryTaskIdempotencyStore",
    "InvalidIdempotencyKey",
    "Pending",
    "PgTaskIdempotencyStore",
    "Replayed",
    "SqliteTaskIdempotencyStore",
    "TaskIdempotencyStore",
    "admission_scope_key",
    "from_epoch_us",
    "normalize_idempotency_key",
    "request_fingerprint",
    "wire_task_idempotency",
]

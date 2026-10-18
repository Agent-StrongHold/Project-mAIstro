"""Tasks-owned immutable PostgreSQL admission generations (#1845).

Generation admission freezes original identity while lease ownership rotates.
Preparation/hydration occur outside admission acquisitions; Run INSERT and
binding share one row-first transaction. Unknown commits are resolved through
fresh locking reads. Temporary old APIs are retained for source compatibility,
not a mixed-writer rollout. Merge/activation prerequisites remain documented.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

from maistro.runs import admission_identity as identity
from maistro.runs.concurrency import RunConcurrencyExceeded
from maistro.runs.evidence_json import decode_evidence, json_of, model_of_json
from maistro.runs.model import Run, RunStatus, evidence_values_equal
from maistro.runs.store import RunIntegrityError, RunNotFound
from maistro.tasks.admission_codec import (
    decode_admission_header,
    decode_admission_record,
    encode_admission_record,
)
from maistro.tasks.admission_generation import _assess
from maistro.tasks.idempotency import (
    IDEMPOTENCY_PURGE_INTERVAL_SECONDS,
    IDEMPOTENCY_PURGE_LIMIT,
    PENDING_LEASE,
    AdmissionRecord,
    IdempotencyKeyMismatch,
    _to_us,
    task_idempotency_purge_failures_total,
)
from maistro.tasks.models import TaskResponse

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg

logger = logging.getLogger(__name__)

# Fixed forward columns: completed_at remains optional legacy evidence only.
_V2_COLUMNS = (
    "scope_key",
    "format_version",
    "fingerprint",
    "created_at",
    "expires_at",
    "lease_expires_at",
    "generation_id",
    "claim_token",
    "workspace_id",
    "project_id",
    "origin_principal_id",
    "actor_principal_id",
    "action",
    "receipt_id",
    "request",
    "receipt_snapshot",
    "provenance_snapshot",
    "task_id",
    "run_id",
    "acknowledged_at",
)
_LOCK_GENERATION_SQL = (
    f"SELECT {', '.join(_V2_COLUMNS)} FROM task_idempotency WHERE scope_key = $1 FOR UPDATE"
)
_INSERT_GENERATION_SQL = (
    f"INSERT INTO task_idempotency ({', '.join(_V2_COLUMNS)}) VALUES ("
    + ", ".join(f"${i}" for i in range(1, len(_V2_COLUMNS) + 1))
    + ") ON CONFLICT (scope_key) DO NOTHING RETURNING scope_key"
)
_REPLACE_GENERATION_SQL = (
    "UPDATE task_idempotency SET "
    + ", ".join(f"{name} = ${i}" for i, name in enumerate(_V2_COLUMNS[1:], 2))
    + " WHERE scope_key = $1"
)


def _parameters(record: identity.AdmissionRecordV2) -> list[object]:
    encoded = encode_admission_record(record)
    return [encoded[name] for name in _V2_COLUMNS]


def _ticket(record: identity.AdmissionRecordV2) -> identity.AdmissionTicket:
    return identity.AdmissionTicket(
        record.envelope.scope_key, record.envelope.generation_id, record.owner_token
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_budget(deadline: float) -> None:
    if not math.isfinite(deadline):
        raise ValueError("admission deadline must be finite monotonic time")
    if deadline <= asyncio.get_running_loop().time():
        raise TimeoutError("admission submission deadline exhausted")


class LegacyAdmissionUnresolvedError(RuntimeError):
    """Unproven legacy binding is preserved for reviewed reconciliation; no HTTP mapping."""


#: The admission row, read under the transaction's lock. Every fence below is
# checked against this locked current row, never against a snapshot taken
# before it.
_LOCK_ROW_SQL = """
SELECT scope_key, claim_token, fingerprint, request, task_id, run_id,
       completed_at, created_at, expires_at, lease_expires_at
FROM task_idempotency WHERE scope_key = $1
FOR UPDATE
"""

#: The binding write. The row is already locked by the SELECT above, so the
#: ``task_id IS NULL`` guard is belt and braces — it also makes this the same
#: predicate ``complete`` carries, which keeps "late acknowledgement cannot
#: rewrite the binding" true as a property of the row, not of the lock dance.
_BIND_SQL = """
UPDATE task_idempotency
SET task_id = $2, run_id = $3,
    completed_at = (EXTRACT(EPOCH FROM clock_timestamp()) * 1000000)::bigint
WHERE scope_key = $1 AND completed_at = 0
"""

#: The generation-fenced release: only this caller's own unbound generation
#: may be deleted. A successor's takeover resets created_at and the lease, so
#: a late owner holding superseded values cannot release — or delete — work a
#: live successor claimed after it.
_RELEASE_CLAIM_SQL = """
DELETE FROM task_idempotency
WHERE scope_key = $1 AND completed_at = 0
  AND claim_token = $2 AND created_at = $3 AND lease_expires_at = $4
"""


class PreparedRunSource(Protocol):
    """The narrow per-Workspace half of an atomic admission.

    Implemented by :class:`~maistro.tasks.admission.TaskRunAdmitter`: resolve
    the work, the provenance and the Project, and build the Run — all before
    the coordinator's transaction opens, because the Project store may
    acquire its own connection and must not hold the admission row's lock
    while it does.
    """

    async def prepare_run(self, task: Any) -> Run: ...


@dataclass(frozen=True)
class AdmissionBound:
    """The joint commit landed: the Run and this binding are one durable fact.

    ``record`` is the frozen post-binding decision, read back from the values
    this transaction wrote — after both the transaction and the acquired
    connection contexts have exited."""

    record: AdmissionRecord
    task_id: str
    run_id: str


@dataclass(frozen=True)
class AdmissionAlreadyBound:
    """A bound row answered under this scope: replay it, mint nothing.

    Owner-independent by design — the binding names the canonical work for
    this submission identity, and whoever committed it is nobody's business
    (the owner token never enters receipts or provenance)."""

    record: AdmissionRecord


@dataclass(frozen=True)
class AdmissionRowMissing:
    """The admission row is gone (released or purged): claim again."""


@dataclass(frozen=True)
class AdmissionRowReplaced:
    """This caller's claim generation was taken over while it worked.

    The current unbound row belongs to a successor whose lease is (or was)
    its own; the late owner must not insert, complete or release — the
    caller re-claims, bounded, without touching the successor's row."""

    record: AdmissionRecord


AdmissionOutcome = (
    AdmissionBound | AdmissionAlreadyBound | AdmissionRowMissing | AdmissionRowReplaced
)


class RunInsert(Protocol):
    """The connection-owned insert callback, task- and Workspace-agnostic.

    Satisfied by :meth:`~maistro.runs.pg_store.PgRunStore.insert_prepared_run`:
    root-admission advisory locks, the canonical_runs INSERT and the root
    ceiling count, on the connection the coordinator holds."""

    async def __call__(self, conn: Any, run: Run) -> None: ...


def _same_generation(row: AdmissionRecord, claim: AdmissionRecord) -> bool:
    """Whether a locked row is still the claim this caller won.

    The generation is the claim's own identity fields: same payload digest,
    same stored request, same creation and windows. A takeover rewrites all
    of them, so any mismatch means this caller is late. (``task_id``/
    ``run_id`` are excluded on purpose: the binding is the row's outcome, not
    its identity.)
    """
    return (
        row.claim_token,
        row.fingerprint,
        row.request,
        row.completed_at_us,
        row.created_at_us,
        row.expires_at_us,
        row.lease_expires_at_us,
    ) == (
        claim.claim_token,
        claim.fingerprint,
        claim.request,
        claim.completed_at_us,
        claim.created_at_us,
        claim.expires_at_us,
        claim.lease_expires_at_us,
    )


def _connection_errors() -> tuple[type[BaseException], ...]:
    """Driver and raw reconnect failures that leave a transaction outcome unknown.

    Imported lazily to match the other tasks modules: the dialect is a
    deployment fact, not an import-time dependency of the queue's package.
    """
    import asyncpg

    return (asyncpg.exceptions.PostgresConnectionError, asyncpg.InterfaceError, OSError)


class PgRootAdmissionCoordinator:
    """Bind task admission identity and canonical Run in one PG commit.

    Owns the ``task_idempotency`` SQL for the atomic lane. The pool is the
    shared one composition already holds; nothing here outlives the call.
    """

    def __init__(
        self,
        pool: Any,
        *,
        insert_run: RunInsert,
        prepare: Callable[[identity.RootAdmissionEnvelope], Awaitable[Run]] | None = None,
        get_run: Callable[[str], Awaitable[Run | None]] | None = None,
        utc_clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._pool = pool
        self._insert_run = insert_run
        self._prepare = prepare
        self._get_run = get_run
        self._utc_clock = utc_clock
        self._last_purge = time.monotonic()
        self._purge_backlog = False
        self._purge_lock = asyncio.Lock()

    @property
    def generation_admission_ready(self) -> bool:
        """Whether composition supplied the generation preparation and reader."""
        return self._prepare is not None and self._get_run is not None

    def _now_us(self) -> int:
        return _to_us(self._utc_clock())

    def _fresh_record(
        self, envelope: identity.RootAdmissionEnvelope, now_us: int
    ) -> identity.AdmissionRecordV2:
        if envelope.expires_at_us <= now_us:
            raise TimeoutError("the proposed admission generation has expired")
        return identity.AdmissionRecordV2(
            envelope=envelope,
            owner_token=uuid4(),
            lease_expires_at_us=min(
                envelope.expires_at_us,
                max(envelope.created_at_us, now_us + int(PENDING_LEASE.total_seconds() * 1e6)),
            ),
        )

    async def claim(
        self, candidate: identity.RootAdmissionEnvelope, *, deadline: float
    ) -> identity.ClaimResult:
        """Classify under a row lock, with expiry/mismatch before full decoding."""
        _require_budget(deadline)
        async with asyncio.timeout_at(deadline):
            await self._maybe_purge_expired(candidate.scope_key, deadline=deadline)
            _require_budget(deadline)
            async with self._pool.acquire() as conn, conn.transaction(isolation="read_committed"):
                while True:
                    row = await conn.fetchrow(_LOCK_GENERATION_SQL, candidate.scope_key)
                    now_us = self._now_us()
                    if row is None:
                        record = self._fresh_record(candidate, now_us)
                        inserted = await conn.fetchval(_INSERT_GENERATION_SQL, *_parameters(record))
                        if inserted is None:
                            continue  # Concurrent absent-row winner: re-read in this transaction.
                        record = replace(
                            record,
                            lease_expires_at_us=self._fresh_record(
                                candidate, self._now_us()
                            ).lease_expires_at_us,
                        )
                        await conn.execute(
                            "UPDATE task_idempotency SET lease_expires_at = $2 WHERE scope_key = $1",
                            candidate.scope_key,
                            record.lease_expires_at_us,
                        )
                        return identity.Claimed(_ticket(record), record)
                    header = decode_admission_header(row)
                    if header.expires_at_us <= now_us:
                        record = self._fresh_record(candidate, now_us)
                        await conn.execute(_REPLACE_GENERATION_SQL, *_parameters(record))
                        return identity.Claimed(_ticket(record), record)
                    if header.fingerprint != candidate.fingerprint:
                        raise IdempotencyKeyMismatch(
                            "idempotency key already names another payload"
                        )
                    current = decode_admission_record(row, header=header)
                    assessment = _assess(current, fingerprint=candidate.fingerprint, now_us=now_us)
                    if assessment is identity.AdmissionAssessment.REPLAYED:
                        return identity.Replayed(current)
                    if isinstance(current, identity.LegacyAdmissionRecord):
                        return identity.LegacyUnresolved(current)
                    if assessment is identity.AdmissionAssessment.PENDING:
                        return identity.Pending(current)
                    if assessment is not identity.AdmissionAssessment.TAKEOVER:
                        raise AssertionError("locked admission classification is inconsistent")
                    rotated = replace(
                        current,
                        owner_token=uuid4(),
                        lease_expires_at_us=min(
                            current.envelope.expires_at_us,
                            now_us + int(PENDING_LEASE.total_seconds() * 1e6),
                        ),
                    )
                    await conn.execute(
                        "UPDATE task_idempotency SET claim_token = $2, lease_expires_at = $3 "
                        "WHERE scope_key = $1",
                        candidate.scope_key,
                        rotated.owner_token.hex,
                        rotated.lease_expires_at_us,
                    )
                    return identity.Claimed(_ticket(rotated), rotated)

    async def _maybe_purge_expired(self, submitted_scope: str, *, deadline: float) -> None:
        """Preserve bounded TTL housekeeping, excluding unsupported/malformed headers."""
        due = self._purge_backlog or (
            time.monotonic() - self._last_purge >= IDEMPOTENCY_PURGE_INTERVAL_SECONDS
        )
        if not due or self._purge_lock.locked():
            return
        async with self._purge_lock:
            self._last_purge = time.monotonic()
            self._purge_backlog = False
            try:
                _require_budget(deadline)
                async with (
                    self._pool.acquire() as conn,
                    conn.transaction(isolation="read_committed"),
                ):
                    tag = await conn.execute(
                        """
                        DELETE FROM task_idempotency WHERE scope_key IN (
                            SELECT scope_key FROM task_idempotency
                            WHERE expires_at <= $1 AND scope_key <> $3
                              AND format_version IN (1, 2)
                              AND scope_key ~ '^[0-9a-f]{64}$'
                              AND fingerprint ~ '^[0-9a-f]{64}$'
                            ORDER BY created_at, scope_key LIMIT $2
                            FOR UPDATE SKIP LOCKED
                        ) AND expires_at <= $1 AND format_version IN (1, 2)
                        """,
                        self._now_us(),
                        IDEMPOTENCY_PURGE_LIMIT,
                        submitted_scope,
                    )
            except Exception:
                task_idempotency_purge_failures_total.inc()
                logger.warning(
                    "task_idempotency purge failed; retrying next interval", exc_info=True
                )
                return
            self._purge_backlog = int(tag.rsplit(" ", 1)[-1]) >= IDEMPOTENCY_PURGE_LIMIT

    async def complete(
        self,
        ticket: identity.AdmissionTicket,
        binding: identity.AdmissionBinding,
        *,
        deadline: float,
    ) -> identity.CompletionResult:
        """Acknowledge an identical binding without creating or renewing it."""
        _require_budget(deadline)
        async with asyncio.timeout_at(deadline):
            async with self._pool.acquire() as conn, conn.transaction(isolation="read_committed"):
                row = await conn.fetchrow(_LOCK_GENERATION_SQL, ticket.scope_key)
                if row is None:
                    return identity.StaleOwner()
                record = decode_admission_record(row, header=decode_admission_header(row))
                if not isinstance(record, identity.AdmissionRecordV2) or not record.owns(ticket):
                    return identity.StaleOwner()
                if record.binding != binding:
                    return identity.BindingMismatch()
                if record.acknowledged_at_us is not None:
                    return identity.AlreadyAcknowledged()
                await conn.execute(
                    "UPDATE task_idempotency SET acknowledged_at = $2 WHERE scope_key = $1",
                    ticket.scope_key,
                    max(record.envelope.created_at_us, self._now_us()),
                )
                return identity.Acknowledged()

    async def release(
        self, ticket: identity.AdmissionTicket, *, deadline: float
    ) -> identity.ReleaseResult:
        """Delete only this ticket's definitively unbound generation."""
        _require_budget(deadline)
        async with asyncio.timeout_at(deadline):
            async with self._pool.acquire() as conn, conn.transaction(isolation="read_committed"):
                row = await conn.fetchrow(_LOCK_GENERATION_SQL, ticket.scope_key)
                if row is None:
                    return identity.StaleOwner()
                record = decode_admission_record(row, header=decode_admission_header(row))
                if isinstance(record, identity.LegacyAdmissionRecord):
                    if record.binding is not None:
                        return identity.AlreadyBound(record.binding)
                    return identity.LegacyUnresolved(record)
                if not record.owns(ticket):
                    return identity.StaleOwner()
                if record.binding is not None:
                    return identity.AlreadyBound(record.binding)
                await conn.execute(
                    "DELETE FROM task_idempotency WHERE scope_key = $1", ticket.scope_key
                )
                return identity.Released()

    async def _generation_decision(
        self, conn: Any, ticket: identity.AdmissionTicket, envelope: identity.RootAdmissionEnvelope
    ) -> identity.AdmissionRecordV2 | identity.StaleOwner:
        row = await conn.fetchrow(_LOCK_GENERATION_SQL, ticket.scope_key)
        if row is None:
            return identity.StaleOwner()
        record = decode_admission_record(row, header=decode_admission_header(row))
        if not isinstance(record, identity.AdmissionRecordV2) or record.envelope != envelope:
            return identity.StaleOwner()
        if (
            record.envelope.scope_key != ticket.scope_key
            or record.envelope.generation_id != ticket.generation_id
        ):
            return identity.StaleOwner()
        if record.binding is not None:
            return record  # Same-generation bound replay is owner independent.
        if (
            not record.owns(ticket)
            or min(record.lease_expires_at_us, envelope.expires_at_us) <= self._now_us()
        ):
            return identity.StaleOwner()
        return record

    async def admit(
        self,
        ticket: identity.AdmissionTicket,
        envelope: identity.RootAdmissionEnvelope,
        *,
        deadline: float,
    ) -> identity.RootAdmissionResult | identity.StaleOwner:
        """Prepare outside acquisition, then insert and bind in one row-first transaction."""
        _require_budget(deadline)
        async with asyncio.timeout_at(deadline):
            async with self._pool.acquire() as conn, conn.transaction(isolation="read_committed"):
                decision = await self._generation_decision(conn, ticket, envelope)
            if isinstance(decision, identity.StaleOwner):
                return decision
            if decision.binding is not None:
                return await self.replay(
                    decision,
                    origin_principal_id=envelope.origin_principal_id,
                    workspace_id=envelope.workspace_id,
                    deadline=deadline,
                )
            run = await self._prepare_claimed(ticket, decision.envelope, deadline=deadline)
            while True:
                created = False
                try:
                    async with (
                        self._pool.acquire() as conn,
                        conn.transaction(isolation="read_committed"),
                    ):
                        decision = await self._generation_decision(conn, ticket, envelope)
                        if isinstance(decision, identity.StaleOwner):
                            return decision
                        if decision.binding is None:
                            await self._insert_run(conn, run)
                            binding = identity.AdmissionBinding(run.run_id, envelope.receipt_id)
                            await conn.execute(
                                "UPDATE task_idempotency SET task_id = $2, run_id = $3 WHERE scope_key = $1",
                                ticket.scope_key,
                                binding.receipt_id,
                                binding.run_id,
                            )
                            decision = replace(decision, binding=binding)
                            created = True
                except _connection_errors():
                    # A fresh locking read waits for the old transaction outcome.
                    # Both old contexts have exited, including at pool size one.
                    async with (
                        self._pool.acquire() as conn,
                        conn.transaction(isolation="read_committed"),
                    ):
                        decision = await self._generation_decision(conn, ticket, envelope)
                    if isinstance(decision, identity.StaleOwner):
                        return decision
                    if decision.binding is None:
                        continue  # Proven rollback: retry same private Run and budget.
                    created = False
                except RunConcurrencyExceeded:
                    await self._release_refused(ticket, deadline=deadline)
                    raise
                result = await self.replay(
                    decision,
                    origin_principal_id=envelope.origin_principal_id,
                    workspace_id=envelope.workspace_id,
                    deadline=deadline,
                )
                return replace(result, created=created)

    async def _release_refused(self, ticket: identity.AdmissionTicket, *, deadline: float) -> None:
        if asyncio.get_running_loop().time() < deadline:
            with suppress(Exception):
                await self.release(ticket, deadline=deadline)

    async def _prepare_claimed(
        self,
        ticket: identity.AdmissionTicket,
        envelope: identity.RootAdmissionEnvelope,
        *,
        deadline: float,
    ) -> Run:
        try:
            return await self._prepare_generation(envelope)
        except _connection_errors():
            raise
        except TimeoutError:
            raise
        except Exception:
            # Preparation is read-only; no mutating admission transaction began.
            await self._release_refused(ticket, deadline=deadline)
            raise

    async def _prepare_generation(self, envelope: identity.RootAdmissionEnvelope) -> Run:
        if self._prepare is None:
            raise RuntimeError("generation admission requires the preparation callback")
        run = await self._prepare(envelope)
        self._validate_v2_run(run, envelope)
        if run.status is not RunStatus.QUEUED:
            raise RunIntegrityError("prepared task root must initially be queued")
        return run

    @staticmethod
    def _validate_v2_run(run: Run, envelope: identity.RootAdmissionEnvelope) -> None:
        PgRootAdmissionCoordinator._validate_root_identity(run, envelope)
        PgRootAdmissionCoordinator._validate_original_provenance(run, envelope)
        PgRootAdmissionCoordinator._validate_original_receipt(run, envelope)

    @staticmethod
    def _validate_root_identity(run: Run, envelope: identity.RootAdmissionEnvelope) -> None:
        if (
            run.workspace_id != envelope.workspace_id
            or run.project_id != envelope.project_id
            or run.actor_principal_id != envelope.actor_principal_id
            or run.parent_run_id is not None
            or run.parent_node_run_id is not None
        ):
            raise RunIntegrityError("bound Run scope or admitted actor differs from admission")

    @staticmethod
    def _validate_original_provenance(run: Run, envelope: identity.RootAdmissionEnvelope) -> None:
        expected = decode_evidence(json.loads(envelope.provenance_snapshot.text))
        if not all(
            key in run.provenance and evidence_values_equal(run.provenance[key], value)
            for key, value in expected.items()
        ):
            raise RunIntegrityError("bound Run original admission evidence differs")

    @staticmethod
    def _validate_original_receipt(run: Run, envelope: identity.RootAdmissionEnvelope) -> None:
        receipt = model_of_json(TaskResponse, envelope.receipt_snapshot.text)
        if (
            receipt.task_id != envelope.receipt_id
            or receipt.user_id != envelope.origin_principal_id
            or run.provenance.get("task_id") != envelope.receipt_id
            or run.provenance.get("user_id") != envelope.origin_principal_id
            or not evidence_values_equal(
                run.provenance.get("task_payload"),
                decode_evidence(json.loads(envelope.receipt_snapshot.text)),
            )
        ):
            raise RunIntegrityError("bound Run original receipt or principal differs")

    async def replay(
        self,
        record: identity.AdmissionRecordV2 | identity.LegacyAdmissionRecord,
        *,
        origin_principal_id: str,
        workspace_id: str,
        deadline: float,
    ) -> identity.RootAdmissionResult:
        """Hydrate canonical/archive binding outside admission connections; never remint."""
        binding = record.binding
        if binding is None:
            raise RunIntegrityError("replay requires a canonical binding")
        if isinstance(record, identity.AdmissionRecordV2) and (
            record.envelope.origin_principal_id != origin_principal_id
            or record.envelope.workspace_id != workspace_id
        ):
            raise RunIntegrityError("admission is outside the authorized submission scope")
        if self._get_run is None:
            raise RuntimeError("generation replay requires the canonical reader callback")
        _require_budget(deadline)
        async with asyncio.timeout_at(deadline):
            run = await self._get_run(binding.run_id)
            if run is None:
                raise RunNotFound(binding.run_id)
            if run.run_id != binding.run_id or run.workspace_id != workspace_id:
                raise RunIntegrityError("bound Run identity or Workspace differs")
            if isinstance(record, identity.AdmissionRecordV2):
                self._validate_v2_run(run, record.envelope)
            else:
                self._validate_legacy_run(run, binding, origin_principal_id)
            return identity.RootAdmissionResult(
                binding.run_id,
                binding.receipt_id,
                identity.CanonicalJsonObject(json_of(run)),
                created=False,
            )

    @staticmethod
    def _validate_legacy_run(
        run: Run, binding: identity.AdmissionBinding, origin_principal_id: str
    ) -> None:
        payload = run.provenance.get("task_payload")
        if not isinstance(payload, dict):
            raise RunIntegrityError("legacy bound Run lacks its original receipt")
        try:
            receipt = TaskResponse.model_validate(payload)
        except ValueError:
            raise RunIntegrityError("legacy bound Run has invalid receipt evidence") from None
        if (
            run.parent_run_id is not None
            or run.parent_node_run_id is not None
            or run.actor_principal_id != origin_principal_id
            or run.provenance.get("user_id") != origin_principal_id
            or receipt.user_id != origin_principal_id
            or receipt.task_id != binding.receipt_id
            or run.provenance.get("task_id") != binding.receipt_id
        ):
            raise RunIntegrityError("legacy bound Run root, receipt or principal differs")

    async def bind_admission(
        self,
        *,
        scope_key: str,
        claim: AdmissionRecord,
        task_id: str,
        prepare_run: Callable[[], Awaitable[Run]],
    ) -> AdmissionOutcome:
        """Make one submission's Run and its binding the same commit.

        ``claim`` is the admission row as this caller won it (from the claim
        store's ``get``); it is the generation the fences are checked against.
        ``prepare_run`` runs first, outside any transaction. Raises
        :class:`IdempotencyKeyMismatch` on the scope's 409 and re-raises any
        storage error whose commit outcome could be read as "not admitted" —
        ambiguous connection failures are resolved first by rereading the
        durable row on a fresh connection, and only a row still unbound is
        reported upward as a failure the caller may release.
        """
        run = await prepare_run()
        try:
            conn: asyncpg.Connection
            # READ COMMITTED, like every canonical spine transaction: the
            # fences must evaluate against the locked row's current values,
            # and the binding INSERT…UPDATE re-reads nothing older than the
            # lock.
            async with self._pool.acquire() as conn, conn.transaction(isolation="read_committed"):
                return await self._bind_locked(
                    conn,
                    scope_key=scope_key,
                    claim=claim,
                    task_id=task_id,
                    run=run,
                )
        except _connection_errors():
            # Ambiguous: the commit may or may not have landed. The failed
            # connection must be released before the durable reread: otherwise
            # a one-connection pool deadlocks exactly when recovery is needed.
            # `_read` now necessarily acquires a fresh connection rather than
            # reusing a connection whose transaction outcome is unknown.
            reread = await self._read(scope_key)
            if reread is not None and reread.admitted:
                return AdmissionAlreadyBound(reread)
            raise
        # Unreachable: every path above returns or raises.
        raise AssertionError("bind_admission transaction context fell through")  # pragma: no cover

    async def _bind_locked(
        self,
        conn: Any,
        *,
        scope_key: str,
        claim: AdmissionRecord,
        task_id: str,
        run: Run,
    ) -> AdmissionOutcome:
        """The fenced decision, then the joint write, under the row lock."""
        row = await conn.fetchrow(_LOCK_ROW_SQL, scope_key)
        if row is None:
            return AdmissionRowMissing()
        record = self._record_of(row)
        if record.fingerprint != claim.fingerprint:
            # The scope's 409, enforced against the locked row: the key
            # admitted a different payload, whoever holds it now.
            raise IdempotencyKeyMismatch(
                "this idempotency key already admitted a different request payload; "
                "a replay must repeat the original payload or use a new key"
            )
        if record.admitted:
            # A bound row under this scope is the canonical admission of this
            # very submission: replay it. Inserting would be the second Run
            # the issue forbids; capacity is never consulted on this path, so
            # a replay succeeds even at ceiling.
            return AdmissionAlreadyBound(record)
        if not _same_generation(record, claim):
            # Unbound, but no longer this caller's generation: a successor
            # took the claim over while this owner was mid-admission. Insert
            # nothing; do not release; let the caller re-claim. (Expiry is
            # deliberately not a fence here: the claim flow stamps a fresh
            # window when it grants a generation, and the legacy path commits
            # an admission it won the same way.)
            return AdmissionRowReplaced(record)
        # The joint write, one connection, no nested pool acquisition: the
        # Run's insertion (advisory locks, canonical_runs INSERT, root
        # ceilings) and the binding rise or fall together.
        await self._insert_run(conn, run)
        await conn.execute(_BIND_SQL, scope_key, task_id, run.run_id)
        bound = replace(
            claim,
            task_id=task_id,
            run_id=run.run_id,
            completed_at_us=max(claim.created_at_us, 1),
        )
        return AdmissionBound(record=bound, task_id=task_id, run_id=run.run_id)

    async def release_claim(self, scope_key: str, claim: AdmissionRecord) -> bool:
        """The failure path's release, fenced to this caller's own generation.

        True when this caller's unbound claim was deleted; False when the row
        is bound (nothing to release — the admission committed), missing, or
        now belongs to a successor generation. Never raises on "no": a failed
        admission's cleanup must not turn into the caller's error.
        """
        conn: asyncpg.Connection
        async with self._pool.acquire() as conn:
            tag: str = await conn.execute(  # nosec B608 — literal SQL, bound params
                _RELEASE_CLAIM_SQL,
                scope_key,
                claim.claim_token,
                claim.created_at_us,
                claim.lease_expires_at_us,
            )
        return tag.rsplit(" ", 1)[-1] == "1"

    async def _read(self, scope_key: str) -> AdmissionRecord | None:
        """One admission row, on its own connection — the ambiguity reread."""
        conn: asyncpg.Connection
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT scope_key, claim_token, fingerprint, request, task_id, run_id,
                       completed_at, created_at, expires_at, lease_expires_at
                FROM task_idempotency WHERE scope_key = $1
                """,
                scope_key,
            )
        return self._record_of(row) if row is not None else None

    @staticmethod
    def _record_of(row: Any) -> AdmissionRecord:
        """One positional row — the columns in the SELECT's order — as its
        record. The same codec the claim stores use, owned here for the
        atomic lane's statements."""
        return AdmissionRecord(
            claim_token=row[1],
            fingerprint=row[2],
            request=row[3],
            task_id=row[4],
            run_id=row[5],
            completed_at_us=row[6],
            created_at_us=row[7],
            expires_at_us=row[8],
            lease_expires_at_us=row[9],
        )


__all__ = [
    "AdmissionAlreadyBound",
    "AdmissionBound",
    "AdmissionOutcome",
    "AdmissionRowMissing",
    "AdmissionRowReplaced",
    "PgRootAdmissionCoordinator",
    "PreparedRunSource",
    "RunInsert",
]

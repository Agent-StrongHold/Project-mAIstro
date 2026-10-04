"""Atomic task admission binding for the PostgreSQL spine (#1845).

``TaskQueue._submit_idempotent`` used to make the canonical Run and the
admission binding two commits: ``claim`` (commit 1), ``_submit_once`` — whose
admitter commits the Run on its own connection (commit 2) — and a best-effort
``complete`` (commit 3). A process death between commits 2 and 3 left a bound
Run behind an unbound claim; when the pending lease lapsed, the takeover
reset the row and the retry minted a *second* Run for one submission
identity. No amount of guarding ``complete`` can close that window, because
the binding happens after the Run and in a different transaction.

This module closes it from the tasks side. :class:`PgRootAdmissionCoordinator`
owns the ``task_idempotency`` SQL and one asyncpg READ COMMITTED transaction
that, in order:

1. locks the admission row (``SELECT … FOR UPDATE``) — first in the lock
   order, before the Run store's Workspace/principal advisory locks;
2. re-checks the fences against that locked current row: the scope
   fingerprint (else the shared 409), then the binding (a bound row is a
   same-identity replay, owner-independent), then the generation (an unbound
   row that no longer matches this caller's claim was taken over by a
   successor, and this caller is late);
3. inserts the prepared canonical Run through the injected connection-owned
   callback — root-admission advisory locks, the INSERT, and the root ceiling
   count, exactly ``PgRunStore.create_run``'s transaction body, on this same
   connection;
4. writes ``task_id``/``run_id`` onto the admission row — the binding — on
   the same connection.

Commit is therefore the event that makes the Run replayable. A crash before
it leaves the claim unbound and the takeover path honest (no Run was minted);
a crash after it leaves the binding durable, so every later claim, takeover
or late acknowledgement finds ``task_id`` set and replays instead of
minting. The best-effort ``complete`` remains as evidence for the legacy
path only; on this path nothing waits on it.

The queue gets no database handles here: composition injects the pool and
the narrow, task-agnostic insert callback, and each bound admitter supplies
only a ``prepare_run`` callable that builds the Run *before* the transaction
opens (graph/scope validation may acquire its own connection through the
Project store). ``release_claim`` is the generation-fenced release the
queue's failure path uses: it refuses bound rows and rows a successor now
owns, so a late owner can neither release nor rewrite a successor's claim.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol

from maistro.runs.model import Run
from maistro.tasks.idempotency import AdmissionRecord, IdempotencyKeyMismatch

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg

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
    """The asyncpg failures that leave a transaction's commit outcome unknown.

    Imported lazily to match the other tasks modules: the dialect is a
    deployment fact, not an import-time dependency of the queue's package.
    """
    import asyncpg

    return (asyncpg.exceptions.PostgresConnectionError, asyncpg.InterfaceError)


class PgRootAdmissionCoordinator:
    """Bind task admission identity and canonical Run in one PG commit.

    Owns the ``task_idempotency`` SQL for the atomic lane. The pool is the
    shared one composition already holds; nothing here outlives the call.
    """

    def __init__(self, pool: Any, *, insert_run: RunInsert) -> None:
        self._pool = pool
        self._insert_run = insert_run

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
        conn: asyncpg.Connection
        async with self._pool.acquire() as conn:
            try:
                # READ COMMITTED, like every canonical spine transaction: the
                # fences must evaluate against the locked row's current
                # values, and the binding INSERT…UPDATE re-reads nothing
                # older than the lock.
                async with conn.transaction(isolation="read_committed"):
                    return await self._bind_locked(
                        conn,
                        scope_key=scope_key,
                        claim=claim,
                        task_id=task_id,
                        run=run,
                    )
            except _connection_errors():
                # Ambiguous: the commit may or may not have landed. Reread the
                # durable generation on a new connection instead of assuming
                # "nothing admitted" — deleting the key here would be exactly
                # the duplicate mint this module exists to forbid.
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

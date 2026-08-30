"""PostgreSQL session store."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from maistro.observability.correlation import observed_provenance
from maistro.sessions.turns import reject_blank_turn_id

if TYPE_CHECKING:
    import asyncpg
    import asyncpg.pool


_SESSION_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))"


async def _purge_through(
    conn: asyncpg.Connection | asyncpg.pool.PoolConnectionProxy, cutoff: float
) -> str:
    """Delete expired messages and the turn markers that admitted them.

    Both, always, and inside the caller's transaction. A marker outliving its
    messages would suppress a retry of a turn that no longer exists; messages
    outliving their marker would let one duplicate. Neither half may commit
    alone, so every caller wraps this -- the two `execute` calls here are one
    unit or they are a bug.

    The returned command tag counts messages only: `purge_expired` reports how
    much conversation it removed, and markers are bookkeeping.
    """
    status: str = await conn.execute(
        "DELETE FROM sessions WHERE timestamp <= to_timestamp($1)",
        cutoff,
    )
    await conn.execute(
        "DELETE FROM session_turns WHERE timestamp <= to_timestamp($1)",
        cutoff,
    )
    return status


class PgSessionStore:
    """PostgreSQL-backed session store."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        max_messages: int = 20,
        ttl_seconds: int = 86400,
    ) -> None:
        self._pool = pool
        self._max_messages = max_messages
        self._ttl_seconds = ttl_seconds

    async def get_history(
        self,
        session_id: str,
        max_messages: int | None = None,
        ttl_seconds: int | None = None,
    ) -> list[dict[str, str]]:
        """Retrieve conversation history, pruning expired messages."""
        max_msg = max_messages or self._max_messages
        # `or` here would swallow an explicit 0; see purge_expired below.
        ttl = self._ttl_seconds if ttl_seconds is None else ttl_seconds
        cutoff = time.time() - ttl

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT role, content FROM sessions
                   WHERE session_id = $1 AND timestamp > to_timestamp($2)
                   ORDER BY seq DESC LIMIT $3""",
                session_id,
                cutoff,
                max_msg,
            )
        rows = list(reversed(rows))
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    async def append_messages(
        self,
        session_id: str,
        messages: list[dict[str, str]],
        turn_id: str | None = None,
    ) -> None:
        """Append one complete message batch atomically, at most once.

        Sequence numbers are scoped to a session, so a transaction-scoped
        advisory lock on that identity is the narrowest database authority that
        can serialize ``MAX(seq) + 1`` across independent connections. The lock,
        sequence read, every insert, the turn marker, and the inline retention
        purge are one transaction: a failed message cannot commit a prefix, and
        another writer cannot observe the next sequence until the whole batch is
        durable.

        ``turn_id`` names the turn this batch belongs to (ADR-083026-5fab). It
        is opaque -- never parsed, never derived here -- and a batch appended
        under an identity already recorded for this session is a retry: nothing
        is written and nothing is raised. Without one the append is unchanged,
        because a store cannot invent an identity for a turn it did not observe
        being retried, and deduplicating on content would silently drop a user
        who says the same thing twice.

        The turn marker also records the execution that produced it, resolved
        from the ambient context (ADR-083026-56ee). That is a *separate* fact
        from ``turn_id``: the one production caller happens to pass a Run id as
        the turn identity, but the identity is opaque by contract and any caller
        may pass any non-empty string, so a reader of ``session_turns`` could
        not tell a Run id from a UUID. The provenance columns can be read as
        Run ids because nothing else is ever written to them.
        """
        reject_blank_turn_id(turn_id)
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(_SESSION_LOCK_SQL, session_id)
            if turn_id is not None and await conn.fetchval(
                "SELECT 1 FROM session_turns WHERE session_id = $1 AND turn_id = $2",
                session_id,
                turn_id,
            ):
                return
            row = await conn.fetchrow(
                "SELECT COALESCE(MAX(seq), -1) + 1 AS next_seq FROM sessions WHERE session_id = $1",
                session_id,
            )
            next_seq: int = row["next_seq"] if row else 0

            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role in ("user", "assistant"):
                    await conn.execute(
                        """INSERT INTO sessions (session_id, seq, role, content)
                           VALUES ($1, $2, $3, $4)""",
                        session_id,
                        next_seq,
                        role,
                        content,
                    )
                    next_seq += 1

            if turn_id is not None:
                # Inside the same transaction as the messages it admits, so a
                # batch that fails partway leaves the identity free for a later
                # append. The primary key is what makes at-most-once a database
                # guarantee rather than a property of everyone remembering to
                # take the lock above.
                await conn.execute(
                    """INSERT INTO session_turns
                           (session_id, turn_id, run_id, node_run_id, attempt_id)
                       VALUES ($1, $2, $3, $4, $5)""",
                    session_id,
                    turn_id,
                    *observed_provenance().as_columns(),
                )

            # Purge inline while the append transaction is still open. A normal
            # positive TTL cannot delete the just-inserted rows because their
            # server timestamp is newer than this cutoff; an explicit zero or
            # negative TTL intentionally means "purge through now".
            await _purge_through(conn, time.time() - self._ttl_seconds)

    async def purge_expired(self, ttl_seconds: int | None = None) -> int:
        """Delete messages older than the TTL. Returns the number removed."""
        # `ttl_seconds or self._ttl_seconds` treated an explicit 0 as "not
        # supplied" and fell back to the default TTL, so the one call that means
        # "purge everything" was the one call that purged nothing. Same shape as
        # the `task.user_id and ...` scope bug: a falsy but meaningful value
        # swallowed by `or`.
        ttl = self._ttl_seconds if ttl_seconds is None else ttl_seconds
        # One transaction, because `_purge_through` issues two DELETEs and the
        # state between them is exactly the one the marker must never be left
        # in: messages gone, marker committed, and the next retry of that turn
        # silently suppressed. Without this the two run as separate implicit
        # transactions, so a cancellation or a failure between them commits it
        # (Codex, #327). `append_messages` was already inside one.
        async with self._pool.acquire() as conn, conn.transaction():
            status = await _purge_through(conn, time.time() - ttl)
        # asyncpg returns a command tag such as "DELETE 12".
        try:
            return int(str(status).rsplit(" ", 1)[-1])
        except ValueError:  # pragma: no cover - defensive
            return 0

    async def produced_runs(self, session_id: str) -> list[str]:
        """The canonical Runs that produced this session's turns, oldest first.

        The session-to-Run direction, which until ADR-083026-56ee existed only
        as a coincidence of one call site passing a Run id as an opaque turn
        identity. Distinct, and never blank: a turn appended with no execution
        in scope contributes nothing rather than an empty name.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT run_id FROM session_turns
                   WHERE session_id = $1 AND run_id IS NOT NULL
                   GROUP BY run_id ORDER BY MIN(timestamp)""",
                session_id,
            )
        # `GROUP BY` rather than `DISTINCT ON`, which would have to lead its
        # sort with `run_id` and so could not also promise oldest-first.
        return [r["run_id"] for r in rows]

    async def delete_session(self, session_id: str) -> None:
        """Delete a session without interleaving with an append to that session."""
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(_SESSION_LOCK_SQL, session_id)
            await conn.execute(
                "DELETE FROM sessions WHERE session_id = $1",
                session_id,
            )
            # A session recreated under a reused id must not have its first
            # turn silently swallowed by the deleted one's marker.
            await conn.execute(
                "DELETE FROM session_turns WHERE session_id = $1",
                session_id,
            )

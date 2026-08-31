"""SQLite-backed session store (homelab/single-instance deployments)."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from maistro.observability.correlation import observed_provenance
from maistro.sessions.turns import reject_blank_turn_id

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp REAL NOT NULL,
    PRIMARY KEY (session_id, seq)
)
"""

#: The twin of migration 023's `session_turns` (#327, ADR-083026-5fab). The
#: primary key is the guarantee: at-most-once holds for a writer that reaches
#: this table without the append path's lock.
_TURNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_turns (
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    run_id TEXT,
    node_run_id TEXT,
    attempt_id TEXT,
    PRIMARY KEY (session_id, turn_id)
)
"""

#: Migration 028's columns, for a database file created before it (#748).
#: `CREATE TABLE IF NOT EXISTS` leaves an existing table exactly as it was, so
#: without these an older homelab file would keep a three-column table and every
#: append would fail on the insert -- the failure mode #710 hit on the same
#: shape of change.
_TURN_PROVENANCE_COLUMNS = ("run_id", "node_run_id", "attempt_id")


class SqliteSessionStore:
    """SQLite-backed session store implementing the same protocol as PgSessionStore."""

    def __init__(
        self,
        conn: aiosqlite.Connection,
        max_messages: int = 20,
        ttl_seconds: int = 86400,
    ) -> None:
        self._conn = conn
        self._max_messages = max_messages
        self._ttl_seconds = ttl_seconds
        # One connection, so `BEGIN IMMEDIATE` below is a database-level write
        # lock that two coroutines on this connection would deadlock against
        # rather than queue behind. The asyncio lock is what makes them queue.
        self._write_lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        """Create the sessions table if it doesn't exist."""
        await self._conn.execute(_SCHEMA)
        await self._conn.execute(_TURNS_SCHEMA)
        cursor = await self._conn.execute("PRAGMA table_info(session_turns)")
        existing = {row[1] for row in await cursor.fetchall()}
        for column in _TURN_PROVENANCE_COLUMNS:
            if column not in existing:
                await self._conn.execute(f"ALTER TABLE session_turns ADD COLUMN {column} TEXT")
        # Without this, the TTL purge is a full table scan on every append —
        # which is how a retention sweep turns into a reason to disable the
        # retention sweep.
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_timestamp ON sessions (timestamp)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_turns_timestamp ON session_turns (timestamp)"
        )
        await self._conn.commit()

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

        cursor = await self._conn.execute(
            """SELECT role, content FROM sessions
               WHERE session_id = ? AND timestamp > ?
               ORDER BY seq DESC LIMIT ?""",
            (session_id, cutoff, max_msg),
        )
        rows = list(reversed(list(await cursor.fetchall())))
        return [{"role": r[0], "content": r[1]} for r in rows]

    async def append_messages(
        self,
        session_id: str,
        messages: list[dict[str, str]],
        turn_id: str | None = None,
    ) -> None:
        """Append one complete message batch atomically, at most once.

        The twin of `PgSessionStore.append_messages`, holding the same two
        properties by the means SQLite offers. `BEGIN IMMEDIATE` takes the
        write lock before the sequence read rather than on the first write, so
        the read-then-write is serialized and a failed message rolls back the
        whole batch instead of leaving a prefix committed. `turn_id` has
        exactly the meaning it has there (ADR-083026-5fab).
        """
        reject_blank_turn_id(turn_id)
        async with self._write_lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                if turn_id is not None:
                    cursor = await self._conn.execute(
                        "SELECT 1 FROM session_turns WHERE session_id = ? AND turn_id = ?",
                        (session_id, turn_id),
                    )
                    if await cursor.fetchone() is not None:
                        await self._conn.rollback()
                        return

                cursor = await self._conn.execute(
                    "SELECT COALESCE(MAX(seq), -1) + 1 FROM sessions WHERE session_id = ?",
                    (session_id,),
                )
                row = await cursor.fetchone()
                next_seq: int = row[0] if row else 0

                now = time.time()
                for msg in messages:
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if role in ("user", "assistant"):
                        await self._conn.execute(
                            """INSERT INTO sessions (session_id, seq, role, content, timestamp)
                               VALUES (?, ?, ?, ?, ?)""",
                            (session_id, next_seq, role, content, now),
                        )
                        next_seq += 1

                if turn_id is not None:
                    # The execution that produced the turn, resolved from the
                    # ambient context and recorded beside the opaque identity
                    # rather than read out of it (ADR-083026-56ee).
                    await self._conn.execute(
                        "INSERT INTO session_turns "
                        "(session_id, turn_id, timestamp, run_id, node_run_id, attempt_id) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (session_id, turn_id, now, *observed_provenance().as_columns()),
                    )
            except BaseException:
                await self._conn.rollback()
                raise
            await self._conn.commit()

        # Purge as part of normal operation rather than relying on a scheduled
        # sweeper — there isn't one, which is exactly why the TTL never deleted
        # anything. This mirrors security/pg_strikes.py, which clears its
        # expired windows inline on every check.
        await self.purge_expired()

    async def produced_runs(self, session_id: str) -> list[str]:
        """The canonical Runs that produced this session's turns, oldest first.

        The session-to-Run direction, which until ADR-083026-56ee existed only
        as a coincidence of one call site passing a Run id as an opaque turn
        identity. Distinct, and never blank: a turn appended with no execution
        in scope contributes nothing rather than an empty name.
        """
        cursor = await self._conn.execute(
            "SELECT run_id FROM session_turns "
            "WHERE session_id = ? AND run_id IS NOT NULL "
            "GROUP BY run_id ORDER BY MIN(timestamp)",
            (session_id,),
        )
        return [str(row[0]) for row in await cursor.fetchall()]

    async def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        await self._conn.execute(
            "DELETE FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        # A session recreated under a reused id must not have its first turn
        # silently swallowed by the deleted one's marker.
        await self._conn.execute(
            "DELETE FROM session_turns WHERE session_id = ?",
            (session_id,),
        )
        await self._conn.commit()

    async def purge_expired(self, ttl_seconds: int | None = None) -> int:
        """Delete messages older than the TTL. Returns the number removed.

        TTL was enforced only as a read-time filter (`timestamp > ?` in
        `get_history`), so expired conversation content was hidden but never
        removed — the table grew without bound and retained user messages
        indefinitely, which is a data-retention problem rather than a
        performance one. The only DELETE was session-id-scoped and called by
        nothing scheduled.

        `security/pg_strikes.py` already had the right shape for this: delete
        the expired window as part of normal operation rather than relying on
        an external sweeper that does not exist.
        """
        # `ttl_seconds or self._ttl_seconds` treated an explicit 0 as "not
        # supplied" and fell back to the default TTL, so the one call that means
        # "purge everything" was the one call that purged nothing. Same shape as
        # the `task.user_id and ...` scope bug: a falsy but meaningful value
        # swallowed by `or`.
        ttl = self._ttl_seconds if ttl_seconds is None else ttl_seconds
        cutoff = time.time() - ttl
        cursor = await self._conn.execute(
            "DELETE FROM sessions WHERE timestamp <= ?",
            (cutoff,),
        )
        # Both, always: a marker outliving its messages would suppress a retry
        # of a turn that no longer exists, and messages outliving their marker
        # would let one duplicate. The count stays the message count, because
        # that is how much conversation was removed.
        await self._conn.execute(
            "DELETE FROM session_turns WHERE timestamp <= ?",
            (cutoff,),
        )
        await self._conn.commit()
        return cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0

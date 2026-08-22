"""SQLite-backed session store (homelab/single-instance deployments)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

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

    async def ensure_schema(self) -> None:
        """Create the sessions table if it doesn't exist."""
        await self._conn.execute(_SCHEMA)
        # Without this, the TTL purge is a full table scan on every append —
        # which is how a retention sweep turns into a reason to disable the
        # retention sweep.
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_timestamp ON sessions (timestamp)"
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
    ) -> None:
        """Append messages to session history."""
        cursor = await self._conn.execute(
            "SELECT COALESCE(MAX(seq), -1) + 1 FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        next_seq: int = row[0] if row else 0

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant"):
                await self._conn.execute(
                    """INSERT INTO sessions (session_id, seq, role, content, timestamp)
                       VALUES (?, ?, ?, ?, ?)""",
                    (session_id, next_seq, role, content, time.time()),
                )
                next_seq += 1
        await self._conn.commit()

        # Purge as part of normal operation rather than relying on a scheduled
        # sweeper — there isn't one, which is exactly why the TTL never deleted
        # anything. This mirrors security/pg_strikes.py, which clears its
        # expired windows inline on every check.
        await self.purge_expired()

    async def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        await self._conn.execute(
            "DELETE FROM sessions WHERE session_id = ?",
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
        await self._conn.commit()
        return cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0

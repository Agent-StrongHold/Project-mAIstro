"""PostgreSQL session store."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg


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
    ) -> None:
        """Append messages to session history."""
        async with self._pool.acquire() as conn:
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

            # Purge inline. TTL was a read-time filter only
            # (`timestamp > to_timestamp($2)` in get_history), so expired
            # conversation content was hidden but never deleted — unbounded
            # growth and indefinite retention of user messages. There is no
            # scheduled sweeper to defer this to, which is precisely why
            # nothing was ever removed. Same shape as
            # security/pg_strikes.py:187-190, which clears its expired windows
            # as part of the normal path.
            await conn.execute(
                "DELETE FROM sessions WHERE timestamp <= to_timestamp($1)",
                time.time() - self._ttl_seconds,
            )

    async def purge_expired(self, ttl_seconds: int | None = None) -> int:
        """Delete messages older than the TTL. Returns the number removed."""
        # `ttl_seconds or self._ttl_seconds` treated an explicit 0 as "not
        # supplied" and fell back to the default TTL, so the one call that means
        # "purge everything" was the one call that purged nothing. Same shape as
        # the `task.user_id and ...` scope bug: a falsy but meaningful value
        # swallowed by `or`.
        ttl = self._ttl_seconds if ttl_seconds is None else ttl_seconds
        async with self._pool.acquire() as conn:
            status = await conn.execute(
                "DELETE FROM sessions WHERE timestamp <= to_timestamp($1)",
                time.time() - ttl,
            )
        # asyncpg returns a command tag such as "DELETE 12".
        try:
            return int(str(status).rsplit(" ", 1)[-1])
        except ValueError:  # pragma: no cover - defensive
            return 0

    async def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM sessions WHERE session_id = $1",
                session_id,
            )

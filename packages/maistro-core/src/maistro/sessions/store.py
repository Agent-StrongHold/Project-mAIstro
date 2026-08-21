"""Session store: in-memory conversation history with TTL pruning."""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from maistro.types.session import SessionConfig

logger = logging.getLogger("maistro.sessions.store")


class InMemorySessionStore:
    """In-memory session store for testing and local dev."""

    def __init__(self, config: SessionConfig | None = None) -> None:
        self._config = config or SessionConfig()
        self._sessions: dict[str, list[tuple[int, str, str, float]]] = defaultdict(list)
        self._next_seq: dict[str, int] = defaultdict(int)

    async def get_history(
        self,
        session_id: str,
        max_messages: int | None = None,
        ttl_seconds: int | None = None,
    ) -> list[dict[str, str]]:
        """Retrieve conversation history, pruning expired messages."""
        max_msgs = max_messages or self._config.max_messages
        ttl = ttl_seconds or self._config.ttl_seconds
        cutoff = time.time() - ttl

        entries = self._sessions.get(session_id, [])
        valid = [(seq, role, content, ts) for seq, role, content, ts in entries if ts >= cutoff]
        valid.sort(key=lambda x: x[0])
        valid = valid[-max_msgs:]

        return [{"role": role, "content": content} for _, role, content, _ in valid]

    async def append_messages(
        self,
        session_id: str,
        messages: list[dict[str, str]],
    ) -> None:
        """Append messages to session history."""
        now = time.time()
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role not in ("user", "assistant"):
                continue
            if not isinstance(content, str):
                continue
            seq = self._next_seq[session_id]
            self._next_seq[session_id] = seq + 1
            self._sessions[session_id].append((seq, role, content, now))

        ttl = self._config.ttl_seconds
        cutoff = now - ttl
        entries = self._sessions[session_id]
        self._sessions[session_id] = [e for e in entries if e[3] >= cutoff]

    async def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        self._sessions.pop(session_id, None)
        self._next_seq.pop(session_id, None)

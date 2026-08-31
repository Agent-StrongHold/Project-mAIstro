"""Session store: in-memory conversation history with TTL pruning."""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from maistro.observability.correlation import ExecutionProvenance, observed_provenance
from maistro.sessions.turns import reject_blank_turn_id
from maistro.types.session import SessionConfig

logger = logging.getLogger("maistro.sessions.store")


class InMemorySessionStore:
    """In-memory session store for testing and local dev."""

    def __init__(self, config: SessionConfig | None = None) -> None:
        self._config = config or SessionConfig()
        self._sessions: dict[str, list[tuple[int, str, str, float]]] = defaultdict(list)
        self._next_seq: dict[str, int] = defaultdict(int)
        # The in-memory twin of `session_turns` (ADR-083026-5fab): the identity
        # mapped to when it was recorded, so the TTL sweep can expire a marker
        # with the messages it admitted rather than outliving them, and to the
        # Run that produced it (ADR-083026-56ee). One dict rather than two: a
        # parallel map is a map the sweep can forget to purge.
        self._turns: dict[tuple[str, str], tuple[float, ExecutionProvenance]] = {}

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
        turn_id: str | None = None,
    ) -> None:
        """Append messages to session history, at most once per turn identity.

        `turn_id` has the meaning the durable stores give it
        (ADR-083026-5fab). Held here too rather than ignored: a test double
        that cannot reproduce a retry is a test double that hides one. The
        producing execution (ADR-083026-56ee) is recorded for the same reason.
        """
        reject_blank_turn_id(turn_id)
        now = time.time()
        if turn_id is not None:
            if (session_id, turn_id) in self._turns:
                return
            self._turns[(session_id, turn_id)] = (now, observed_provenance())
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
        self._turns = {
            key: recorded for key, recorded in self._turns.items() if recorded[0] >= cutoff
        }

    async def purge_expired(self, ttl_seconds: int | None = None) -> int:
        """Delete messages older than the TTL. Returns the number removed.

        Both durable stores have carried this since #182; the twin did not, so
        its retention could only ever be applied to the one session an append
        touched. A twin that cannot be swept is a twin no test can hold to
        SPEC-083026-5fab's AC-5 — that a turn marker does not outlive the
        messages it admitted.

        `ttl_seconds or self._config.ttl_seconds` would swallow an explicit 0,
        the one value that means "purge through now"; the durable twins carry
        the same note over the same mistake.
        """
        ttl = self._config.ttl_seconds if ttl_seconds is None else ttl_seconds
        cutoff = time.time() - ttl
        removed = 0
        for session_id, entries in list(self._sessions.items()):
            kept = [entry for entry in entries if entry[3] > cutoff]
            removed += len(entries) - len(kept)
            self._sessions[session_id] = kept
        self._turns = {
            key: recorded for key, recorded in self._turns.items() if recorded[0] > cutoff
        }
        return removed

    async def produced_runs(self, session_id: str) -> list[str]:
        """The canonical Runs that produced this session's turns, oldest first.

        The session-to-Run direction, which until ADR-083026-56ee existed only
        as a coincidence of one call site passing a Run id as an opaque turn
        identity. Distinct, and never blank: a turn appended with no execution
        in scope contributes nothing rather than an empty name.
        """
        seen: dict[str, None] = {}
        for (turn_session, _), (_, produced_by) in sorted(
            self._turns.items(), key=lambda item: item[1][0]
        ):
            if turn_session == session_id and produced_by.run_id:
                seen[produced_by.run_id] = None
        return list(seen)

    def turn_provenance(self, session_id: str, turn_id: str) -> ExecutionProvenance | None:
        """The execution recorded for one turn, or None if no such turn.

        Only on the twin. The durable stores answer this with a `SELECT` the
        conformance tests issue directly against the row; the twin has no row
        to select, and a test that could read the marker on two backends out of
        three would be a test that proves the twin holds the fact only where it
        is easiest to hold.
        """
        recorded = self._turns.get((session_id, turn_id))
        return None if recorded is None else recorded[1]

    async def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        self._sessions.pop(session_id, None)
        self._next_seq.pop(session_id, None)
        # A session recreated under a reused id must not have its first turn
        # silently swallowed by the deleted one's marker.
        self._turns = {
            key: recorded for key, recorded in self._turns.items() if key[0] != session_id
        }

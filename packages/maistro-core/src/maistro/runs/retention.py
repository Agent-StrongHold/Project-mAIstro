"""Bounding the spine's growth from high-volume entry points (ADR-082226-c126).

`POST /tasks` produces a Run per submission, which is a rate a human sets. Chat
produces a Run per turn, which is a rate a conversation sets — orders of
magnitude higher, and unbounded in a way the spine has never had to carry.

The policy is deliberately not in the store. A store-side rule would have to
reach into `provenance['admission_source']` and hard-code which classes of work
it may delete, and every entry point added later would silently inherit whichever
branch it happened to fall into. Instead the admitting seam — which is the only
layer that knows what kind of work it just admitted — stamps a deadline onto the
Run, and the store enforces nothing more specific than "delete expired terminal
Runs".

The sweep rides on admission rather than a scheduled process, because this
repository has no scheduled process to ride on. Two subsystems learned that the
hard way: `maistro.security.pg_strikes` clears its expired windows on every
check, and `SqliteSessionStore.purge_expired` exists because a read-time TTL
filter hid expired content for months without ever deleting it. A retention
policy that depends on a cron job nobody has written is not a retention policy.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from maistro.runs.store import DEFAULT_PURGE_BATCH

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.runs.store import RunStore

#: Default lifetime of a chat-originated Run. Long enough that "what happened in
#: my conversation yesterday?" is answerable, short enough that a busy
#: deployment's spine reaches a steady state instead of a ceiling.
DEFAULT_CHAT_RETENTION_SECONDS = 7 * 24 * 60 * 60

#: How often a sweeper riding on admission will actually sweep. Retention lag is
#: measured in days; sweeping more often than this spends database round-trips
#: to shave minutes off a deadline nobody is watching that closely.
DEFAULT_SWEEP_INTERVAL_SECONDS = 300.0


@dataclass(frozen=True)
class RetentionPolicy:
    """How long one class of admitted work is retained, and how it is swept."""

    #: Lifetime in seconds, or None to retain indefinitely — which is what every
    #: Run outside this policy already does, so `None` is the setting that opts
    #: a deployment back out to today's behavior.
    ttl_seconds: int | None = DEFAULT_CHAT_RETENTION_SECONDS
    sweep_interval_seconds: float = DEFAULT_SWEEP_INTERVAL_SECONDS
    batch_limit: int = DEFAULT_PURGE_BATCH

    def __post_init__(self) -> None:
        if self.ttl_seconds is not None and self.ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive, or None to retain indefinitely")
        if self.sweep_interval_seconds < 0:
            raise ValueError("sweep_interval_seconds cannot be negative")
        if self.batch_limit <= 0:
            raise ValueError("batch_limit must be positive")

    @property
    def bounded(self) -> bool:
        """Whether this policy actually bounds anything."""
        return self.ttl_seconds is not None

    def deadline(self, *, now: datetime | None = None) -> datetime | None:
        """The `retention_expires_at` a Run admitted under this policy carries."""
        if self.ttl_seconds is None:
            return None
        return (now if now is not None else datetime.now(UTC)) + timedelta(seconds=self.ttl_seconds)


#: Retain everything, sweep nothing. What a deployment gets by opting out.
UNBOUNDED_RETENTION = RetentionPolicy(ttl_seconds=None)


class RunRetentionSweeper:
    """Drives `RunStore.purge_expired_runs` opportunistically, at most one at a time.

    Two properties matter more than the throttle:

    - **It never blocks the admission it rides on.** A sweep already in flight
      means this caller returns immediately rather than queuing behind it, so a
      burst of concurrent chat turns produces one sweep, not a queue of them.
    - **It never fails the admission it rides on.** Retention is housekeeping; a
      database hiccup during a sweep must not turn into a user's chat turn being
      refused. Failures are reported through `last_error` for a caller that
      wants to log them, and swallowed otherwise.
    """

    def __init__(self, store: RunStore, policy: RetentionPolicy | None = None) -> None:
        self._store = store
        self._policy = policy if policy is not None else RetentionPolicy()
        self._lock = asyncio.Lock()
        self._last_sweep: float | None = None
        self.last_error: BaseException | None = None

    @property
    def policy(self) -> RetentionPolicy:
        return self._policy

    def _due(self) -> bool:
        if not self._policy.bounded:
            return False
        if self._last_sweep is None:
            return True
        return (time.monotonic() - self._last_sweep) >= self._policy.sweep_interval_seconds

    async def maybe_sweep(self, *, now: datetime | None = None) -> int:
        """Sweep if one is due and none is running. Returns Runs purged, or 0."""
        if not self._due() or self._lock.locked():
            return 0
        async with self._lock:
            # Re-checked under the lock: two coroutines can both pass the
            # unlocked check above, and without this the second would sweep
            # again the instant the first finished.
            if not self._due():
                return 0
            self._last_sweep = time.monotonic()
            try:
                purged = await self._store.purge_expired_runs(
                    now=now, limit=self._policy.batch_limit
                )
            except Exception as exc:
                self.last_error = exc
                return 0
            self.last_error = None
            return purged

    async def sweep_now(self, *, now: datetime | None = None) -> int:
        """Sweep unconditionally, ignoring the interval. Errors propagate."""
        if not self._policy.bounded:
            return 0
        async with self._lock:
            self._last_sweep = time.monotonic()
            return await self._store.purge_expired_runs(now=now, limit=self._policy.batch_limit)


__all__ = [
    "DEFAULT_CHAT_RETENTION_SECONDS",
    "DEFAULT_SWEEP_INTERVAL_SECONDS",
    "UNBOUNDED_RETENTION",
    "RetentionPolicy",
    "RunRetentionSweeper",
]

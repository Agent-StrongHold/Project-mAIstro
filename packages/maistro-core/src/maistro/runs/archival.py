"""Driving the archive sweep, and the clock it rides on (#273, ADR-082226-f436).

Separate from `retention.py` on purpose. The two modules look alike — a policy,
a throttle, a sweep that rides on admission — and collapsing them is exactly the
mistake decision 2 forbids: *"A record whose identity nothing needs either is
not archived — it is deleted, by whatever policy governs deletion. Archiving is
not a way to avoid deciding that."* One module deletes records somebody chose a
deletion date for; this one moves the payload of records nobody did. Decision 10
makes the two populations disjoint by predicate (`retention_expires_at` not-null
selects the first, null the second), and keeping them in separate files is what
stops a later edit from quietly hooking one into the other.

**Admission is the clock, not a claim about the admitted Run.** `retention.py`
explains why the sweep rides on admission rather than a scheduled process: this
repository has no scheduled process to ride on, and "a retention policy that
depends on a cron job nobody has written is not a retention policy". The same
holds here, with one asymmetry worth stating outright — a chat Run carries a
retention deadline, so a chat turn's own Run is precisely the kind that is
*never* archived. The admission event is being used only as a tick. What the
sweep then scans is the whole store.

**Off unless a deployment says otherwise** (decision 9). `ArchivePolicy` defaults
`archive_after` to `None`, so wiring this in changes nothing until an operator
picks a horizon. That is deliberate rather than cautious: a deployment that
configures an archive URL for some other purpose must not discover that its Run
spine started emptying itself into a bucket.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from maistro.runs.store import DEFAULT_ARCHIVE_AFTER, DEFAULT_PURGE_BATCH

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.runs.store import RunStore

logger = logging.getLogger(__name__)

#: How often a sweeper riding on admission will actually sweep. An order of
#: magnitude slower than retention's five minutes, because the horizon is
#: measured in months rather than days: sweeping hourly puts a Run in the
#: archive within an hour of becoming eligible, which is punctual to the point
#: of absurdity against a 90-day deadline and still cheap.
DEFAULT_ARCHIVE_SWEEP_INTERVAL_SECONDS = 3600.0


@runtime_checkable
class ColdRunArchiver(Protocol):
    """A store that can move cold Run payloads to the archive tier.

    A *capability* protocol rather than a method on `RunStore`, because the
    tier is optional by design (decision 9) and a store that cannot archive is
    still a complete system of record. Bolting this onto `RunStore` would say
    the opposite — that every backend owes an implementation — and the first
    consequence would be a stub somewhere returning 0 while claiming to be an
    archive tier.

    `runtime_checkable` buys exactly one thing here: `isinstance` reports
    whether a store has the method, which is what lets the sweeper be
    constructed against any `RunStore` and stay inert on one that cannot.
    """

    async def archive_cold_runs(
        self,
        *,
        now: datetime | None = None,
        archive_after: timedelta = DEFAULT_ARCHIVE_AFTER,
        limit: int = DEFAULT_PURGE_BATCH,
    ) -> int: ...


@dataclass(frozen=True)
class ArchivePolicy:
    """How cold a Run must be before its payload moves, and how it is swept."""

    #: How long after a Run finished its payload may be archived, or None to
    #: archive nothing — which is what every deployment does today, so `None`
    #: is the setting that preserves current behavior rather than the one that
    #: opts out of it.
    archive_after: timedelta | None = None
    sweep_interval_seconds: float = DEFAULT_ARCHIVE_SWEEP_INTERVAL_SECONDS
    batch_limit: int = DEFAULT_PURGE_BATCH

    def __post_init__(self) -> None:
        if self.archive_after is not None and self.archive_after <= timedelta(0):
            raise ValueError("archive_after must be positive, or None to archive nothing")
        if self.sweep_interval_seconds < 0:
            raise ValueError("sweep_interval_seconds cannot be negative")
        if self.batch_limit <= 0:
            raise ValueError("batch_limit must be positive")

    @property
    def enabled(self) -> bool:
        """Whether this policy actually archives anything."""
        return self.archive_after is not None


#: Archive nothing. What a deployment gets until it names a horizon.
ARCHIVE_DISABLED = ArchivePolicy()


class RunArchiveSweeper:
    """Drives `ColdRunArchiver.archive_cold_runs` opportunistically, one at a time.

    Three properties, and the third is the one that makes it safe to call from
    a request path:

    - **It never blocks the admission it rides on.** A sweep already in flight
      means this caller returns immediately rather than queuing behind it.
    - **It never fails the admission it rides on.** Moving cold bytes is
      housekeeping; an unreachable bucket must not turn into a user's chat turn
      being refused. Failures are logged and swallowed.
    - **It is inert on a store that cannot archive.** The capability check
      happens once, in the constructor, so callers wire the sweeper
      unconditionally and the SQLite twin — which has no archive columns — is
      not a special case at every call site.
    """

    def __init__(self, store: RunStore, policy: ArchivePolicy | None = None) -> None:
        self._archiver: ColdRunArchiver | None = (
            store if isinstance(store, ColdRunArchiver) else None
        )
        self._policy = policy if policy is not None else ARCHIVE_DISABLED
        self._lock = asyncio.Lock()
        self._last_sweep: float | None = None

    @property
    def policy(self) -> ArchivePolicy:
        return self._policy

    def _due(self) -> bool:
        if self._archiver is None or not self._policy.enabled:
            return False
        if self._last_sweep is None:
            return True
        return (time.monotonic() - self._last_sweep) >= self._policy.sweep_interval_seconds

    async def maybe_sweep(self, *, now: datetime | None = None) -> int:
        """Sweep if one is due and none is running. Returns Runs archived, or 0."""
        if not self._due() or self._lock.locked():
            return 0
        async with self._lock:
            # Re-checked under the lock: two coroutines can both pass the
            # unlocked check above, and without this the second would sweep
            # again the instant the first finished.
            if not self._due():
                return 0
            self._last_sweep = time.monotonic()
            archiver = self._archiver
            horizon = self._policy.archive_after
            # Both are non-None whenever `_due()` is true; naming them satisfies
            # the type checker without a cast that would outlive the reason.
            if archiver is None or horizon is None:  # pragma: no cover - _due covers it
                return 0
            try:
                return await archiver.archive_cold_runs(
                    now=now if now is not None else datetime.now(UTC),
                    archive_after=horizon,
                    limit=self._policy.batch_limit,
                )
            except Exception:
                logger.warning("archive sweep failed; Runs stay resident", exc_info=True)
                return 0


__all__ = [
    "ARCHIVE_DISABLED",
    "DEFAULT_ARCHIVE_SWEEP_INTERVAL_SECONDS",
    "ArchivePolicy",
    "ColdRunArchiver",
    "RunArchiveSweeper",
]

"""Unit coverage for ``PgCanvasStore``'s job-lease edge branches.

``claim_next_pending`` and ``reap_expired_leases`` each guard a state a
correctly-behaving PostgreSQL server rarely (or, for the vanished-row case,
never under this code's own locking) produces on the happy path: an empty
pending queue, an empty expired-lease set, a non-positive lease duration, and
a claimed row that has disappeared by the time its details are re-fetched.
Per the package's own guidance (``packages/maistro-canvas/CLAUDE.md``:
"tests assume mocked/in-memory stores" for this async PostgreSQL-backed
store), these fake the ``AsyncSession`` the store opens rather than standing
up a real server, so each branch is reachable deterministically instead of
depending on races or DB unavailability.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro_canvas.canvas.store import PgCanvasStore
from maistro_canvas.types import JobNotFoundError

pytestmark = pytest.mark.asyncio


class _FakeAsyncSession:
    """Stands in for ``sqlalchemy.ext.asyncio.AsyncSession`` as an async
    context manager, replaying canned ``execute`` results in order so a
    specific statement in a multi-statement method can be made to return
    whatever the branch under test needs."""

    def __init__(self, results: list[Any]) -> None:
        self._results = iter(results)
        self.committed = False

    async def __aenter__(self) -> _FakeAsyncSession:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        return next(self._results)

    async def commit(self) -> None:
        self.committed = True


class _FirstResult:
    """A result whose only relevant method is ``.first()`` (the claim
    UPDATE...RETURNING and the reap-set-iteration query never go through
    ``.mappings()``)."""

    def __init__(self, row: Any) -> None:
        self._row = row

    def first(self) -> Any:
        return self._row


class _MappingResult:
    """A result whose caller goes through ``.mappings().first()``, as the
    job-detail SELECT in ``claim_next_pending`` does."""

    def __init__(self, row: Any) -> None:
        self._row = row

    def mappings(self) -> _MappingResult:
        return self

    def first(self) -> Any:
        return self._row


class _EmptyIterableResult:
    """A result that is directly iterated for rows, as the reap UPDATE's
    ``RETURNING`` set is in ``reap_expired_leases``."""

    def __iter__(self) -> Any:
        return iter(())


def _patch_session(monkeypatch: pytest.MonkeyPatch, results: list[Any]) -> _FakeAsyncSession:
    session = _FakeAsyncSession(results)
    monkeypatch.setattr(
        "maistro_canvas.canvas.store.AsyncSession",
        lambda _engine: session,
    )
    return session


# ─────────────────────────────────────────────────────────────────────
# claim_next_pending
# ─────────────────────────────────────────────────────────────────────


async def test_claim_next_pending_rejects_nonpositive_lease_seconds() -> None:
    """A zero or negative lease would never expire (or would already be
    expired), so the store refuses it before ever touching the database —
    no session is opened at all."""
    store = PgCanvasStore(engine=None)
    with pytest.raises(ValueError, match="lease_seconds must be positive"):
        await store.claim_next_pending("worker-1", 0)
    with pytest.raises(ValueError, match="lease_seconds must be positive"):
        await store.claim_next_pending("worker-1", -30)


async def test_claim_next_pending_returns_none_when_queue_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No pending job to claim: the atomic UPDATE...RETURNING finds nothing,
    and the store reports that as ``None`` rather than fabricating a job or
    running the second (detail) query at all."""
    session = _patch_session(monkeypatch, [_FirstResult(None)])
    store = PgCanvasStore(engine=object())

    claimed = await store.claim_next_pending("worker-1", 30)

    assert claimed is None
    # Nothing was claimed, so the method returns before its commit — the
    # transaction has nothing to persist.
    assert session.committed is False


async def test_claim_next_pending_raises_when_claimed_job_vanishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The claim UPDATE reports a row id, but the immediate detail SELECT
    for that same id comes back empty. The store treats this as the
    invariant violation it is (its own uncommitted claim should still hold
    the row lock) and raises ``JobNotFoundError`` rather than returning a
    job it cannot actually describe."""
    _patch_session(
        monkeypatch,
        [_FirstResult(("job-ghost",)), _MappingResult(None)],
    )
    store = PgCanvasStore(engine=object())

    with pytest.raises(JobNotFoundError):
        await store.claim_next_pending("worker-1", 30)


# ─────────────────────────────────────────────────────────────────────
# reap_expired_leases
# ─────────────────────────────────────────────────────────────────────


async def test_reap_expired_leases_returns_empty_list_when_none_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No running job has an expired lease: the reap UPDATE's RETURNING set
    is empty, so the store commits (there is nothing to roll back) and
    reports an empty list without issuing the second (detail-fetch) query."""
    session = _patch_session(monkeypatch, [_EmptyIterableResult()])
    store = PgCanvasStore(engine=object())

    reaped = await store.reap_expired_leases()

    assert reaped == []
    assert session.committed is True

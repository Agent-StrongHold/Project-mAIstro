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
from maistro_canvas.types import GenerationJobRecord, JobLeaseLostError, JobNotFoundError

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
    """A result that is directly iterated for rows, as each reap UPDATE's
    ``RETURNING`` set is in ``reap_expired_leases``."""

    def __iter__(self) -> Any:
        return iter(())


class _IterableResult:
    """A result directly iterated for ``(id,)`` rows, as a reap UPDATE's
    non-empty ``RETURNING`` set is."""

    def __init__(self, ids: list[str]) -> None:
        self._ids = ids

    def __iter__(self) -> Any:
        return iter((job_id,) for job_id in self._ids)


class _AllMappingResult:
    """A result whose caller goes through ``.mappings().all()``, as the
    reap detail SELECT does."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _AllMappingResult:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _RowCountResult:
    """A result whose only relevant attribute is ``.rowcount``, as the
    ``update_job``/``renew_lease`` UPDATEs are read through."""

    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


def _job(**overrides: Any) -> GenerationJobRecord:
    defaults: dict[str, Any] = {
        "id": "job1",
        "layer_id": "l1",
        "canvas_id": "c1",
        "action": "generate",
        "status": "running",
        "model_id": "draft-model",
        "prompt": "a castle",
        "params": {},
        "attempts": 1,
        "max_attempts": 3,
        "leased_by": "worker-1",
        "lease_expires_at": None,
    }
    defaults.update(overrides)
    return GenerationJobRecord(**defaults)


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
    """No running job has an expired lease: both the requeue and the
    exhausted-clear UPDATEs' RETURNING sets are empty, so the store commits
    (there is nothing to roll back) and reports an empty list without
    issuing the third (detail-fetch) query."""
    session = _patch_session(monkeypatch, [_EmptyIterableResult(), _EmptyIterableResult()])
    store = PgCanvasStore(engine=object())

    reaped = await store.reap_expired_leases()

    assert reaped == []
    assert session.committed is True


async def test_reap_expired_leases_requeues_budget_and_leaves_exhausted_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A candidate with retry budget left comes back requeued (``pending``);
    a candidate at its retry ceiling comes back with its lease holder
    cleared but ``status`` still ``running`` — it is deliberately *not*
    terminalized here (Codex #1527 finding: only the caller, after canonical
    reconciliation succeeds, may make it ``failed``)."""
    session = _patch_session(
        monkeypatch,
        [
            _IterableResult(["job-requeued"]),
            _IterableResult(["job-exhausted"]),
            _AllMappingResult(
                [
                    {
                        "id": "job-requeued",
                        "layer_id": "l1",
                        "canvas_id": "c1",
                        "status": "pending",
                        "attempts": 1,
                        "max_attempts": 3,
                        "leased_by": None,
                    },
                    {
                        "id": "job-exhausted",
                        "layer_id": "l1",
                        "canvas_id": "c1",
                        "status": "running",
                        "attempts": 3,
                        "max_attempts": 3,
                        "leased_by": None,
                    },
                ]
            ),
        ],
    )
    store = PgCanvasStore(engine=object())

    reaped = await store.reap_expired_leases()

    assert session.committed is True
    by_id = {job.id: job for job in reaped}
    assert by_id["job-requeued"].status == "pending"
    assert by_id["job-exhausted"].status == "running"
    assert by_id["job-exhausted"].leased_by is None


# ─────────────────────────────────────────────────────────────────────
# update_job — worker-owned completion fencing
# ─────────────────────────────────────────────────────────────────────


async def test_update_job_without_fencing_succeeds_unconditionally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pre-existing call shape (no ``expected_leased_by``) is unchanged:
    a matched row commits and the fencing follow-up query never runs."""
    session = _patch_session(monkeypatch, [_RowCountResult(1)])
    store = PgCanvasStore(engine=object())

    result = await store.update_job(_job(), org_id="org-1")

    assert result.id == "job1"
    assert session.committed is True


async def test_update_job_fencing_raises_lease_lost_when_reclaimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another worker reclaimed the lease before this worker's own
    completion write landed: the fenced UPDATE matches zero rows, the
    follow-up existence check finds the row still present (just held by
    someone else now), and the store refuses with ``JobLeaseLostError``
    instead of silently clobbering the new holder's state."""
    session = _patch_session(
        monkeypatch,
        [_RowCountResult(0), _FirstResult((1,))],
    )
    store = PgCanvasStore(engine=object())

    with pytest.raises(JobLeaseLostError):
        await store.update_job(_job(), org_id="org-1", expected_leased_by="stale-worker")

    # The raise happens before commit — no partial write is persisted.
    assert session.committed is False


async def test_update_job_fencing_raises_not_found_when_job_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fenced write on a job that no longer exists at all (not merely
    reclaimed) still raises the pre-existing ``JobNotFoundError``, not
    ``JobLeaseLostError`` — the existence check distinguishes the two."""
    session = _patch_session(
        monkeypatch,
        [_RowCountResult(0), _FirstResult(None)],
    )
    store = PgCanvasStore(engine=object())

    with pytest.raises(JobNotFoundError):
        await store.update_job(_job(), org_id="org-1", expected_leased_by="stale-worker")

    assert session.committed is False


# ─────────────────────────────────────────────────────────────────────
# renew_lease
# ─────────────────────────────────────────────────────────────────────


async def test_renew_lease_rejects_nonpositive_lease_seconds() -> None:
    store = PgCanvasStore(engine=None)
    with pytest.raises(ValueError, match="lease_seconds must be positive"):
        await store.renew_lease("job1", "worker-1", 0)


async def test_renew_lease_returns_true_when_still_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _patch_session(monkeypatch, [_RowCountResult(1)])
    store = PgCanvasStore(engine=object())

    renewed = await store.renew_lease("job1", "worker-1", 300)

    assert renewed is True
    assert session.committed is True


async def test_renew_lease_returns_false_when_lease_no_longer_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lease was already reaped out from under this caller (expired and
    reclaimed, or requeued): the fenced UPDATE matches nothing, and the
    store reports that as a no-op ``False`` rather than an error — the
    caller's heartbeat has simply lost the race and should stop."""
    session = _patch_session(monkeypatch, [_RowCountResult(0)])
    store = PgCanvasStore(engine=object())

    renewed = await store.renew_lease("job1", "worker-1", 300)

    assert renewed is False
    assert session.committed is True

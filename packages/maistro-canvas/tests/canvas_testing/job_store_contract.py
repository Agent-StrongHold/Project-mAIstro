"""The one Canvas job-store contract (#398), run against every store leg.

``CanvasJobStore`` (``maistro_canvas.protocols``) is the typed protocol; this
module is its behavioral half. The same body functions run against:

- ``InMemoryJobStore`` — the runner-focused fake, mirroring ``PgCanvasStore``'s
  claim/renew/reap semantics in memory (always runs);
- ``PgCanvasStore`` against a real PostgreSQL server in a throwaway schema
  (skips without ``MAISTRO_TEST_PG_DSN``; ``MAISTRO_REQUIRE_PG_LEGS`` turns the
  skip into a failure), the same contract as the scope-conformance suite.

Running the identical bodies against both legs is the drift guard the issue
asks for: a fake that grows a behavior the production store lacks (or vice
versa) fails the leg that did not move. The fake below must therefore mirror
production semantics exactly — claim charges an attempt and refuses rows
waiting out ``next_retry_at``, the reaper writes the shared backoff schedule,
and every read hands back an independent copy.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from maistro_canvas.canvas.retry_policy import DEFAULT_RETRY_BACKOFF, RetryBackoff
from maistro_canvas.protocols import CanvasJobStore
from maistro_canvas.types import (
    CanvasRecord,
    GenerationJobRecord,
    JobQueueStats,
    JobStatus,
    LayerRecord,
)

#: A schedule whose delays are zero: requeues are reclaimable immediately.
#: Runner-lifecycle tests use it to keep their tick timing deterministic; the
#: backoff semantics themselves are asserted with a real schedule in the
#: contract bodies.
ZERO_BACKOFF = RetryBackoff(base_seconds=0.0, factor=1.0, cap_seconds=0.0)


class InMemoryJobStore:
    """In-memory job store reproducing the real claim/reap/stats semantics.

    Every method that hands a job to a caller returns an independent
    ``dataclasses.replace`` copy, never the internally-held row itself —
    mirroring ``PgCanvasStore``, where each query builds a fresh
    ``GenerationJobRecord`` from a DB row via ``_coerce_job``. A caller's
    in-memory mutations (e.g. the runner setting ``job.status = DONE`` while
    a provider call runs) must NOT silently leak into this store's
    'true' row until an explicit ``update_job``/``renew_lease`` write —
    sharing the object instead would hide exactly the stale-write races
    (Codex #1527) these tests exist to catch.

    ``retry_backoff`` defaults to the production schedule so the fake cannot
    quietly drift into always-instant retries; tests that depend on reclaim
    timing pass ``ZERO_BACKOFF`` explicitly.
    """

    def __init__(self, *, retry_backoff: RetryBackoff = DEFAULT_RETRY_BACKOFF) -> None:
        self._jobs: dict[str, GenerationJobRecord] = {}
        self._canvases: dict[str, CanvasRecord] = {}
        self._layers: dict[str, LayerRecord] = {}
        self._claim_lock = asyncio.Lock()
        self._retry_backoff = retry_backoff

    async def create_canvas(
        self,
        *,
        name: str,
        width: int,
        height: int,
        background_color: str = "#FFFFFF",
        org_id: str = "",
    ) -> CanvasRecord:
        """Minimal canvas rows — only what the job seeder's scope join needs.

        The fake is a job-store contract leg, not a full canvas twin (the
        conformance suite deliberately declares none): rows exist so seeded
        jobs carry a real ``canvas_id``/``layer_id`` under their org.
        """
        canvas = CanvasRecord(
            id=f"canvas-{uuid.uuid4().hex[:8]}",
            name=name,
            width=width,
            height=height,
            background_color=background_color,
            org_id=org_id,
        )
        self._canvases[canvas.id] = canvas
        return dataclasses.replace(canvas)

    async def add_layer(
        self,
        canvas_id: str,
        *,
        org_id: str = "",
        name: str = "L",
        layer_type: str = "background",
        z_index: int | None = None,
        **kwargs: Any,
    ) -> LayerRecord:
        if canvas_id not in self._canvases:
            from maistro_canvas.types import CanvasNotFoundError

            raise CanvasNotFoundError(canvas_id)
        layer = LayerRecord(
            id=f"layer-{uuid.uuid4().hex[:8]}",
            canvas_id=canvas_id,
            name=name,
            layer_type=layer_type,
            z_index=z_index if z_index is not None else len(self._layers),
        )
        self._layers[layer.id] = layer
        return dataclasses.replace(layer)

    async def create_job(
        self, job: GenerationJobRecord, *, org_id: str = ""
    ) -> GenerationJobRecord:
        self._jobs[job.id] = job
        return dataclasses.replace(job)

    async def get_job(self, job_id: str, *, org_id: str = "") -> GenerationJobRecord | None:
        job = self._jobs.get(job_id)
        return dataclasses.replace(job) if job is not None else None

    async def update_job(
        self,
        job: GenerationJobRecord,
        *,
        org_id: str = "",
        expected_leased_by: str | None = None,
        expected_attempts: int | None = None,
        expected_status: str | None = None,
    ) -> GenerationJobRecord:
        fences = {
            "leased_by": expected_leased_by,
            "attempts": expected_attempts,
            "status": expected_status,
        }
        if any(value is not None for value in fences.values()):
            from maistro_canvas.types import JobLeaseLostError, JobNotFoundError

            current = self._jobs.get(job.id)
            if current is None:
                raise JobNotFoundError(job.id)
            for field, expected in fences.items():
                if expected is not None and getattr(current, field) != expected:
                    raise JobLeaseLostError(
                        f"job {job.id!r} fenced write refused: {field}={expected!r}"
                    )
        self._jobs[job.id] = dataclasses.replace(job)
        return job

    async def active_job_for_layer(
        self, layer_id: str, *, org_id: str = ""
    ) -> GenerationJobRecord | None:
        """The org's active (pending/running) job for one layer, or None."""
        for job in self._jobs.values():
            if (
                job.layer_id == layer_id
                and job.org_id == org_id
                and job.status in (JobStatus.PENDING, JobStatus.RUNNING)
            ):
                return dataclasses.replace(job)
        return None

    async def list_jobs_for_layer(
        self, layer_id: str, *, org_id: str = ""
    ) -> list[GenerationJobRecord]:
        rows = [j for j in self._jobs.values() if j.layer_id == layer_id and j.org_id == org_id]
        rows.sort(key=lambda j: j.created_at, reverse=True)
        return [dataclasses.replace(j) for j in rows]

    async def claim_next_pending(
        self, worker_id: str, lease_seconds: int
    ) -> GenerationJobRecord | None:
        async with self._claim_lock:
            now = datetime.now(UTC)
            pending = sorted(
                (
                    j
                    for j in self._jobs.values()
                    if j.status == JobStatus.PENDING
                    and j.attempts < j.max_attempts
                    and (j.next_retry_at is None or j.next_retry_at <= now)
                ),
                key=lambda j: j.created_at,
            )
            if not pending:
                return None
            job = pending[0]
            job.status = JobStatus.RUNNING
            job.leased_by = worker_id
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            job.attempts += 1
            job.next_retry_at = None
            return dataclasses.replace(job)

    async def reap_expired_leases(self) -> list[GenerationJobRecord]:
        """Mirrors ``PgCanvasStore.reap_expired_leases`` (Codex #1527, #398).

        A candidate with retry budget left is requeued to ``pending`` *with*
        the shared backoff written to ``next_retry_at``; one at its retry
        ceiling only has its stale lease holder cleared and stays ``running``
        — the caller (``CanvasJobRunner.reap_once``) terminalizes it after
        canonical reconciliation. An over-budget ``pending`` row is handed
        back the same way.
        """
        now = datetime.now(UTC)
        reaped: list[GenerationJobRecord] = []
        for job in self._jobs.values():
            if job.status == JobStatus.PENDING and job.attempts >= job.max_attempts:
                # Over-budget pending (unclaimable): handed back for terminalizing.
                job.status = JobStatus.RUNNING
                job.leased_by = None
                job.lease_expires_at = now
                job.next_retry_at = None
                reaped.append(dataclasses.replace(job))
                continue
            if (
                job.status == JobStatus.RUNNING
                and job.lease_expires_at is not None
                and job.lease_expires_at < now
            ):
                job.leased_by = None
                if job.attempts < job.max_attempts:
                    job.status = JobStatus.PENDING
                    job.lease_expires_at = None
                    delay = self._retry_backoff.delay_for_attempt(max(job.attempts, 1))
                    job.next_retry_at = now + timedelta(seconds=delay) if delay > 0 else None
                reaped.append(dataclasses.replace(job))
        return reaped

    async def renew_lease(
        self,
        job_id: str,
        worker_id: str,
        lease_seconds: int,
        *,
        expected_attempts: int | None = None,
    ) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.leased_by != worker_id or job.status != JobStatus.RUNNING:
            return False
        if expected_attempts is not None and job.attempts != expected_attempts:
            return False
        job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        return True

    async def job_queue_stats(self, *, org_id: str = "") -> JobQueueStats:
        """Mirrors ``PgCanvasStore.job_queue_stats`` over the in-memory rows.

        The fake scopes by the record's ``org_id`` field — the same axis the
        real store joins through ``canvases``.
        """
        now = datetime.now(UTC)
        rows = [j for j in self._jobs.values() if j.org_id == org_id]
        return JobQueueStats(
            org_id=org_id,
            pending=sum(1 for j in rows if j.status == JobStatus.PENDING),
            running=sum(1 for j in rows if j.status == JobStatus.RUNNING),
            stuck=sum(
                1
                for j in rows
                if j.status == JobStatus.RUNNING
                and j.lease_expires_at is not None
                and j.lease_expires_at < now
            ),
            retrying=sum(1 for j in rows if j.status == JobStatus.PENDING and j.attempts > 0),
            exhausted=sum(
                1
                for j in rows
                if j.attempts >= j.max_attempts
                and j.status in (JobStatus.PENDING, JobStatus.RUNNING)
            ),
        )


# ─────────────────────────────────────────────────────────────────────
# Shared contract bodies — one body, every leg
# ─────────────────────────────────────────────────────────────────────


async def seed_job(
    store: Any,
    *,
    org: str,
    job_id: str | None = None,
    status: str = JobStatus.PENDING,
    attempts: int = 0,
    max_attempts: int = 3,
    leased_by: str | None = None,
    lease_expires_at: datetime | None = None,
    next_retry_at: datetime | None = None,
) -> GenerationJobRecord:
    """Admit one generation job through the store's own scope-checked path.

    The production store requires real canvas/layer rows under ``org`` (jobs
    scope through their canvas, #857), so the seeder creates them via the
    store itself — the same authorization path a route would take — and then
    writes the queue state with an unfenced ``update_job``, exactly the
    latitude the store's unfenced mode grants.
    """
    from maistro_canvas.types import LayerType

    canvas = await store.create_canvas(name=f"contract-{org}", width=8, height=8, org_id=org)
    layer = await store.add_layer(canvas.id, org_id=org, name="L", layer_type=LayerType.BACKGROUND)
    job = GenerationJobRecord(
        id=job_id or f"job-{uuid.uuid4().hex[:8]}",
        layer_id=layer.id,
        canvas_id=canvas.id,
        status=status,
        attempts=attempts,
        max_attempts=max_attempts,
        leased_by=leased_by,
        lease_expires_at=lease_expires_at,
        next_retry_at=next_retry_at,
        org_id=org,
    )
    created = cast(GenerationJobRecord, await store.create_job(job, org_id=org))
    if (status, attempts, leased_by, lease_expires_at, next_retry_at) != (
        JobStatus.PENDING,
        0,
        None,
        None,
        None,
    ):
        # Mirror the real writers: queue state rides the same update_job the
        # runner/reaper use, not a private back door.
        pending = dataclasses.replace(created)
        pending.status = status
        pending.attempts = attempts
        pending.leased_by = leased_by
        pending.lease_expires_at = lease_expires_at
        pending.next_retry_at = next_retry_at
        return cast(GenerationJobRecord, await store.update_job(pending, org_id=org))
    return created


async def body_store_satisfies_the_job_store_protocol(store: Any) -> None:
    """Structural half of the contract: the leg implements ``CanvasJobStore``.

    ``runtime_checkable`` isinstance checks member presence; signature and
    behavior are pinned statically (mypy against the protocol) and by the
    behavioral bodies below.
    """
    assert isinstance(store, CanvasJobStore)


async def body_claim_gates_on_next_retry_at(store: Any) -> None:
    """A requeued receipt is unclaimable until ``next_retry_at``, then claimable.

    The gate is the durable half of #398's bounded-retry promise: the delay
    survives the requeueing process because it lives on the row, and the claim
    that finally takes the attempt clears it.
    """
    org = "contract-backoff"
    delay = timedelta(hours=1)
    job = await seed_job(store, org=org, job_id="job-gate")
    # Requeue-with-backoff, as both production writers do.
    queued = dataclasses.replace(job)
    queued.status = JobStatus.PENDING
    queued.attempts = 1
    queued.next_retry_at = datetime.now(UTC) + delay
    await store.update_job(queued, org_id=org)

    claimed = await store.claim_next_pending("w1", lease_seconds=60)
    assert claimed is None, "claim took a receipt still waiting out its backoff"

    # Once the delay passes, the claim charges the attempt and clears the gate.
    due = dataclasses.replace(queued)
    due.next_retry_at = datetime.now(UTC) - delay
    await store.update_job(due, org_id=org)
    claimed = await store.claim_next_pending("w1", lease_seconds=60)
    assert claimed is not None
    assert claimed.id == "job-gate"
    assert claimed.attempts == 2
    assert claimed.status == JobStatus.RUNNING
    assert claimed.next_retry_at is None, "claim did not clear the backoff gate"


async def body_reap_writes_the_shared_backoff(store: Any) -> None:
    """The reaper's requeue carries ``next_retry_at`` from the shared schedule.

    A worker that dies right after its reaper requeues a job must leave the
    backoff on the row — if the delay lived only in the dead process, the next
    claim would retry the provider in a tight loop.
    """
    org = "contract-reap"
    backoff = RetryBackoff(base_seconds=120.0, factor=2.0, cap_seconds=600.0)
    holder = getattr(store, "_retry_backoff", None)
    if holder is not None:
        store._retry_backoff = backoff
    try:
        job = await seed_job(store, org=org, job_id="job-reap")
        claimed = await store.claim_next_pending("w1", lease_seconds=60)
        assert claimed is not None and claimed.id == job.id
        # The worker dies: its lease goes stale with one charged attempt.
        stale = dataclasses.replace(claimed)
        stale.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await store.update_job(stale, org_id=org)

        reaped = await store.reap_expired_leases()
        assert [j.id for j in reaped] == ["job-reap"]
        first = reaped[0]
        assert first.status == JobStatus.PENDING
        assert first.next_retry_at is not None
        # Attempt 1 failed: the first requeue waits base_seconds, not factor**0 drift.
        expected = timedelta(seconds=120.0)
        assert abs((first.next_retry_at - datetime.now(UTC)) - expected) < timedelta(seconds=5), (
            f"reaper wrote an unexpected backoff delay: {first.next_retry_at}"
        )

        # And the gate holds: no claim before the delay passes.
        assert await store.claim_next_pending("w1", lease_seconds=60) is None
    finally:
        if holder is not None:
            store._retry_backoff = holder


async def body_over_budget_pending_is_never_claimed(store: Any) -> None:
    """An out-of-budget pending row is unclaimable, and the reaper surfaces it.

    No writer produces this state (the runner terminalizes at the ceiling),
    which is exactly why the store must refuse it independently: retry budget
    is the store's own invariant, not the runner's good intentions (#398).
    """
    org = "contract-overbudget"
    await seed_job(store, org=org, job_id="job-over", attempts=3, max_attempts=3)
    assert await store.claim_next_pending("w1", lease_seconds=60) is None
    reaped = await store.reap_expired_leases()
    assert [j.id for j in reaped] == ["job-over"]
    surfaced = reaped[0]
    assert surfaced.status == JobStatus.RUNNING, "over-budget row must be surfaced, not retried"
    assert surfaced.leased_by is None


async def body_queue_stats_mirror_writer_states(store: Any) -> None:
    """Health counts name the states the store's own writers produce (#398).

    One job per classification, in one org, plus a job in another org that
    must be absent from the count entirely — scope (#857) applies to health
    reads too.
    """
    org = "contract-stats"
    other = "contract-stats-other"
    stale = datetime.now(UTC) - timedelta(seconds=1)
    fresh = datetime.now(UTC) + timedelta(seconds=60)
    await seed_job(store, org=org, job_id="job-fresh")
    await seed_job(store, org=org, job_id="job-retrying", attempts=1, next_retry_at=fresh)
    await seed_job(
        store,
        org=org,
        job_id="job-held",
        status=JobStatus.RUNNING,
        attempts=1,
        leased_by="w1",
        lease_expires_at=fresh,
    )
    await seed_job(
        store,
        org=org,
        job_id="job-stuck",
        status=JobStatus.RUNNING,
        attempts=1,
        leased_by="w0",
        lease_expires_at=stale,
    )
    await seed_job(
        store,
        org=org,
        job_id="job-exhausted-pending",
        attempts=3,
        max_attempts=3,
    )
    await seed_job(store, org=other, job_id="job-foreign")

    stats = await store.job_queue_stats(org_id=org)
    assert isinstance(stats, JobQueueStats)
    assert stats.pending == 3  # fresh + retrying + exhausted-pending (still pending)
    assert stats.running == 2  # held + stuck
    assert stats.stuck == 1
    assert stats.retrying == 2  # job-retrying + exhausted-pending (has charged attempts)
    assert stats.exhausted == 1
    other_stats = await store.job_queue_stats(org_id=other)
    assert other_stats.pending == 1
    assert other_stats.stuck == 0


CONTRACT_BODIES = (
    body_store_satisfies_the_job_store_protocol,
    body_claim_gates_on_next_retry_at,
    body_reap_writes_the_shared_backoff,
    body_over_budget_pending_is_never_claimed,
    body_queue_stats_mirror_writer_states,
)


async def run_job_store_contract(store: Any) -> None:
    """Run every contract body against one store leg."""
    for body in CONTRACT_BODIES:
        await body(store)


def require_pg() -> str:
    """The scope-conformance suite's DSN discipline, shared."""
    from maistro.testing.postgres import postgres_dsn

    dsn = str(postgres_dsn())
    if dsn:
        return dsn
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
            "the job-store contract PostgreSQL leg cannot run and must not be "
            "silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_PG_DSN is unset; the PostgreSQL leg needs a real server")

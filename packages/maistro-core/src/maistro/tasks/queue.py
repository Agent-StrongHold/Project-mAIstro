"""In-memory task queue with best-effort TaskRecord persistence (ADR-018).

Live task state is held in memory. When a database is configured
(``get_async_session_factory()`` returns a factory), every mutation —
``submit()``, ``update_status()``, ``set_result()`` and ``update_progress()``
— upserts a ``TaskRecord`` row, fire-and-forget, so task execution never
fails because the database is unavailable. Writes for one task are chained so
they land in the order the state changed. With no database the queue behaves
exactly as before. Wired canonical Runs are the restart source (#1114); an
unwired queue remains intentionally in-memory. A restart re-enqueues queued
task Runs from the durable provenance payload committed at admission — the
same snapshot that carries the originating-principal evidence (#1057) — so
recovery never depends on a second handoff path the admission did not
already commit.

When an idempotency store is wired (#1176), ``submit()`` first claims stable
admission identity for the request — supplied or payload-derived key, scoped
to the principal and the effective Workspace — so a retry reconciles to the
original admission instead of minting a second Run. The claim store is the
admission contract; the queue stays the receipt's home. See
:mod:`maistro.tasks.idempotency` for the window, scope and concurrency
semantics this thin integration relies on.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import structlog

from maistro.constants import DESCRIPTION_LOG_PREVIEW_LEN
from maistro.memory.store import TaskRecord, get_async_session_factory
from maistro.observability.metrics import (
    active_tasks,
    tasks_completed_total,
    tasks_failed_total,
    tasks_submitted_total,
)
from maistro.runs.model import RunStatus
from maistro.runs.sources import ADMISSION_SOURCE
from maistro.tasks.admission import (
    TASK_ID_KEY,
    TASK_PAYLOAD_KEY,
    TASK_QUEUE_SOURCE,
    TaskAdmitter,
)
from maistro.tasks.idempotency import (
    DEFAULT_REPLAY_WINDOW,
    DERIVED_KEY_PREFIX,
    MAX_PENDING_POLLS,
    PENDING_POLL,
    TASK_SUBMIT_ACTION,
    AdmissionRecord,
    Claimed,
    IdempotencyPendingTimeout,
    Replayed,
    TaskIdempotencyStore,
    admission_scope_key,
    from_epoch_us,
    normalize_idempotency_key,
    request_fingerprint,
)
from maistro.tasks.models import (
    TaskActorKind,
    TaskCreate,
    TaskProgress,
    TaskResponse,
    TaskResult,
    TaskStatus,
)
from maistro.tasks.status import can_transition

logger = structlog.get_logger()


def _record_values(task: TaskResponse) -> dict[str, Any]:
    """Snapshot the TaskRecord column values for one task, taken synchronously
    so the fire-and-forget write cannot race later in-memory mutation."""
    return {
        "id": task.task_id,
        "run_id": task.run_id,
        "user_id": task.user_id,
        "service_principal_id": task.service_principal_id,
        "delegation_id": task.delegation_id,
        "actor_kind": task.actor_kind,
        "status": task.status.value,
        "description": task.description,
        "workspace": task.workspace,
        "constraints": list(task.constraints),
        "branch": task.branch,
        "tier": task.tier,
        "phase": task.phase,
        "progress": task.progress.model_dump(mode="json") if task.progress else None,
        "result": task.result.model_dump(mode="json") if task.result else None,
        "task_type": task.task_type,
        "agent_id": task.agent_id,
        "capability": task.capability,
        "program_context": task.program_context,
        "lane": task.lane.value,
        "priority_tier": task.priority_tier,
        "session_id": task.session_id,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
    }


async def _write_after(
    previous: asyncio.Task[None] | None, factory: Any, values: dict[str, Any]
) -> None:
    """Wait for this task's prior write, then upsert.

    Ordering is the point: without it the persisted row is last-writer-wins
    across concurrent sessions rather than last-state-wins.
    """
    if previous is not None and not previous.done():
        with contextlib.suppress(BaseException):
            await previous
    await _write_record(factory, values)


async def _write_record(factory: Any, values: dict[str, Any]) -> None:
    """Upsert one TaskRecord. Failures are logged and swallowed (ADR-018):
    persistence is best-effort and must never take task execution down."""
    try:
        async with factory() as session:
            await session.merge(TaskRecord(**values))
            await session.commit()
    except Exception as exc:
        logger.warning(
            "task_record_persist_failed",
            task_id=values.get("id"),
            error=str(exc),
        )


# Maximum number of tasks stored in memory before pruning terminal tasks
MAX_TASK_STORE_SIZE = 10_000
# Prune down to this size when limit is hit
PRUNE_TARGET = 8_000

# Terminal statuses that can be pruned
_TERMINAL = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED})

#: The receipt's terminal reading of each terminal Run status (#849). TIMED_OUT
#: is a canonical failure: the work did not finish, which is what the receipt
#: must say. This is projection, not lifecycle — a receipt reconciled from its
#: Run takes the Run's state verbatim rather than walking the task machine.
_TERMINAL_TASK_STATUS_BY_RUN: dict[RunStatus, TaskStatus] = {
    RunStatus.COMPLETED: TaskStatus.COMPLETED,
    RunStatus.FAILED: TaskStatus.FAILED,
    RunStatus.CANCELLED: TaskStatus.CANCELLED,
    RunStatus.TIMED_OUT: TaskStatus.FAILED,
}

#: How long `drain_persistence` waits for in-flight receipt writes before
#: cancelling them. Generous: these are single-row upserts, and shutdown only
#: reaches the drain after in-flight tasks have already been settled.
PERSIST_DRAIN_TIMEOUT = 10.0


def _apply_status_effects(task: TaskResponse, status: TaskStatus) -> None:
    """Timestamps and queue counters for one committed receipt transition.

    The single source of the gauges' truth (#849): `update_status`'s ordinary
    path and the canonical-refusal reconciliation both go through here, so an
    exception before a later phase cannot leak a gauge — every route to a
    terminal receipt decrements `active_tasks` exactly once, because both
    routes are fenced by the task machine (or by the reconcile guard that the
    receipt is not already terminal).
    """
    if status is TaskStatus.PLANNING:
        task.started_at = datetime.now(UTC)
    elif status in _TERMINAL:
        task.completed_at = datetime.now(UTC)
        active_tasks.dec()
        if status is TaskStatus.COMPLETED:
            tasks_completed_total.inc()
        elif status is TaskStatus.FAILED:
            tasks_failed_total.inc()


def _receipt_result_for_run(run: Any, terminal: TaskStatus) -> TaskResult | None:
    """The receipt result projected from a terminal Run's own outcome.

    The Run is the execution identity and holds what actually happened: a
    completed Run's logical result (the task's `files_changed` shape), a
    failed or timed-out Run's error, a cancellation's absence of both. Used by
    both reconciliation routes so a recovered receipt answers `GET /tasks`
    with the same content the living receipt would have carried.
    """
    if terminal is TaskStatus.COMPLETED:
        result = run.result if isinstance(run.result, dict) else {}
        files = result.get("files_changed")
        return TaskResult(files_changed=list(files) if isinstance(files, list) else [])
    if run.error:
        return TaskResult(error=run.error)
    return None


def _task_from_record(record: TaskRecord) -> TaskResponse:
    """Rebuild a receipt without creating a new Run or delegation.

    Used by the idempotency replay path (#1176/#1057): the durable receipt row
    carries the originating-principal evidence the claim's stored request does
    not, so a replay answered from it re-answers with the original identity.
    """
    from maistro.tasks.lanes import Lane

    actor_kind = record.actor_kind
    # Tuple membership, not a set literal: only the tuple form narrows the
    # restored ``str`` back to the Literal for the type checker, so the guard
    # and the proof stay one statement instead of drifting apart.
    if actor_kind not in ("user", "system", "service"):
        raise ValueError("invalid persisted task actor kind")
    if not isinstance(record.user_id, str) or not record.user_id.strip():
        # A malformed/partially migrated receipt must never become runnable
        # ownerless work. Migration 041 classifies pre-provenance rows as the
        # explicit system actor; this guard protects a restart during or before
        # that migration as well as hand-edited data.
        raise ValueError("persisted task has no effective actor")
    try:
        lane: Lane = Lane(record.lane)
    except ValueError:
        lane = Lane.BACKGROUND
    priority_tier = (
        record.priority_tier
        if record.priority_tier in ("P0", "P1", "P2", "P3", "P4", "P5")
        else "P2"
    )
    return TaskResponse(
        task_id=record.id,
        status=TaskStatus(record.status),
        description=record.description,
        workspace=record.workspace,
        user_id=record.user_id,
        service_principal_id=record.service_principal_id,
        delegation_id=record.delegation_id,
        actor_kind=actor_kind,
        task_type=record.task_type,
        agent_id=record.agent_id,
        capability=record.capability,
        program_context=record.program_context,
        tier=record.tier,
        lane=lane,
        priority_tier=priority_tier,
        session_id=record.session_id,
        run_id=record.run_id,
        phase=record.phase,
        progress=TaskProgress.model_validate(record.progress or {}),
        result=TaskResult.model_validate(record.result) if record.result is not None else None,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
    )


def _task_from_run(run: Any) -> tuple[TaskResponse | None, str | None]:
    """Validate one canonical task payload, returning a visible failure reason."""
    raw = run.provenance.get(TASK_PAYLOAD_KEY)
    if raw is None:
        return None, "missing durable task payload"
    try:
        task = TaskResponse.model_validate(raw)
        if run.provenance.get(TASK_ID_KEY) != task.task_id:
            raise ValueError("task payload task_id does not match Run provenance")
        if task.status is not TaskStatus.QUEUED:
            raise ValueError("task payload is not queued")
    except Exception as exc:
        return None, f"invalid durable task payload: {exc}"
    return task.model_copy(update={"run_id": run.run_id, "status": TaskStatus.QUEUED}), None


async def _has_attempt_evidence(run_store: Any, node_runs: list[Any]) -> bool:
    """Whether any physical Attempt exists under these NodeRuns.

    A NodeRun is logical scaffolding: it says where a try would run, not that
    one ever started. The Attempt is the physical evidence — active, its lease
    is the Attempt sweep's to expire; terminal, its outcome is the
    reconciler's to re-derive. A NodeRun with no Attempt under it is an
    execution record that is incomplete rather than absent, and no sweep
    anchored on physical evidence can reach it.
    """
    for node_run in node_runs:
        if await run_store.list_attempts(node_run.node_run_id):
            return True
    return False


class TaskQueue:
    """In-memory task queue with event-based notification and async lock."""

    def __init__(
        self,
        *,
        admitter: TaskAdmitter | None = None,
        idempotency_store: TaskIdempotencyStore | None = None,
    ) -> None:
        # Canonical execution identity (#41). When an admitter is wired every
        # submission creates a Run before the task is queued, and the task row
        # carries its run_id. When it is not, submission behaves as it always
        # did and `run_id` stays None — the queue does not fabricate an
        # execution identity it cannot back with a Run.
        self._admitter = admitter
        # Stable admission identity (#1176). None keeps submission exactly as
        # it was — every call mints a receipt (and a Run when the admitter is
        # wired) — which is the documented behaviour for a deployment that has
        # not grown the claim tier yet.
        self._idempotency = idempotency_store
        self._tasks: OrderedDict[str, TaskResponse] = OrderedDict()
        self._pending: asyncio.Queue[str] = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._claimed: set[str] = set()
        self._events: dict[str, asyncio.Event] = {}
        # In-flight fire-and-forget TaskRecord writes (ADR-018); referenced so
        # the event loop cannot garbage-collect them mid-write.
        self._persist_writes: set[asyncio.Task[None]] = set()
        # The most recent write per task, so the next one for that task can
        # wait on it. Independent writes with independent sessions can commit
        # in any order, and a slow `queued` merge landing after `completed`
        # would silently regress the persisted row to an older status.
        self._last_write: dict[str, asyncio.Task[None]] = {}

    def _persist(self, task: TaskResponse) -> None:
        """Schedule a best-effort TaskRecord upsert when a DB is configured.

        The snapshot is taken synchronously so it cannot race later in-memory
        mutation, and each task's writes are chained so they commit in the
        order the state actually changed.
        """
        factory = get_async_session_factory()
        if factory is None:
            return
        values = _record_values(task)
        previous = self._last_write.get(task.task_id)
        write = asyncio.create_task(_write_after(previous, factory, values))
        self._persist_writes.add(write)
        self._last_write[task.task_id] = write

        def _done(finished: asyncio.Task[None]) -> None:
            self._persist_writes.discard(finished)
            if self._last_write.get(task.task_id) is finished:
                self._last_write.pop(task.task_id, None)

        write.add_done_callback(_done)

    def _get_event(self, task_id: str) -> asyncio.Event:
        """Get or create an asyncio.Event for a task."""
        if task_id not in self._events:
            self._events[task_id] = asyncio.Event()
        return self._events[task_id]

    async def wait_for_update(self, task_id: str) -> None:
        """Wait until the task status or progress changes."""
        event = self._get_event(task_id)
        event.clear()
        await event.wait()

    def _notify(self, task_id: str) -> None:
        """Signal waiters that a task has been updated."""
        event = self._events.get(task_id)
        if event:
            event.set()

    def _maybe_prune(self) -> None:
        """Remove oldest terminal tasks when store exceeds max size."""
        if len(self._tasks) <= MAX_TASK_STORE_SIZE:
            return
        to_remove: list[str] = []
        for tid, task in self._tasks.items():
            if len(self._tasks) - len(to_remove) <= PRUNE_TARGET:
                break
            if task.status in _TERMINAL:
                to_remove.append(tid)
        for tid in to_remove:
            del self._tasks[tid]
            self._events.pop(tid, None)
        if to_remove:
            logger.info("task_store_pruned", removed=len(to_remove), remaining=len(self._tasks))

    async def drain_persistence(self, timeout: float = PERSIST_DRAIN_TIMEOUT) -> int:
        """Wait for in-flight TaskRecord writes to land, then give up on the rest.

        Receipt writes are fire-and-forget (ADR-018) so execution never waits on
        the database — which is exactly why shutdown must own them explicitly
        (#849): an abandoned write takes a completed transition, a result or a
        failure with it as the event loop closes, leaving a durable receipt that
        stops one write short of the truth. This drain is that ownership: the
        runner calls it from `stop()`/`drain()` and the server lifespan before
        the singleton is dropped, so a graceful shutdown completes only after
        every scheduled receipt write has been awaited or cancelled. Idempotent;
        returns how many writes did not settle (already logged).
        """
        writes = set(self._persist_writes)
        if not writes:
            return 0
        _, pending = await asyncio.wait(writes, timeout=timeout)
        if not pending:
            return 0
        # Cancelling is the honest disposition for a write that would not
        # settle: letting it run un-awaited past shutdown is the defect. The
        # gather reaps the cancellations so nothing is left mid-flight; the
        # canonical Run still holds the truth, and recovery reconciles from it.
        for write in pending:
            write.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await logger.awarning(
            "task_record_drain_incomplete",
            abandoned=len(pending),
            settled=len(writes) - len(pending),
        )
        return len(pending)

    async def submit(
        self,
        request: TaskCreate,
        *,
        user_id: str = "",
        workspace_id: str | None = None,
        service_principal_id: str | None = None,
        delegation_id: str | None = None,
        actor_kind: TaskActorKind = "user",
        idempotency_key: str | None = None,
    ) -> TaskResponse:
        """Queue one task, admitting it as a Run when an admitter is wired.

        ``workspace_id`` is the Workspace the caller submitted under, already
        authorized by whoever accepted the request (#158). It is passed to the
        admitter rather than stored on the task: scope is a binding, not a task
        field, and a task row that carried its own Workspace would be a second
        answer to a question the Run already answers. None — every caller before
        this parameter existed — means the deployment's default Workspace.

        ``idempotency_key`` is the caller's explicit admission key (#1176);
        ``request.idempotency_key`` is its other spelling, and the two must
        agree when both are given. Without one, admission derives a stable key
        from the payload: a byte-identical retry inside the replay window then
        reconciles to the original receipt and Run instead of minting a second
        one. With no idempotency store wired, the key is accepted and echoed
        but reconciles nothing — the deployment's own durability tier.
        """
        key = normalize_idempotency_key(idempotency_key, request.idempotency_key)
        if self._idempotency is None:
            return await self._submit_once(
                request,
                user_id=user_id,
                workspace_id=workspace_id,
                service_principal_id=service_principal_id,
                delegation_id=delegation_id,
                actor_kind=actor_kind,
                idempotency_key=key,
            )
        return await self._submit_idempotent(
            request,
            key,
            user_id=user_id,
            workspace_id=workspace_id,
            service_principal_id=service_principal_id,
            delegation_id=delegation_id,
            actor_kind=actor_kind,
        )

    async def _scope_workspace(self, workspace_id: str | None) -> str:
        """The Workspace a submission will actually land in, for key scoping.

        The scope must name the *effective* Workspace, not the spelled one: a
        retry that arrives without the Workspace header has to meet the claim
        its first call made under the default. Routers resolve None to the
        deployment default, bound admitters know their one Workspace, and an
        admitter that knows neither gets the submission's own spelling.
        """
        admitter = self._admitter
        route = getattr(admitter, "admitter_for", None)
        if route is not None:
            bound = await route(workspace_id)
            return str(bound.workspace_id).strip()
        fixed = getattr(admitter, "workspace_id", None)
        if isinstance(fixed, str) and fixed.strip():
            return fixed.strip()
        return (workspace_id or "").strip()

    async def _submit_idempotent(
        self,
        request: TaskCreate,
        key: str | None,
        *,
        user_id: str,
        workspace_id: str | None,
        service_principal_id: str | None = None,
        delegation_id: str | None = None,
        actor_kind: TaskActorKind = "user",
    ) -> TaskResponse:
        """Submit through the claim store: reconcile, or admit exactly once.

        The ordering is the contract: claim, admit, complete — and release on
        any admission failure, which is what keeps a failure before Run
        creation retryable rather than pinning the key to an outcome that never
        happened. A replay returns the recorded receipt; a pending twin is
        waited out, with the claim lease's takeover as the backstop for a twin
        that died mid-admission.
        """
        store = self._idempotency
        if store is None:  # pragma: no cover - guarded by the only caller
            raise RuntimeError("_submit_idempotent called without an idempotency store")
        owner = user_id or request.user_id or ""
        fingerprint = request_fingerprint(request)
        textual = key if key is not None else f"{DERIVED_KEY_PREFIX}{fingerprint}"
        scope_key = admission_scope_key(
            principal=owner,
            workspace_id=await self._scope_workspace(workspace_id),
            action=TASK_SUBMIT_ACTION,
            key=textual,
        )
        # The request as admitted: the owner filled in, so a replay after a
        # restart reconstructs a receipt that names the same principal.
        request_json = json.dumps(
            request.model_copy(
                update={
                    "user_id": owner,
                    "service_principal_id": service_principal_id,
                    "delegation_id": delegation_id,
                    "actor_kind": actor_kind,
                }
            ).model_dump(mode="json")
        )
        outcome = await self._claim_until_resolved(
            store,
            scope_key,
            fingerprint=fingerprint,
            request=request_json,
        )
        if isinstance(outcome, AdmissionRecord):
            await logger.ainfo(
                "task_admission_replayed",
                task_id=outcome.task_id,
                run_id=outcome.run_id,
                explicit_key=key is not None,
            )
            return await self._replay_receipt(outcome)
        try:
            task = await self._submit_once(
                request,
                user_id=user_id,
                workspace_id=workspace_id,
                service_principal_id=service_principal_id,
                delegation_id=delegation_id,
                actor_kind=actor_kind,
                idempotency_key=key,
            )
        except BaseException:
            # Nothing was admitted. Releasing is what makes the caller's retry
            # a fresh submission instead of a replay of a failure.
            with contextlib.suppress(Exception):
                await store.release(scope_key)
            raise
        # Best-effort like the receipt's own persistence: a failed write here
        # is logged, not raised — the task exists, and failing the caller's
        # 202 after admission would teach it to retry an admission that
        # already happened.
        try:
            await store.complete(scope_key, task_id=task.task_id, run_id=task.run_id)
        except Exception as exc:
            await logger.awarning(
                "task_admission_complete_failed",
                task_id=task.task_id,
                run_id=task.run_id,
                error=str(exc),
            )
        return task

    async def _claim_until_resolved(
        self,
        store: TaskIdempotencyStore,
        scope_key: str,
        *,
        fingerprint: str,
        request: str,
    ) -> Claimed | AdmissionRecord:
        """Claim once, waiting out a twin that is still mid-admission.

        Resolves to the twin's recorded admission (a replayable record) or to
        this call's own ``Claimed``. A pending twin's lease lapses long before
        this loop's bound, so a dead twin's claim is taken over by a later
        iteration rather than waited on forever; the bound itself is the
        caller-visible backstop (#1176).
        """
        waited = 0
        while True:
            now = datetime.now(UTC)
            outcome = await store.claim(
                scope_key,
                fingerprint=fingerprint,
                request=request,
                now=now,
                replay_window=DEFAULT_REPLAY_WINDOW,
            )
            if isinstance(outcome, Replayed):
                return outcome.record
            if isinstance(outcome, Claimed):
                return outcome
            waited += 1
            if waited > MAX_PENDING_POLLS:
                raise IdempotencyPendingTimeout(
                    "a concurrent submission under this idempotency key has not "
                    "resolved within the bounded wait"
                )
            await asyncio.sleep(PENDING_POLL)

    async def _replay_receipt(self, record: AdmissionRecord) -> TaskResponse:
        """The original submission's answer, without minting anything.

        The live receipt when this process still holds it; otherwise the durable
        TaskRecord row, which carries the originating-principal evidence
        (#1057) the claim's stored request does not; otherwise one reconstructed
        from the claim's stored request. A reconstructed receipt says ``queued``
        because that is what admission said — the Run behind it has moved on
        without the queue, and current state is read from the task/Run
        endpoints, not from a replay.
        """
        if record.task_id is not None:
            live = self._tasks.get(record.task_id)
            if live is not None:
                return live
            persisted = await self._persisted_receipt(record.task_id)
            if persisted is not None:
                return persisted
        stored = TaskCreate.model_validate_json(record.request)
        if record.task_id is None:  # pragma: no cover - replayed claims are admitted
            raise RuntimeError("replayed admission claim carries no receipt id")
        return TaskResponse(
            task_id=record.task_id,
            status=TaskStatus.QUEUED,
            description=stored.description,
            workspace=stored.workspace,
            user_id=stored.user_id or "",
            service_principal_id=stored.service_principal_id,
            delegation_id=stored.delegation_id,
            actor_kind=stored.actor_kind,
            task_type=stored.task_type,
            agent_id=stored.agent_id,
            capability=stored.capability,
            program_context=stored.program_context,
            tier=stored.tier or 2,
            lane=stored.lane,
            priority_tier=stored.priority_tier,
            session_id=stored.session_id,
            idempotency_key=stored.idempotency_key,
            run_id=record.run_id,
            phase="queued",
            progress=TaskProgress(),
            created_at=from_epoch_us(record.created_at_us),
        )

    async def _persisted_receipt(self, task_id: str) -> TaskResponse | None:
        """The durable receipt row for a replayed admission, best-effort.

        Receipt persistence is best-effort (ADR-018) and the claim store, not
        this row, is the admission contract — a missing or unreadable row is a
        fall-through to the stored-request reconstruction, never an error the
        caller's retry has to answer for.
        """
        factory = get_async_session_factory()
        if factory is None:
            return None
        try:
            async with factory() as session:
                row = await session.get(TaskRecord, task_id)
        except Exception:
            return None
        if row is None:
            return None
        try:
            return _task_from_record(row)
        except (TypeError, ValueError):
            return None

    async def _submit_once(
        self,
        request: TaskCreate,
        *,
        user_id: str = "",
        workspace_id: str | None = None,
        service_principal_id: str | None = None,
        delegation_id: str | None = None,
        actor_kind: TaskActorKind = "user",
        idempotency_key: str | None = None,
    ) -> TaskResponse:
        """Admit and queue one submission unconditionally — the pre-#1176 path.

        No claim is consulted or written here: idempotency wraps this method,
        which stays the single place a receipt is born and a Run minted.
        """
        task_id = TaskResponse.new_id()
        owner = user_id or request.user_id or ""
        task = TaskResponse(
            task_id=task_id,
            status=TaskStatus.QUEUED,
            description=request.description,
            workspace=request.workspace,
            user_id=owner,
            service_principal_id=service_principal_id,
            delegation_id=delegation_id,
            actor_kind=actor_kind,
            task_type=request.task_type,
            agent_id=request.agent_id,
            capability=request.capability,
            program_context=request.program_context,
            branch=request.branch,
            constraints=list(request.constraints),
            tier=request.tier or 2,
            lane=request.lane,
            priority_tier=request.priority_tier,
            session_id=request.session_id,
            idempotency_key=idempotency_key,
            phase="queued",
            progress=TaskProgress(),
            created_at=datetime.now(UTC),
        )
        if self._admitter is not None:
            # Deliberately not best-effort. TaskRecord persistence may fail
            # without the task failing, because the row is a receipt; the Run
            # is the execution identity, and a task admitted without one would
            # be exactly the untracked second lifecycle #41 exists to remove.
            task.run_id = await self._admitter.admit(task, workspace_id=workspace_id)
        async with self._lock:
            self._tasks[task_id] = task
            self._maybe_prune()
        self._persist(task)
        await self._pending.put(task_id)
        tasks_submitted_total.inc()
        active_tasks.inc()
        await logger.ainfo(
            "task_queued",
            task_id=task_id,
            run_id=task.run_id,
            description=request.description[:DESCRIPTION_LOG_PREVIEW_LEN],
        )
        return task

    async def recover(self, run_store: Any, *, batch_size: int = 100) -> int:
        """Rebuild task receipts from queued canonical Runs after a restart.

        The Run contains the immutable task payload and is inserted as QUEUED in
        the same durable write as admission. Rehydrating from that source closes
        both process-death windows without adding a second queue lifecycle.
        A malformed snapshot is claimed and failed on the canonical Run so it
        cannot remain an invisible QUEUED row forever. Task Runs left RUNNING
        with no physical execution evidence — the residue of a refused
        terminalization, or of a dispatch that wrote RUNNING separately from
        its Attempt, including one that died after creating a NodeRun but
        before any Attempt under it — are failed visibly for the same reason
        (#1114). Terminal task Runs whose receipt write never landed — a
        forced shutdown abandoning the fire-and-forget write (#849) — get that
        receipt written here, projected from the Run, so a completed Run can
        never be permanently missing its receipt.
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        from maistro.runs.store import run_cursor_key

        recovered = 0
        after: tuple[str, str] | None = None
        while True:
            queued = await run_store.list_by_status(RunStatus.QUEUED, limit=batch_size, after=after)
            if not queued:
                break
            for run in queued:
                after = run_cursor_key(run)
                if run.provenance.get(ADMISSION_SOURCE) != TASK_QUEUE_SOURCE:
                    continue
                task, reason = _task_from_run(run)
                if reason is not None:
                    await self._fail_unrecoverable_run(run_store, run.run_id, reason)
                    continue
                assert task is not None
                async with self._lock:
                    if task.task_id in self._tasks:
                        continue
                    self._tasks[task.task_id] = task
                    self._maybe_prune()
                await self._pending.put(task.task_id)
                active_tasks.inc()
                recovered += 1
                await logger.ainfo(
                    "task_recovered",
                    task_id=task.task_id,
                    run_id=task.run_id,
                )
            if len(queued) < batch_size:
                break
        await self._terminalize_stranded_claims(run_store, batch_size=batch_size)
        await self._reconcile_terminal_receipts(run_store, batch_size=batch_size)
        return recovered

    async def _reconcile_terminal_receipts(self, run_store: Any, *, batch_size: int) -> None:
        """Write the receipts terminal task Runs finished without (#849).

        Receipt persistence is best-effort, and a forced shutdown between the
        terminal transition and the in-flight upsert loses exactly that write:
        the Run says COMPLETED (or FAILED, or CANCELLED) while no durable
        receipt does. Recovery is where the projection is repaired — from the
        canonical owner, never from memory, because memory is the thing that
        died. The scan is paged like its siblings and idempotent by construction:
        a terminal Run's payload and outcome are immutable, and a receipt row
        that already reads terminal is left untouched, so re-running recovery
        rewrites nothing and duplicates no results.
        """
        from maistro.runs.store import run_cursor_key

        reconciled = 0
        for status, terminal in _TERMINAL_TASK_STATUS_BY_RUN.items():
            after: tuple[str, str] | None = None
            while True:
                page = await run_store.list_by_status(
                    status,
                    limit=batch_size,
                    after=after,
                    admission_source=TASK_QUEUE_SOURCE,
                )
                if not page:
                    break
                for run in page:
                    after = run_cursor_key(run)
                    if await self._reconcile_terminal_receipt(run, terminal):
                        reconciled += 1
                if len(page) < batch_size:
                    break
        if reconciled:
            await logger.ainfo("task_receipts_reconciled_on_recovery", count=reconciled)

    async def _reconcile_terminal_receipt(self, run: Any, terminal: TaskStatus) -> bool:
        """Project one terminal Run onto its durable receipt; True when written.

        A malformed admission payload is logged and skipped rather than failed:
        the Run is already terminal, so the QUEUED-recovery disposition (claim
        and fail visibly) has nothing left to do — the row was disposed of when
        it terminalized, and only its receipt question remains.
        """
        task, reason = _task_from_run(run)
        if reason is not None:
            await logger.awarning(
                "task_terminal_receipt_payload_invalid",
                run_id=run.run_id,
                reason=reason,
            )
            return False
        assert task is not None
        persisted = await self._persisted_receipt(task.task_id)
        durable_is_current = persisted is not None and persisted.status in _TERMINAL
        receipt = task.model_copy(
            update={
                "status": terminal,
                "phase": terminal.value,
                "started_at": run.started_at,
                "completed_at": run.finished_at or task.completed_at,
                "result": _receipt_result_for_run(run, terminal),
            }
        )
        # Repair the durable row unless it already tells the truth — rewriting
        # a current receipt could only regress it, and equal is the common case
        # on every restart. Chained behind any write this process already
        # scheduled for the task, so ordering matches every other write.
        factory = get_async_session_factory()
        wrote = False
        if factory is not None and not durable_is_current:
            await _write_after(self._last_write.get(task.task_id), factory, _record_values(receipt))
            wrote = True
        # And the same truth for any live copy this process holds, so a
        # recovery run against a warm queue leaves one story, not two — even
        # when the durable row needed no repair. Effects first (they stamp
        # wall-clock fields), then the Run's own timestamps over the stamps.
        async with self._lock:
            live = self._tasks.get(task.task_id)
            if live is not None and live.status not in _TERMINAL:
                _apply_status_effects(live, terminal)
                live.status = terminal
                live.phase = terminal.value
                live.started_at = receipt.started_at
                live.completed_at = receipt.completed_at
                live.result = receipt.result
        if not wrote:
            return False
        await logger.ainfo(
            "task_receipt_reconciled_on_recovery",
            task_id=task.task_id,
            run_id=run.run_id,
            status=terminal.value,
        )
        return True

    async def _terminalize_stranded_claims(self, run_store: Any, *, batch_size: int) -> None:
        """Fail task Runs claiming execution with no physical evidence (#1114).

        A task Run that is RUNNING with no Attempt — with or without a NodeRun
        — has no lease and no dispatch path. A NodeRun alone is not evidence:
        one with no Attempt under it is an execution record that is incomplete
        rather than absent, left by a worker that died between creating the
        NodeRun and persisting its first Attempt. On a claiming store RUNNING
        is only ever committed together with the NodeRun and leased Attempt
        that make it true, so these states are the residue of a terminalization
        whose FAILED write was refused, of a pre-repair worker that wrote
        RUNNING before creating its evidence, or of a legacy worker mid-dispatch
        during a rolling upgrade — whose execute then fails visibly against the
        terminal Run rather than silently racing the recovering process. An
        Attempt, active or terminal, is evidence: active, the lease sweep
        (#232) owns reclaiming it; terminal, the reconciler re-derives the
        logical record from it. Failing the rest is the honest disposition, and
        every restart retries it, so it cannot outlive recovery as an immortal
        RUNNING Run.
        """
        from maistro.runs.store import run_cursor_key

        after: tuple[str, str] | None = None
        while True:
            running = await run_store.list_by_status(
                RunStatus.RUNNING, limit=batch_size, after=after
            )
            if not running:
                return
            for run in running:
                after = run_cursor_key(run)
                if run.provenance.get(ADMISSION_SOURCE) != TASK_QUEUE_SOURCE:
                    continue
                node_runs = await run_store.list_node_runs(run.run_id)
                if await _has_attempt_evidence(run_store, node_runs):
                    # Physical evidence exists — an Attempt, not a NodeRun: the
                    # Attempt lease sweep (#232) owns the active ones and the
                    # reconciler the terminal ones, not this scan.
                    continue
                try:
                    await run_store.transition_run(
                        run.run_id,
                        RunStatus.FAILED,
                        error=(
                            "task_recovery_failed: running task Run has no physical "
                            "execution evidence (stranded dispatch)"
                        ),
                    )
                    await logger.awarning(
                        "task_recovery_stranded_claim_failed",
                        run_id=run.run_id,
                    )
                except Exception:
                    await logger.awarning(
                        "task_recovery_stranded_claim_not_terminalized",
                        run_id=run.run_id,
                    )
            if len(running) < batch_size:
                return

    async def _fail_unrecoverable_run(self, run_store: Any, run_id: str, reason: str) -> None:
        """Record malformed admitted work as a terminal canonical failure."""
        try:
            await run_store.transition_run(run_id, RunStatus.RUNNING)
        except Exception:
            # A concurrent worker owns the Run, so it is not safe for recovery
            # to overwrite its outcome. The canonical claim remains the fence.
            logger.warning("task recovery lost claim", run_id=run_id, reason=reason)
            return
        try:
            await run_store.transition_run(
                run_id,
                RunStatus.FAILED,
                error=f"task_recovery_failed: {reason}",
            )
        except Exception:
            # Not terminalized this pass — but no longer invisible either: the
            # Run is now RUNNING with no NodeRun, which
            # `_terminalize_stranded_claims` re-examines on this and every
            # later restart until the FAILED write lands. Eventual, explicit
            # disposition rather than an immortal Run (#1114).
            logger.warning("task recovery failure was not terminalized", run_id=run_id)

    def get(self, task_id: str, *, user_id: str | None = None) -> TaskResponse | None:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        # Fail closed: when a caller scopes by user_id, a task whose owner is
        # empty ("") must NOT match — the old `task.user_id and ...` guard
        # short-circuited on the empty string and returned ownerless tasks to
        # any caller. A caller who wants no scoping passes user_id=None.
        if user_id is not None and task.user_id != user_id:
            return None
        return task

    async def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        result: object | None = None,
        error: str | None = None,
    ) -> bool:
        """Advance the task, and the Run behind it, together.

        ``result``/``error`` are the terminal outcome. They go to the Run rather
        than the receipt — `set_result` still owns the receipt's own copy — so a
        caller following the canonical run_id learns *how* the work ended and not
        merely that it did.
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                logger.warning(
                    "update_status_missing_task", task_id=task_id, requested=status.value
                )
                return False
            if not can_transition(task.status, status):
                logger.warning(
                    "invalid_state_transition",
                    task_id=task_id,
                    current=task.status.value,
                    requested=status.value,
                )
                return False

            # The Run moves first, and refusing there refuses here (#41). The
            # receipt must never record a state the execution identity rejected,
            # or the two tell different stories about the same work.
            if (
                self._admitter is not None
                and task.run_id
                and not await self._admitter.record_transition(
                    task.run_id,
                    status,
                    result=result,
                    error=error,
                    previous_status=task.status,
                )
            ):
                logger.warning(
                    "run_refused_task_transition",
                    task_id=task_id,
                    run_id=task.run_id,
                    current=task.status.value,
                    requested=status.value,
                )
                # A refusal is not a place to strand the receipt (#849). The
                # Run owns the truth; read it and reconcile the receipt to it
                # so a refused transition can never leave a QUEUED receipt
                # behind work the canonical side has already finished, failed
                # or lost.
                await self._reconcile_refused(task, requested=status)
                self._notify(task_id)
                return False

            task.status = status
            task.phase = status.value
            _apply_status_effects(task, status)

            self._persist(task)

        self._notify(task_id)
        return True

    async def _reconcile_refused(self, task: TaskResponse, *, requested: TaskStatus) -> None:
        """Reconcile a receipt whose canonical Run refused to advance (#849).

        Called with the queue lock held, immediately after `record_transition`
        refused. The receipt is a projection, so it takes the Run's actual
        state: terminal, the receipt terminalizes to match — including the
        QUEUED case, where the Run finished (or was cancelled, or was consumed
        by another worker) before this receipt ever reached PLANNING. Missing,
        the receipt records an explicit canonical error receipt instead of
        failing silently forever. Still owned and non-terminal (WAITING or
        PAUSED — a live Attempt lease or an answer-gated pause), the receipt is
        deliberately left exactly as it is: failing it would lie about work the
        canonical owner may yet finish, and the recovery scan reconciles the
        projection from the Run once the owner settles it.
        """
        try:
            run = await self._lookup_run(task.run_id or "")
        except Exception:
            # A lookup failure is not evidence about the Run. Leave the receipt
            # untouched and let a later pass reconcile it; failing the receipt
            # on a read error would fabricate a failure the Run never recorded.
            await logger.awarning(
                "task_receipt_reconcile_lookup_failed",
                task_id=task.task_id,
                run_id=task.run_id,
                exc_info=True,
            )
            return
        if run is None:
            await self._fail_receipt(
                task,
                error=(
                    "canonical error receipt: canonical Run does not exist; "
                    f"refused {requested.value}"
                ),
            )
            return
        terminal = _TERMINAL_TASK_STATUS_BY_RUN.get(run.status)
        if terminal is None:
            await logger.awarning(
                "task_receipt_reconcile_deferred_to_owner",
                task_id=task.task_id,
                run_id=task.run_id,
                run_status=run.status.value,
            )
            return
        if terminal is task.status:
            return
        task.status = terminal
        task.phase = terminal.value
        # Effects first (they stamp completed_at with wall-clock time), then the
        # Run's own timestamps over the stamps: the canonical record of when
        # this work started and ended outranks the projection's clock.
        _apply_status_effects(task, terminal)
        if run.started_at is not None:
            task.started_at = run.started_at
        task.completed_at = run.finished_at or task.completed_at
        task.result = _receipt_result_for_run(run, terminal)
        self._persist(task)
        await logger.ainfo(
            "task_receipt_reconciled_from_run",
            task_id=task.task_id,
            run_id=task.run_id,
            status=terminal.value,
            refused=requested.value,
        )

    async def _fail_receipt(self, task: TaskResponse, *, error: str) -> None:
        """Record an explicit canonical error receipt on a non-terminal task.

        The last-resort disposition (#849): every failure point from QUEUED
        onward must end in a legal terminal receipt, and a Run that does not
        exist cannot be projected from. LEGAL because QUEUED -> FAILED is a
        task-machine transition; HONEST because the error text names the
        canonical fact (the Run is gone) rather than inventing an outcome the
        work never reported.
        """
        if task.status in _TERMINAL:
            return
        if not can_transition(task.status, TaskStatus.FAILED):  # pragma: no cover - guarded
            return
        task.status = TaskStatus.FAILED
        task.phase = TaskStatus.FAILED.value
        task.completed_at = datetime.now(UTC)
        task.result = TaskResult(error=error)
        _apply_status_effects(task, TaskStatus.FAILED)
        self._persist(task)
        await logger.awarning(
            "task_receipt_failed_without_run",
            task_id=task.task_id,
            run_id=task.run_id,
            error=error,
        )

    async def _lookup_run(self, run_id: str) -> Any:
        """The canonical Run behind a receipt, via the wired admitter.

        Raises when the admitter cannot answer — callers must treat that as
        unknown, not as absent. An admitter without `lookup_run` (a custom
        implementation predating the projection contract) answers nothing, so
        reconciliation is skipped rather than guessed.
        """
        if self._admitter is None:
            raise RuntimeError("no admitter wired; canonical Run state is unknowable")
        lookup = getattr(self._admitter, "lookup_run", None)
        if lookup is None:
            raise RuntimeError("admitter does not expose canonical Run lookups")
        return await lookup(run_id)

    def update_progress(self, task_id: str, progress: TaskProgress) -> None:
        task = self._tasks.get(task_id)
        if task:
            task.progress = progress
            self._persist(task)
            self._notify(task_id)

    def set_result(self, task_id: str, result: TaskResult) -> None:
        task = self._tasks.get(task_id)
        if task:
            task.result = result
            # The runner transitions to COMPLETED/FAILED *before* attaching the
            # result, so persisting only on status change stored every finished
            # task with a NULL result — durable rows that answer neither an
            # audit nor a recovery.
            self._persist(task)
            self._notify(task_id)

    async def cancel(self, task_id: str) -> bool:
        """Cancel the canonical Run before updating its task receipt.

        The receipt is a projection. For admitted work, cancellation must
        first reach the Run/Attempt service so an in-flight provider receives
        the same signal as a queued task that has not started yet.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return False
        # A request that found the receipt already terminal is a repeat of an
        # old cancellation, not a new one — it stays False so the route keeps
        # mapping it to 400 (the pinned API contract).
        arrived_terminal = task.status in _TERMINAL
        if (
            self._admitter is not None
            and task.run_id
            and not await self._admitter.cancel_run(task.run_id)
        ):
            return False
        # The canonical cancellation may already have reached the receipt: the
        # worker's cancellation handler reconciles it from the Run (#849), and
        # that reconcile can win the race against this method's own write. A
        # receipt that flipped CANCELLED *during this call* is the cancellation
        # having succeeded, not having failed — reporting False would turn a
        # win into a lie. One that already read CANCELLED on arrival is the
        # repeat case above and stays False.
        current = self._tasks.get(task_id)
        if not arrived_terminal and current is not None and current.status is TaskStatus.CANCELLED:
            return True
        return await self.update_status(task_id, TaskStatus.CANCELLED)

    def remove(self, task_id: str) -> bool:
        """Drop a terminal task from the in-memory store (POC cleanup)."""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if task.status not in _TERMINAL:
            return False
        del self._tasks[task_id]
        self._events.pop(task_id, None)
        self._claimed.discard(task_id)
        return True

    def remove_where(self, *, status: TaskStatus | None = None) -> int:
        """Remove terminal tasks, optionally filtered by status. Returns count removed."""
        to_remove = [
            tid
            for tid, task in self._tasks.items()
            if task.status in _TERMINAL and (status is None or task.status == status)
        ]
        for tid in to_remove:
            self.remove(tid)
        return len(to_remove)

    async def next_task(self) -> str:
        """Block until a task is available, return its ID."""
        return await self._pending.get()

    def list_tasks(
        self,
        limit: int = 50,
        cursor: str | None = None,
        *,
        user_id: str | None = None,
    ) -> tuple[list[TaskResponse], str | None]:
        """Return a page of tasks with cursor-based pagination.

        Returns (items, next_cursor) where next_cursor is None if no more pages.
        """
        all_tasks = list(self._tasks.values())
        if user_id is not None:
            # Fail closed: exact-owner match only. The old `not t.user_id or ...`
            # leaked every ownerless ("") task into every user-scoped listing.
            all_tasks = [t for t in all_tasks if t.user_id == user_id]

        if cursor:
            found = False
            items: list[TaskResponse] = []
            for task in all_tasks:
                if not found:
                    if task.task_id == cursor:
                        found = True
                    continue
                items.append(task)
                if len(items) >= limit:
                    break
        else:
            items = all_tasks[:limit]

        next_cursor = items[-1].task_id if len(items) == limit else None
        return items, next_cursor

    @asynccontextmanager
    async def claim(self, task_id: str) -> AsyncIterator[TaskResponse]:
        """Context manager that transitions task through its lifecycle."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise ValueError(f"Task {task_id} not found")
            if task_id in self._claimed:
                raise ValueError(f"Task {task_id} already claimed")
            self._claimed.add(task_id)
        try:
            yield task
        except BaseException as exc:
            await self.update_status(task_id, TaskStatus.FAILED)
            self.set_result(task_id, TaskResult(error=str(exc)))
            await logger.aexception("task_failed", task_id=task_id)
            raise
        finally:
            self._claimed.discard(task_id)


# Singleton — replaced by DI in production
_queue: TaskQueue | None = None


def get_task_queue() -> TaskQueue:
    global _queue
    if _queue is None:
        _queue = TaskQueue()
    return _queue


def reset_task_queue() -> None:
    """Drop the process singleton, so a later lifespan can install a fresh one.

    Startup refuses to replace a queue that already accepted tasks, which is
    right — a queued task cannot be given a Run after the fact. But shutdown
    never cleared it, so any interpreter that ran the FastAPI lifespan twice
    after serving traffic (an embedded server, a TestClient reused across
    modules) could not start again. Teardown clearing the singleton is what
    makes the startup check a guard rather than a one-shot latch.
    """
    global _queue
    _queue = None


def configure_task_queue(
    *,
    admitter: TaskAdmitter | None,
    idempotency_store: TaskIdempotencyStore | None = None,
) -> TaskQueue:
    """Install the process singleton with a Run admitter wired (#41).

    Call once at startup, before anything resolves `get_task_queue`. FastAPI
    routes depend on the singleton, so the admitter has to reach it here rather
    than at each call site — and it has to be installed before the first
    submission, because a task admitted without a Run cannot be given one
    afterwards without inventing its execution history. The idempotency store
    rides along for the same reason (#1176): a claim tier chosen after the
    first submission would leave those first submissions unreconcilable.
    """
    global _queue
    if _queue is not None and _queue._tasks:
        raise RuntimeError(
            "configure_task_queue() called after tasks were submitted; the "
            "already-queued tasks have no Run and cannot be given one"
        )
    _queue = TaskQueue(admitter=admitter, idempotency_store=idempotency_store)
    return _queue

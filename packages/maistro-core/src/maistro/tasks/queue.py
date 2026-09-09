"""In-memory task queue with best-effort TaskRecord persistence (ADR-018).

Live task state is held in memory. When a database is configured
(``get_async_session_factory()`` returns a factory), every mutation —
``submit()``, ``update_status()``, ``set_result()`` and ``update_progress()``
— upserts a ``TaskRecord`` row, fire-and-forget, so task execution never
fails because the database is unavailable. Writes for one task are chained so
they land in the order the state changed. With no database the queue behaves
exactly as before and a restart loses all tasks.

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
from maistro.tasks.admission import TaskAdmitter
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
from maistro.tasks.models import TaskCreate, TaskProgress, TaskResponse, TaskResult, TaskStatus
from maistro.tasks.status import can_transition

logger = structlog.get_logger()


def _record_values(task: TaskResponse) -> dict[str, Any]:
    """Snapshot the TaskRecord column values for one task, taken synchronously
    so the fire-and-forget write cannot race later in-memory mutation."""
    return {
        "id": task.task_id,
        "run_id": task.run_id,
        "status": task.status.value,
        "description": task.description,
        "workspace": task.workspace,
        "tier": task.tier,
        "phase": task.phase,
        "progress": task.progress.model_dump(mode="json") if task.progress else None,
        "result": task.result.model_dump(mode="json") if task.result else None,
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

    async def submit(
        self,
        request: TaskCreate,
        *,
        user_id: str = "",
        workspace_id: str | None = None,
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
                request, user_id=user_id, workspace_id=workspace_id, idempotency_key=key
            )
        return await self._submit_idempotent(
            request, key, user_id=user_id, workspace_id=workspace_id
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
            request.model_copy(update={"user_id": owner}).model_dump(mode="json")
        )
        waited = 0
        while True:
            now = datetime.now(UTC)
            outcome = await store.claim(
                scope_key,
                fingerprint=fingerprint,
                request=request_json,
                now=now,
                replay_window=DEFAULT_REPLAY_WINDOW,
            )
            if isinstance(outcome, Replayed):
                await logger.ainfo(
                    "task_admission_replayed",
                    task_id=outcome.record.task_id,
                    run_id=outcome.record.run_id,
                    explicit_key=key is not None,
                )
                return self._replay_receipt(outcome.record)
            if isinstance(outcome, Claimed):
                break
            # Pending: a twin is mid-admission. Its lease lapses long before
            # this loop's bound, so a dead twin's claim is taken over by the
            # next iteration rather than waited on forever.
            waited += 1
            if waited > MAX_PENDING_POLLS:
                raise IdempotencyPendingTimeout(
                    "a concurrent submission under this idempotency key has not "
                    "resolved within the bounded wait"
                )
            await asyncio.sleep(PENDING_POLL)
        try:
            task = await self._submit_once(
                request, user_id=user_id, workspace_id=workspace_id, idempotency_key=key
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

    def _replay_receipt(self, record: AdmissionRecord) -> TaskResponse:
        """The original submission's answer, without minting anything.

        The live receipt when this process still holds it; otherwise one
        reconstructed from the claim's stored request. A reconstructed receipt
        says ``queued`` because that is what admission said — the Run behind it
        has moved on without the queue, and current state is read from the
        task/Run endpoints, not from a replay.
        """
        if record.task_id is not None:
            live = self._tasks.get(record.task_id)
            if live is not None:
                return live
        stored = TaskCreate.model_validate_json(record.request)
        if record.task_id is None:  # pragma: no cover - replayed claims are admitted
            raise RuntimeError("replayed admission claim carries no receipt id")
        return TaskResponse(
            task_id=record.task_id,
            status=TaskStatus.QUEUED,
            description=stored.description,
            workspace=stored.workspace,
            user_id=stored.user_id or "",
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

    async def _submit_once(
        self,
        request: TaskCreate,
        *,
        user_id: str = "",
        workspace_id: str | None = None,
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
            task_type=request.task_type,
            agent_id=request.agent_id,
            capability=request.capability,
            program_context=request.program_context,
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
                    task.run_id, status, result=result, error=error
                )
            ):
                logger.warning(
                    "run_refused_task_transition",
                    task_id=task_id,
                    run_id=task.run_id,
                    current=task.status.value,
                    requested=status.value,
                )
                return False

            task.status = status
            task.phase = status.value

            if status == TaskStatus.PLANNING:
                task.started_at = datetime.now(UTC)
            elif status in _TERMINAL:
                task.completed_at = datetime.now(UTC)
                active_tasks.dec()
                if status == TaskStatus.COMPLETED:
                    tasks_completed_total.inc()
                elif status == TaskStatus.FAILED:
                    tasks_failed_total.inc()

            self._persist(task)

        self._notify(task_id)
        return True

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

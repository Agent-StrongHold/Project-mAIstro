"""Background schedule runner — turns due schedules into canonical Runs.

Recurrence and fire semantics live in `maistro.scheduling`: this module is
the loop that asks "what is due?" and performs the effects. It owns no cron
dialect of its own — the matcher that used to live here indexed day-of-week
by Python's Monday=0 convention (firing every `0`-means-Sunday schedule a day
late) and ANDed day-of-month with day-of-week where POSIX ORs them.

A fire produces a Run through the same provenanced durable path every other
Hive DAG execution uses, so scheduled work is not a second lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from maistro.scheduling import FireDecision, OverlapPolicy, Schedule, evaluate

logger = logging.getLogger(__name__)

# The Hive `/v1/schedules` model has no timezone column yet, so recurrence is
# evaluated in UTC. The core definition carries a timezone, so adding the
# column is the only remaining step to per-user local schedules.
_DEFAULT_TIMEZONE = "UTC"

# Fallback creation time for a row that predates the column. Treating such a
# row as "created at the dawn of time" keeps it firing; treating it as new
# would silently retire it.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_runner: _ScheduleRunner | None = None


def start_scheduler() -> None:
    global _runner
    if _runner is not None:
        return
    _runner = _ScheduleRunner()
    # Keep a reference to the background task so it isn't garbage-collected mid-flight.
    _runner.task = asyncio.ensure_future(_runner.run())


def stop_scheduler() -> None:
    global _runner
    if _runner is not None:
        _runner.stop()
        _runner = None


class ScheduleNotFireable(Exception):
    """A fire was asked for and could not happen. The reason is the message."""


async def fire_now(sid: str) -> str:
    """Fire a schedule on demand, through the path a tick uses.

    `POST /v1/schedules/{id}/run` used to stamp `last_run` and stop there: no
    Run, no cursor, nothing counted. That is the same "receipt for work that
    never started" the tick path carried before #231 — a schedule asserting it
    fired with no `run_id` anywhere — and it outlived that fix because it sits
    on the route rather than in the loop.

    A manual fire is a fire: it creates a canonical Run, records the cursor,
    and counts against `max_runs`. Raises `ScheduleNotFireable` rather than
    half-firing, so the caller can say why.

    **It advances the cursor**, which is the one real cost: occurrences owed
    from before now are no longer backfilled, because `last_fired_at` moves to
    now. The next *scheduled* occurrence is unaffected — `next_fire_after(now)`
    is still it — so what is given up is bounded by the catch-up window. That
    is the trade chosen for "run it now" meaning the schedule has run now.
    """
    import stores

    schedule = stores.schedules.get(sid)
    if schedule is None:
        raise ScheduleNotFireable(f"schedule {sid} does not exist")

    runner = _runner or _ScheduleRunner()
    store = runner._canonical_store()
    definition = await runner._definition_for(sid, schedule, store=store)
    if definition is None:
        raise ScheduleNotFireable(
            f"schedule {sid} names no mission template, so there is nothing to run"
        )
    if definition.exhausted:
        raise ScheduleNotFireable(f"schedule {sid} has used all {definition.max_runs} of its runs")

    now = datetime.now(UTC)
    run_id = await runner._fire_schedule(sid, schedule, scheduled_for=now, catchup=False)
    if run_id is None:
        # `_fire_schedule` has already logged and audited why. The cursor is
        # deliberately not advanced: the occurrence stays owed, exactly as it
        # does on the tick path.
        raise ScheduleNotFireable(
            f"schedule {sid} could not create a Run; its target may not be registered"
        )

    await runner._record_fire(
        sid,
        schedule,
        definition,
        store=store,
        fire=FireDecision(scheduled_for=now, catchup=False),
        run_id=run_id,
    )
    return run_id


class _ScheduleRunner:
    def __init__(self) -> None:
        self._running = True
        self._last_check: datetime | None = None
        self._last_repair: datetime | None = None
        # Schedules with a Run this loop started and has not yet finished.
        # The overlap policy is only meaningful if this is answered truthfully.
        self._in_flight: set[str] = set()
        self.task: asyncio.Task[None] | None = None

    def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        self._last_check = datetime.now(UTC)
        while self._running:
            await asyncio.sleep(30)
            try:
                await self._tick()
            except Exception as exc:
                logger.warning("Schedule tick failed: %s", exc)
            try:
                await self._self_repair_tick()
            except Exception as exc:
                logger.warning("Self-repair tick failed: %s", exc)

    async def _self_repair_tick(self) -> None:
        """Run the self_repair loop on its configured cadence (SPEC-188).

        Resolution is the kill-switch: a disabled slot resolves to None and
        nothing runs. interval <= 0 disables the periodic loop entirely.
        """
        from config import get_settings

        interval = get_settings().self_repair_interval_s
        if interval <= 0:
            return
        now = datetime.now(UTC)
        if self._last_repair is not None and (now - self._last_repair).total_seconds() < interval:
            return
        self._last_repair = now

        from services.capabilities_wiring import run_self_repair_once
        from services.engine import get_engine

        registry = get_engine().capabilities
        await run_self_repair_once(registry)

    async def _tick(self) -> None:
        import stores

        now = datetime.now(UTC)
        for sid, schedule in list(stores.schedules.items()):
            if not getattr(schedule, "enabled", False):
                continue
            try:
                await self._evaluate_schedule(sid, schedule, now=now)
            except Exception as exc:
                logger.warning("Failed to evaluate schedule %s: %s", sid, exc)

        self._last_check = now

    def _as_definition(self, sid: str, schedule: Any) -> Schedule | None:
        """Project the live `/v1/schedules` row onto the canonical definition.

        The HTTP surface keeps its shape; only the semantics move. Overlap
        defaults to SKIP so a long agent Run is never stacked on itself.

        Returns None for a row with no target: a schedule that names nothing
        to run cannot produce work, and a definition is required to say what
        it instantiates rather than carrying an empty pointer.
        """
        template_id = str(getattr(schedule, "mission_template_id", "") or "")
        if not template_id:
            return None
        return Schedule(
            schedule_id=sid,
            workspace_id=f"hive:schedule:{sid}",
            project_id=f"hive:schedule:{sid}",
            name=str(getattr(schedule, "name", "") or sid),
            cron=str(schedule.cron_expression),
            # From the row now, not hardcoded. `getattr` with the same default
            # keeps a row (or a stub) predating the column evaluating in UTC,
            # which is exactly what it did before.
            timezone=str(getattr(schedule, "timezone", None) or _DEFAULT_TIMEZONE),
            graph_template_id=template_id,
            # Bounded recurrence is enforced on the canonical cursor, which can
            # only apply a bound it is told about. `None` — every row before
            # this column — stays unbounded.
            max_runs=getattr(schedule, "max_runs", None),
            # The row's own flag rather than a hardcoded True. `_tick` already
            # skips a disabled row, so this only matters for the write below:
            # `_definition_for` ends in `store.put(definition)`, and putting a
            # hardcoded True would resurrect a schedule that `record_fire`
            # disabled on exhaustion.
            enabled=bool(getattr(schedule, "enabled", True)),
            overlap_policy=OverlapPolicy.SKIP,
            last_fired_at=getattr(schedule, "last_run", None),
            # Carry the row's real creation time. Without it the definition
            # defaults to *now*, and the rule that a schedule cannot fire for
            # occurrences predating its own existence would suppress every
            # tick — a scheduler that never fires.
            created_at=getattr(schedule, "created_at", None) or _EPOCH,
            actor_principal_id=str(getattr(schedule, "user_id", "") or "") or None,
        )

    @staticmethod
    def _canonical_store() -> Any:
        """The Container's ScheduleStore, or None when there is no bridge.

        None is a real answer here, exactly as it is for `engine.run_store`: a
        Conductor running without the core bridge has no canonical store, and
        the cursor then stays on the in-memory row as it did before #231 —
        degraded, but not broken.
        """
        try:
            from services.engine import get_engine

            return get_engine().schedule_store
        except Exception:  # pragma: no cover - engine unavailable in tests
            return None

    async def _definition_for(self, sid: str, schedule: Any, *, store: Any) -> Schedule | None:
        """The canonical definition to evaluate, with the durable cursor on it.

        The `/v1/schedules` row stays the editable surface — a changed cron or a
        disable must take effect — so the projection is rebuilt from it every
        tick. What comes from the store instead is the *cursor*: `last_fired_at`,
        `last_run_id`, `runs_so_far` and `next_due_at`. Those are the fields that
        say what has already happened, and the in-memory row is the wrong place
        to keep them: it is lost on restart and private to one replica.
        """
        definition = self._as_definition(sid, schedule)
        if definition is None or store is None:
            return definition
        recorded = await store.get(sid)
        if recorded is not None:
            definition = definition.model_copy(
                update={
                    "last_fired_at": recorded.last_fired_at,
                    "last_run_id": recorded.last_run_id,
                    "runs_so_far": recorded.runs_so_far,
                    "next_due_at": recorded.next_due_at,
                    "created_at": recorded.created_at,
                }
            )
        await store.put(definition)
        return definition

    async def _evaluate_schedule(self, sid: str, schedule: Any, *, now: datetime) -> None:
        store = self._canonical_store()
        definition = await self._definition_for(sid, schedule, store=store)
        if definition is None:
            logger.debug("Schedule %s names no mission template; nothing to run", sid)
            return
        decision = evaluate(definition, now=now, active_run=sid in self._in_flight)

        for skipped in decision.skipped:
            logger.info(
                "Schedule %s skipped occurrence %s: %s",
                sid,
                skipped.scheduled_for.isoformat(),
                skipped.reason.value,
            )

        # `decision.exhausted` is the engine's own answer to "does `max_runs`
        # run out once these fires are recorded", so exhaustion is not
        # re-derived here from a `runs_so_far` that was read once per tick and
        # is stale for any fire after the first. It describes the batch, so it
        # belongs on the batch's last fire — which under `OverlapPolicy.SKIP`,
        # hardcoded in `_as_definition`, is also its only one.
        last_index = len(decision.fires) - 1
        for fire_index, fire in enumerate(decision.fires):
            self._in_flight.add(sid)
            try:
                # `catchup` was evaluated and then dropped here. A backfill
                # after downtime and an on-time fire mean different things, and
                # once the Run exists there is nothing left to tell them apart
                # (#145).
                run_id = await self._fire_schedule(
                    sid, schedule, scheduled_for=fire.scheduled_for, catchup=fire.catchup
                )
            finally:
                self._in_flight.discard(sid)
            if run_id is None:
                # Stop the batch, and leave the cursor where it is. The
                # occurrence is still owed, and so is every one after it —
                # advancing past a fire that produced no Run is the receipt for
                # work that never started this issue exists to remove. Stopping
                # rather than continuing is `ScheduleRunAdmitter`'s rule too:
                # the cursor covers a contiguous range, so skipping one failure
                # would either lose it or duplicate its successors.
                return
            await self._record_fire(
                sid,
                schedule,
                definition,
                store=store,
                fire=fire,
                run_id=run_id,
                exhausted=decision.exhausted and fire_index == last_index,
            )

    async def _record_fire(
        self,
        sid: str,
        schedule: Any,
        definition: Schedule,
        *,
        store: Any,
        fire: Any,
        run_id: str,
        exhausted: bool = False,
    ) -> None:
        """Advance the cursor, canonically when there is a store to advance.

        ``exhausted`` says this fire spends the last of `max_runs`; the caller
        gets it from `evaluate`, which is where the count is not stale.
        """
        import stores

        fired_at = fire.scheduled_for
        next_due_at = definition.next_fire_after(fired_at)
        if store is not None:
            await store.record_fire(
                sid,
                fired_at=fired_at,
                run_id=run_id,
                next_due_at=next_due_at,
                disable=exhausted,
            )
        # The `/v1/schedules` row keeps showing what it always showed. It is a
        # projection now rather than the record, so it is written after the
        # cursor it mirrors, never before.
        current = stores.schedules.get(sid)
        if current is not None:
            update: dict[str, Any] = {
                "last_run": fired_at,
                # The Run that claimed this occurrence, so a caller holding the
                # schedule can reach it. `last_run` alone said only *that*
                # something fired.
                "last_run_id": run_id,
                "next_run": next_due_at,
                "updated_at": datetime.now(UTC),
            }
            if exhausted:
                # The same disable `record_fire` just wrote canonically, on the
                # surface a user reads. Without it the row keeps reporting
                # `enabled: true` for a spent schedule, and — because `_tick`
                # skips only disabled rows — the next tick would `put` that
                # `enabled: true` straight back over the canonical disable.
                update["enabled"] = False
                update["next_run"] = None
            stores.schedules[sid] = current.model_copy(update=update)
        if exhausted:
            logger.info(
                "Schedule %s reached max_runs (%s) and is now disabled",
                sid,
                definition.max_runs,
            )
        logger.info("Schedule %s fired: %s (run %s)", sid, schedule.name, run_id)

    async def _fire_schedule(
        self,
        sid: str,
        schedule: Any,
        *,
        scheduled_for: datetime | None = None,
        catchup: bool = False,
    ) -> str | None:
        """Create the occurrence's Run, and return its id, or None if it did not.

        The cursor advance is the caller's, and only on a returned run_id. This
        function used to stamp `last_run` on its first line and check whether the
        work could happen afterwards, so an unresolvable template or a failed Run
        creation left a schedule asserting it had fired with no `run_id` anywhere
        — a receipt for work that never started (#231).
        """
        t = datetime.now(UTC)

        template_id = schedule.mission_template_id
        if not template_id:
            return None

        from routes.audit import log_audit

        log_audit(
            "schedule_fire",
            "system",
            target=sid,
            detail={
                "name": schedule.name,
                # The nominal occurrence, not the moment the tick noticed it,
                # so a Run that started late is still attributable.
                "scheduled_for": (scheduled_for or t).isoformat(),
                "catchup": catchup,
            },
        )

        # Schedule -> Run: a firing whose target is a registered DAG produces
        # canonical durable work — the same GraphTemplate-provenanced Run path
        # every other Hive DAG execution uses — instead of a bare audit line.
        # Targets that don't resolve keep the historical log-only behavior
        # (no other mission-template kind is executable yet).
        from services.dag_agents import get_registry, run_registered_dag

        if get_registry().get(str(template_id)) is None:
            # `DagRegistry` is an in-process dict, so this is the normal state
            # after a restart until something re-registers the DAG -- exactly
            # when an operator most needs to be told (#145).
            #
            # Returning None now leaves the occurrence *owed*: the caller does
            # not advance the cursor, so once the DAG is registered the fire
            # happens. Before #231 the cursor was already advanced by the time
            # this branch ran, and the comment here argued that was deliberate
            # because rewinding would stampede. That reasoning was sound about
            # rewinding and wrong about the remedy -- never advancing in the
            # first place costs nothing, and the catch-up window (which bounds
            # backfill to an hour by default) is what stops the stampede.
            logger.warning(
                "Schedule %s targets mission template %s, which is not registered; "
                "no Run was created. The in-process DAG registry is empty until "
                "something re-registers it, which is the usual state after a restart.",
                sid,
                template_id,
            )
            log_audit(
                "schedule_run",
                "system",
                target=sid,
                detail={"dag_id": str(template_id), "error": "template_not_registered"},
            )
            return None

        scope_id = f"hive:schedule:{sid}"
        user_id = str(getattr(schedule, "user_id", "") or "") or None
        try:
            graph, record = await run_registered_dag(
                str(template_id),
                workspace_id=scope_id,
                project_id=scope_id,
                user_id=user_id,
                # On the Run, not beside it. #46 asks for schedule provenance
                # "retained on the Run"; it lived only in the `schedule_run`
                # audit line, so a scheduled Run was indistinguishable from one
                # a person started. Tasks (#41) and chat turns (#131) both
                # carry theirs on the Run; scheduling was the outlier.
                provenance={
                    "admission_source": "schedule",
                    "schedule_id": sid,
                    "schedule_name": schedule.name,
                    # The nominal occurrence, not the tick that noticed it, so
                    # a Run that started late is still attributable to the
                    # occurrence it belongs to.
                    "scheduled_for": (scheduled_for or t).isoformat(),
                    "catchup": catchup,
                },
            )
        except Exception as exc:
            logger.warning("Schedule %s run failed: %s", sid, exc)
            log_audit(
                "schedule_run",
                "system",
                target=sid,
                detail={"dag_id": str(template_id), "error": type(exc).__name__},
            )
            return None

        provenance = graph.source_template
        log_audit(
            "schedule_run",
            "system",
            target=sid,
            detail={
                "dag_id": str(template_id),
                "run_id": record.run.run_id,
                "status": str(record.run.status.value),
                "template_version": provenance.template_version if provenance else None,
            },
        )
        return str(record.run.run_id)

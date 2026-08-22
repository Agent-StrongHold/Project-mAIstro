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

from maistro.runs.admission import ADMISSION_SOURCE
from maistro.scheduling import OverlapPolicy, Schedule, evaluate
from maistro.scheduling.admission import (
    CATCHUP_KEY,
    SCHEDULE_ID_KEY,
    SCHEDULE_SOURCE,
    SCHEDULED_FOR_KEY,
)

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
            timezone=_DEFAULT_TIMEZONE,
            graph_template_id=template_id,
            enabled=True,
            overlap_policy=OverlapPolicy.SKIP,
            last_fired_at=getattr(schedule, "last_run", None),
            # Carry the row's real creation time. Without it the definition
            # defaults to *now*, and the rule that a schedule cannot fire for
            # occurrences predating its own existence would suppress every
            # tick — a scheduler that never fires.
            created_at=getattr(schedule, "created_at", None) or _EPOCH,
            actor_principal_id=str(getattr(schedule, "user_id", "") or "") or None,
        )

    async def _evaluate_schedule(self, sid: str, schedule: Any, *, now: datetime) -> None:
        definition = self._as_definition(sid, schedule)
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

        for fire in decision.fires:
            self._in_flight.add(sid)
            try:
                await self._fire_schedule(
                    sid,
                    schedule,
                    scheduled_for=fire.scheduled_for,
                    catchup=fire.catchup,
                )
            finally:
                self._in_flight.discard(sid)

    async def _fire_schedule(
        self,
        sid: str,
        schedule: Any,
        *,
        scheduled_for: datetime | None = None,
        catchup: bool = False,
    ) -> None:
        import stores

        t = datetime.now(UTC)
        stores.schedules[sid] = schedule.model_copy(update={"last_run": t, "updated_at": t})
        logger.info("Schedule %s fired: %s", sid, schedule.name)

        template_id = schedule.mission_template_id
        if not template_id:
            return

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
            },
        )

        # Schedule -> Run: a firing whose target is a registered DAG produces
        # canonical durable work — the same GraphTemplate-provenanced Run path
        # every other Hive DAG execution uses — instead of a bare audit line.
        # Targets that don't resolve keep the historical log-only behavior
        # (no other mission-template kind is executable yet).
        from services.dag_agents import get_registry, run_registered_dag

        if get_registry().get(str(template_id)) is None:
            # `DagRegistry` is in-process, so after a restart a schedule whose
            # DAG has not been re-registered lands here — and `last_run` was
            # stamped above, so from the outside the fire looks like it
            # happened. Say so rather than returning silently; the durable
            # registry that removes this case is #145's scope item 1.
            logger.warning(
                "Schedule %s names DAG %s, which is not registered in this process; "
                "no Run was created",
                sid,
                template_id,
            )
            log_audit(
                "schedule_run",
                "system",
                target=sid,
                detail={"dag_id": str(template_id), "error": "template_not_registered"},
            )
            return

        scope_id = f"hive:schedule:{sid}"
        user_id = str(getattr(schedule, "user_id", "") or "") or None
        try:
            graph, record = await run_registered_dag(
                str(template_id),
                workspace_id=scope_id,
                project_id=scope_id,
                user_id=user_id,
                # On the Run, not only in the audit line beside it (#145). A
                # scheduled Run that cannot say which occurrence it belongs to
                # is attributable only by correlating timestamps, and a Run
                # that started late correlates to the wrong one.
                provenance={
                    ADMISSION_SOURCE: SCHEDULE_SOURCE,
                    SCHEDULE_ID_KEY: sid,
                    SCHEDULED_FOR_KEY: (scheduled_for or t).isoformat(),
                    CATCHUP_KEY: catchup,
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
            return

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

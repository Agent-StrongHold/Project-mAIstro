"""Background schedule runner — evaluates cron expressions and fires scheduled missions.

Uses a lightweight cron matcher (no external deps) for common patterns.
Runs as an asyncio background task started by the app lifespan.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

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
        now = datetime.now(UTC)
        if self._last_check is None:
            self._last_check = now
            return

        import stores

        for sid, schedule in list(stores.schedules.items()):
            if not schedule.enabled:
                continue
            if _should_fire(schedule.cron_expression, self._last_check, now):
                try:
                    await self._fire_schedule(sid, schedule)
                except Exception as exc:
                    logger.warning("Failed to fire schedule %s: %s", sid, exc)

        self._last_check = now

    async def _fire_schedule(self, sid: str, schedule: object) -> None:
        import stores

        t = datetime.now(UTC)
        stores.schedules[sid] = schedule.model_copy(  # type: ignore[attr-defined]
            update={"last_run": t, "updated_at": t}
        )
        logger.info("Schedule %s fired: %s", sid, schedule.name)  # type: ignore[attr-defined]

        template_id = schedule.mission_template_id  # type: ignore[attr-defined]
        if not template_id:
            return

        from routes.audit import log_audit

        log_audit("schedule_fire", "system", target=sid, detail={"name": schedule.name})  # type: ignore[attr-defined]

        # Schedule → Run: a firing whose target is a registered DAG produces
        # canonical durable work — the same GraphTemplate-provenanced Run path
        # every other Hive DAG execution uses — instead of a bare audit line.
        # Targets that don't resolve keep the historical log-only behavior
        # (no other mission-template kind is executable yet).
        from services.dag_agents import get_registry, run_registered_dag

        if get_registry().get(str(template_id)) is None:
            return

        scope_id = f"hive:schedule:{sid}"
        user_id = str(getattr(schedule, "user_id", "") or "") or None
        try:
            graph, record = await run_registered_dag(
                str(template_id),
                workspace_id=scope_id,
                project_id=scope_id,
                user_id=user_id,
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


def _should_fire(cron_expr: str, last: datetime, now: datetime) -> bool:
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return False
    minute, hour, day_month, month, day_week = parts
    checks = [
        _field_matches(minute, now.minute, 0, 59),
        _field_matches(hour, now.hour, 0, 23),
        _field_matches(day_month, now.day, 1, 31),
        _field_matches(month, now.month, 1, 12),
        _field_matches(day_week, now.weekday(), 0, 6),
    ]
    if not all(checks):
        return False
    delta = now - last
    return delta >= timedelta(minutes=1)


def _field_matches(field: str, value: int, low: int, high: int) -> bool:
    if field == "*":
        return True
    if "," in field:
        return any(_field_matches(f.strip(), value, low, high) for f in field.split(","))
    if "/" in field:
        base, step = field.split("/", 1)
        step_val = int(step)
        if step_val <= 0:
            return False
        start = low if base == "*" else int(base)
        return value >= start and (value - start) % step_val == 0
    if "-" in field:
        lo, hi = field.split("-", 1)
        return int(lo) <= value <= int(hi)
    return int(field) == value

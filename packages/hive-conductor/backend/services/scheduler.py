"""Background schedule runner — turns due schedules into canonical Runs.

Recurrence and fire semantics live in ``maistro.scheduling``.  A configured
Hive process delegates the complete evaluate -> occurrence claim -> Run admit
-> cursor advance transaction to ``ScheduleRunAdmitter`` — for recurring ticks
*and* for the manual ``fire_now`` surface (#1120), which admits a first-class
manual occurrence through the same Run store the admitter claims nominal
occurrences with.  The historical in-process path remains only as a
compatibility fallback for standalone/demo contexts that have no core
Container; it is not the production authority.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from maistro.runs.model import TERMINAL_RUN_STATUSES
from maistro.scheduling import FireDecision, OverlapPolicy, Schedule, evaluate
from maistro.scheduling.admission import ScheduleRunAdmitter

logger = logging.getLogger(__name__)

_DEFAULT_TIMEZONE = "UTC"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_runner: _ScheduleRunner | None = None


def start_scheduler() -> None:
    global _runner
    if _runner is not None:
        return
    _runner = _ScheduleRunner()
    _runner.task = asyncio.ensure_future(_runner.run())


def stop_scheduler() -> None:
    global _runner
    if _runner is not None:
        _runner.stop()
        _runner = None


class ScheduleNotFireable(Exception):
    """A fire was asked for and could not happen. The reason is the message."""


async def fire_now(sid: str, *, fire_id: str | None = None) -> str:
    """Fire a schedule on demand through the canonical schedule execution spine.

    A manual fire is a first-class manual occurrence (#1120), not a cron tick
    with a fabricated timestamp: its identity is ``(schedule_id, fire_id)``,
    claimed through the same Run store uniqueness the recurring admitter claims
    ``(schedule_id, scheduled_for)`` with.  A retried or concurrent call
    carrying the same ``fire_id`` therefore resolves to the Run the first call
    created — the documented reconciliation — instead of minting a second Run
    behind a fresh ``datetime.now()``.  The claim is durable canonical state, so
    the reconciliation survives a process restart.  A caller that sends no
    ``fire_id`` gets a server-minted one: each such request is its own
    deliberate firing.

    What a manual fire deliberately does *not* do is move the recurring
    enumeration cursor (``last_fired_at``/``next_due_at``): advancing it would
    suppress nominal occurrences still owed inside the catch-up window, which
    is recurrence semantics a hand fire must not rewrite.  It does count as a
    fire (``runs_so_far``, ``max_runs``) and its Run becomes the schedule's
    ``last_run_id``.

    Standalone/demo contexts with no core Container keep the historical
    immediate execution path, selected by exactly the same gate the recurring
    loop uses; a configured production instance never reaches it.
    """
    import stores

    schedule = stores.schedules.get(sid)
    if schedule is None:
        raise ScheduleNotFireable(f"schedule {sid} does not exist")

    runner = _runner or _ScheduleRunner()
    container = runner._canonical_container()
    if runner._canonical_admitter(container) is not None:
        assert container is not None  # for the type checker; the gate proved it
        return await runner._fire_now_canonical(sid, schedule, container, fire_id=fire_id)

    # Standalone/demo compatibility path.  Production must never reach this:
    # the gate above is the same ``_canonical_admitter`` predicate the recurring
    # loop uses, so an instance that recurses canonically also fires manually
    # canonically.  It exists so a scheduler unit can still be exercised
    # without constructing the entire Container.
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
        # Compatibility fallback only.  Configured production overlap is read
        # from the canonical Run named by Schedule.last_run_id.
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
        """Run the self_repair loop on its configured cadence (SPEC-188)."""
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
        """Project the live ``/v1/schedules`` row onto the canonical definition.

        The synthetic scope values below are retained only for the standalone
        compatibility path.  A configured Hive replaces them with the actual
        configured Workspace and its canonical Root Project before persisting
        or admitting the definition.
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
            timezone=str(getattr(schedule, "timezone", None) or _DEFAULT_TIMEZONE),
            graph_template_id=template_id,
            max_runs=getattr(schedule, "max_runs", None),
            enabled=bool(getattr(schedule, "enabled", True)),
            overlap_policy=OverlapPolicy.SKIP,
            last_fired_at=getattr(schedule, "last_run", None),
            created_at=getattr(schedule, "created_at", None) or _EPOCH,
            actor_principal_id=str(getattr(schedule, "user_id", "") or "") or None,
        )

    @staticmethod
    def _canonical_container() -> Any:
        """Return the wired core Container, or None in standalone/demo tests."""
        try:
            from services.engine import get_engine

            engine = get_engine()
            return getattr(getattr(engine, "_agent_port", None), "container", None)
        except Exception:  # pragma: no cover - engine unavailable in isolation
            return None

    @staticmethod
    def _canonical_store() -> Any:
        """The Container's ScheduleStore, or None when there is no bridge."""
        container = _ScheduleRunner._canonical_container()
        return getattr(container, "schedule_store", None) if container is not None else None

    @staticmethod
    def _canonical_admitter(container: Any) -> ScheduleRunAdmitter | None:
        """Build the one production schedule admission boundary.

        Attribute reads are explicit so the wiring-read fitness gate can prove
        that these Container fields are actually consumed.
        """
        if container is None:
            return None
        run_store = container.run_store
        template_store = container.template_store
        schedule_store = container.schedule_store
        if run_store is None or template_store is None or schedule_store is None:
            return None
        return ScheduleRunAdmitter(run_store, template_store, schedule_store)

    async def _canonical_scope(self, schedule: Any, container: Any) -> tuple[str, str]:
        """Resolve real Workspace/Project ownership for a Hive schedule.

        The current product surface has no per-schedule Project selector, so a
        schedule defaults to Hive's configured Workspace and that Workspace's
        canonical Root Project — the same rule ordinary task admission uses.
        Future rows may carry explicit ``workspace_id``/``project_id`` fields;
        when present they are honored rather than overwritten.
        """
        from config import get_settings

        workspace_id = str(
            getattr(schedule, "workspace_id", "") or get_settings().hive_default_workspace_id
        )
        explicit_project = str(getattr(schedule, "project_id", "") or "")
        if explicit_project:
            project = await container.project_scope_store.get(explicit_project)
            if project is None:
                raise ValueError(f"schedule names unknown Project {explicit_project!r}")
            if project.workspace_id != workspace_id:
                raise ValueError("schedule Project does not belong to its Workspace")
            return workspace_id, explicit_project

        root = await container.project_scope_store.root_for_workspace(workspace_id)
        return workspace_id, root.project_id

    async def _prime_template(self, definition: Schedule, container: Any) -> None:
        """Persist the current Hive DAG descriptor as a canonical GraphTemplate.

        Reads always come from the template store afterwards.  The in-process
        registry is only a migration source for a descriptor that has not been
        written there yet; after that, a restart with an empty registry does not
        erase the scheduled target.
        """
        template_store = container.template_store
        existing = await template_store.get(
            definition.graph_template_id, version=definition.template_version
        )
        if existing is not None:
            if existing.workspace_id != definition.workspace_id:
                raise ValueError(
                    f"GraphTemplate {definition.graph_template_id!r} belongs to Workspace "
                    f"{existing.workspace_id!r}, not {definition.workspace_id!r}"
                )
            return

        from maistro.graph.template_adapter import descriptor_to_template
        from services.dag_agents import get_registry

        descriptor = get_registry().get(definition.graph_template_id)
        if descriptor is None:
            # ScheduleRunAdmitter will return the precise GraphTemplateNotFound
            # failure and, critically, leave the occurrence owed.
            return
        await template_store.put(
            descriptor_to_template(descriptor, workspace_id=definition.workspace_id)
        )

    async def _definition_for(
        self,
        sid: str,
        schedule: Any,
        *,
        store: Any,
        scope: tuple[str, str] | None = None,
    ) -> Schedule | None:
        """Return the editable definition with the durable cursor overlaid."""
        definition = self._as_definition(sid, schedule)
        if definition is None:
            return None
        if scope is not None:
            definition = definition.model_copy(
                update={"workspace_id": scope[0], "project_id": scope[1]}
            )
        if store is None:
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

    async def _canonical_active_run(self, definition: Schedule, container: Any) -> bool:
        """Whether the schedule's latest Run is still non-terminal."""
        if not definition.last_run_id:
            return False
        run = await container.run_store.get_run(definition.last_run_id)
        return run is not None and run.status not in TERMINAL_RUN_STATUSES

    @staticmethod
    def _project_cursor(sid: str, recorded: Schedule) -> None:
        """Mirror canonical cursor state onto the legacy Hive response row."""
        import stores

        current = stores.schedules.get(sid)
        if current is None:
            return
        stores.schedules[sid] = current.model_copy(
            update={
                "last_run": recorded.last_fired_at,
                "last_run_id": recorded.last_run_id,
                "next_run": recorded.next_due_at,
                "enabled": recorded.enabled,
                "updated_at": datetime.now(UTC),
            }
        )

    async def _audit_canonical_admission(
        self,
        sid: str,
        schedule: Any,
        admission: Any,
        container: Any,
    ) -> None:
        """Keep the existing Hive audit surface while core owns admission."""
        from routes.audit import log_audit

        for run_id in admission.run_ids:
            run = await container.run_store.get_run(run_id)
            provenance = dict(run.provenance) if run is not None else {}
            # GraphSnapshot is an immutable envelope (extra="forbid") that
            # carries the definition as JSON; the durable template identity
            # lives on the materialized Graph, not on the snapshot itself.
            template = run.graph.materialize().source_template if run is not None else None
            log_audit(
                "schedule_fire",
                "system",
                target=sid,
                detail={
                    "name": schedule.name,
                    "scheduled_for": provenance.get("scheduled_for"),
                    "catchup": provenance.get("catchup", False),
                },
            )
            log_audit(
                "schedule_run",
                "system",
                target=sid,
                detail={
                    "dag_id": str(schedule.mission_template_id),
                    "run_id": run_id,
                    "status": run.status.value if run is not None else "unknown",
                    "template_version": (
                        template.template_version if template is not None else None
                    ),
                },
            )
        for exc in admission.failures:
            log_audit(
                "schedule_run",
                "system",
                target=sid,
                detail={
                    "dag_id": str(schedule.mission_template_id),
                    "error": type(exc).__name__,
                },
            )

    async def _fire_now_canonical(
        self,
        sid: str,
        schedule: Any,
        container: Any,
        *,
        fire_id: str | None = None,
    ) -> str:
        """Admit a manual fire as a first-class occurrence of the canonical spine.

        Same authority as a recurring tick — the canonical Run store's
        occurrence claim, a QUEUED admission, the Container consumer for
        execution — and the same scope and template resolution.  Different
        identity (a ``fire_id`` token, not a cron instant) and different cursor
        semantics (``runs_so_far``/``last_run_id`` move; the enumeration cursor
        does not), which is what makes it a *manual* occurrence rather than a
        fake cron one (#1120).
        """
        from uuid import uuid4

        from routes.audit import log_audit

        from maistro.graph.templates import require_template
        from maistro.runs.model import RunStatus
        from maistro.runs.sources import (
            ADMISSION_SOURCE,
            SCHEDULE_FIRE_ID_KEY,
            SCHEDULE_ID_KEY,
            SCHEDULE_INPUTS_KEY,
            SCHEDULE_SOURCE,
            SCHEDULE_TRIGGER_KEY,
            SCHEDULE_TRIGGER_MANUAL,
            SCHEDULED_FOR_KEY,
        )
        from maistro.runs.store import DuplicateOccurrence

        scope = await self._canonical_scope(schedule, container)
        definition = await self._definition_for(
            sid, schedule, store=container.schedule_store, scope=scope
        )
        if definition is None:
            raise ScheduleNotFireable(
                f"schedule {sid} names no mission template, so there is nothing to run"
            )
        if definition.exhausted:
            raise ScheduleNotFireable(
                f"schedule {sid} has used all {definition.max_runs} of its runs"
            )

        await self._prime_template(definition, container)
        try:
            template = await require_template(
                container.template_store,
                definition.graph_template_id,
                version=definition.template_version,
            )
        except Exception as exc:
            # Nothing claimed, nothing recorded: the fire that could not be
            # admitted never existed, so there is no receipt to hand back.
            raise ScheduleNotFireable(
                f"schedule {sid} cannot resolve its mission template: {exc}"
            ) from exc

        token = fire_id or uuid4().hex
        requested_at = datetime.now(UTC)
        graph = template.instantiate(project_id=definition.project_id, name=schedule.name or None)
        provenance: dict[str, Any] = {
            ADMISSION_SOURCE: SCHEDULE_SOURCE,
            SCHEDULE_ID_KEY: sid,
            # The identity. Opaque and stable across retries of the same
            # logical request — never a wall-clock instant, which is how a
            # double submit used to become two Runs.
            SCHEDULE_FIRE_ID_KEY: token,
            SCHEDULE_TRIGGER_KEY: SCHEDULE_TRIGGER_MANUAL,
            # Observability, not identity: the instant the fire was asked for.
            SCHEDULED_FOR_KEY: requested_at.isoformat(),
        }
        if definition.inputs:
            provenance[SCHEDULE_INPUTS_KEY] = definition.inputs

        try:
            run = await container.run_store.create_run(
                graph,
                persona_id=definition.persona_id,
                actor_principal_id=definition.actor_principal_id,
                provenance=provenance,
                # QUEUED in the same insert, exactly like `_admit_one`: the
                # admission is the submission, and the consumer tick owns
                # execution from there.
                initial_status=RunStatus.QUEUED,
            )
        except DuplicateOccurrence:
            # Same logical request, already fired. The documented
            # reconciliation is the first call's receipt — no second Run, no
            # second count against max_runs. `find_occurrence_run` reads the
            # claim the winner holds, so this works across processes and
            # restarts, not just within one caller's memory.
            existing = await container.run_store.find_occurrence_run(provenance)
            if existing is None:  # pragma: no cover - claim without a Run
                raise ScheduleNotFireable(
                    f"schedule {sid} manual fire {token!r} was already admitted "
                    "but its Run is not resolvable"
                ) from None
            logger.info(
                "Schedule %s manual fire %s reconciled to existing Run %s",
                sid,
                token,
                existing.run_id,
            )
            self._project_manual_receipt(sid, requested_at, existing.run_id, exhausted=False)
            await self._consume_promptly(container)
            # ``str()`` because the store is ``Any`` here: the bridge is
            # duck-typed by design, and the receipt crossing back into typed
            # Hive code should be re-asserted at the boundary, not trusted as
            # ``Any``.
            return str(existing.run_id)

        # A manual fire counts (runs_so_far, max_runs) but does not advance the
        # recurring enumeration cursor: `ScheduleStore.record_fire` stamps
        # `last_fired_at` unconditionally, and moving it would make the next
        # tick resume enumeration after this hand fire — silently dropping
        # nominal occurrences still owed inside the catch-up window. So the
        # receipt is written as a definition update instead. Re-read first to
        # shrink (not close; the store is last-writer-wins) the window against
        # a concurrent recurring tick's own cursor write.
        exhausted = (
            definition.max_runs is not None and definition.runs_so_far + 1 >= definition.max_runs
        )
        recorded = await container.schedule_store.get(sid) or definition
        await container.schedule_store.put(
            recorded.model_copy(
                update={
                    "last_run_id": run.run_id,
                    "runs_so_far": recorded.runs_so_far + 1,
                    "next_due_at": None if exhausted else recorded.next_due_at,
                    "enabled": False if exhausted else recorded.enabled,
                    "updated_at": datetime.now(UTC),
                }
            )
        )

        log_audit(
            "schedule_fire",
            "system",
            target=sid,
            detail={
                "name": schedule.name,
                "scheduled_for": requested_at.isoformat(),
                "trigger": SCHEDULE_TRIGGER_MANUAL,
            },
        )
        log_audit(
            "schedule_run",
            "system",
            target=sid,
            detail={
                "dag_id": str(schedule.mission_template_id),
                "run_id": run.run_id,
                "status": str(run.status.value),
                "template_version": template.version,
                "trigger": SCHEDULE_TRIGGER_MANUAL,
            },
        )
        if exhausted:
            logger.info(
                "Schedule %s reached max_runs (%s) with a manual fire and is now disabled",
                sid,
                definition.max_runs,
            )
        self._project_manual_receipt(sid, requested_at, run.run_id, exhausted=exhausted)
        await self._consume_promptly(container)
        return str(run.run_id)

    def _project_manual_receipt(
        self,
        sid: str,
        requested_at: datetime,
        run_id: str,
        *,
        exhausted: bool,
    ) -> None:
        """Mirror a manual fire's receipt onto the legacy Hive response row.

        Same projection `_record_fire` performs, minus the cursor fields a
        manual fire does not own (`next_run` reflects the cron, not the hand
        fire, unless exhaustion just cleared it).
        """
        import stores

        current = stores.schedules.get(sid)
        if current is None:
            return
        update: dict[str, Any] = {
            "last_run": requested_at,
            "last_run_id": run_id,
            "updated_at": datetime.now(UTC),
        }
        if exhausted:
            update["enabled"] = False
            update["next_run"] = None
        stores.schedules[sid] = current.model_copy(update=update)

    @staticmethod
    async def _consume_promptly(container: Any) -> None:
        """Nudge the canonical consumer so the admitted Run starts now.

        The immediate UX a manual fire promises is kept by prompt *consumption*
        of the admitted Run, never by bypassing admission (#1120).
        `execute_admitted_runs` is the same operator-scheduled tick (ADR-019)
        that consumes recurring admissions; a hand fire merely asks it to run
        once, now.  Best-effort by design: if consumption cannot proceed (no
        claim capability wired, executor construction failure), the Run stays
        QUEUED — durable, visible, recoverable canonical state, the same
        posture a recurring admission has between ticks — and the caller still
        holds its receipt.
        """
        tick = getattr(container, "execute_admitted_runs", None)
        if tick is None:
            return
        try:
            await tick()
        except Exception as exc:
            logger.warning(
                "Schedule manual fire's prompt consumption deferred to the next tick: %s", exc
            )

    async def _evaluate_canonical(
        self,
        sid: str,
        schedule: Any,
        *,
        now: datetime,
        container: Any,
        admitter: ScheduleRunAdmitter,
    ) -> None:
        """Configured Hive path: one canonical scheduler authority."""
        scope = await self._canonical_scope(schedule, container)
        definition = await self._definition_for(
            sid, schedule, store=container.schedule_store, scope=scope
        )
        if definition is None:
            logger.debug("Schedule %s names no mission template; nothing to run", sid)
            return

        await self._prime_template(definition, container)
        admission = await admitter.admit_due(
            definition,
            now=now,
            active_run=await self._canonical_active_run(definition, container),
        )

        for skipped in admission.skipped:
            logger.info(
                "Schedule %s skipped occurrence %s: %s",
                sid,
                skipped.scheduled_for.isoformat(),
                skipped.reason.value,
            )
        for occurred in admission.already_fired:
            logger.info(
                "Schedule %s occurrence %s was already claimed by another runner",
                sid,
                occurred.isoformat(),
            )
        for exc in admission.failures:
            logger.warning("Schedule %s admission failed: %s", sid, exc)

        await self._audit_canonical_admission(sid, schedule, admission, container)
        recorded = await container.schedule_store.get(sid)
        if recorded is not None:
            self._project_cursor(sid, recorded)

    async def _evaluate_schedule(self, sid: str, schedule: Any, *, now: datetime) -> None:
        container = self._canonical_container()
        admitter = self._canonical_admitter(container)
        if admitter is not None:
            await self._evaluate_canonical(
                sid,
                schedule,
                now=now,
                container=container,
                admitter=admitter,
            )
            return

        # Standalone/demo compatibility path. Production must never reach this
        # when the core bridge is configured; it exists so a scheduler unit can
        # still be exercised without constructing the entire Container.
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

        last_index = len(decision.fires) - 1
        for fire_index, fire in enumerate(decision.fires):
            self._in_flight.add(sid)
            try:
                run_id = await self._fire_schedule(
                    sid, schedule, scheduled_for=fire.scheduled_for, catchup=fire.catchup
                )
            finally:
                self._in_flight.discard(sid)
            if run_id is None:
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
        """Compatibility cursor advance; configured Hive uses the admitter."""
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
        current = stores.schedules.get(sid)
        if current is not None:
            update: dict[str, Any] = {
                "last_run": fired_at,
                "last_run_id": run_id,
                "next_run": next_due_at,
                "updated_at": datetime.now(UTC),
            }
            if exhausted:
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
        """Standalone/demo immediate execution path — never a configured one.

        Selected only when there is no core Container bridge (the same gate the
        recurring loop's fallback uses), so a configured production instance
        cannot reach this; `fire_now` and `_evaluate_canonical` own the
        canonical admission spine in that case.  It fabricates the historical
        ``hive:schedule:{sid}`` execution scope and executes through the
        in-process registry, both of which are exactly what the canonical path
        replaces.
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
                "scheduled_for": (scheduled_for or t).isoformat(),
                "catchup": catchup,
            },
        )

        from services.dag_agents import get_registry, run_registered_dag

        if get_registry().get(str(template_id)) is None:
            logger.warning(
                "Schedule %s targets mission template %s, which is not registered; no Run was created.",
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
                provenance={
                    "admission_source": "schedule",
                    "schedule_id": sid,
                    "schedule_name": schedule.name,
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

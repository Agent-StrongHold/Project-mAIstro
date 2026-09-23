"""Background schedule runner — turns due schedules into canonical Runs.

Recurrence and fire semantics live in ``maistro.scheduling``.  A configured
Hive process delegates the complete evaluate -> occurrence claim -> Run admit
-> cursor advance transaction to ``ScheduleRunAdmitter`` — for recurring
ticks and manual ``POST /v1/schedules/{id}/run`` fires alike — then ticks
the canonical consumer for the admitted Runs.  The historical in-process
path remains only as a compatibility fallback for standalone/demo contexts
that have no core Container; it is not the production authority.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from maistro.graph.templates import GraphTemplateNotFound
from maistro.observability.correlation import (
    bind_execution_context,
    current_execution_context,
    detached_execution_context,
)
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


class ScheduleAdmissionUnavailable(RuntimeError):
    """A configured Container cannot admit schedule fires.

    This is a configuration failure, not a schedule property: the core bridge
    is present but a collaborator it owes the scheduler (run, template, or
    schedule store) is missing. Manual fire fails closed here rather than
    degrade to the compatibility path, because firing through the in-process
    registry while a Container exists would make the same persisted schedule
    reachable through two execution authorities.
    """


async def fire_now(sid: str, *, fire_id: str | None = None) -> str:
    """Fire a schedule now through the one canonical admission authority.

    Configured production enters ``ScheduleRunAdmitter.admit_due(manual=True)`` —
    the same Container, canonical Workspace/Project scope, durable
    ``GraphTemplate`` resolution, occurrence claim, and cursor transaction the
    recurring loop uses — so a manual fire and a scheduled fire of one schedule are
    indistinguishable in Run history apart from their provenance.  The
    compatibility path below remains only for processes with no core Container
    at all; a Container that is missing one of its admission collaborators
    raises :class:`ScheduleAdmissionUnavailable` instead of degrading.

    ``fire_id`` is the fire's occurrence identity (#1120): an opaque,
    caller-stable token — the body's ``fire_id`` or the ``Idempotency-Key``
    header at the route — so a retried or concurrent double submit of the same
    logical request reconciles to the Run the first call created instead of
    minting a fresh identity per call.  A call carrying no token gets a
    server-minted one, making each request its own deliberate firing.
    """
    import stores

    schedule = stores.schedules.get(sid)
    if schedule is None:
        raise ScheduleNotFireable(f"schedule {sid} does not exist")

    runner = _runner or _ScheduleRunner()
    container = runner._canonical_container()
    admitter = runner._canonical_admitter(container)
    if admitter is not None:
        assert container is not None  # for the type checker; the gate proved it
        token = fire_id if fire_id else uuid.uuid4().hex
        return await runner._fire_manual_canonical(
            sid, schedule, container=container, admitter=admitter, fire_id=token
        )
    if container is not None:
        raise ScheduleAdmissionUnavailable(
            f"schedule {sid} cannot be fired: the configured Container is missing its "
            "run/template/schedule store wiring, so canonical schedule admission is unavailable"
        )

    store = runner._canonical_store()
    definition = await runner._definition_for(sid, schedule, store=store)
    if definition is None:
        raise ScheduleNotFireable(
            f"schedule {sid} names no mission template, so there is nothing to run"
        )
    if definition.exhausted:
        raise ScheduleNotFireable(f"schedule {sid} has used all {definition.max_runs} of its runs")

    now = datetime.now(UTC)
    # Captured here, at the one call site with a trustworthy ambient context
    # (#1063): this coroutine runs inside the HTTP request RequestIDMiddleware
    # already bound an id for, so forwarding it explicitly is what keeps the
    # request/response and the resulting Run in the same trace.
    # `_fire_schedule` never reads ambient context itself -- it is also
    # reachable from the tick loop, which shares an event loop with whatever
    # else is running and cannot make the same claim.
    request_id = current_execution_context().request_id or None
    run_id = await runner._fire_schedule(
        sid, schedule, scheduled_for=now, catchup=False, request_id=request_id
    )
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

        # Admission is the submission for schedule work. The same configured
        # process owns the bounded canonical consumer tick, so a Run admitted
        # above cannot remain QUEUED merely because no task receipt exists.
        container = self._canonical_container()
        if container is not None:
            try:
                executed = await container.execute_admitted_runs()
                if executed:
                    logger.info("Consumed %d admitted canonical Run(s)", executed)
            except Exception as exc:
                logger.warning("Failed to consume admitted canonical Runs: %s", exc)

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
        """Read the Container-owned schedule admission boundary.

        The Container constructs this seam once so every producer shares the
        same admission authority and its store dependencies. Reconstructing an
        admitter here would let the scheduler silently invent a second
        authority, especially when the configured seam is absent.
        """
        if container is None:
            return None
        return getattr(container, "schedule_admitter", None)

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
        """Return the editable definition with the durable cursor overlaid.

        The overlay is the store's: `ScheduleStore.put` keeps the cursors
        `record_fire` recorded on an existing row and returns the row as
        stored, so the copy this returns carries what is on disk *after* the
        put, not what a read before it saw. A read-then-put here used to do
        the overlay itself, and a fire that landed between the two halves
        was written back over by the stale copy (Codex, #1199).
        """
        definition = self._as_definition(sid, schedule)
        if definition is None:
            return None
        if scope is not None:
            definition = definition.model_copy(
                update={"workspace_id": scope[0], "project_id": scope[1]}
            )
        if store is None:
            return definition
        stored: Schedule = await store.put(definition)
        return stored

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
        if admission.active_run_id is not None:
            # A live Run the pointer did not name -- a winner whose ticker died
            # before recording it (#1059). The admitter judged overlap against
            # it and, under CANCEL_OTHER, this is the Run it asked to cancel.
            logger.info(
                "Schedule %s has a live Run %s the cursor did not name (cancel requested: %s)",
                sid,
                admission.active_run_id,
                admission.cancel_active_run,
            )
        for exc in admission.failures:
            logger.warning("Schedule %s admission failed: %s", sid, exc)

        await self._audit_canonical_admission(sid, schedule, admission, container)
        recorded = await container.schedule_store.get(sid)
        if recorded is not None:
            self._project_cursor(sid, recorded)

    async def _fire_manual_canonical(
        self,
        sid: str,
        schedule: Any,
        *,
        container: Any,
        admitter: ScheduleRunAdmitter,
        fire_id: str,
    ) -> str:
        """Configured Hive manual fire: the recurring path's authority, once.

        ``_evaluate_canonical`` derives its occurrences from the cron;
        ``admit_due(manual=True)`` takes the one the caller asked for. Everything else is
        deliberately identical — canonical Workspace/Project scope via
        ``_canonical_scope`` (never the synthetic ``hive:schedule:{id}``
        identities the compatibility path used), the durable ``GraphTemplate``
        (primed from the registry exactly as a tick would prime it), the
        occurrence claim, and a cursor that moves only after the Run exists.
        #1119 retired manual fire from the compatibility path's reach because
        two firing semantics for one persisted schedule is a second execution
        authority, not an API convenience.

        The one identity difference (#1120): the occurrence claimed is
        ``(schedule_id, 'manual:' + fire_id)`` — the caller-stable token — so a
        retried or concurrent double submit carrying the same token reconciles
        to the Run the first call created: the loser is handed the winner's
        receipt, nothing is counted twice, and the reconciliation is durable
        canonical state (it survives restarts, and works across processes).
        """
        from maistro.scheduling.admission import ScheduleAdmission

        scope = await self._canonical_scope(schedule, container)
        definition = await self._definition_for(
            sid, schedule, store=container.schedule_store, scope=scope
        )
        if definition is None:
            raise ScheduleNotFireable(
                f"schedule {sid} names no mission template, so there is nothing to run"
            )
        # No local `exhausted` pre-check here, deliberately: the admitter asks
        # the occurrence claim before it refuses (#1120), so a retry of the
        # same fire_id reconciles to the winner's Run even when that fire
        # spent the last `max_runs` unit — a refusal ordering in this layer
        # would answer a retried caller "could not be fired" about a Run that
        # demonstrably exists.

        await self._prime_template(definition, container)
        now = datetime.now(UTC)
        try:
            admission = await admitter.admit_due(definition, now=now, manual=True, fire_id=fire_id)
        except GraphTemplateNotFound as exc:
            # The durable template is the authority; the registry was only ever
            # a migration source above. Nothing was created, so the schedule's
            # state is untouched and the caller gets the same refusal the
            # compatibility path gave for an unregistered target (#265).
            self._audit_manual_failure(sid, schedule, "template_not_found")
            raise ScheduleNotFireable(
                f"schedule {sid} could not create a Run; its target may not be registered"
            ) from exc
        except Exception as exc:
            self._audit_manual_failure(sid, schedule, type(exc).__name__)
            raise ScheduleNotFireable(f"schedule {sid} could not be fired: {exc}") from exc

        if admission.reconciled_run_id is not None:
            # Same logical request, already fired: the documented
            # reconciliation (#1120) is the first call's receipt — no second
            # Run, no second count against max_runs, and the caller's retry is
            # answered with the winner's Run rather than a refusal.
            winner_id = admission.reconciled_run_id
            logger.info(
                "Schedule %s manual fire %s reconciled to existing Run %s",
                sid,
                fire_id,
                winner_id,
            )
            # The winner's disable may live only in the durable row (its own
            # projection answered a different process), so the loser's receipt
            # reads the store — the authority — rather than assume the fire
            # left the schedule enabled.
            recorded = await container.schedule_store.get(sid)
            self._project_manual_receipt(
                sid, now, winner_id, exhausted=recorded is not None and not recorded.enabled
            )
            await self._consume_promptly(container)
            # ``str()`` because the admission crosses back from duck-typed
            # Container land into typed Hive code: re-assert the receipt at
            # the boundary rather than trust it as ``Any``.
            return str(winner_id)
        for occurred in admission.already_fired:
            # A duplicate claim whose winner could not be resolved — the claim
            # exists, so treating it as free would double-fire the request.
            raise ScheduleNotFireable(
                f"schedule {sid} occurrence at {occurred.isoformat()} was already "
                "claimed by another admission"
            )
        if not admission.run_ids:
            raise ScheduleNotFireable(
                f"schedule {sid} could not create a Run; its target may not be registered"
            )

        await self._audit_canonical_admission(
            sid,
            schedule,
            ScheduleAdmission(run_ids=admission.run_ids),
            container,
        )
        recorded = await container.schedule_store.get(sid)
        if recorded is not None:
            self._project_cursor(sid, recorded)
        # The admitter moved `last_run_id` and the count, never the recurrence
        # cursor (`last_fired_at`/`next_due_at`), so `_project_cursor` above
        # mirrors a `last_run` the hand fire never touched. Project the fire's
        # own receipt — the moment it was asked for — without moving the cron's
        # fields, exactly as a manual occurrence should read (#1120).
        self._project_manual_receipt(sid, now, admission.run_ids[-1], exhausted=admission.disabled)
        # The immediate UX a manual fire promises is prompt *consumption* of the
        # admitted Run, never a bypass of admission (#1120): best-effort, since
        # an unconsumed QUEUED Run is durable, recoverable canonical state.
        await self._consume_promptly(container)
        return admission.run_ids[-1]

    @staticmethod
    def _audit_manual_failure(sid: str, schedule: Any, error: str) -> None:
        """Audit a refused manual fire without touching any schedule state."""
        from routes.audit import log_audit

        log_audit(
            "schedule_run",
            "system",
            target=sid,
            detail={"dag_id": str(schedule.mission_template_id), "error": error},
        )

    @staticmethod
    def _project_manual_receipt(
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

    async def _evaluate_schedule(self, sid: str, schedule: Any, *, now: datetime) -> None:
        container = self._canonical_container()
        admitter = self._canonical_admitter(container)
        if container is not None:
            if admitter is None:
                raise ScheduleAdmissionUnavailable(
                    "configured Container is missing its run/template/schedule store wiring; "
                    "canonical schedule admission is unavailable"
                )
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
        # Manual fire does *not* share this branch: `fire_now` fails closed on
        # a configured-but-unwired Container, because unlike the tick — which
        # can simply wait for the next one — a manual fire is a caller holding
        # a request that must either become a canonical Run or say why not.
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
        request_id: str | None = None,
    ) -> str | None:
        """Compatibility immediate execution path, standalone/demo contexts only.

        ``fire_now`` routes configured production through
        ``_fire_manual_canonical`` and refuses a half-wired Container outright;
        this method stays reachable from the tick's no-Container branch and
        from the tests that exercise it without a Container.
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
            # Always a clean slate (#1063): this path shares an event loop
            # with whatever else is running (the tick loop) and cannot tell a
            # trustworthy caller-supplied id from a stray one some unrelated
            # Attempt left bound on the same tick just by looking at ambient
            # context. `fire_now()` -- the one caller with a real HTTP
            # request behind it -- passes its own id explicitly instead;
            # a caller that passes none (the tick loop) gets a fresh root.
            with detached_execution_context():
                effective_request_id = request_id or uuid.uuid4().hex[:12]
                with bind_execution_context(request_id=effective_request_id):
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
                            "request_id": effective_request_id,
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

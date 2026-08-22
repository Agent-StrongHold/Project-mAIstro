"""Turning a schedule firing into a canonical Run (#145).

The third entry point onto the same seam, after the task queue (#41) and chat
(#131). Unlike those two it is not a migration of an existing lifecycle: there
was no scheduler execution lifecycle to migrate. `maistro.scheduling` was a
complete, well-covered decision engine that nothing called, and
`hive-conductor`'s `POST /schedules/{id}/run` stamped a timestamp and executed
nothing. The two halves had never been connected, and the missing piece between
them was a way to resolve `Schedule.graph_template_id` — now
`maistro.graph.templates`.

What differs from the other two entry points is that a scheduled Run is not
trivial work. Tasks and chat turns admit as a one-node Graph built at admission;
a schedule names a `GraphTemplate` somebody drew, and firing instantiates it. So
this module does not go through `runs.admission.direct_work_graph` — there is a
real Graph — but it does record the same `admission_source` provenance, because
the question "how did this Run enter the system?" has to be answerable the same
way for all three.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.graph.templates import GraphTemplateStore, require_template
from maistro.runs.admission import ADMISSION_SOURCE
from maistro.scheduling.engine import FireDecision, ScheduleEvaluation, evaluate

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.runs.model import Run
    from maistro.runs.store import RunStore
    from maistro.scheduling.model import Schedule
    from maistro.scheduling.store import ScheduleStore

#: `admission_source` value for work that entered through a schedule firing.
SCHEDULE_SOURCE = "schedule"

#: Provenance keys a scheduled Run carries.
SCHEDULE_ID_KEY = "schedule_id"
#: The *nominal* fire time — the occurrence this Run belongs to, not the moment
#: a tick noticed it. A Run that started twenty minutes late is still
#: attributable to the 09:00 occurrence, and only this field says so.
SCHEDULED_FOR_KEY = "scheduled_for"
#: True when the occurrence came due while nothing was evaluating it: a backfill
#: after downtime rather than a fire on time. Worth recording because the two
#: are indistinguishable afterwards and mean different things to whoever reads
#: the Run.
CATCHUP_KEY = "catchup"


class ScheduleRunAdmitter:
    """Admit schedule firings as canonical Runs over their instantiated Graph."""

    def __init__(
        self,
        run_store: RunStore,
        schedule_store: ScheduleStore,
        template_store: GraphTemplateStore,
        *,
        retention_expires_at_factory: Any = None,
    ) -> None:
        self._runs = run_store
        self._schedules = schedule_store
        self._templates = template_store
        # Scheduled work recurs, so its Runs are unbounded over time in the same
        # way chat turns are (ADR-082226-c126). Whether they get a deadline is a
        # policy decision that has not been made, so the default is None —
        # today's behavior — and a deployment that wants a bound supplies one
        # rather than inheriting one nobody chose. See #145's "not in scope".
        self._retention = retention_expires_at_factory

    async def admit_fire(self, schedule: Schedule, fire: FireDecision) -> Run:
        """Admit one occurrence as a Run over the instantiated template.

        Does not advance the schedule's cursor; :meth:`fire_due` does that after
        the Run exists. Splitting them is deliberate — a cursor advanced before
        the Run is created would skip an occurrence that never ran.
        """
        template = await require_template(
            self._templates,
            schedule.graph_template_id,
            version=schedule.template_version,
        )
        graph = template.instantiate(
            project_id=schedule.project_id,
            name=schedule.name or template.name,
        )
        provenance: dict[str, Any] = {
            ADMISSION_SOURCE: SCHEDULE_SOURCE,
            SCHEDULE_ID_KEY: schedule.schedule_id,
            SCHEDULED_FOR_KEY: fire.scheduled_for.isoformat(),
            CATCHUP_KEY: fire.catchup,
        }
        if schedule.inputs:
            provenance["inputs"] = dict(schedule.inputs)
        return await self._runs.create_run(
            graph,
            persona_id=schedule.persona_id,
            actor_principal_id=schedule.actor_principal_id,
            provenance=provenance,
            retention_expires_at=self._retention() if self._retention is not None else None,
        )

    async def fire_due(
        self,
        schedule: Schedule,
        *,
        now: datetime | None = None,
        active_run: bool = False,
    ) -> tuple[ScheduleEvaluation, list[Run]]:
        """Evaluate one schedule and admit a Run for every occurrence it fires.

        Returns the evaluation alongside the Runs so a caller can see what was
        skipped and why — the engine reports refusals rather than dropping them,
        and swallowing that here would undo the distinction.

        The cursor is advanced once, after all the Runs exist, recording the
        last occurrence's nominal time and the last Run's id. `max_runs`
        exhaustion disables the schedule in the same write that records the
        fire: `ScheduleEvaluation.exhausted` has always reported it and nothing
        consumed it, so a bounded schedule ran forever.
        """
        moment = now if now is not None else datetime.now(UTC)
        decision = evaluate(schedule, now=moment, active_run=active_run)
        if not decision.fires:
            return decision, []
        runs = [await self.admit_fire(schedule, fire) for fire in decision.fires]
        await self._schedules.record_fire(
            schedule.schedule_id,
            fired_at=decision.fires[-1].scheduled_for,
            run_id=runs[-1].run_id,
            next_due_at=decision.next_due_at,
            fires=len(runs),
            disable=decision.exhausted,
        )
        return decision, runs


__all__ = [
    "CATCHUP_KEY",
    "SCHEDULED_FOR_KEY",
    "SCHEDULE_ID_KEY",
    "SCHEDULE_SOURCE",
    "ScheduleRunAdmitter",
]

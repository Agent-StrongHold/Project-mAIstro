"""Schedule firings become canonical Runs, with provenance (#145, #46).

The third admitter, beside `tasks.admission.TaskRunAdmitter` (#41) and
`runs.chat_admission.ChatRunAdmitter` (#131). Scheduling was the outlier: a
scheduled Run recorded nothing about the Schedule that fired it, so the linkage
existed only as an audit line beside the Run rather than on it. #46 asks for
"trigger/schedule provenance retained **on the Run**", and this is where that
becomes true.

Three things this is careful about, all of them ordering:

**The cursor advances only after the Runs exist.** `record_fire` stamps
`last_fired_at`, and a tick that stamped first and then failed to create the
Run would skip that occurrence permanently and silently — the next evaluation
enumerates from the new cursor and never looks back. Creating first can at
worst repeat an occurrence after a crash, which is recoverable; skipping one is
not.

**A missing template is a failure, not a quiet no-op.** `DagRegistry` returned
`None` for an unregistered id and the caller returned early — while the
schedule's `last_run` had already been stamped, so it looked like it fired.
`require_template` raises instead, and the cursor has not moved when it does,
so the occurrence is still there to retry once the template is registered.

**Exhaustion is decided against the fires that actually happened.**
`ScheduleEvaluation.exhausted` answers "does `max_runs` run out once these
fires are recorded", which is only true if all of them were. Partial failure
recomputes it from the count that survived, so a schedule is never disabled for
reaching a limit it did not reach.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from maistro.graph.templates import require_template
from maistro.runs.sources import (
    ADMISSION_SOURCE,
    SCHEDULE_CATCHUP_KEY,
    SCHEDULE_ID_KEY,
    SCHEDULE_SOURCE,
    SCHEDULED_FOR_KEY,
)
from maistro.scheduling.engine import evaluate

if TYPE_CHECKING:
    from maistro.graph.templates import GraphTemplateStore
    from maistro.runs.store import RunStore
    from maistro.scheduling.engine import FireDecision, SkippedFire
    from maistro.scheduling.model import Schedule
    from maistro.scheduling.store import ScheduleStore

logger = logging.getLogger("maistro.scheduling.admission")


@dataclass(frozen=True)
class ScheduleAdmission:
    """What one evaluation of one schedule produced."""

    run_ids: tuple[str, ...] = ()
    """The Runs created, oldest occurrence first."""

    skipped: tuple[SkippedFire, ...] = ()
    """Occurrences deliberately not run, each with its reason."""

    next_due_at: datetime | None = None

    disabled: bool = False
    """The schedule reached `max_runs` and was disabled in the same write."""

    cancel_active_run: bool = False
    """CANCEL_OTHER asked for the in-flight Run to be cancelled before firing.

    Reported rather than acted on: this admitter creates Runs and does not know
    which one is in flight — the caller tracking that is the one that can
    cancel it.
    """

    failures: tuple[Exception, ...] = field(default=())
    """Occurrences that could not be admitted, with why.

    Returned rather than raised, because one unresolvable template must not
    discard the sibling occurrences that resolved fine — and because the cursor
    still has to advance for the ones that did.
    """


class ScheduleRunAdmitter:
    """Evaluate a schedule, admit its due occurrences, then advance its cursor."""

    def __init__(
        self,
        run_store: RunStore,
        template_store: GraphTemplateStore,
        schedule_store: ScheduleStore,
    ) -> None:
        self._runs = run_store
        self._templates = template_store
        self._schedules = schedule_store

    async def admit_due(
        self,
        schedule: Schedule,
        *,
        now: datetime,
        active_run: bool = False,
    ) -> ScheduleAdmission:
        """Admit every occurrence `schedule` owes at `now`.

        `active_run` is whether a Run this schedule started is still in flight.
        The caller answers it from Run state, which is the only place it lives —
        the same contract `evaluate()` states.
        """
        decision = evaluate(schedule, now=now, active_run=active_run)
        if not decision.fires:
            # Nothing fired, so nothing to record. `next_due_at` still moved and
            # the caller wants it, but writing it here would stamp
            # `last_fired_at` for a fire that did not happen.
            return ScheduleAdmission(
                skipped=decision.skipped,
                next_due_at=decision.next_due_at,
                cancel_active_run=decision.cancel_active_run,
            )

        run_ids: list[str] = []
        failures: list[Exception] = []
        for fire in decision.fires:
            try:
                run_ids.append(await self._admit_one(schedule, fire))
            except Exception as exc:
                logger.warning(
                    "schedule %s could not admit its %s occurrence: %s",
                    schedule.schedule_id,
                    fire.scheduled_for.isoformat(),
                    exc,
                )
                failures.append(exc)

        if not run_ids:
            # Every occurrence failed. Leaving the cursor untouched is what
            # makes them retryable: the next evaluation enumerates the same
            # occurrences and can succeed once the template exists.
            return ScheduleAdmission(
                skipped=decision.skipped,
                next_due_at=decision.next_due_at,
                cancel_active_run=decision.cancel_active_run,
                failures=tuple(failures),
            )

        disable = self._exhausted_after(schedule, fires=len(run_ids))
        await self._schedules.record_fire(
            schedule.schedule_id,
            fired_at=now,
            # The newest Run, matching `last_fired_at` being the newest fire.
            # `Schedule.last_run_id` is a pointer to the latest occurrence, not
            # a history of them; the history is on the Runs, each naming this
            # schedule.
            run_id=run_ids[-1],
            next_due_at=decision.next_due_at,
            fires=len(run_ids),
            disable=disable,
        )
        return ScheduleAdmission(
            run_ids=tuple(run_ids),
            skipped=decision.skipped,
            next_due_at=decision.next_due_at,
            disabled=disable,
            cancel_active_run=decision.cancel_active_run,
            failures=tuple(failures),
        )

    @staticmethod
    def _exhausted_after(schedule: Schedule, *, fires: int) -> bool:
        """Whether `max_runs` is spent once `fires` occurrences are recorded.

        `ScheduleEvaluation.exhausted` already answered this — for the fires it
        *proposed*. Recomputed against the ones that were actually admitted,
        because a partial failure means fewer were recorded, and disabling a
        schedule for a limit it has not reached loses every future occurrence.
        """
        if schedule.max_runs is None:
            return False
        return schedule.runs_so_far + fires >= schedule.max_runs

    async def _admit_one(self, schedule: Schedule, fire: FireDecision) -> str:
        template = await require_template(
            self._templates,
            schedule.graph_template_id,
            version=schedule.template_version,
        )
        graph = template.instantiate(project_id=schedule.project_id, name=schedule.name or None)
        provenance: dict[str, Any] = {
            ADMISSION_SOURCE: SCHEDULE_SOURCE,
            SCHEDULE_ID_KEY: schedule.schedule_id,
            SCHEDULED_FOR_KEY: fire.scheduled_for.isoformat(),
            SCHEDULE_CATCHUP_KEY: fire.catchup,
        }
        run = await self._runs.create_run(
            graph,
            persona_id=schedule.persona_id,
            actor_principal_id=schedule.actor_principal_id,
            provenance=provenance,
        )
        return run.run_id


__all__ = ["ScheduleAdmission", "ScheduleRunAdmitter"]

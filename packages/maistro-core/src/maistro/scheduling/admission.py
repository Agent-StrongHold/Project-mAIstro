"""Schedule firings become canonical Runs, with provenance (#145, #46).

The third admitter, beside `tasks.admission.TaskRunAdmitter` (#41) and
`runs.chat_admission.ChatRunAdmitter` (#131). Scheduling was the outlier: a
scheduled Run recorded nothing about the Schedule that fired it, so the linkage
existed only as an audit line beside the Run rather than on it. #46 asks for
"trigger/schedule provenance retained **on the Run**", and this is where that
becomes true.

Three things this is careful about, all of them ordering:

**The occurrence is what gets claimed, and the cursor is where enumeration
resumes (#220).** `(schedule_id, scheduled_for)` is the identity of a firing;
a cursor never was. The Run store refuses a second Run for an occurrence that
already has one, so two tickers evaluating the same due window produce one Run
between them and a crash between creating a Run and stamping the cursor cannot
duplicate the firing on the next tick.

That leaves `record_fire` doing what it is actually good at. The cursor is now
an optimisation — where to start enumerating, so a schedule does not re-derive
its whole history every tick — rather than the mechanism that makes firing
exactly-once. Both were load-bearing before, silently, and only one of them
could carry the weight.

**The cursor still advances only after the Runs exist.** `record_fire` stamps
`last_fired_at`, and a tick that stamped first and then failed to create the
Run would skip that occurrence permanently and silently — the next evaluation
enumerates from the new cursor and never looks back. Creating first can at
worst repeat an occurrence after a crash, and with the claim in place that
repeat is now refused rather than merely preferred to a skip.

**A missing template is a failure, not a quiet no-op.** `DagRegistry` returned
`None` for an unregistered id and the caller returned early — while the
schedule's `last_run` had already been stamped, so it looked like it fired.
`require_template` raises instead, and the cursor has not moved when it does,
so the occurrence is still there to retry once the template is registered.

**A duplicate claim is not a failure.** Every other admission error stops the
batch, because the cursor moves past everything it covers and continuing would
lose the failure or duplicate the success. A duplicate is the opposite case:
that occurrence *did* fire, so it is consumed — the cursor may pass it — while
not counting toward `max_runs`, which the admitter that actually created the
Run counts for itself.

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
from typing import TYPE_CHECKING, Any, Final

from maistro.graph.templates import require_template
from maistro.runs.model import RunStatus
from maistro.runs.sources import (
    ADMISSION_SOURCE,
    SCHEDULE_CATCHUP_KEY,
    SCHEDULE_ID_KEY,
    SCHEDULE_INPUTS_KEY,
    SCHEDULE_SOURCE,
    SCHEDULED_FOR_KEY,
)
from maistro.runs.store import DuplicateOccurrence
from maistro.scheduling.engine import SkipReason, evaluate

if TYPE_CHECKING:
    from maistro.graph.definitions import GraphTemplate
    from maistro.graph.templates import GraphTemplateStore
    from maistro.runs.store import RunStore
    from maistro.scheduling.engine import FireDecision, ScheduleEvaluation, SkippedFire
    from maistro.scheduling.model import Schedule
    from maistro.scheduling.store import ScheduleStore

logger = logging.getLogger("maistro.scheduling.admission")

#: Skip reasons whose occurrence is still owed, so the cursor must not pass it.
#:
#: Read from `SkipReason`'s own documentation rather than restated: BUFFERED
#: says the cursor does not advance because "run one queued occurrence
#: afterwards" is what BUFFER_ONE means, and TRUNCATED says a caller advancing
#: on it "would otherwise lose the occurrence with no record of it". Every other
#: reason is a decision not to run that occurrence at all.
_UNCONSUMED_SKIPS: Final = frozenset({SkipReason.BUFFERED, SkipReason.TRUNCATED})


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

    already_fired: tuple[datetime, ...] = ()
    """Occurrences another admitter had already claimed (#220).

    Not failures and not skips. The firing happened — some other ticker, or
    this process before a crash, created its Run — so the work is done and the
    cursor may pass it. They are reported because "this tick admitted nothing
    because everything was already admitted" and "this tick admitted nothing
    because nothing was due" are different operational facts.
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
            return await self._consume_without_firing(schedule, decision)

        # Resolved once for the batch, not once per occurrence. A minutely
        # schedule naming a template nobody registered has hundreds of due
        # occurrences after an outage, and resolving per occurrence turned one
        # configuration error into hundreds of store round trips and log lines
        # on every tick — while the cursor stayed put, so the burst repeated.
        try:
            template = await require_template(
                self._templates,
                schedule.graph_template_id,
                version=schedule.template_version,
            )
        except Exception as exc:
            logger.warning(
                "schedule %s cannot resolve template %s: %s",
                schedule.schedule_id,
                schedule.graph_template_id,
                exc,
            )
            # Cursor untouched: the occurrences are still owed, and become
            # admissible the moment the template is registered.
            return ScheduleAdmission(
                skipped=decision.skipped,
                next_due_at=decision.next_due_at,
                cancel_active_run=decision.cancel_active_run,
                failures=(exc,),
            )

        run_ids: list[str] = []
        admitted: list[FireDecision] = []
        already_fired: list[datetime] = []
        consumed: list[FireDecision] = []
        failures: list[Exception] = []
        for fire in decision.fires:
            try:
                run_ids.append(await self._admit_one(schedule, template, fire))
                admitted.append(fire)
                consumed.append(fire)
            except DuplicateOccurrence:
                # **Continue**, unlike every other failure below. The claim
                # refusing this insert says the occurrence already has its Run
                # (#220) — nothing is owed, so stopping here would re-enumerate
                # a firing that has already happened on every subsequent tick.
                #
                # Counted as consumed so the cursor may pass it, but *not* as
                # admitted: `fires` feeds `runs_so_far`, and both tickers
                # counting one firing would exhaust `max_runs` at half the
                # occurrences it was configured for.
                logger.info(
                    "schedule %s occurrence %s was already admitted elsewhere",
                    schedule.schedule_id,
                    fire.scheduled_for.isoformat(),
                )
                already_fired.append(fire.scheduled_for)
                consumed.append(fire)
            except Exception as exc:
                # **Stop**, rather than continue. `record_fire` moves the cursor
                # past everything it covers, so admitting a later occurrence
                # after an earlier one failed would either lose the failure
                # (cursor past it) or duplicate the success (cursor before it).
                # Stopping keeps the failed occurrence and everything after it
                # owed, which is the property this admitter exists to hold.
                logger.warning(
                    "schedule %s could not admit its %s occurrence, stopping the batch: %s",
                    schedule.schedule_id,
                    fire.scheduled_for.isoformat(),
                    exc,
                )
                failures.append(exc)
                break

        if not consumed:
            return ScheduleAdmission(
                skipped=decision.skipped,
                next_due_at=decision.next_due_at,
                cancel_active_run=decision.cancel_active_run,
                failures=tuple(failures),
            )

        disable = self._exhausted_after(schedule, fires=len(admitted))
        # `next_due_at` is recomputed only when the whole batch landed. A
        # partial batch leaves occurrences owed, and `evaluate()`'s answer
        # assumed all of them fired.
        complete = len(consumed) == len(decision.fires)
        await self._schedules.record_fire(
            schedule.schedule_id,
            # The newest occurrence *admitted*, not `now`. This value becomes
            # the lower bound of the next enumeration, so `now` would carry the
            # cursor past occurrences this batch stopped short of and lose them
            # permanently — the exact failure the ordering above prevents.
            fired_at=consumed[-1].scheduled_for,
            # The newest Run, matching the cursor being the newest fire.
            # `Schedule.last_run_id` is a pointer to the latest occurrence, not
            # a history of them; the history is on the Runs, each naming this
            # schedule.
            # None when the batch's last consumed occurrence was one another
            # admitter had claimed: `_advance` keeps the existing id rather
            # than clearing it, and pointing `last_run_id` at an older Run of
            # ours would be less true than leaving it where it was.
            run_id=run_ids[-1] if run_ids else None,
            next_due_at=decision.next_due_at if complete else schedule.next_due_at,
            fires=len(admitted),
            disable=disable,
        )
        return ScheduleAdmission(
            run_ids=tuple(run_ids),
            skipped=decision.skipped,
            next_due_at=decision.next_due_at,
            disabled=disable,
            cancel_active_run=decision.cancel_active_run,
            already_fired=tuple(already_fired),
            failures=tuple(failures),
        )

    async def _consume_without_firing(
        self, schedule: Schedule, decision: ScheduleEvaluation
    ) -> ScheduleAdmission:
        """Advance past occurrences that were *dropped*, not deferred.

        `OverlapPolicy.SKIP` means "drop the fire; the in-flight Run keeps
        going". Leaving the cursor behind turned that into *defer*: the
        occurrence came due again on the next tick, and once the active Run
        finished it fired after all — the opposite of what the default policy
        promises.

        `SkipReason` already draws the line and this reads it rather than
        restating it. `BUFFERED` says in as many words that the cursor does not
        advance, because "run one queued occurrence afterwards" is what
        BUFFER_ONE means; `TRUNCATED` says a caller that advanced on it "would
        otherwise lose the occurrence with no record of it". Everything else —
        overlap, disabled, exhausted, outside the catch-up window — is a
        decision not to run that occurrence at all.
        """
        consumable = [skip for skip in decision.skipped if skip.reason not in _UNCONSUMED_SKIPS]
        if consumable:
            newest = max(skip.scheduled_for for skip in consumable)
            await self._schedules.record_fire(
                schedule.schedule_id,
                fired_at=newest,
                # No Run was created, so neither `last_run_id` nor the fire
                # count moves. `_advance` keeps the existing id when this is
                # None, which is what makes "the last Run this schedule
                # produced" survive an occurrence that produced none.
                run_id=None,
                next_due_at=decision.next_due_at,
                fires=0,
            )
        return ScheduleAdmission(
            skipped=decision.skipped,
            next_due_at=decision.next_due_at,
            cancel_active_run=decision.cancel_active_run,
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

    async def _admit_one(
        self, schedule: Schedule, template: GraphTemplate, fire: FireDecision
    ) -> str:
        graph = template.instantiate(project_id=schedule.project_id, name=schedule.name or None)
        provenance: dict[str, Any] = {
            ADMISSION_SOURCE: SCHEDULE_SOURCE,
            SCHEDULE_ID_KEY: schedule.schedule_id,
            SCHEDULED_FOR_KEY: fire.scheduled_for.isoformat(),
            SCHEDULE_CATCHUP_KEY: fire.catchup,
        }
        if schedule.inputs:
            # `Schedule.inputs` is the schedule's configured payload, and
            # instantiating the template alone dropped it: a parameterized
            # schedule produced a Run indistinguishable from one configured
            # with nothing. Recorded on the Run rather than only handed to a
            # runner, because a Run that cannot say what it was asked to do
            # cannot be audited or replayed.
            provenance[SCHEDULE_INPUTS_KEY] = schedule.inputs
        run = await self._runs.create_run(
            graph,
            persona_id=schedule.persona_id,
            actor_principal_id=schedule.actor_principal_id,
            provenance=provenance,
            # QUEUED in the same insert (#251). A schedule Run's admission IS
            # its submission — there is no caller holding a receipt who will
            # queue it later, so a Run left CREATED here was admitted work
            # nobody would ever execute. `admit_in_state` exists precisely so
            # this claim needs no second commit.
            initial_status=RunStatus.QUEUED,
        )
        return run.run_id


__all__ = ["ScheduleAdmission", "ScheduleRunAdmitter"]

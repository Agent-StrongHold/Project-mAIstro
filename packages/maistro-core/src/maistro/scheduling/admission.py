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
that occurrence *did* fire, so it is consumed — the cursor may pass it — and
it carries the *winner's* identity (#1059): `last_run_id` is linked to the Run
that holds the claim, because the caller answers `active_run` from that
pointer and a stale one let a SKIP schedule run two occurrences at once.

**The Run store is read before the overlap policy is applied (#1059
review).** A ticker that died between `create_run` and `record_fire` left a
Run with no pointer to it. The next tick re-enumerates that occurrence beside
newer ones, and a policy judging overlap from the caller's stale `active_run`
would drop the crashed one into `skipped` — under `CANCEL_OTHER`, admitting
the newer occurrence beside the old Run with no cancellation asked for. So
every enumerated occurrence is checked for an existing Run first: one that has
a Run is already fired, whichever side of the policy it fell on, and a live
one is what the policy sees as in flight. The caller learns that Run's
identity through `ScheduleAdmission.active_run_id`.

**Firings are counted by the store, once each.** Whether this ticker created
the Run or another one won the claim, a consumed occurrence is a firing, and
`record_fire` counts it against `max_runs` only if the cursor had not passed
it yet. That is what keeps two tickers consuming one occurrence from counting
it twice, and a winner that died before recording from never being counted at
all. Exhaustion is therefore the store's decision, made against the fires that
actually happened, and the admitter reports what the store decided.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from maistro.graph.templates import require_template
from maistro.runs.model import TERMINAL_RUN_STATUSES, RunStatus
from maistro.runs.sources import (
    ADMISSION_SOURCE,
    SCHEDULE_CATCHUP_KEY,
    SCHEDULE_ID_KEY,
    SCHEDULE_INPUTS_KEY,
    SCHEDULE_SOURCE,
    SCHEDULED_FOR_KEY,
)
from maistro.runs.store import DuplicateOccurrence
from maistro.scheduling.engine import SkipReason, enumeration_start, evaluate

if TYPE_CHECKING:
    from collections.abc import Sequence

    from maistro.graph.definitions import GraphTemplate
    from maistro.graph.templates import GraphTemplateStore
    from maistro.runs.model import Run
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


def _owes(skipped: Sequence[SkippedFire]) -> bool:
    """Whether the evaluation left an occurrence that still has to run."""
    return any(skip.reason in _UNCONSUMED_SKIPS for skip in skipped)


#: Skips whose occurrences the policy never acts on, so their claims are not
#: looked up: the window already dropped them, or the enumeration cap did.
_UNCLAIMABLE: Final = frozenset({SkipReason.OUTSIDE_CATCHUP, SkipReason.TRUNCATED})


@dataclass
class _Batch:
    """What one pass over the due occurrences produced."""

    run_ids: list[str] = field(default_factory=list)
    already_fired: list[datetime] = field(default_factory=list)
    consumed: list[datetime] = field(default_factory=list)
    links: dict[datetime, str] = field(default_factory=dict)
    """The Run behind each consumed occurrence whose Run is known."""
    failures: list[Exception] = field(default_factory=list)


def _enumerated(decision: ScheduleEvaluation) -> list[datetime]:
    """The occurrences this evaluation acts on: its fires, and the skips the
    policy decided rather than the window or the cap."""
    return [fire.scheduled_for for fire in decision.fires] + [
        skip.scheduled_for for skip in decision.skipped if skip.reason not in _UNCLAIMABLE
    ]


def _live_claim(claims: dict[datetime, Run]) -> Run | None:
    """The newest claimed Run still in flight, if any."""
    for moment in sorted(claims, reverse=True):
        if claims[moment].status not in TERMINAL_RUN_STATUSES:
            return claims[moment]
    return None


def _pointer(links: dict[datetime, str], fired: list[datetime]) -> str | None:
    """The Run `last_run_id` should name after `fired` occurrences got Runs.

    The Run behind the *newest* fired occurrence — ours, or the rival's that
    won the claim (#1059). `Schedule.last_run_id` is a pointer to the latest
    Run this schedule produced, not a history of them; the history is on the
    Runs, each naming this schedule. When that winner cannot be resolved (only
    ever a finished Run that was evicted or purged) the answer is None, and
    `_advance` keeps the existing pointer: an earlier Run of this batch must
    not masquerade as the newest, because the caller answers `active_run`
    from the pointer and would be judging overlap against a Run that is not
    the latest. Occurrences consumed *without* a Run (a policy skip) are not
    in `fired`: they produced nothing, so they do not compete for the pointer.
    """
    return links.get(max(fired)) if fired else None


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

    Reported rather than acted on: this admitter creates Runs and cancels
    none. The caller tracking the in-flight Run is the one that can cancel it
    — through `last_run_id`, or `active_run_id` when this evaluation found the
    live Run itself.
    """

    active_run_id: str | None = None
    """A live Run this evaluation found on one of its own occurrences.

    The winner of an occurrence whose ticker died before recording it (#1059):
    the caller's pointer did not name it, the Run store did. Reported so the
    caller can treat it as the in-flight Run — cancel it under CANCEL_OTHER,
    or read overlap from it next tick — rather than discover it by accident.
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


@dataclass(frozen=True)
class _Due:
    """One evaluation with the Run store's knowledge folded in.

    `evaluate()` is pure over the schedule; it cannot know that an occurrence
    it proposes already has a Run. This splits its answer against the claims
    the store holds: an occurrence with a Run is already fired — not a fire to
    attempt, not a skip to report — whichever side of the policy it fell on.
    """

    fires: tuple[FireDecision, ...]
    skipped: tuple[SkippedFire, ...]
    already_fired: tuple[datetime, ...]
    links: dict[datetime, str]
    next_due_at: datetime | None
    cancel_active_run: bool
    active_run_id: str | None

    @classmethod
    def of(
        cls,
        decision: ScheduleEvaluation,
        claims: dict[datetime, Run],
        *,
        active_run_id: str | None,
    ) -> _Due:
        # Every claim found is an occurrence to consume: the enumerated ones
        # the policy would otherwise act on, and the ones before the horizon
        # the evaluation never saw.
        already = sorted(claims)
        return cls(
            fires=tuple(f for f in decision.fires if f.scheduled_for not in claims),
            skipped=tuple(s for s in decision.skipped if s.scheduled_for not in claims),
            already_fired=tuple(already),
            links={moment: claims[moment].run_id for moment in already},
            next_due_at=decision.next_due_at,
            cancel_active_run=decision.cancel_active_run,
            active_run_id=active_run_id,
        )

    def admission(
        self,
        *,
        run_ids: tuple[str, ...] = (),
        disabled: bool = False,
        already_fired: tuple[datetime, ...] = (),
        failures: tuple[Exception, ...] = (),
    ) -> ScheduleAdmission:
        return ScheduleAdmission(
            run_ids=run_ids,
            skipped=self.skipped,
            next_due_at=self.next_due_at,
            disabled=disabled,
            cancel_active_run=self.cancel_active_run,
            active_run_id=self.active_run_id,
            already_fired=already_fired,
            failures=failures,
        )


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
        The caller answers it from Run state via `last_run_id` — the same
        contract `evaluate()` states — and that pointer can be stale: a ticker
        that created a Run and died before `record_fire` left it unset (#1059).
        So the occurrences this evaluation enumerates are checked against the
        Run store *before* the overlap policy is applied: an occurrence that
        already has its Run is already fired, whatever the policy would have
        done with it, and a live one is what the policy sees as in flight,
        whatever the pointer said.
        """
        decision = evaluate(schedule, now=now, active_run=active_run)
        claims = await self._existing_claims(schedule, decision, now=now)
        live = _live_claim(claims)
        if live is not None and not active_run:
            decision = evaluate(schedule, now=now, active_run=True)
        due = _Due.of(decision, claims, active_run_id=live.run_id if live is not None else None)
        if not due.fires:
            return await self._consume_without_firing(schedule, due)

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
            return due.admission(failures=(exc,))

        batch = await self._admit_batch(schedule, template, due)
        if not batch.consumed:
            return due.admission(failures=tuple(batch.failures))

        recorded = await self._record_batch(schedule, due, batch)
        return due.admission(
            run_ids=tuple(batch.run_ids),
            disabled=recorded is not None and not recorded.enabled,
            already_fired=tuple(batch.already_fired),
            failures=tuple(batch.failures),
        )

    async def _existing_claims(
        self, schedule: Schedule, decision: ScheduleEvaluation, *, now: datetime
    ) -> dict[datetime, Run]:
        """The Runs that already hold a claim on this evaluation's occurrences.

        Recovery's blind spot (#1059 review): after a ticker dies between
        `create_run` and `record_fire`, the next tick re-enumerates that
        occurrence beside newer ones. Under `CANCEL_OTHER` the policy keeps
        only the newest and drops the crashed one into `skipped`, so it never
        reaches the duplicate handler — the newer Run is admitted with no
        cancellation asked for while the old winner keeps running, unlinked and
        uncounted. Reading the claims first is what lets the policy, the
        pointer and the fire count all see the Run that exists.

        One index probe per enumerated occurrence, which is zero on an idle
        tick. Occurrences the window already dropped or the enumeration cap
        truncated are not looked up: the policy does not act on them.

        The enumeration starts after the catch-up horizon, so a winner that
        crashed before it — the ticker died mid-fire and stayed down longer
        than the window — is never enumerated at all. Those claims are walked
        instead, from the cursor forward (`_claims_before`): a batch admits
        occurrences in order and dies at one, so its Runs sit contiguously
        after the cursor and the walk stops at the first occurrence without a
        Run. Bounded by one batch's worth of lookups, and one lookup on the
        common path. A claim that is not contiguous from the cursor is not
        found; nothing this admitter does can leave one.
        """
        claims: dict[datetime, Run] = {}
        for moment in _enumerated(decision):
            run = await self._runs.get_run_for_occurrence(schedule.schedule_id, moment.isoformat())
            if run is not None:
                claims[moment] = run
        claims.update(await self._claims_before(schedule, enumeration_start(schedule, now=now)))
        return claims

    async def _claims_before(self, schedule: Schedule, since: datetime) -> dict[datetime, Run]:
        """Contiguous claims from the cursor up to and including `since`."""
        claims: dict[datetime, Run] = {}
        moment = schedule.next_fire_after(schedule.last_fired_at or schedule.created_at)
        while moment <= since:
            run = await self._runs.get_run_for_occurrence(schedule.schedule_id, moment.isoformat())
            if run is None:
                break
            claims[moment] = run
            moment = schedule.next_fire_after(moment)
        return claims

    async def _admit_batch(self, schedule: Schedule, template: GraphTemplate, due: _Due) -> _Batch:
        """Create a Run per due occurrence, stopping at the first real failure.

        Occurrences that already had a Run when the tick began are consumed
        without an insert; one that gains a rival's Run between that read and
        this insert is refused by the claim and consumed the same way.
        """
        batch = _Batch(already_fired=list(due.already_fired), links=dict(due.links))
        batch.consumed.extend(due.already_fired)
        for fire in due.fires:
            try:
                run_id = await self._admit_one(schedule, template, fire)
                batch.run_ids.append(run_id)
                batch.links[fire.scheduled_for] = run_id
                batch.consumed.append(fire.scheduled_for)
            except DuplicateOccurrence:
                # **Continue**, unlike every other failure below. The claim
                # refusing this insert says the occurrence already has its Run
                # (#220) — nothing is owed, so stopping here would re-enumerate
                # a firing that has already happened on every subsequent tick.
                winner_id = await self._winning_run_id(schedule, fire)
                if winner_id is not None:
                    batch.links[fire.scheduled_for] = winner_id
                batch.already_fired.append(fire.scheduled_for)
                batch.consumed.append(fire.scheduled_for)
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
                batch.failures.append(exc)
                break
        batch.already_fired.sort()
        batch.consumed.sort()
        return batch

    async def _record_batch(self, schedule: Schedule, due: _Due, batch: _Batch) -> Schedule | None:
        """Advance the cursor past what this batch consumed."""
        # `next_due_at` is recomputed only when the whole batch landed and
        # nothing was held back. A partial batch leaves occurrences owed, and
        # `evaluate()`'s answer assumed all of them fired; a buffered
        # occurrence is owed the same way (#1199).
        complete = not batch.failures and not _owes(due.skipped)
        return await self._schedules.record_fire(
            schedule.schedule_id,
            # The newest occurrence *consumed*, not `now`. This value becomes
            # the lower bound of the next enumeration, so `now` would carry the
            # cursor past occurrences this batch stopped short of and lose them
            # permanently — the exact failure the ordering above prevents.
            fired_at=batch.consumed[-1],
            run_id=_pointer(batch.links, batch.consumed),
            next_due_at=due.next_due_at if complete else schedule.next_due_at,
            # Every consumed occurrence has a Run — ours, or the one that won
            # the claim — so every one is a firing. Passed as occurrences, not
            # a count: the store counts each once against its stored cursor,
            # so the ticker that won and the ticker that was refused cannot
            # count one firing twice, and a winner that died before recording
            # is still counted once (#1059 review).
            fires=0,
            fired=batch.consumed,
        )

    async def _consume_without_firing(self, schedule: Schedule, due: _Due) -> ScheduleAdmission:
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

        An occurrence that already had its Run when the tick began — a crashed
        winner the policy would have dropped in favour of a newer one — is not
        a skip: it fired, so it is consumed, linked and counted like any other
        firing (#1059 review).
        """
        consumable = [s.scheduled_for for s in due.skipped if s.reason not in _UNCONSUMED_SKIPS]
        consumed = sorted(consumable + list(due.already_fired))
        # The due cursor moves only when nothing is owed (#1199). `due()`
        # selects on `next_due_at`, so advancing it past a buffered occurrence
        # would hide the schedule from the tick until the occurrence *after*
        # the one it still has to run.
        next_due_at = schedule.next_due_at if _owes(due.skipped) else due.next_due_at
        if not consumed:
            if next_due_at is not None and next_due_at != schedule.next_due_at:
                # Nothing fired and nothing was dropped, but the evaluation
                # still learned when the next occurrence is — and a schedule
                # that never records it stays selected by `due()` on every
                # tick until its first occurrence, however far off that is
                # (#1199). No occurrence was consumed, so `fired_at=None`
                # leaves the enumeration cursor where it is; only the due
                # cursor is written, and only when it changed, so an idle
                # schedule costs no write per tick.
                await self._schedules.record_fire(
                    schedule.schedule_id, fired_at=None, run_id=None, next_due_at=next_due_at
                )
            return due.admission()
        recorded = await self._schedules.record_fire(
            schedule.schedule_id,
            fired_at=consumed[-1],
            # The Run behind the newest occurrence that *has* one — a skip
            # produced nothing and does not compete — or None when its Run
            # cannot be resolved: `_advance` keeps the existing id rather than
            # clearing it, which is what makes "the last Run this schedule
            # produced" survive an occurrence that produced none.
            run_id=_pointer(due.links, list(due.already_fired)),
            next_due_at=next_due_at,
            fires=0,
            fired=list(due.already_fired),
        )
        return due.admission(
            disabled=recorded is not None and not recorded.enabled,
            already_fired=due.already_fired,
        )

    async def _winning_run_id(self, schedule: Schedule, fire: FireDecision) -> str | None:
        """The Run that holds the claim this admitter was just refused (#1059).

        A `DuplicateOccurrence` says the firing happened; it does not say
        which Run it became, and `record_fire` needs that Run to keep
        `last_run_id` truthful. Before this the cursor advanced past a rival's
        occurrence with the pointer stale, the caller then answered
        `active_run` from the wrong Run, and a SKIP schedule admitted a later
        occurrence on top of the one still running.

        None, not an error, when the claim's Run can no longer be found: the
        stores only ever evict or purge a *terminal* Run, so an unresolvable
        winner is one that has finished, and nothing needs to be linked for
        overlap to be judged correctly. Logged either way, because "this tick
        admitted nothing because it was already admitted" is an operational
        fact and the winner's identity is the useful half of it.
        """
        winner = await self._runs.get_run_for_occurrence(
            schedule.schedule_id, fire.scheduled_for.isoformat()
        )
        logger.info(
            "schedule %s occurrence %s was already admitted elsewhere as Run %s",
            schedule.schedule_id,
            fire.scheduled_for.isoformat(),
            winner.run_id if winner is not None else "<unresolvable>",
        )
        return winner.run_id if winner is not None else None

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

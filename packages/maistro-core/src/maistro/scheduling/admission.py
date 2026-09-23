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

**A manual fire is the same authority, one occurrence wide (#1119, #1120).**
The `manual=True` variant of `admit_due` exists because a product "run this
schedule now" request is not an occurrence the cron enumerated — `evaluate()`
has nothing to say about it — but everything *after* that decision is the
recurring path's: the durable template resolution, `_admit_one`'s Run with its
provenance, the occurrence claim, and `record_fire`'s advance-and-disable. A manual fire counts against
`max_runs` and names the schedule in Run provenance exactly as an enumerated
one does, so the product cannot grow a second set of firing semantics by
asking for a fire by hand. Its occurrence identity is the caller-stable
`fire_id` token rather than a fresh instant per request, so a retried or
concurrent double submit reconciles to the one Run the first call created
(#1120) instead of silently becoming two.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from maistro.graph.templates import require_template
from maistro.observability.correlation import (
    bind_execution_context,
    current_execution_context,
    detached_execution_context,
)
from maistro.runs.model import TERMINAL_RUN_STATUSES, RunStatus
from maistro.runs.sources import (
    ADMISSION_SOURCE,
    SCHEDULE_CATCHUP_KEY,
    SCHEDULE_FIRE_ID_KEY,
    SCHEDULE_ID_KEY,
    SCHEDULE_INPUTS_KEY,
    SCHEDULE_SOURCE,
    SCHEDULE_TRIGGER_KEY,
    SCHEDULE_TRIGGER_MANUAL,
    SCHEDULE_TRIGGER_RECURRING,
    SCHEDULED_FOR_KEY,
)
from maistro.runs.store import DuplicateOccurrence, RunIntegrityError
from maistro.scheduling.engine import FireDecision, SkipReason, enumeration_start, evaluate
from maistro.scheduling.store import ScheduleExhausted

if TYPE_CHECKING:
    from maistro.graph.definitions import GraphTemplate
    from maistro.graph.templates import GraphTemplateStore
    from maistro.runs.model import Run
    from maistro.runs.store import RunStore
    from maistro.scheduling.engine import ScheduleEvaluation, SkippedFire
    from maistro.scheduling.model import Schedule
    from maistro.scheduling.store import ScheduleStore

logger = logging.getLogger("maistro.scheduling.admission")

#: Provenance key recording a scheduled Run's own correlation root (#1063).
#: `admit_due` runs on the background tick loop, never inside an incoming
#: request, so each admitted occurrence mints its own rather than leaving the
#: Run uncorrelated or risking a stray id from an unrelated Attempt left
#: bound on the same event loop tick.
REQUEST_ID_KEY = "request_id"

#: Skip reasons whose occurrence is still owed, so the cursor must not pass it.
#:
#: Read from `SkipReason`'s own documentation rather than restated: BUFFERED
#: says the cursor does not advance because "run one queued occurrence
#: afterwards" is what BUFFER_ONE means, and TRUNCATED says a caller advancing
#: on it "would otherwise lose the occurrence with no record of it". Every other
#: reason is a decision not to run that occurrence at all.
_UNCONSUMED_SKIPS: Final = frozenset({SkipReason.BUFFERED, SkipReason.TRUNCATED})


class ManualFireRefused(Exception):
    """A manually requested occurrence was refused before anything happened.

    `admit_due` reports refusals in a `failures` tuple because one bad
    occurrence must not discard the sibling occurrences sharing its batch. A
    manual fire is one occurrence — there are no siblings, and the caller owes
    whoever pressed "run now" a direct answer rather than a log line — so this
    raises instead. Nothing has been created or recorded when it does: the
    schedule's cursor, `runs_so_far`, and enabled flag are all exactly as they
    were.
    """


def _owes(decision: ScheduleEvaluation) -> bool:
    """Whether the evaluation left an occurrence that still has to run."""
    return any(skip.reason in _UNCONSUMED_SKIPS for skip in decision.skipped)


#: Skips whose occurrences the policy never acts on, so their claims are not
#: looked up: the window already dropped them, or the enumeration cap did.
_UNCLAIMABLE: Final = frozenset({SkipReason.OUTSIDE_CATCHUP, SkipReason.TRUNCATED})


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
    Runs, each naming this schedule. When that winner cannot be resolved the
    answer is None, and `_advance` keeps the existing pointer: an earlier Run
    of this batch must not masquerade as the newest, because the caller
    answers `active_run` from the pointer and would be judging overlap against
    a Run that is not the latest. Occurrences consumed *without* a Run (a
    policy skip) are not in `fired`: they produced nothing, so they do not
    compete for the pointer.
    """
    return links.get(max(fired)) if fired else None


def _dropped_moments(decision: ScheduleEvaluation) -> list[datetime]:
    """The occurrences this evaluation *dropped* rather than deferred.

    `_UNCONSUMED_SKIPS` draws the line and this reads it: BUFFERED and
    TRUNCATED are occurrences still owed, so the cursor must not pass them.
    Every other reason — overlap, disabled, exhausted, outside the catch-up
    window — is a decision not to run that occurrence at all, and the cursor
    consumes it.
    """
    return [skip.scheduled_for for skip in decision.skipped if skip.reason not in _UNCONSUMED_SKIPS]


def _recovered_fires(claimed: list[datetime], recovered: frozenset[datetime]) -> int:
    """How many of `claimed` count as firings this tick must record.

    Recovered claims — the pre-horizon walk's, provably unrecorded — are the
    dead ticker's earned count, recovered exactly once (#1059). Claims on
    enumerated occurrences are not counted here: the ticker that won them
    counts those itself (#1269), so counting them again would fire a
    `max_runs` schedule short.
    """
    return sum(1 for moment in claimed if moment in recovered)


def _due_cursor_changed(schedule: Schedule, next_due_at: datetime | None) -> bool:
    """Whether the evaluation learned a due time the schedule does not carry.

    A schedule that never records its first `next_due_at` stays selected by
    `due()` on every tick until that occurrence arrives, however far off it is
    (#1199); writing it only when it changed keeps an idle schedule free.
    """
    return next_due_at is not None and next_due_at != schedule.next_due_at


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

    reconciled_run_id: str | None = None
    """The Run that already held this admission's own duplicate claim (#1120).

    Set for a manual fire whose `(schedule_id, fire_id)` occurrence was
    claimed by a concurrent or retried caller of the same logical request:
    the documented reconciliation is the first caller's receipt, not a
    refusal, so the loser resolves and returns the winner's Run instead of
    creating a second one. Unset for recurring admissions, whose winners are
    already linked through `last_run_id`.
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
        manual: bool = False,
        fire_id: str | None = None,
    ) -> ScheduleAdmission:
        """Admit due occurrences, or one explicit manual occurrence.

        `active_run` is whether a Run this schedule started is still in flight.
        The caller answers it from Run state, which is the only place it lives —
        the same contract `evaluate()` states. When `manual` is true, the
        caller's `now` is the instant the fire was asked for (observability,
        kept in the Run's `scheduled_for`), cron overlap policy is deliberately
        bypassed, and `fire_id` is the fire's occurrence identity: the opaque
        token that makes a retried or concurrent double submit of the same
        logical request reconcile to the Run the first call created (#1120),
        the same authority, template, Run, occurrence claim, and cursor as a
        nominal occurrence. A manual fire without a `fire_id` mints one, which
        makes each call its own deliberate firing.
        """
        if manual:
            return await self._admit_manual(schedule, now=now, fire_id=fire_id)

        decision = evaluate(schedule, now=now, active_run=active_run)
        decision, claims, active_run_id, recovered_moments = await self._reconcile_claims(
            schedule, decision, now=now, active_run=active_run
        )
        if not decision.fires:
            return await self._consume_without_firing(
                schedule,
                decision,
                claims=claims,
                active_run_id=active_run_id,
                recovered=recovered_moments,
            )

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
        # The cursor's last_run_id follows the newest consumed occurrence, not
        # merely the newest Run created by this admitter. A duplicate claim may
        # be the winning Run from another ticker (or before this process
        # crashed), and losing that identity is what makes overlap recovery
        # unsafe.
        consumed_run_ids: list[str] = []
        admitted: list[FireDecision] = []
        already_fired: list[datetime] = []
        consumed: list[datetime] = []
        failures: list[Exception] = []
        already_fired, seeded_run_ids, seeded = self._seed_off_fire_claims(claims, decision)
        consumed_run_ids.extend(seeded_run_ids)
        consumed.extend(seeded)
        # Recovered claims — the pre-horizon walk's, provably unrecorded —
        # are firings nobody recorded, so this tick records the count the
        # dead ticker earned, once. Claims on enumerated occurrences are NOT
        # counted: the winner's ticker counts those, whichever direction the
        # race resolved (#1269).
        recovered = len(recovered_moments)
        for fire in decision.fires:
            try:
                # A clean slate, not just a fresh id: this loop runs on the
                # background tick loop, sharing an event loop with whatever
                # else happens to be running, so it must not risk inheriting
                # a stray Attempt's ids still bound on this tick.
                with (
                    detached_execution_context(),
                    bind_execution_context(request_id=uuid.uuid4().hex[:12]),
                ):
                    run_id = await self._admit_one(schedule, template, fire)
                run_ids.append(run_id)
                consumed_run_ids.append(run_id)
                admitted.append(fire)
                consumed.append(fire.scheduled_for)
            except DuplicateOccurrence as exc:
                # The unique claim proves that a canonical Run exists, but the
                # exception alone does not identify it. Resolve through the
                # RunStore's occurrence index before advancing the cursor; a
                # provenance scan here would make recovery linear and would
                # duplicate the store's execution authority.
                winner = await self._resolve_duplicate_winner(exc, schedule, failures)
                if winner is None:
                    break
                # **Continue**, unlike every other failure below. The claim
                # refusing this insert says the occurrence already has its Run
                # (#220) — nothing is owed, so stopping here would re-enumerate
                # a firing that has already happened on every subsequent tick.
                #
                # Counted as consumed so the cursor may pass it, but *not* as
                # admitted: `fires` feeds `runs_so_far`, and both tickers
                # counting one firing would exhaust `max_runs` at half the
                # occurrences it was configured for. The winning identity is
                # nevertheless carried into the cursor projection.
                logger.info(
                    "schedule %s occurrence %s was already admitted elsewhere as %s",
                    schedule.schedule_id,
                    fire.scheduled_for.isoformat(),
                    winner.run_id,
                )
                already_fired.append(fire.scheduled_for)
                consumed_run_ids.append(winner.run_id)
                consumed.append(fire.scheduled_for)
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

        consumed.sort()

        if not consumed:
            return ScheduleAdmission(
                skipped=decision.skipped,
                next_due_at=decision.next_due_at,
                cancel_active_run=decision.cancel_active_run,
                active_run_id=active_run_id,
                failures=tuple(failures),
            )

        # Recovered claims count toward `max_runs`; claims on this batch's own
        # fires do not — the winner's ticker counts those.
        fires_recorded = len(admitted) + recovered
        disable = self._exhausted_after(schedule, fires=fires_recorded)
        # `next_due_at` is recomputed only when the whole batch landed and
        # nothing was held back. A partial batch leaves occurrences owed, and
        # `evaluate()`'s answer assumed all of them fired; a buffered
        # occurrence is owed the same way (#1199). Recovered claims are
        # consumed *beside* the batch, so `consumed` can exceed the fires
        # without any fire being left behind.
        complete = len(consumed) >= len(decision.fires) and not _owes(decision)
        await self._schedules.record_fire(
            schedule.schedule_id,
            # The newest occurrence *admitted*, not `now`. This value becomes
            # the lower bound of the next enumeration, so `now` would carry the
            # cursor past occurrences this batch stopped short of and lose them
            # permanently — the exact failure the ordering above prevents.
            fired_at=consumed[-1],
            # The newest Run, matching the cursor being the newest fire.
            # `Schedule.last_run_id` is a pointer to the latest occurrence, not
            # a history of them; the history is on the Runs, each naming this
            # schedule.
            # The newest consumed occurrence may have been claimed by another
            # admitter. Its resolved winner is the truthful linkage; leaving an
            # older id in place makes `_canonical_active_run()` lie about live
            # work after a crash between Run creation and this write.
            run_id=consumed_run_ids[-1],
            next_due_at=decision.next_due_at if complete else schedule.next_due_at,
            fires=fires_recorded,
            disable=disable,
        )
        return ScheduleAdmission(
            run_ids=tuple(run_ids),
            skipped=decision.skipped,
            next_due_at=decision.next_due_at,
            disabled=disable,
            cancel_active_run=decision.cancel_active_run,
            active_run_id=active_run_id,
            already_fired=tuple(sorted(already_fired)),
            failures=tuple(failures),
        )

    @staticmethod
    def _seed_off_fire_claims(
        claims: dict[datetime, Run], decision: ScheduleEvaluation
    ) -> tuple[list[datetime], list[str], list[datetime]]:
        """Consume the claims that sit off this batch's enumerated fires.

        A winner that crashed before the catch-up horizon, or one the policy
        just dropped in favour of a newer occurrence, never reaches the
        refusing-claim path below, so it is consumed here, without an insert:
        it fired when its Run was created (#1059). Claims on this batch's own
        fires are left alone — they are resolved reactively, through the
        refusing claim itself, which is also what keeps the fire count honest:
        the ticker that won the claim counts it, whichever direction the race
        resolves (#1269).
        """
        enumerated = {fire.scheduled_for for fire in decision.fires}
        moments: list[datetime] = []
        run_ids: list[str] = []
        for moment in sorted(claims):
            if moment in enumerated:
                continue
            moments.append(moment)
            run_ids.append(claims[moment].run_id)
        return moments, run_ids, moments

    async def _reconcile_claims(
        self,
        schedule: Schedule,
        decision: ScheduleEvaluation,
        *,
        now: datetime,
        active_run: bool,
    ) -> tuple[ScheduleEvaluation, dict[datetime, Run], str | None, frozenset[datetime]]:
        """Fold the Run store's claims into one evaluation, before the policy.

        The pointer the caller answered `active_run` from can be stale: a
        ticker that created a Run and died before `record_fire` left it unset
        (#1059). So the occurrences this evaluation enumerates — and the
        contiguous ones just before its horizon — are checked against the Run
        store *before* the overlap policy is applied: an occurrence that
        already has its Run is already fired, whatever the policy would have
        done with it, and a live one is what the policy sees as in flight,
        whatever the pointer said — so the decision is re-asked with the truth
        and `SKIP` defers to the crashed winner, `CANCEL_OTHER` reports it.

        Returns the (possibly re-asked) decision, the claims, the live
        winner's id, and the *recoverable* claims: the pre-horizon walk's,
        which are provably unrecorded — recording an occurrence moves the
        cursor onto it, and these sit behind the cursor — so this tick counts
        them. Claims on enumerated occurrences are a different provenance: the
        boundary re-enumerates an occurrence the cursor sits on, whose winner
        may well have recorded it, so those stay with the reactive rule — the
        winner's ticker counts, this one does not (#1269).
        """
        claims, recovered = await self._existing_claims(schedule, decision, now=now)
        live = _live_claim(claims)
        if live is not None and not active_run:
            decision = evaluate(schedule, now=now, active_run=True)
        return decision, claims, live.run_id if live is not None else None, frozenset(recovered)

    async def _existing_claims(
        self, schedule: Schedule, decision: ScheduleEvaluation, *, now: datetime
    ) -> tuple[dict[datetime, Run], list[datetime]]:
        """The Runs that already hold a claim on this evaluation's occurrences.

        Recovery's blind spot (#1059): after a ticker dies between
        `create_run` and `record_fire`, the next tick re-enumerates that
        occurrence beside newer ones, and the reactive duplicate path does
        resolve it — but only for occurrences the evaluation still enumerates.
        Under `CANCEL_OTHER` the policy keeps only the newest and drops the
        crashed one into `skipped`, so it never reaches the duplicate handler;
        the newer Run is admitted with no cancellation asked for while the old
        winner keeps running, counted by nobody. Reading the claims first is
        what lets the policy, the pointer and the fire count all see the Run
        that exists.

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
            run = await self._lookup_claim(schedule, moment)
            if run is not None:
                claims[moment] = run
        walk: list[datetime] = []
        for moment in self._claims_before(schedule, enumeration_start(schedule, now=now)):
            run = await self._lookup_claim(schedule, moment)
            if run is None:
                break
            claims[moment] = run
            walk.append(moment)
        return claims, walk

    async def _lookup_claim(self, schedule: Schedule, moment: datetime) -> Run | None:
        """One occurrence-claim probe, or None when the store cannot answer.

        The pre-policy read is an *extra* chance to see a winner, never the
        only one: an occurrence this evaluation still enumerates is protected
        anyway by its refusing claim, resolved — and its lookup failure
        recorded — in the reactive path. Degrading a transient outage to "no
        claim seen" defers recovery one tick; raising here would crash a tick
        that the reactive design rides out (#1059).
        """
        try:
            return await self._runs.get_run_for_occurrence(schedule.schedule_id, moment.isoformat())
        except Exception as exc:
            logger.warning(
                "schedule %s could not probe the claim on %s: %s",
                schedule.schedule_id,
                moment.isoformat(),
                exc,
            )
            return None

    def _claims_before(self, schedule: Schedule, since: datetime) -> Iterator[datetime]:
        """Candidate occurrences from the cursor up to and including `since`.

        A batch admits occurrences in order and dies at one, so its Runs sit
        contiguously after the cursor; the caller stops at the first probe
        that comes back empty, which is what bounds this to one batch's worth
        of moments and makes an idle tick pay nothing.
        """
        moment = schedule.next_fire_after(schedule.last_fired_at or schedule.created_at)
        while moment <= since:
            yield moment
            moment = schedule.next_fire_after(moment)

    async def _resolve_duplicate_winner(
        self,
        exc: DuplicateOccurrence,
        schedule: Schedule,
        failures: list[Exception],
    ) -> Run | None:
        """The winning Run of an occurrence that was already claimed.

        Two ways to come up empty, and both are recorded in `failures` rather
        than raised, because the caller's batch loop turns an escape from
        `admit_due` into a broken contract: occurrences the batch already
        admitted would never reach `record_fire`, losing the cursor advance
        they have earned (#1269). The first is torn state — the claim's
        insert was refused but the occurrence index names no canonical Run.
        The second is transient: the resolution is a store read like any
        other, and a connection drop must not masquerade as an admission
        bug. Both stop the batch; the caller breaks on the `None`.
        """
        try:
            winner = await self._runs.get_run_for_occurrence(exc.schedule_id, exc.scheduled_for)
        except Exception as lookup_failure:
            logger.warning(
                "schedule %s could not resolve occurrence %s: %s",
                schedule.schedule_id,
                exc.scheduled_for,
                lookup_failure,
            )
            failures.append(lookup_failure)
            return None
        if winner is None:
            failure = RunIntegrityError(
                "duplicate occurrence claim has no resolvable canonical Run"
            )
            logger.warning(
                "schedule %s could not reconcile occurrence %s: %s",
                schedule.schedule_id,
                exc.scheduled_for,
                failure,
            )
            failures.append(failure)
        return winner

    async def _admit_manual(
        self,
        schedule: Schedule,
        *,
        now: datetime,
        fire_id: str | None = None,
    ) -> ScheduleAdmission:
        """Admit the one occurrence the caller asked for *now*, off the cron.

        The returned `ScheduleAdmission` holds exactly one entry: `run_ids` of
        length one on success, or `already_fired` naming the fire's identity
        with `reconciled_run_id` resolving the Run that already holds it
        (#220, #1120).

        Four things differ from `admit_due`, each because a manual fire is
        not a cron occurrence:

        * **The occurrence identity is the fire's token, not the instant.**
          `fire_id` (minted as an opaque uuid when the caller supplies none,
          making each call its own deliberate firing) claims
          `(schedule_id, 'manual:' + fire_id)` — the same occurrence-claim
          uniqueness a nominal `(schedule_id, scheduled_for)` fires under, so
          a retried or concurrent double submit of the same logical request
          reconciles to the Run the first call created instead of minting a
          fresh identity per request (#1120). `now` is observability: it is
          the Run's `scheduled_for`, when the fire was asked for.
        * **The quota is claimed first, atomically.** `reserve_fire` counts
          the run and disables on exhaustion under the store's own lock,
          *before* the Run exists. Two callers racing on the last run cannot
          both pass an exhaustion check read from the same snapshot; the
          loser is refused. The order also fixes what a crash leaves behind:
          a process that dies between the reservation and the Run loses one
          slot (visible: `runs_so_far` moved, `last_run_id` did not), never
          the reverse, where a Run exists that no count admits to and the
          next request duplicates it. A duplicate claim — the reconciliation
          case above — settles the slot back: the winner already counted it.
        * **The recurrence cursor does not move.** `last_fired_at` and
          `next_due_at` describe the cron's occurrences; stamping *now* on
          them would carry the cursor past an occurrence that was already due
          but not yet ticked, and lose it. `last_run_id` is recorded, so the
          product row still resolves to the Run.
        * **Overlap policy is not consulted.** It keeps an automatic
          recurrence from stacking on its own in-flight Run; a manual fire is
          a person explicitly asking for another Run *now*.

        Refusals raise rather than fill `failures`: `ManualFireRefused` for a
        schedule at `max_runs`, the template store's own error for an
        unresolvable target, and the run store's for a Run that could not be
        created. A refusal before the reservation touches nothing; one after
        it releases the reservation, so the schedule reads as it did before.
        """
        if schedule.exhausted:
            raise ManualFireRefused(
                f"schedule {schedule.schedule_id} has used all {schedule.max_runs} of its runs"
            )
        try:
            template = await require_template(
                self._templates,
                schedule.graph_template_id,
                version=schedule.template_version,
            )
        except Exception as exc:
            logger.warning(
                "schedule %s cannot resolve template %s for its manual fire: %s",
                schedule.schedule_id,
                schedule.graph_template_id,
                exc,
            )
            raise

        token = fire_id if fire_id else uuid.uuid4().hex
        try:
            reserved = await self._schedules.reserve_fire(schedule.schedule_id)
        except ScheduleExhausted as exc:
            raise ManualFireRefused(str(exc)) from exc
        if reserved is None:
            raise ManualFireRefused(f"schedule {schedule.schedule_id} no longer exists")
        current, reservation = reserved

        fire = FireDecision(scheduled_for=now, catchup=False)
        try:
            run_id = await self._admit_one(current, template, fire, fire_id=token)
        except DuplicateOccurrence:
            logger.info(
                "schedule %s manual fire %s was already admitted elsewhere",
                schedule.schedule_id,
                token,
            )
            # The firing happened — some other admitter claimed this exact
            # logical request — so there is nothing to create; the slot goes
            # back and the loser is handed the winner's receipt, which is the
            # documented reconciliation for a retried or concurrent double
            # submit (#1120).
            await self._schedules.settle_fire(schedule.schedule_id, reservation, run_id=None)
            winner = await self._runs.find_occurrence_run(
                {
                    SCHEDULE_ID_KEY: schedule.schedule_id,
                    SCHEDULE_FIRE_ID_KEY: token,
                }
            )
            return ScheduleAdmission(
                already_fired=(now,),
                reconciled_run_id=winner.run_id if winner is not None else None,
            )
        except BaseException:
            await self._schedules.settle_fire(schedule.schedule_id, reservation, run_id=None)
            raise

        settled = await self._schedules.settle_fire(
            schedule.schedule_id, reservation, run_id=run_id
        )
        recorded = settled if settled is not None else current
        return ScheduleAdmission(
            run_ids=(run_id,),
            next_due_at=recorded.next_due_at,
            disabled=reservation.disabled,
        )

    async def _consume_without_firing(
        self,
        schedule: Schedule,
        decision: ScheduleEvaluation,
        *,
        claims: dict[datetime, Run] | None = None,
        active_run_id: str | None = None,
        recovered: frozenset[datetime] = frozenset(),
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

        An occurrence that already had its Run when the tick began — a crashed
        winner the policy would have dropped in favour of a newer one — is not
        a skip: it fired, so it is consumed, linked and counted like any other
        firing (#1059).
        """
        claims = claims or {}
        claimed = sorted(claims)
        consumed = sorted(_dropped_moments(decision) + claimed)
        # The due cursor moves only when nothing is owed (#1199). `due()`
        # selects on `next_due_at`, so advancing it past a buffered occurrence
        # would hide the schedule from the tick until the occurrence *after*
        # the one it still has to run.
        next_due_at = schedule.next_due_at if _owes(decision) else decision.next_due_at
        if consumed:
            fires = _recovered_fires(claimed, recovered)
            recorded = await self._schedules.record_fire(
                schedule.schedule_id,
                fired_at=consumed[-1],
                # The Run behind the newest occurrence that *has* one — a skip
                # produced nothing and does not compete. `_pointer` answers
                # None when only drops were consumed, and `_advance` keeps the
                # existing id then, which is what makes "the last Run this
                # schedule produced" survive an occurrence that produced none.
                run_id=_pointer({moment: claims[moment].run_id for moment in claimed}, claimed),
                next_due_at=next_due_at,
                fires=fires,
                disable=self._exhausted_after(schedule, fires=fires),
            )
            return ScheduleAdmission(
                skipped=decision.skipped,
                next_due_at=decision.next_due_at,
                disabled=recorded is not None and not recorded.enabled,
                cancel_active_run=decision.cancel_active_run,
                active_run_id=active_run_id,
                already_fired=tuple(claimed),
            )
        if _due_cursor_changed(schedule, next_due_at):
            # Nothing fired and nothing was dropped, but the evaluation still
            # learned when the next occurrence is — and a schedule that never
            # records it stays selected by `due()` on every tick until its
            # first occurrence, however far off that is (#1199). No occurrence
            # was consumed, so `fired_at=None` leaves the enumeration cursor
            # where it is; only the due cursor is written, and only when it
            # changed, so an idle schedule costs no write per tick.
            await self._schedules.record_fire(
                schedule.schedule_id,
                fired_at=None,
                run_id=None,
                next_due_at=next_due_at,
                fires=0,
            )
        return ScheduleAdmission(
            skipped=decision.skipped,
            next_due_at=decision.next_due_at,
            cancel_active_run=decision.cancel_active_run,
            active_run_id=active_run_id,
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
        self,
        schedule: Schedule,
        template: GraphTemplate,
        fire: FireDecision,
        *,
        fire_id: str | None = None,
    ) -> str:
        graph = template.instantiate(project_id=schedule.project_id, name=schedule.name or None)
        provenance: dict[str, Any] = {
            ADMISSION_SOURCE: SCHEDULE_SOURCE,
            SCHEDULE_ID_KEY: schedule.schedule_id,
            SCHEDULED_FOR_KEY: fire.scheduled_for.isoformat(),
            SCHEDULE_CATCHUP_KEY: fire.catchup,
        }
        if fire_id is not None:
            # A manual fire's identity is its caller-stable token, not the
            # instant its request arrived (#1120): `occurrence_key` reads this
            # before `scheduled_for`, so the claim — and therefore a retry's
            # reconciliation — is the same token across processes and
            # restarts, while `scheduled_for` above stays what it means
            # everywhere else: when the fire was asked for.
            provenance[SCHEDULE_FIRE_ID_KEY] = fire_id
            # Named, not implied by an absence: a Run with no trigger key is a
            # Run from before the distinction existed (#1120), which is a
            # different fact from "this was a nominal occurrence".
            provenance[SCHEDULE_TRIGGER_KEY] = SCHEDULE_TRIGGER_MANUAL
        else:
            provenance[SCHEDULE_TRIGGER_KEY] = SCHEDULE_TRIGGER_RECURRING
        if schedule.inputs:
            # `Schedule.inputs` is the schedule's configured payload, and
            # instantiating the template alone dropped it: a parameterized
            # schedule produced a Run indistinguishable from one configured
            # with nothing. Recorded on the Run rather than only handed to a
            # runner, because a Run that cannot say what it was asked to do
            # cannot be audited or replayed.
            provenance[SCHEDULE_INPUTS_KEY] = schedule.inputs
        request_id = current_execution_context().request_id
        if request_id:
            provenance[REQUEST_ID_KEY] = request_id
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


__all__ = ["ManualFireRefused", "ScheduleAdmission", "ScheduleRunAdmitter"]

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
provenance, the occurrence claim, and the same advance-and-disable discipline
— a manual fire settles its slot through `reserve_fire` /
`settle_pending_fire` rather than `record_fire` only because its occurrence is
the caller's token, not a cron moment the enumeration cursor could pass. A
manual fire counts against `max_runs` and names the schedule in Run provenance
exactly as an enumerated one does, so the product cannot grow a second set of
firing semantics by asking for a fire by hand. Its occurrence identity is the
caller-stable `fire_id` token rather than a fresh instant per request, so a
retried or concurrent double submit reconciles to the one Run the first call
created (#1120) instead of silently becoming two — and its slot is held, not
spent, until that Run exists, so a crash before the Run leaves no firing
behind and a crash after it is recoverable from the marker plus the Run.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
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
from maistro.scheduling.engine import (
    FireDecision,
    SkippedFire,
    SkipReason,
    enumeration_start,
    evaluate,
)
from maistro.scheduling.store import ScheduleExhausted

if TYPE_CHECKING:
    from maistro.graph.definitions import GraphTemplate
    from maistro.graph.templates import GraphTemplateStore
    from maistro.runs.model import Run
    from maistro.runs.store import RunStore
    from maistro.scheduling.engine import ScheduleEvaluation
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

#: How long a pending manual-fire marker is trusted as held by a live fire
#: (#1120).
#
# The marker exists to serialize the last `max_runs` unit between callers
# without spending it before the Run does, and its holder closes it in the
# one store write that also links the Run — a window of one Run-store insert.
# A lease far longer than that window is what lets recovery tell a dead
# holder from a live one: inside the lease the marker is untouchable (the
# race safety #1119 demanded), past it no healthy process can still be
# mid-fire, so the marker is a crash leftover and the next admission settles
# it against the Run store — a Run confirms the spend, none returns the slot.
# A process frozen mid-fire longer than the lease can have its slot taken
# while its Run lands anyway; both Runs then exist and are both counted,
# which is the honest durable state for work that really ran twice, and the
# price of un-bricking every schedule whose holder simply died.
_PENDING_FIRE_LEASE: Final = timedelta(seconds=60)


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
#: looked up: the catch-up window already dropped them.
#:
#: TRUNCATED is deliberately *not* here (Codex review, #1059): the enumeration
#: cap drops the oldest occurrences of an over-large batch from `evaluate()`'s
#: own output, but they are still real, in-window occurrences a live winner
#: can sit on — a high-frequency schedule stuck long enough to enumerate past
#: `_MAX_ENUMERATED_FIRES` is exactly the case recovery exists for. Probed
#: through `get_runs_for_occurrences` (#1533), one batched query rather than
#: one per truncated occurrence — see `_MAX_TRUNCATED_CLAIM_PROBES`.
_UNCLAIMABLE: Final = frozenset({SkipReason.OUTSIDE_CATCHUP})

#: How far the pre-horizon walk (`_claims_before`) will probe for a crashed
#: winner's claim, matching `evaluate()`'s own `_MAX_ENUMERATED_FIRES` order
#: of magnitude. A schedule stuck longer than this, at this cadence, is a
#: known, documented limit rather than an unbounded per-tick scan.
_MAX_RECOVERY_PROBES: Final = 512

#: How many `SkipReason.TRUNCATED` occurrences one evaluation's recovery walk
#: will probe for a claim, and the same order of magnitude as
#: `_MAX_RECOVERY_PROBES` for the same reason: `_enumerate_due` can truncate
#: tens of thousands of occurrences on a schedule stuck far longer than its
#: cadence allows, and probing every one of them — even in a single batched
#: query — is not a bound a per-tick recovery walk should be without (Codex
#: review, #1533). The newest of the dropped tail are probed first: they sit
#: closest to what `evaluate()` actually kept, so they are the likeliest to
#: share a winner with a rival ticker evaluating the same overloaded window.
_MAX_TRUNCATED_CLAIM_PROBES: Final = 512


def _enumerated(decision: ScheduleEvaluation) -> list[datetime]:
    """The occurrences probed one at a time: fires, and the skips the policy
    decided rather than the window or the cap.

    `TRUNCATED` is excluded here specifically (unlike `_UNCLAIMABLE`, which
    the catch-up window already dropped): it is still claimable, but
    `_existing_claims` probes it separately, batched and bounded, rather than
    joining this one-probe-per-occurrence loop — see
    `_MAX_TRUNCATED_CLAIM_PROBES` (#1533).
    """
    return [fire.scheduled_for for fire in decision.fires] + [
        skip.scheduled_for
        for skip in decision.skipped
        if skip.reason not in _UNCLAIMABLE and skip.reason is not SkipReason.TRUNCATED
    ]


def _truncated(decision: ScheduleEvaluation) -> list[datetime]:
    """This evaluation's dropped tail, oldest first — `evaluate()`'s own order."""
    return [skip.scheduled_for for skip in decision.skipped if skip.reason is SkipReason.TRUNCATED]


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


def _without_claimed_skips(
    decision: ScheduleEvaluation, claims: dict[datetime, Run]
) -> ScheduleEvaluation:
    """Drop a skip whose occurrence a claim lookup already found a Run for.

    `evaluate()` decides `skipped` (OVERLAP, EXHAUSTED, ...) with no idea the
    occurrence already fired elsewhere (#1059 review, Codex). Once the claim
    lookup answers that question, reporting the same occurrence in `skipped`
    *and* in `already_fired` is self-contradictory — one says it never ran,
    the other says it did. The claim is the truth; the skip is stale.
    """
    if not claims:
        return decision
    kept = tuple(skip for skip in decision.skipped if skip.scheduled_for not in claims)
    if len(kept) == len(decision.skipped):
        return decision
    return replace(decision, skipped=kept)


def _reserve_recovery_budget(
    schedule: Schedule, decision: ScheduleEvaluation, recovered: frozenset[datetime]
) -> ScheduleEvaluation:
    """Refuse new fires that recovered claims have already spent the quota on.

    `evaluate()` decided `decision.fires` against `schedule.runs_remaining`
    before recovery was known, because the recovered claims only surface
    afterwards, from the Run store (#1059 review, Codex). A recovered claim is
    the dead ticker's earned count — real, `max_runs`-spending firings — and
    this tick records them *beside* whatever it admits, in the same
    `record_fire` call. Left unreserved, a bounded schedule can end up with
    more live Runs than `max_runs` ever allowed: `evaluate()` sees the old,
    not-yet-spent `runs_so_far` and lets a new occurrence through, and only
    *after* that Run exists does the batch's total (admitted + recovered)
    turn out to have been one too many.

    Refused fires keep the same ordering `_apply_max_runs` already uses —
    the oldest admitted, the newest refused — so a partial batch still makes
    forward progress rather than starving on its earliest occurrence.
    """
    if schedule.max_runs is None or not recovered or not decision.fires:
        return decision
    remaining = max(0, schedule.max_runs - schedule.runs_so_far - len(recovered))
    if len(decision.fires) <= remaining:
        return decision
    allowed, refused = decision.fires[:remaining], decision.fires[remaining:]
    refused_skips = tuple(
        SkippedFire(scheduled_for=fire.scheduled_for, reason=SkipReason.EXHAUSTED)
        for fire in refused
    )
    return replace(
        decision,
        fires=allowed,
        skipped=decision.skipped + refused_skips,
        # Nothing new will fire to take over from the active Run when the
        # quota recovery already spent refuses the only candidate.
        cancel_active_run=decision.cancel_active_run and bool(allowed),
        exhausted=True,
    )


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

    async def _record_fire(
        self,
        schedule_id: str,
        *,
        fired_at: datetime | None,
        run_id: str | None,
        next_due_at: datetime | None,
        fires: int | None,
        recovered: frozenset[datetime],
    ) -> Schedule | None:
        """`ScheduleStore.record_fire`, naming `recovered=` only when there
        is something to credit.

        `record_fire` grew `recovered` with a default value (`frozenset()`,
        #1059), which is exactly what protects a downstream `ScheduleStore`
        implementation that predates the parameter — *as long as nothing
        calls it by name*. This admitter used to name it on every call
        regardless, so an external implementation using the previously valid
        signature — `record_fire(self, schedule_id, *, fired_at, run_id,
        next_due_at, fires=None, disable=False)`, no `recovered` parameter
        at all — raised `TypeError: unexpected keyword argument 'recovered'`
        on every ordinary recurring fire after upgrading, not merely a
        recovering one (Codex review, #1533).

        Two literal calls rather than one built from `**kwargs`: a
        conditionally-assembled kwargs dict cannot be checked against
        `record_fire`'s mixed-type keyword signature under `mypy --strict`,
        and this reads exactly as directly. The common, no-recovery case
        stays compatible with an old implementation; a genuinely recovered
        claim still names the keyword, and still fails loudly against a
        store that cannot accept it — the correct outcome, since silently
        omitting it there would silently drop the credit, reintroducing the
        exact under-counting bug `recovered` exists to close (#1059, #1533).
        """
        if recovered:
            return await self._schedules.record_fire(
                schedule_id,
                fired_at=fired_at,
                run_id=run_id,
                next_due_at=next_due_at,
                fires=fires,
                recovered=recovered,
            )
        return await self._schedules.record_fire(
            schedule_id,
            fired_at=fired_at,
            run_id=run_id,
            next_due_at=next_due_at,
            fires=fires,
        )

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

        if schedule.pending_fires:
            # A manual fire died mid-window and left its marker behind
            # (#1120). Guarded on the snapshot so an idle schedule — the
            # overwhelmingly common tick — pays nothing: only a row that
            # actually holds markers triggers the reconciliation read.
            schedule = await self._reconcile_pending_fires(schedule.schedule_id) or schedule

        decision = evaluate(schedule, now=now, active_run=active_run)
        decision, claims, active_run_id, recovered_moments = await self._reconcile_claims(
            schedule, decision, now=now, active_run=active_run
        )
        # Recovered claims spend `max_runs` too, and `evaluate()` decided
        # `decision.fires` before it knew about them.
        decision = _reserve_recovery_budget(schedule, decision, recovered_moments)
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

        # The cursor's last_run_id follows the newest consumed occurrence, not
        # merely the newest Run created by this admitter. A duplicate claim may
        # be the winning Run from another ticker (or before this process
        # crashed), and losing that identity is what makes overlap recovery
        # unsafe. Kept as (occurrence, run_id) pairs, not two parallel lists
        # (Codex review, #1269): a seeded claim and a batch fire are not
        # necessarily chronological relative to each other — BUFFER_ONE's own
        # skip can sit *after* its fire — so sorting one list and not the
        # other can pair a timestamp with a different occurrence's Run.
        consumed_links: list[tuple[datetime, str]] = []
        failures: list[Exception] = []
        already_fired, seeded_run_ids, seeded = self._seed_off_fire_claims(claims, decision)
        consumed_links.extend(zip(seeded, seeded_run_ids, strict=True))
        # `batch_completed` (see `_admit_batch`) is what `complete` below is
        # computed from, rather than comparing lengths against
        # `consumed_links`: a seeded recovered claim (off this batch
        # entirely) can pad `consumed_links` to the same length as
        # `decision.fires` even when a later fire in the batch failed and was
        # never reached (Codex review, #1059) — the length coincidence says
        # nothing about whether *this* batch actually finished.
        run_ids, admitted_count, batch_completed = await self._admit_batch(
            schedule,
            template,
            decision.fires,
            already_fired=already_fired,
            consumed_links=consumed_links,
            failures=failures,
        )

        consumed_links.sort(key=lambda link: link[0])

        if not consumed_links:
            return ScheduleAdmission(
                skipped=decision.skipped,
                next_due_at=decision.next_due_at,
                cancel_active_run=decision.cancel_active_run,
                active_run_id=active_run_id,
                failures=tuple(failures),
            )

        # `next_due_at` is recomputed only when the whole batch landed and
        # nothing was held back. A partial batch leaves occurrences owed, and
        # `evaluate()`'s answer assumed all of them fired; a buffered
        # occurrence is owed the same way (#1199).
        complete = batch_completed and not _owes(decision)
        recorded = await self._record_fire(
            schedule.schedule_id,
            # The newest occurrence *admitted*, not `now`. This value becomes
            # the lower bound of the next enumeration, so `now` would carry the
            # cursor past occurrences this batch stopped short of and lose them
            # permanently — the exact failure the ordering above prevents.
            fired_at=consumed_links[-1][0],
            # The newest Run, matching the cursor being the newest fire.
            # `Schedule.last_run_id` is a pointer to the latest occurrence, not
            # a history of them; the history is on the Runs, each naming this
            # schedule.
            # The newest consumed occurrence may have been claimed by another
            # admitter. Its resolved winner is the truthful linkage; leaving an
            # older id in place makes `_canonical_active_run()` lie about live
            # work after a crash between Run creation and this write.
            run_id=consumed_links[-1][1],
            next_due_at=decision.next_due_at if complete else schedule.next_due_at,
            # Certain: each of this batch's admitted Runs is this call's own,
            # protected by the RunStore's own occurrence uniqueness. Recovered
            # claims are credited separately, deduplicated by the store itself
            # against a rival ticker crediting the same claim (#1059 review).
            fires=admitted_count,
            recovered=recovered_moments,
        )
        disabled = recorded is not None and not recorded.enabled
        return ScheduleAdmission(
            run_ids=tuple(run_ids),
            skipped=decision.skipped,
            next_due_at=decision.next_due_at,
            disabled=disabled,
            cancel_active_run=decision.cancel_active_run,
            active_run_id=active_run_id,
            already_fired=tuple(sorted(already_fired)),
            failures=tuple(failures),
        )

    async def _admit_batch(
        self,
        schedule: Schedule,
        template: GraphTemplate,
        fires: tuple[FireDecision, ...],
        *,
        already_fired: list[datetime],
        consumed_links: list[tuple[datetime, str]],
        failures: list[Exception],
    ) -> tuple[list[str], int, bool]:
        """Admit each due occurrence in order, stopping at the first real failure.

        `already_fired`, `consumed_links`, and `failures` arrive already
        seeded from `_seed_off_fire_claims` and are extended in place, the
        same lists `admit_due` goes on to use. Returns this batch's own Run
        ids, how many of `fires` were actually admitted (as opposed to merely
        resolved as a duplicate), and whether the batch ran to completion.
        """
        run_ids: list[str] = []
        admitted_count = 0
        # Whether every one of `fires` was resolved, admitted or found
        # already-fired, rather than cut short by a real failure. `admit_due`
        # uses this instead of comparing lengths against `consumed_links`: a
        # seeded recovered claim (off this batch entirely) can pad
        # `consumed_links` to the same length as `fires` even when a later
        # fire in the batch failed and was never reached (Codex review,
        # #1059) — the length coincidence says nothing about whether *this*
        # batch actually finished.
        batch_completed = True
        for fire in fires:
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
                consumed_links.append((fire.scheduled_for, run_id))
                admitted_count += 1
            except DuplicateOccurrence as exc:
                # The unique claim proves that a canonical Run exists, but the
                # exception alone does not identify it. Resolve through the
                # RunStore's occurrence index before advancing the cursor; a
                # provenance scan here would make recovery linear and would
                # duplicate the store's execution authority.
                winner = await self._resolve_duplicate_winner(exc, schedule, failures)
                if winner is None:
                    batch_completed = False
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
                consumed_links.append((fire.scheduled_for, winner.run_id))
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
                batch_completed = False
                break
        return run_ids, admitted_count, batch_completed

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
        # A claim resolves what `evaluate()` could not have known: an
        # occurrence it skipped (OVERLAP, EXHAUSTED, ...) may already have a
        # Run. Reporting both a skip and `already_fired` for the same
        # occurrence contradicts itself (Codex, #1059 review).
        decision = _without_claimed_skips(decision, claims)
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
        tick. Occurrences the catch-up window already dropped are not looked
        up: the policy does not act on them.

        `TRUNCATED` occurrences are probed separately, in one batched query
        bounded by `_MAX_TRUNCATED_CLAIM_PROBES` (Codex review, #1533):
        `_enumerate_due` can truncate tens of thousands of occurrences on a
        schedule stuck far longer than its cadence allows, and joining that
        many into the per-occurrence loop above would turn one recovery tick
        into that many serial, awaited Run-store queries even though the
        truncation itself cost nothing but memory.

        The enumeration starts after the catch-up horizon, so a winner that
        crashed before it — the ticker died mid-fire and stayed down longer
        than the window — is never enumerated at all. Those claims are walked
        instead, from the cursor forward (`_claims_before`).

        The walk does *not* stop at the first occurrence without a Run (Codex
        review, #1059): a batch's own Runs sit contiguously, but a crashed
        batch's *cursor* does not move, so a later tick's walk starts at the
        same place a policy like `CANCEL_OTHER` or `BUFFER_ONE` left
        legitimately Run-less occurrences the *first* time — the ones it chose
        not to admit, beside the one it did. Stopping there would read "never
        admitted" off an occurrence that was simply never meant to have a Run,
        and miss the live winner sitting just past it. The walk is bounded
        instead by `_MAX_RECOVERY_PROBES`, the same order of magnitude as
        `evaluate()`'s own enumeration cap, so a schedule stuck far longer
        than that remains a known, documented limit rather than an unbounded
        scan — one lookup on the idle common path, at most that many on the
        crashed-and-lagging one.
        """
        claims: dict[datetime, Run] = {}
        for moment in _enumerated(decision):
            run = await self._lookup_claim(schedule, moment)
            if run is not None:
                claims[moment] = run
        claims.update(await self._lookup_truncated_claims(schedule, decision))
        walk: list[datetime] = []
        for moment in self._claims_before(schedule, enumeration_start(schedule, now=now)):
            run = await self._lookup_claim(schedule, moment)
            if run is not None:
                claims[moment] = run
                walk.append(moment)
        return claims, walk

    async def _lookup_truncated_claims(
        self, schedule: Schedule, decision: ScheduleEvaluation
    ) -> dict[datetime, Run]:
        """The dropped tail's claims, one batched query bounded by
        `_MAX_TRUNCATED_CLAIM_PROBES` rather than one query per occurrence.

        The newest `_MAX_TRUNCATED_CLAIM_PROBES` of the tail are probed —
        `evaluate()` returns `truncated` oldest first (#1533), so this is the
        slice nearest the horizon it actually enumerated, the likeliest to
        share a winner with a rival ticker evaluating the same overloaded
        window. A batch read failing transiently degrades to "no claims seen"
        for this call, the same as a single `_lookup_claim` miss: it is an
        extra chance to see a winner, not the only one, and the occurrences
        this evaluation still enumerates are protected by the reactive
        duplicate path regardless.
        """
        truncated = _truncated(decision)
        if not truncated:
            return {}
        probe = truncated[-_MAX_TRUNCATED_CLAIM_PROBES:]
        try:
            found = await self._runs.get_runs_for_occurrences(
                schedule.schedule_id, [moment.isoformat() for moment in probe]
            )
        except Exception as exc:
            logger.warning(
                "schedule %s could not batch-probe %d truncated claim(s): %s",
                schedule.schedule_id,
                len(probe),
                exc,
            )
            return {}
        by_moment = {moment.isoformat(): moment for moment in probe}
        return {
            by_moment[scheduled_for]: run
            for scheduled_for, run in found.items()
            if scheduled_for in by_moment
        }

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

        An idle schedule pays nothing: `since` is at or before the cursor, so
        the loop below never starts. A crashed-and-lagging one is bounded by
        `_MAX_RECOVERY_PROBES`, not by how far it has to walk — see
        `_existing_claims` for why the walk no longer stops at the first empty
        probe.
        """
        moment = schedule.next_fire_after(schedule.last_fired_at or schedule.created_at)
        probes = 0
        while moment <= since and probes < _MAX_RECOVERY_PROBES:
            yield moment
            probes += 1
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
        * **The quota is claimed first, atomically.** `reserve_fire` holds
          the run under the store's own lock, *before* the Run exists, so two
          callers racing on the last run cannot both pass an exhaustion
          check read from the same snapshot; the loser is refused. The hold
          is a durable `PendingFire` marker naming the token, not a spend:
          `runs_so_far`, `enabled`, and the cursors are exactly as they
          were, and the count, the disable, and `last_run_id` land only in
          `settle_pending_fire` — the same write that removes the marker and
          links the Run. So a process that dies between the hold and the Run
          leaves no firing behind at all (#1120: "failure before canonical
          Run creation does not advance/claim a firing that never existed"),
          and the orphaned marker is settled by the next admission
          (`_reconcile_pending_fires`): a Run for its token confirms the
          spend, none releases the slot. A marker inside its lease window is
          left alone — its holder may still be mid-fire — which is what
          keeps the last-run race closed (#1119). A duplicate claim — the
          reconciliation case above — releases the marker unspent: the
          winner already counted it.
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
        it releases the marker, so the schedule reads as it did before.

        One refusal a retry never meets: the claim is asked **first**. A
        caller-stable `fire_id` whose Run already exists is that logical
        firing's winner answering, so it reconciles even when the winner's
        fire has since spent the last `max_runs` unit (or the template has
        disappeared) — telling a retried caller "could not be fired" about a
        fire whose Run demonstrably exists would be the one answer worse
        than a refusal. A minted token skips the probe: it is fresh by
        construction, so the read could only ever cost.
        """
        # Settle whatever a previous holder left behind before doing anything
        # else. A manual fire is the one admission a caller retries by hand,
        # so this is where a crashed fire's marker must not outlive its
        # usefulness: released, a retry of the same token can fire again;
        # confirmed, the retry reconciles through the claim probe below. One
        # store read on a path a human clicked — never the tick's hot path.
        schedule = await self._reconcile_pending_fires(schedule.schedule_id) or schedule
        token = fire_id if fire_id else uuid.uuid4().hex
        reconciled = await self._already_admitted(schedule, now, fire_id)
        if reconciled is not None:
            return reconciled
        if schedule.exhausted:
            raise ManualFireRefused(
                f"schedule {schedule.schedule_id} has used all {schedule.max_runs} of its runs"
            )
        template = await self._resolve_manual_template(schedule)
        try:
            reserved = await self._schedules.reserve_fire(schedule.schedule_id, fire_id=token)
        except ScheduleExhausted as exc:
            raise ManualFireRefused(str(exc)) from exc
        if reserved is None:
            raise ManualFireRefused(f"schedule {schedule.schedule_id} no longer exists")

        fire = FireDecision(scheduled_for=now, catchup=False)
        try:
            run_id = await self._admit_one(reserved, template, fire, fire_id=token)
        except DuplicateOccurrence:
            return await self._duplicate_manual_receipt(schedule, now, token)
        except BaseException:
            await self._schedules.settle_pending_fire(schedule.schedule_id, token, run_id=None)
            raise
        return await self._manual_fire_receipt(reserved, token, run_id)

    async def _already_admitted(
        self,
        schedule: Schedule,
        now: datetime,
        fire_id: str | None,
    ) -> ScheduleAdmission | None:
        """The receipt of a caller-stable fire whose Run already exists (#1120).

        Only a caller-supplied `fire_id` can collide: a minted token is fresh
        by construction, so probing it could only ever cost a read. A retried
        or concurrent double submit of the same logical request therefore
        reconciles to the winner's Run instead of minting a fresh identity
        per request. `None` means nothing was admitted yet and the fire
        should proceed.
        """
        if fire_id is None:
            return None
        winner = await self._runs.find_occurrence_run(
            {
                SCHEDULE_ID_KEY: schedule.schedule_id,
                SCHEDULE_FIRE_ID_KEY: fire_id,
            }
        )
        if winner is None:
            return None
        logger.info(
            "schedule %s manual fire %s was already admitted as %s",
            schedule.schedule_id,
            fire_id,
            winner.run_id,
        )
        return ScheduleAdmission(
            already_fired=(now,),
            reconciled_run_id=winner.run_id,
        )

    async def _resolve_manual_template(self, schedule: Schedule) -> GraphTemplate:
        """Resolve the manual fire's target from the canonical template store.

        The store's own error propagates — an unresolvable target is a
        caller-visible misconfiguration, raised after a warning rather than
        folded into a scheduler failure.
        """
        try:
            return await require_template(
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

    async def _duplicate_manual_receipt(
        self,
        schedule: Schedule,
        now: datetime,
        token: str,
    ) -> ScheduleAdmission:
        """Hand the loser of a claimed fire the winner's receipt (#1120).

        The firing happened — some other admitter claimed this exact logical
        request — so there is nothing to create; the marker is released
        unspent (the winner already counted it) and the reconciled Run is the
        documented reconciliation for a retried or concurrent double submit
        (#1120).
        """
        logger.info(
            "schedule %s manual fire %s was already admitted elsewhere",
            schedule.schedule_id,
            token,
        )
        await self._schedules.settle_pending_fire(schedule.schedule_id, token, run_id=None)
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

    async def _manual_fire_receipt(
        self,
        reserved: Schedule,
        token: str,
        run_id: str,
    ) -> ScheduleAdmission:
        """Close the fire's marker on its Run and report what the row now says."""
        settled = await self._schedules.settle_pending_fire(
            reserved.schedule_id, token, run_id=run_id
        )
        recorded = settled if settled is not None else reserved
        return ScheduleAdmission(
            run_ids=(run_id,),
            next_due_at=recorded.next_due_at,
            # What this fire's own settle write disabled: enabled before it,
            # disabled after it. A schedule someone else disabled mid-window
            # is reported as it is, not as this fire's doing.
            disabled=reserved.enabled and not recorded.enabled,
        )

    async def _reconcile_pending_fires(self, schedule_id: str) -> Schedule | None:
        """Settle markers whose holder is provably gone (#1120).

        A pending marker names its fire's token, so the Run store can answer
        the only question that matters: did that firing happen? A Run for the
        token means the holder died *after* creating it — the spend is
        earned, and confirming it here (count, `last_run_id`, the disable on
        exhaustion) is the same write `settle_pending_fire` performs for a
        live fire, so after-admission crashes recover exactly like live
        ones. No Run means the holder died *before* creating anything — the
        slot returns and the schedule reads as though the fire never
        happened, which it did not.

        Freshness decides who gets settled: inside `_PENDING_FIRE_LEASE` a
        marker may belong to a live fire still inside its reserve→settle
        window, and touching it would reopen the last-run race the marker
        exists to close (#1119). Past the lease no healthy holder can still
        be mid-fire, so the marker is a crash leftover. Probes and settles
        degrade rather than raise: recovery is an extra chance to clean up,
        never a reason to fail an admission that would otherwise succeed —
        a marker that cannot be settled now is settled by the next one.

        Returns the row as stored after reconciliation (None when the
        schedule is gone), so the caller evaluates against the truth rather
        than the snapshot it arrived with.
        """
        row = await self._schedules.get(schedule_id)
        if row is None or not row.pending_fires:
            return row
        wall = datetime.now(UTC)
        for marker in row.pending_fires:
            if wall - marker.stamped_at <= _PENDING_FIRE_LEASE:
                continue
            try:
                winner = await self._runs.find_occurrence_run(
                    {
                        SCHEDULE_ID_KEY: schedule_id,
                        SCHEDULE_FIRE_ID_KEY: marker.fire_id,
                    }
                )
            except Exception as exc:
                logger.warning(
                    "schedule %s could not probe pending fire %s for recovery: %s",
                    schedule_id,
                    marker.fire_id,
                    exc,
                )
                continue
            try:
                if winner is not None:
                    await self._schedules.settle_pending_fire(
                        schedule_id, marker.fire_id, run_id=winner.run_id
                    )
                    logger.info(
                        "schedule %s pending fire %s confirmed by its recovered Run %s",
                        schedule_id,
                        marker.fire_id,
                        winner.run_id,
                    )
                else:
                    await self._schedules.settle_pending_fire(
                        schedule_id, marker.fire_id, run_id=None
                    )
                    logger.info(
                        "schedule %s pending fire %s released; its Run was never created",
                        schedule_id,
                        marker.fire_id,
                    )
            except Exception as exc:
                logger.warning(
                    "schedule %s could not settle pending fire %s: %s",
                    schedule_id,
                    marker.fire_id,
                    exc,
                )
        return await self._schedules.get(schedule_id)

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
            recorded = await self._record_fire(
                schedule.schedule_id,
                fired_at=consumed[-1],
                # The Run behind the newest occurrence that *has* one — a skip
                # produced nothing and does not compete. `_pointer` answers
                # None when only drops were consumed, and `_advance` keeps the
                # existing id then, which is what makes "the last Run this
                # schedule produced" survive an occurrence that produced none.
                run_id=_pointer({moment: claims[moment].run_id for moment in claimed}, claimed),
                next_due_at=next_due_at,
                # Nothing was admitted on this path by definition (`decision`
                # had no fires) — `recovered` is the only source of new
                # counted firings, and the store dedupes it itself.
                fires=0,
                recovered=recovered,
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

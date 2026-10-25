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

The claim is an *instant*, not a wall clock (#850). Every store compares
`scheduled_for` as text — provenance is JSON, and the claim indexes are
expressions over that text — so the text is one representation of the
identity. `datetime.isoformat()` renders in the datetime's own offset, and
the cron walker renders moments in the schedule's timezone, so editing a
schedule's timezone used to re-render an already-claimed instant as different
text: the lookup missed, the same firing was admitted twice, and the window
the uniqueness contract exists to close reopened. Nominal claims are now
written and probed as the instant in UTC (`canonical_occurrence_instant`),
so a timezone edit changes the wall clock and never the claim. Rows written
before this identity keep their wall-clock text: a crash-window occurrence
straddling the upgrade can re-fire once, the same narrow, loud-documented
window migrations 015/042 accepted rather than backfill-parse every Run's
provenance (PostgreSQL refuses the non-IMMUTABLE cast in an index).

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

**A manual fire is the same authority, one occurrence wide (#1119).**
The `manual=True` variant of `admit_due` exists because a product "run this
schedule now" request is not an occurrence the cron enumerated — `evaluate()`
has nothing to say about it — but everything *after* that decision is the
recurring path's: the durable template resolution, `_admit_one`'s Run with its
provenance, the occurrence claim, and `record_fire`'s advance-and-disable. A manual fire counts against
`max_runs` and names the schedule in Run provenance exactly as an enumerated
one does, so the product cannot grow a second set of firing semantics by
asking for a fire by hand.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from maistro.graph.templates import require_template
from maistro.observability.correlation import (
    bind_execution_context,
    current_execution_context,
    detached_execution_context,
)
from maistro.runs.model import RunStatus
from maistro.runs.sources import (
    ADMISSION_SOURCE,
    SCHEDULE_CATCHUP_KEY,
    SCHEDULE_FIRE_ID_KEY,
    SCHEDULE_ID_KEY,
    SCHEDULE_INPUTS_KEY,
    SCHEDULE_REQUESTED_BY_KEY,
    SCHEDULE_SOURCE,
    SCHEDULE_TRIGGER_KEY,
    SCHEDULE_TRIGGER_MANUAL,
    SCHEDULE_TRIGGER_RECURRING,
    SCHEDULED_FOR_KEY,
    canonical_occurrence_instant,
)
from maistro.runs.store import DuplicateOccurrence, RunIntegrityError
from maistro.scheduling.engine import FireDecision, SkipReason, evaluate
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
    """Whether the evaluation left work that still has to happen.

    Two kinds of owing, and both keep the due cursor where it is so the next
    tick comes back (#1199):

    - an occurrence that still has to run: BUFFERED says the cursor does not
      advance because "run one queued occurrence afterwards" is what
      BUFFER_ONE means, and TRUNCATED says a caller advancing on it "would
      otherwise lose the occurrence with no record of it";
    - a range that was never examined (#1200): an incomplete catch-up walk —
      budget or step bound reached — considered neither the occurrences in the
      unexamined range nor their absence. Advancing the due cursor past it
      would hide the schedule from `due()` until long after that range should
      have been looked at, so an incomplete walk owes a re-examination.

    Every other reason is a decision not to run that occurrence at all, and
    the cursor consumes it.
    """
    return decision.enumeration_incomplete or any(
        skip.reason in _UNCONSUMED_SKIPS for skip in decision.skipped
    )


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

    reconciled_run_id: str | None = None  # noqa: V107
    """The Run that already held this admission's own duplicate claim (#1120).

    Set for a manual fire whose `(schedule_id, fire_id)` occurrence was
    claimed by a concurrent or retried caller of the same logical request:
    the documented reconciliation is the first caller's receipt, not a
    refusal, so the loser resolves and returns the winner's Run instead of
    creating a second one. Unset for recurring admissions, whose winners are
    already linked through `last_run_id`.

    The field is read by Hive's scheduler
    (hive-conductor/backend/services/scheduler.py), which lies outside the
    vulture CI scan scope (packages/*/src), and a brand-new per-identity
    ledger bank cannot be self-authorized against the trusted base — so the
    declaration carries vulture's own per-finding suppression instead.
    """

    failures: tuple[Exception, ...] = field(default=())
    """Occurrences that could not be admitted, with why.

    Returned rather than raised, because one unresolvable template must not
    discard the sibling occurrences that resolved fine — and because the cursor
    still has to advance for the ones that did.
    """

    enumeration_incomplete: bool = False
    """This evaluation's catch-up walk stopped before reaching `now` (#1200).

    The range between where it stopped and `now` was never considered — not
    fired, not skipped, simply not looked at. The due cursor was left alone so
    the next tick re-examines it. Reported so a host can say truthfully that a
    tick ended with backlog work owed, instead of a clean "nothing due" that a
    budget cut short.
    """

    enumeration_stopped_at: datetime | None = None
    """Where an incomplete walk stopped: the exclusive end of what it examined.
    Everything from here to `now` is the backlog the next tick re-examines."""

    window_clamped: bool = False
    """The host's window bound, not the schedule's own, sized this evaluation's
    catch-up window (#1200). Operator-visible for the same reason: the schedule
    asked to consider more than the host allows."""


class ScheduleRunAdmitter:
    """Evaluate a schedule, admit its due occurrences, then advance its cursor."""

    def __init__(
        self,
        run_store: RunStore,
        template_store: GraphTemplateStore,
        schedule_store: ScheduleStore,
        enumeration_limits: EnumerationLimits | None = None,
    ) -> None:
        self._runs = run_store
        self._templates = template_store
        self._schedules = schedule_store
        # None keeps the substrate's safe defaults (#1200); a host with a
        # different latency/backlog trade-off passes its own bounds, and every
        # evaluate() this admitter drives uses exactly these.
        self._limits = enumeration_limits or DEFAULT_ENUMERATION_LIMITS

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
    ) -> ScheduleAdmission:
        """Admit due occurrences, or one explicit manual occurrence.

        `active_run` is whether a Run this schedule started is still in flight.
        The caller answers it from Run state, which is the only place it lives —
        the same contract `evaluate()` states. When `manual` is true, the
        caller's `now` is the one occurrence to admit and cron overlap policy is
        deliberately bypassed; the same template, Run, occurrence claim, and
        cursor authority still handles the request.
        """
        if manual:
            return await self._admit_manual(schedule, now=now)

        decision = evaluate(schedule, now=now, active_run=active_run)
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
                enumeration_incomplete=decision.enumeration_incomplete,
                enumeration_stopped_at=decision.enumeration_stopped_at,
                window_clamped=decision.window_clamped,
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
        consumed: list[FireDecision] = []
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
                enumeration_incomplete=decision.enumeration_incomplete,
                enumeration_stopped_at=decision.enumeration_stopped_at,
                window_clamped=decision.window_clamped,
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
            enumeration_incomplete=decision.enumeration_incomplete,
            enumeration_stopped_at=decision.enumeration_stopped_at,
            window_clamped=decision.window_clamped,
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
                consumed_run_ids.append(run_id)
                admitted.append(fire)
                consumed.append(fire)
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
        for moment in self._claims_before(
            schedule, enumeration_start(schedule, now=now, limits=self._limits)
        ):
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
        # The canonical instant, not the zone-local rendering: the claims on
        # disk were written by whatever timezone the schedule had when its
        # ticker fired (#850).
        probe_keys = [canonical_occurrence_instant(moment) for moment in probe]
        try:
            found = await self._runs.get_runs_for_occurrences(schedule.schedule_id, probe_keys)
        except Exception as exc:
            logger.warning(
                "schedule %s could not batch-probe %d truncated claim(s): %s",
                schedule.schedule_id,
                len(probe),
                exc,
            )
            return {}
        by_moment = dict(zip(probe_keys, probe, strict=True))
        return {
            by_moment[scheduled_for]: run
            for scheduled_for, run in found.items()
            if scheduled_for in by_moment
        }
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
    ) -> ScheduleAdmission:
        """Admit the one occurrence the caller asked for *now*, off the cron.

        The returned `ScheduleAdmission` holds exactly one entry: `run_ids` of
        length one on success, or `already_fired` naming the moment when the
        occurrence-claim found a Run already standing for it (#220).

        Three things differ from `admit_due`, each because a manual fire is
        not a cron occurrence:

        * **The quota is claimed first, atomically.** `reserve_fire` counts
          the run and disables on exhaustion under the store's own lock,
          *before* the Run exists. Two callers racing on the last run cannot
          both pass an exhaustion check read from the same snapshot; the
          loser is refused. The order also fixes what a crash leaves behind:
          a process that dies between the reservation and the Run loses one
          slot (visible: `runs_so_far` moved, `last_run_id` did not), never
          the reverse, where a Run exists that no count admits to and the
          next request duplicates it.
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

        try:
            reserved = await self._schedules.reserve_fire(schedule.schedule_id)
        except ScheduleExhausted as exc:
            raise ManualFireRefused(str(exc)) from exc
        if reserved is None:
            raise ManualFireRefused(f"schedule {schedule.schedule_id} no longer exists")
        current, reservation = reserved

        fire = FireDecision(scheduled_for=now, catchup=False)
        try:
            run_id = await self._admit_one(current, template, fire)
        except DuplicateOccurrence:
            logger.info(
                "schedule %s manual occurrence %s was already admitted elsewhere",
                schedule.schedule_id,
                now.isoformat(),
            )
            # The firing happened — some other admitter claimed this exact
            # moment — so there is nothing to create; the slot goes back.
            await self._schedules.settle_fire(schedule.schedule_id, reservation, run_id=None)
            return ScheduleAdmission(already_fired=(now,))
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
        consumable = [skip for skip in decision.skipped if skip.reason not in _UNCONSUMED_SKIPS]
        # The due cursor moves only when nothing is owed (#1199). `due()`
        # selects on `next_due_at`, so advancing it past a buffered occurrence
        # would hide the schedule from the tick until the occurrence *after*
        # the one it still has to run.
        next_due_at = schedule.next_due_at if _owes(decision) else decision.next_due_at
        if consumable:
            newest = max(skip.scheduled_for for skip in consumable)
            await self._schedules.record_fire(
                schedule.schedule_id,
                fired_at=None,
                run_id=None,
                next_due_at=next_due_at,
                fires=0,
            )
        elif next_due_at is not None and next_due_at != schedule.next_due_at:
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
            enumeration_incomplete=decision.enumeration_incomplete,
            enumeration_stopped_at=decision.enumeration_stopped_at,
            window_clamped=decision.window_clamped,
        )

    async def _admit_one(
        self,
        schedule: Schedule,
        template: GraphTemplate,
        fire: FireDecision,
        *,
        fire_id: str | None = None,
        requested_by: str | None = None,
    ) -> str:
        graph = template.instantiate(project_id=schedule.project_id, name=schedule.name or None)
        provenance: dict[str, Any] = {
            ADMISSION_SOURCE: SCHEDULE_SOURCE,
            SCHEDULE_ID_KEY: schedule.schedule_id,
            # The instant in UTC, not the cron rendering's own offset (#850):
            # the claim every store compares is this text, and a schedule whose
            # timezone changes would otherwise re-render the same instant as a
            # different identity and fire it twice.
            SCHEDULED_FOR_KEY: canonical_occurrence_instant(fire.scheduled_for),
            SCHEDULE_CATCHUP_KEY: fire.catchup,
            SCHEDULER_SERVICE_ID_KEY: SCHEDULER_SERVICE_ID,
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
            if requested_by:
                # The fire spends the schedule actor's authority, but a
                # specific authenticated principal asked for it (#1201).
                # Named only when known: a tick fire has no requester, and
                # the key's absence must keep meaning "no requester", not
                # "nobody looked".
                provenance[SCHEDULE_REQUESTED_BY_KEY] = requested_by
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

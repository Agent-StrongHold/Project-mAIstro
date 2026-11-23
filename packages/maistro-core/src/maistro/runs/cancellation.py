"""What a cancellation actually proved (#1242).

`RunStatus.CANCELLED` is the canonical *logical fence*: once it is durable, no
late provider result may publish Run or Attempt success
(`AttemptExecutionService._settle_provider_success`). That fence is authority
and it stays authority.

What the fence is not is evidence that physical work stopped. The signal path
to a live owner is `AttemptExecutionService._active_services`, a process-local
index. When worker A runs the provider and worker B cancels, B writes the fence
and cannot reach A: the Attempt row is still `RUNNING` and only lease expiry +
reclaim (#232, ADR-082526-b36a) can settle it. Reporting that as "cancelled"
with no qualification is the false stop this module exists to remove.

So a cancellation answer carries two facts separately:

* the fence outcome — `run_status`, canonical, always reported; and
* the physical disposition — `CancellationDisposition`, what this process can
  *prove* about the work, which is `STOP_CONFIRMED` only when every physical
  try it observed is durably terminal.

This is a receipt over canonical state, not a second lifecycle: it never
transitions a Run, NodeRun or Attempt, and its vocabulary names evidence
rather than work states (see `CancellationDisposition`).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from maistro.runs.model import (
    TERMINAL_ATTEMPT_STATUSES,
    Attempt,
    AttemptStatus,
    CancellationCause,
    ExecutionLease,
    RunStatus,
)

#: Terminal-but-not-cancelled: the completion race had a winner that was not
#: the cancellation, so the receipt reports that winner instead of a stop.
_SETTLED_OTHERWISE = TERMINAL_ATTEMPT_STATUSES - {AttemptStatus.CANCELLED}


class CancellationDisposition(StrEnum):
    """The physical evidence a canceller holds — never a work state.

    Deliberately disjoint from `RunStatus`/`AttemptStatus`: this says what was
    *proven*, not what anything *is*. No member name or value is in
    `scripts/check-execution-lifecycles.py`'s work-state vocabulary, so this
    cannot become a second lifecycle by accident — the same property
    ADR-082426-f170 records for `CancellationCause`'s two members.
    """

    #: Every physical try observed is durably terminal (or none ever existed),
    #: so nothing is left running that this receipt fails to account for.
    STOP_CONFIRMED = "stop_confirmed"
    #: The fence is durable and the request went as far as this process could
    #: send it, but a physical try is still non-terminal under a lease that
    #: expires. Reclaim owns resolving it; this process must not claim it
    #: stopped.
    STOP_PENDING = "stop_pending"
    #: A non-terminal physical try that nothing observable will resolve: no
    #: local owner answered the signal and no lease expiry will ever reclaim
    #: it, or the owner answered and the durable row disagreed. Needs a
    #: diagnosis and reconciliation, not a hopeful receipt.
    UNCERTAIN = "uncertain"
    #: The race against completion had a winner that was not the cancellation.
    #: The receipt reports the actual winner instead of a false stop.
    COMPLETION_WON = "completion_won"


#: Worst-evidence-first: one unresolved try decides the whole receipt, because
#: a caller acts on the aggregate and must never be told "confirmed" while any
#: physical work is unaccounted for.
_PRECEDENCE: tuple[CancellationDisposition, ...] = (
    CancellationDisposition.UNCERTAIN,
    CancellationDisposition.STOP_PENDING,
    CancellationDisposition.COMPLETION_WON,
    CancellationDisposition.STOP_CONFIRMED,
)


class AttemptCancellation(BaseModel):
    """One physical try's cancellation evidence, with its diagnosis."""

    model_config = ConfigDict(extra="forbid", frozen=True, ser_json_inf_nan="constants")

    attempt_id: str
    node_run_id: str
    status: AttemptStatus
    disposition: CancellationDisposition
    #: The lease holder named by the durable row — the worker that would have
    #: to stop this try. ``None`` when the row carries no lease.
    owner: str | None = None
    runtime_id: str | None = None
    diagnosis: str = Field(min_length=1)


class CancellationReceipt(BaseModel):
    """A cancellation answer: the canonical fence plus provable physical stop.

    `fenced` and `stop_confirmed` are different questions and the whole point
    of this type is that they are asked separately. A receipt with
    ``fenced=True, stop_confirmed=False`` is the honest cross-replica answer;
    the pre-#1242 public responses could only say the first and were read as
    both.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, ser_json_inf_nan="constants")

    run_id: str
    #: The canonical Run status after the cancellation attempt. `CANCELLED`
    #: when this canceller won the fence; the winner's own status when the
    #: completion race beat it.
    run_status: RunStatus
    disposition: CancellationDisposition
    #: Why the work was stopped. Always `REQUESTED` for a caller-driven
    #: cancellation; `RECOVERED` cancellations are process-loss bookkeeping and
    #: do not produce receipts (ADR-082426-f170).
    cause: CancellationCause = CancellationCause.REQUESTED
    attempts: tuple[AttemptCancellation, ...] = ()
    diagnosis: str = Field(min_length=1)

    @property
    def fenced(self) -> bool:
        """True when the canonical logical fence is durable on this Run."""
        return self.run_status is RunStatus.CANCELLED

    @property
    def stop_confirmed(self) -> bool:
        """True only when no observed physical try is left unaccounted for."""
        return self.disposition is CancellationDisposition.STOP_CONFIRMED


def _lease_diagnosis(lease: ExecutionLease | None) -> tuple[CancellationDisposition, str]:
    """Split an unreachable live try into "reclaim will settle it" vs "won't"."""
    if lease is None:
        return CancellationDisposition.UNCERTAIN, (
            "no local Runtime owner answered and the Attempt carries no execution lease, "
            "so no reclaim can ever settle it"
        )
    if lease.expires_at is None:
        return CancellationDisposition.UNCERTAIN, (
            f"no local Runtime owner answered and the lease held by {lease.holder!r} never "
            "expires, so no reclaim can ever settle it"
        )
    return CancellationDisposition.STOP_PENDING, (
        f"still non-terminal under lease holder {lease.holder!r} (expires {lease.expires_at.isoformat()}); "
        "cancellation is durable but the remote owner was not reached from this process, "
        "so lease expiry and reclaim own the physical stop"
    )


def is_reclaim_settled(attempt: Attempt) -> bool:
    """True when the row was terminalized by reclaim, not by a proven stop.

    `reclaim_expired_attempts` writes CANCELLED+RECOVERED after lease expiry
    alone: it never contacts or joins the worker, and a heartbeat that lost
    its renewals does not cancel the provider coroutine. Such a row is
    durable bookkeeping about a lapsed lease — it is not evidence that the
    physical execution stopped, so a receipt must never read it as one.
    """
    return (
        attempt.status is AttemptStatus.CANCELLED
        and attempt.cancellation_cause is CancellationCause.RECOVERED
    )


def classify_attempt(
    attempt: Attempt,
    *,
    local_signal: bool | None = None,
) -> AttemptCancellation:
    """Report one physical try's cancellation evidence from durable state.

    ``local_signal`` is this process's own answer for the try: ``True`` when a
    local owner joined the Runtime task or terminalized it pre-launch, ``False``
    when a local owner found it already settled, ``None`` when this process
    owns no Runtime handle for it at all. It is evidence about *this* process
    only, which is exactly why the durable row is re-read and decides.
    """
    lease = attempt.execution_lease
    base = {
        "attempt_id": attempt.attempt_id,
        "node_run_id": attempt.node_run_id,
        "status": attempt.status,
        "owner": lease.holder if lease is not None else None,
        "runtime_id": attempt.runtime_id or None,
    }
    if attempt.status is AttemptStatus.CANCELLED:
        if is_reclaim_settled(attempt):
            if local_signal:
                return AttemptCancellation(
                    **base,
                    disposition=CancellationDisposition.STOP_CONFIRMED,
                    diagnosis=(
                        "the row is a RECOVERED reclaim record, but a local Runtime owner "
                        "joined the stop — independent physical evidence the reclaim alone "
                        "cannot provide"
                    ),
                )
            return AttemptCancellation(
                **base,
                disposition=CancellationDisposition.UNCERTAIN,
                diagnosis=(
                    "durably CANCELLED only by lease-expiry reclaim (RECOVERED): the row was "
                    "terminalized without contacting or joining the worker, and a lapsed "
                    "lease does not prove the provider stopped executing"
                ),
            )
        return AttemptCancellation(
            **base,
            disposition=CancellationDisposition.STOP_CONFIRMED,
            diagnosis="durably terminal CANCELLED; the physical try is stopped",
        )
    if attempt.status in _SETTLED_OTHERWISE:
        return AttemptCancellation(
            **base,
            disposition=CancellationDisposition.COMPLETION_WON,
            diagnosis=(
                f"the race ended {attempt.status.value} before cancellation reached it; "
                "the actual winner is reported, not a stop"
            ),
        )
    if local_signal:
        return AttemptCancellation(
            **base,
            disposition=CancellationDisposition.UNCERTAIN,
            diagnosis=(
                f"the local Runtime owner reported this try stopped, yet the durable row is "
                f"still {attempt.status.value}; the two disagree and neither is proof"
            ),
        )
    disposition, diagnosis = _lease_diagnosis(lease)
    return AttemptCancellation(**base, disposition=disposition, diagnosis=diagnosis)


def aggregate_disposition(
    attempts: tuple[AttemptCancellation, ...],
) -> CancellationDisposition:
    """The receipt's disposition: the worst evidence among its physical tries.

    No tries at all is `STOP_CONFIRMED`: a Run cancelled while still queued
    owned no physical work, and the durable fence is what refuses a competing
    consumer claim (`ConsumerClaimLost`), so nothing can start later either.
    """
    for candidate in _PRECEDENCE:
        if any(row.disposition is candidate for row in attempts):
            return candidate
    return CancellationDisposition.STOP_CONFIRMED


__all__ = [
    "AttemptCancellation",
    "CancellationDisposition",
    "CancellationReceipt",
    "aggregate_disposition",
    "classify_attempt",
    "is_reclaim_settled",
]

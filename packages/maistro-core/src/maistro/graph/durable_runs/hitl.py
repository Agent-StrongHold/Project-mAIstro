"""Canonical policy and bounded expiry for durable HITL pauses."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.graph.nodes.base import PAUSE_AWAITING_REMOTE_DELEGATION
from maistro.runs.model import RunStatus

if TYPE_CHECKING:
    from .protocol import DurableRunStore
    from .types import DurableRunRecord


class HitlSettlementError(ValueError):
    """A durable human pause cannot accept the requested settlement."""


class HitlDeadlineElapsed(HitlSettlementError):
    """An answer arrived at or after the pause's durable deadline."""


class HitlDeadlinePending(HitlSettlementError):
    """A timeout was requested before the pause's durable deadline."""


def hitl_pause(record: DurableRunRecord, node_id: str) -> dict[str, object]:
    """Return the server-authored pause entry for one active HITL node."""
    pauses_raw = record.graph_state.metadata.get("pauses", {})
    pauses = pauses_raw if isinstance(pauses_raw, Mapping) else {}
    pause_raw = pauses.get(node_id)
    if not isinstance(pause_raw, Mapping) or pause_raw.get("kind") != "hitl":
        raise HitlSettlementError(
            f"run {record.run_id!r} has no durable HITL pause for node {node_id!r}"
        )
    return {str(key): value for key, value in pause_raw.items()}


def hitl_deadline(
    record: DurableRunRecord,
    node_id: str,
    *,
    require_pause: bool = True,
) -> datetime | None:
    """Read the absolute persisted deadline without deriving a new one.

    Pre-deadline answer compatibility includes records created before pause
    entries existed. They have no deadline and remain answerable. Terminal
    settlement passes ``require_pause=True`` and therefore still refuses to
    invent timeout or cancellation evidence for such a record.
    """
    try:
        pause = hitl_pause(record, node_id)
    except HitlSettlementError:
        if require_pause:
            raise
        return None
    raw = pause.get("resume_at")
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise HitlSettlementError(
            f"run {record.run_id!r} HITL deadline for node {node_id!r} is not an ISO timestamp"
        )
    try:
        deadline = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HitlSettlementError(
            f"run {record.run_id!r} HITL deadline for node {node_id!r} is invalid"
        ) from exc
    if deadline.tzinfo is None:
        raise HitlSettlementError(
            f"run {record.run_id!r} HITL deadline for node {node_id!r} has no timezone"
        )
    return deadline.astimezone(UTC)


def settlement_time(at: datetime | None = None) -> datetime:
    """Normalize a caller clock value for comparisons and persisted evidence."""
    moment = at if at is not None else datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("HITL settlement time must include a timezone")
    return moment.astimezone(UTC)


def _deadline_from_pause(
    pause: Mapping[str, object],
    *,
    node_id: str,
    run_id: str,
) -> datetime | None:
    raw = pause.get("resume_at")
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise HitlSettlementError(
            f"run {run_id!r} HITL deadline for node {node_id!r} is not an ISO timestamp"
        )
    try:
        deadline = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HitlSettlementError(
            f"run {run_id!r} HITL deadline for node {node_id!r} is invalid"
        ) from exc
    if deadline.tzinfo is None:
        raise HitlSettlementError(
            f"run {run_id!r} HITL deadline for node {node_id!r} has no timezone"
        )
    return deadline.astimezone(UTC)


def earliest_hitl_deadline_from_state(
    active_node_ids: Collection[str],
    metadata: Mapping[str, object],
    *,
    run_id: str,
) -> datetime | None:
    """Project the earliest valid active HITL deadline from graph state."""
    pauses_raw = metadata.get("pauses", {})
    pauses = pauses_raw if isinstance(pauses_raw, Mapping) else {}
    deadlines: list[datetime] = []
    for node_id in active_node_ids:
        pause_raw = pauses.get(node_id)
        if not isinstance(pause_raw, Mapping) or pause_raw.get("kind") != "hitl":
            continue
        try:
            deadline = _deadline_from_pause(pause_raw, node_id=node_id, run_id=run_id)
        except HitlSettlementError:
            continue
        if deadline is not None:
            deadlines.append(deadline)
    return min(deadlines) if deadlines else None


def earliest_hitl_deadline(record: DurableRunRecord) -> datetime | None:
    """Return the earliest valid deadline for the active HITL frontier.

    This is a lookup projection only. The durable pause entry remains the
    authority and ``timeout_hitl`` revalidates it before settling the Run.
    Malformed or non-HITL frontier entries are deliberately not indexed; they
    cannot become a timeout through discovery alone.
    """
    return earliest_hitl_deadline_from_state(
        record.graph_state.active_node_ids,
        record.graph_state.metadata,
        run_id=record.run_id,
    )


def _expired_hitl_node_id(record: DurableRunRecord, moment: datetime) -> str | None:
    """The first active node whose durable HITL deadline has elapsed, if any."""
    for node_id in record.graph_state.active_node_ids:
        try:
            hitl_pause(record, node_id)
        except HitlSettlementError:
            continue
        deadline = hitl_deadline(record, node_id)
        if deadline is not None and deadline <= moment:
            return node_id
    return None


async def expire_remote_delegations(  # noqa: C901
    store: DurableRunStore,
    *,
    now: datetime | None = None,
    limit: int = 100,
    eligible: Callable[[Any], bool] | None = None,
) -> list[DurableRunRecord]:
    """Convert elapsed remote waits into one durable timed-out completion.

    The deadline is the dispatch node's persisted ``resume_at``. This tick is
    the timer waker for answer-gated machine waits; it never re-enters the
    dispatch node, so a missing peer response cannot create a second child.
    """
    if limit <= 0:
        return []
    moment = settlement_time(now)
    settled: list[DurableRunRecord] = []
    for record in await store.list_due(now=moment, limit=limit):
        if record.run.status is not RunStatus.WAITING:
            continue
        if eligible is not None and not eligible(record.run):
            continue
        graph_state = getattr(record, "graph_state", None)
        if graph_state is None:
            continue
        pauses = graph_state.metadata.get("pauses", {})
        if not isinstance(pauses, Mapping):
            continue
        for node_id in record.graph_state.active_node_ids:
            pause = pauses.get(node_id)
            metadata = pause.get("metadata") if isinstance(pause, Mapping) else None
            if not isinstance(metadata, Mapping):
                continue
            if metadata.get("paused_reason") != PAUSE_AWAITING_REMOTE_DELEGATION:
                continue
            deadline = pause.get("resume_at") if isinstance(pause, Mapping) else None
            if not isinstance(deadline, str):
                continue
            try:
                due = datetime.fromisoformat(deadline)
            except ValueError:
                continue
            if due.tzinfo is None or due.astimezone(UTC) > moment:
                continue
            try:
                settled.append(
                    await store.complete_remote_delegation(
                        record.run_id,
                        node_id,
                        task_id=str(metadata.get("task_id") or ""),
                        child_run_id=str(metadata.get("run_id") or ""),
                        status="timed_out",
                        error="remote delegation deadline elapsed",
                        at=moment,
                    )
                )
            except ValueError:
                # A completion or another expiry won after the bounded read.
                continue
            break
    return settled



async def expire_hitl_pauses(
    store: DurableRunStore,
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> list[DurableRunRecord]:
    """Settle at most ``limit`` paused Runs whose persisted deadline elapsed.

    This is an operator-scheduled tick, not a background task. It derives no
    deadline from process-local time or node configuration: only the absolute
    timestamp already present in the durable pause is authoritative.

    ``limit`` bounds *expired-HITL* PAUSED Runs settled by this call, not a
    fixed prefix of every PAUSED Run in the store (#1056). Candidates come from
    the deadline index, which contains only due rows, so an arbitrarily large
    run of non-HITL or not-yet-due PAUSED Runs ahead of an expired one cannot
    hide it behind a fixed-size query. The index is a projection, so each
    candidate is still revalidated below against the durable pause itself.
    """
    if limit <= 0:
        return []
    moment = settlement_time(now)
    # ``list_hitl_due`` is a deadline-indexed candidate query. Its limit is
    # settlement work, not a prefix of all PAUSED Runs, so old non-HITL and
    # future-deadline records cannot starve an elapsed human pause.
    #
    # #1275 originally drained this frontier with `fair_page_scan` over every
    # PAUSED Run. The index (#1056) subsumes that: it never reads a row that is
    # not due, so the keyset walk is not needed here. `fair_page_scan` still
    # carries the timed-resume path in `canonical_store.scan_due_page`, which
    # has no equivalent index.
    candidates = await store.list_hitl_due(now=moment, limit=limit)
    settled: list[DurableRunRecord] = []
    for record in candidates:
        expired_node_id = _expired_hitl_node_id(record, moment)
        if expired_node_id is None:
            continue
        try:
            settled.append(await store.timeout_hitl(record.run_id, expired_node_id, at=moment))
        except ValueError:
            # Another answer, cancellation, or expiry may have won after the
            # bounded scan. Its committed decision is the canonical outcome.
            continue
    return settled


__all__ = [
    "HitlDeadlineElapsed",
    "HitlDeadlinePending",
    "HitlSettlementError",
    "earliest_hitl_deadline",
    "expire_hitl_pauses",
    "expire_remote_delegations",
    "hitl_deadline",
    "hitl_pause",
    "settlement_time",
]

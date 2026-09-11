"""Canonical policy and bounded expiry for durable HITL pauses."""

from __future__ import annotations

from collections.abc import Callable, Mapping
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
    """
    if limit <= 0:
        return []
    moment = settlement_time(now)
    candidates = await store.list_by_status(RunStatus.PAUSED, limit=limit)
    settled: list[DurableRunRecord] = []
    for record in candidates:
        expired_node_id: str | None = None
        for node_id in record.graph_state.active_node_ids:
            try:
                hitl_pause(record, node_id)
            except HitlSettlementError:
                continue
            deadline = hitl_deadline(record, node_id)
            if deadline is not None and deadline <= moment:
                expired_node_id = node_id
                break
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
    "expire_hitl_pauses",
    "expire_remote_delegations",
    "hitl_deadline",
    "hitl_pause",
    "settlement_time",
]

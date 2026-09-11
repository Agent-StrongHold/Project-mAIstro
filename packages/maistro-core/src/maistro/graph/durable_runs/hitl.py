"""Canonical policy and bounded expiry for durable HITL pauses."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from maistro.runs.model import RunStatus

from .fair_scan import fair_page_scan

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


def _paused_cursor_key(record: DurableRunRecord) -> tuple[str, str]:
    """The ``(created_at_iso, run_id)`` keyset position of one PAUSED record."""
    return (record.run.created_at.isoformat(), record.run_id)


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
    fixed prefix of every PAUSED Run in the store (#1056). Candidates are
    discovered by paging the store's PAUSED listing with an advancing keyset
    cursor and testing each page for an elapsed deadline, so an arbitrarily
    large run of non-HITL or not-yet-due PAUSED Runs ahead of an expired one
    cannot hide it forever behind a fixed-size query.
    """
    if limit <= 0:
        return []
    moment = settlement_time(now)
    candidates = await fair_page_scan(
        fetch_page=lambda cursor, page_size: store.list_by_status(
            RunStatus.PAUSED, limit=page_size, after=cursor
        ),
        cursor_of=_paused_cursor_key,
        eligible=lambda record: _expired_hitl_node_id(record, moment) is not None,
        limit=limit,
    )
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
    "expire_hitl_pauses",
    "hitl_deadline",
    "hitl_pause",
    "settlement_time",
]

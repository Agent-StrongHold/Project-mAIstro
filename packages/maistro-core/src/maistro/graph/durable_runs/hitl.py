"""Canonical policy and bounded expiry for durable HITL pauses."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .protocol import DurableRunStore
    from .types import DurableRunRecord


class HitlSettlementError(ValueError):
    """A durable human pause cannot accept the requested settlement."""


class HitlDeadlineElapsed(HitlSettlementError):
    """An answer arrived at or after the pause's durable deadline."""


class HitlDeadlinePending(HitlSettlementError):
    """A timeout was requested before the pause's durable deadline."""


@dataclass(frozen=True)
class HitlAuthorization:
    """Effective-principal evidence for a scoped HITL settlement tick.

    The route/service authorization layer constructs this value after resolving
    canonical Workspace membership. The durable layer consumes the resulting
    scope but never treats a caller-supplied list of ids as authorization on
    its own. Delegated callers retain the evidence that established the
    effective principal in ``delegation_evidence``.
    """

    effective_principal: str
    workspace_ids: frozenset[str]
    delegation_evidence: str | None = None

    def __post_init__(self) -> None:
        if not self.effective_principal.strip():
            raise ValueError("HITL authorization requires an effective principal")
        if any(not workspace_id.strip() for workspace_id in self.workspace_ids):
            raise ValueError("HITL authorization cannot contain a blank Workspace id")

    @classmethod
    def for_principal(
        cls,
        effective_principal: str,
        workspace_ids: Collection[str],
    ) -> HitlAuthorization:
        """Bind canonical membership results to one effective principal."""
        return cls(effective_principal, frozenset(workspace_ids))

    @classmethod
    def for_delegated_service(
        cls,
        effective_principal: str,
        workspace_ids: Collection[str],
        *,
        delegation_evidence: str,
    ) -> HitlAuthorization:
        """Bind a service tick to explicit delegation evidence."""
        if not delegation_evidence.strip():
            raise ValueError("delegated HITL authorization requires evidence")
        return cls(effective_principal, frozenset(workspace_ids), delegation_evidence)


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


async def _due_candidates(
    store: DurableRunStore,
    *,
    moment: datetime,
    limit: int,
    authorization: HitlAuthorization | None,
) -> list[DurableRunRecord]:
    """Page the due index until an authorized settlement page is complete."""
    if authorization is None:
        return await store.list_hitl_due(now=moment, limit=limit)

    requested = limit
    candidates: list[DurableRunRecord] = []
    seen: set[str] = set()
    while True:
        page = await store.list_hitl_due(now=moment, limit=requested)
        for record in page:
            if record.run_id in seen:
                continue
            seen.add(record.run_id)
            if record.run.workspace_id in authorization.workspace_ids:
                candidates.append(record)
        if len(candidates) >= limit or len(page) < requested:
            return candidates[:limit]
        requested *= 2


async def expire_hitl_pauses(
    store: DurableRunStore,
    *,
    now: datetime | None = None,
    limit: int = 100,
    authorization: HitlAuthorization | None = None,
) -> list[DurableRunRecord]:
    """Settle at most ``limit`` paused Runs whose persisted deadline elapsed.

    This is an operator-scheduled tick, not a background task. It derives no
    deadline from process-local time or node configuration: only the absolute
    timestamp already present in the durable pause is authoritative. A
    product-supplied authorization binds the effective principal (or explicit
    delegation evidence) to canonical Workspace scope before any timeout
    mutation is requested. ``None`` is reserved for an internal operator tick.
    """
    if limit <= 0:
        return []
    if authorization is not None and not authorization.workspace_ids:
        return []
    moment = settlement_time(now)
    # ``list_hitl_due`` is a deadline-indexed candidate query. Its limit is
    # settlement work, not a prefix of all PAUSED Runs, so old non-HITL and
    # future-deadline records cannot starve an elapsed human pause.
    candidates = await _due_candidates(
        store,
        moment=moment,
        limit=limit,
        authorization=authorization,
    )
    settled: list[DurableRunRecord] = []
    for record in candidates[:limit]:
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
            settled.append(
                await store.timeout_hitl(
                    record.run_id,
                    expired_node_id,
                    at=moment,
                    workspace_id=record.run.workspace_id,
                )
            )
        except ValueError:
            # Another answer, cancellation, or expiry may have won after the
            # bounded scan. Its committed decision is the canonical outcome.
            continue
    return settled


__all__ = [
    "HitlAuthorization",
    "HitlDeadlineElapsed",
    "HitlDeadlinePending",
    "HitlSettlementError",
    "earliest_hitl_deadline",
    "expire_hitl_pauses",
    "hitl_deadline",
    "hitl_pause",
    "settlement_time",
]

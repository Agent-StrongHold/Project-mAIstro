"""Canonical policy and bounded expiry for durable HITL pauses."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .protocol import DurableRunStore
    from .types import DurableRunRecord


class HitlSettlementError(ValueError):
    """A durable human pause cannot accept the requested settlement."""


class HitlAuthorizationRequired(KeyError):
    """A HITL read or mutation must carry effective-principal evidence."""


class HitlDeadlineElapsed(HitlSettlementError):
    """An answer arrived at or after the pause's durable deadline."""


class HitlDeadlinePending(HitlSettlementError):
    """A timeout was requested before the pause's durable deadline."""


WorkspaceMembershipCheck = Callable[[str, str], Awaitable[bool]]
HitlEvidenceValidator = Callable[["HitlDelegationEvidence"], Awaitable[bool]]
HitlEvidenceConsumer = Callable[["HitlDelegationEvidence"], Awaitable[None]]


@dataclass(frozen=True)
class HitlAuthenticatedSession:
    """Verified session evidence supplied by an HTTP/authentication boundary.

    Core cannot authenticate a cookie or bearer token itself. The boundary must
    first resolve the session and then pass this typed effective-principal
    evidence; service callers instead use :class:`HitlDelegationEvidence`.
    """

    effective_principal: str
    membership_check: WorkspaceMembershipCheck

    def __post_init__(self) -> None:
        if not self.effective_principal.strip():
            raise ValueError("HITL session evidence requires an effective principal")


@dataclass(frozen=True)
class HitlDelegationEvidence:
    """Validated shape of a service delegation capability.

    The durable store must not treat an opaque string as authority. The issuer,
    subject, action, Workspace scope, and expiry are all bound in the evidence;
    the supplied validator and consumer connect this shape to the caller's
    live delegation registry and one-use/ledger semantics.
    """

    issuer: str
    subject: str
    workspace_ids: frozenset[str]
    actions: frozenset[str]
    expires_at: datetime
    token_id: str

    def __post_init__(self) -> None:
        if not self.issuer.strip() or not self.subject.strip():
            raise ValueError("HITL delegation evidence requires issuer and subject")
        if not self.workspace_ids or any(not value.strip() for value in self.workspace_ids):
            raise ValueError("HITL delegation evidence requires Workspace scope")
        if not self.actions or any(not value.strip() for value in self.actions):
            raise ValueError("HITL delegation evidence requires an action scope")
        if not self.token_id.strip():
            raise ValueError("HITL delegation evidence requires a token id")
        if self.expires_at.tzinfo is None:
            raise ValueError("HITL delegation evidence expiry must include a timezone")

    def is_current(self, *, effective_principal: str, workspace_id: str, action: str) -> bool:
        """Check claims that can be evaluated without consulting the issuer."""
        return (
            self.subject == effective_principal
            and workspace_id in self.workspace_ids
            and action in self.actions
            and datetime.now(UTC) < self.expires_at.astimezone(UTC)
        )


@dataclass(frozen=True)
class HitlAuthorization:
    """Effective-principal evidence for a scoped HITL operation.

    ``workspace_ids`` is a candidate page, not the authorization decision. The
    membership check is repeated by the canonical mutation immediately before
    it settles a record, so a revoked membership cannot use a stale page or a
    route pre-read to win a later answer, cancellation, or timeout.
    """

    effective_principal: str
    workspace_ids: frozenset[str]
    membership_check: WorkspaceMembershipCheck
    delegation_evidence: HitlDelegationEvidence | None = None
    evidence_validator: HitlEvidenceValidator | None = None
    evidence_consumer: HitlEvidenceConsumer | None = None
    action: str = "hitl.settle"
    _evidence_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not self.effective_principal.strip():
            raise ValueError("HITL authorization requires an effective principal")
        if any(not workspace_id.strip() for workspace_id in self.workspace_ids):
            raise ValueError("HITL authorization cannot contain a blank Workspace id")
        if not self.action.strip():
            raise ValueError("HITL authorization requires an action")
        if self.delegation_evidence is None:
            if self.evidence_validator is not None or self.evidence_consumer is not None:
                raise ValueError("HITL evidence callbacks require delegation evidence")
            return
        if not isinstance(self.delegation_evidence, HitlDelegationEvidence):
            raise TypeError("delegated HITL authorization requires typed evidence")
        if self.delegation_evidence.subject != self.effective_principal:
            raise ValueError("delegation evidence subject must match the effective principal")
        if not self.workspace_ids.issubset(self.delegation_evidence.workspace_ids):
            raise ValueError("delegation evidence does not cover the requested Workspaces")
        if self.evidence_validator is None or self.evidence_consumer is None:
            raise ValueError("delegated HITL authorization requires validation and consumption")

    @classmethod
    def for_verified_session(
        cls,
        session: HitlAuthenticatedSession,
        workspace_ids: Collection[str],
    ) -> HitlAuthorization:
        """Bind canonical Workspace scope to evidence from an auth boundary."""
        if not isinstance(session, HitlAuthenticatedSession):
            raise TypeError("HITL authorization requires typed session evidence")
        return cls(
            session.effective_principal,
            frozenset(workspace_ids),
            session.membership_check,
        )

    @classmethod
    def for_delegated_service(
        cls,
        effective_principal: str,
        workspace_ids: Collection[str],
        *,
        delegation_evidence: HitlDelegationEvidence,
        evidence_validator: HitlEvidenceValidator,
        evidence_consumer: HitlEvidenceConsumer,
        membership_check: WorkspaceMembershipCheck,
        action: str = "hitl.settle",
    ) -> HitlAuthorization:
        """Bind a service to typed, validated, and consumable delegation evidence."""
        return cls(
            effective_principal,
            frozenset(workspace_ids),
            membership_check,
            delegation_evidence,
            evidence_validator,
            evidence_consumer,
            action,
        )

    async def permits(self, workspace_id: str, *, consume_evidence: bool = False) -> bool:
        """Revalidate membership and delegated authority for one Workspace.

        Discovery only validates delegated evidence. Settlement passes
        ``consume_evidence=True`` so one-use authority is not spent while
        paging candidates that may later be rejected by canonical state.
        """
        if workspace_id not in self.workspace_ids:
            return False
        if not await self.membership_check(self.effective_principal, workspace_id):
            return False
        evidence = self.delegation_evidence
        if evidence is None:
            return True
        if not evidence.is_current(
            effective_principal=self.effective_principal,
            workspace_id=workspace_id,
            action=self.action,
        ):
            return False
        validator = self.evidence_validator
        consumer = self.evidence_consumer
        assert validator is not None and consumer is not None
        try:
            # Serialize validation and consumption so a one-use token cannot
            # authorize two concurrent settlements through this object.
            async with self._evidence_lock:
                if not await validator(evidence):
                    return False
                if consume_evidence:
                    await consumer(evidence)
        except Exception:
            # An unavailable or already-consumed delegation is a denial, never
            # a reason to let the canonical store proceed without evidence.
            return False
        return True


def require_hitl_authorization(
    authorization: HitlAuthorization | None,
) -> HitlAuthorization:
    """Reject unscoped callers before resolving a target Run.

    HITL settlement is an object-authorized operation, not a capability-only
    service call. Keeping this check at the shared boundary prevents a new
    durable backend from accidentally treating the argument as optional.
    """
    if authorization is None:
        raise HitlAuthorizationRequired("HITL authorization is required")
    return authorization


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
    authorization: HitlAuthorization,
) -> list[DurableRunRecord]:
    """Page the due index until an authorized settlement page is complete."""
    requested = limit
    candidates: list[DurableRunRecord] = []
    seen: set[str] = set()
    while True:
        page = await store.list_hitl_due(
            authorization=authorization,
            now=moment,
            limit=requested,
        )
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
    authorization: HitlAuthorization,
) -> list[DurableRunRecord]:
    """Settle at most ``limit`` paused Runs whose persisted deadline elapsed.

    This is an operator-scheduled tick, not a background task. It derives no
    deadline from process-local time or node configuration: only the absolute
    timestamp already present in the durable pause is authoritative. A
    product-supplied authorization binds the effective principal (or explicit
    delegation evidence) to canonical Workspace scope before any timeout
    mutation is requested. The authorization is mandatory even for an
    internal operator, which must provide explicit delegation evidence.
    """
    if limit <= 0:
        return []
    if not authorization.workspace_ids:
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
                    authorization=authorization,
                )
            )
        except (KeyError, ValueError):
            # Membership can be revoked after candidate discovery, or another
            # decision can win. Neither case permits a settlement here.
            continue
    return settled


__all__ = [
    "HitlAuthenticatedSession",
    "HitlAuthorization",
    "HitlAuthorizationRequired",
    "HitlDeadlineElapsed",
    "HitlDeadlinePending",
    "HitlDelegationEvidence",
    "HitlSettlementError",
    "earliest_hitl_deadline",
    "expire_hitl_pauses",
    "hitl_deadline",
    "hitl_pause",
    "settlement_time",
]

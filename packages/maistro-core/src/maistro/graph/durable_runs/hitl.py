"""Canonical policy and bounded expiry for durable HITL pauses."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Collection, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from maistro.runs.model import RunStatus

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


def _require_claim_text(value: str, message: str) -> None:
    """Reject blank effective-principal evidence text."""
    if not value.strip():
        raise ValueError(message)


def _require_claim_scope(values: Collection[str], message: str) -> None:
    """Reject an empty Workspace/action scope or any blank member of it."""
    if not values or any(not value.strip() for value in values):
        raise ValueError(message)


def _require_claim_page(values: Collection[str], message: str) -> None:
    """Reject blank members of a candidate page; an empty page stays valid."""
    if any(not value.strip() for value in values):
        raise ValueError(message)


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
        _require_claim_text(self.issuer, "HITL delegation evidence requires an issuer")
        _require_claim_text(self.subject, "HITL delegation evidence requires a subject")
        _require_claim_scope(
            self.workspace_ids, "HITL delegation evidence requires Workspace scope"
        )
        _require_claim_scope(self.actions, "HITL delegation evidence requires an action scope")
        _require_claim_text(self.token_id, "HITL delegation evidence requires a token id")
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

    Construction is the evidence boundary itself: every path through
    ``__init__`` runs the same validation, so a service cannot present an
    opaque string as delegation authority or scope it beyond the evidence's
    own Workspace/action claims. The verified session comes from the
    authentication boundary (the product auth adapter resolves the principal
    and supplies the live membership check); a delegated service must present
    typed :class:`HitlDelegationEvidence` bound to its effective principal.
    """

    effective_principal: str
    workspace_ids: frozenset[str]
    membership_check: WorkspaceMembershipCheck
    membership_mutation_lock: asyncio.Lock | None = field(default=None, repr=False, compare=False)
    delegation_evidence: HitlDelegationEvidence | None = None
    evidence_validator: HitlEvidenceValidator | None = None
    evidence_consumer: HitlEvidenceConsumer | None = None
    action: str = "hitl.settle"
    _evidence_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        _require_claim_text(
            self.effective_principal, "HITL authorization requires an effective principal"
        )
        _require_claim_page(
            self.workspace_ids, "HITL authorization cannot contain a blank Workspace id"
        )
        _require_claim_text(self.action, "HITL authorization requires an action")
        if self.delegation_evidence is None:
            if self.evidence_validator is not None or self.evidence_consumer is not None:
                raise ValueError("HITL evidence callbacks require delegation evidence")
            return
        self._bind_delegation_evidence(self.delegation_evidence)

    def _bind_delegation_evidence(self, evidence: HitlDelegationEvidence) -> None:
        """Fail closed unless typed evidence covers this exact operation."""
        if not isinstance(evidence, HitlDelegationEvidence):
            raise TypeError("delegated HITL authorization requires typed evidence")
        if evidence.subject != self.effective_principal:
            raise ValueError("delegation evidence subject must match the effective principal")
        if not self.workspace_ids.issubset(evidence.workspace_ids):
            raise ValueError("delegation evidence does not cover the requested Workspaces")
        if self.evidence_validator is None or self.evidence_consumer is None:
            raise ValueError("delegated HITL authorization requires validation and consumption")

    @asynccontextmanager
    async def hold_membership_mutation(self) -> AsyncIterator[None]:
        """Hold the auth authority's revocation lock through one settlement.

        Product adapters supply this lock and use it for membership removal, so
        membership cannot be revoked after its live check but before the
        durable write. Backends without a colocated authority retain the
        explicit live predicate but do not claim this stronger serialization.
        """
        if self.membership_mutation_lock is None:
            yield
            return
        async with self.membership_mutation_lock:
            yield

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


def has_active_hitl_pause(
    active_node_ids: Collection[str],
    metadata: Mapping[str, object],
) -> bool:
    """Whether any active frontier node carries a durable human pause entry.

    This is the pause-kind projection behind the pending-discovery index
    (#1109): unlike :func:`earliest_hitl_deadline_from_state`, it does not
    require a deadline, so a human pause without one is still queryable. The
    projection is a candidate filter only — callers revalidate against the
    canonical record and its PAUSED NodeRuns before disclosing anything.
    """
    pauses_raw = metadata.get("pauses", {})
    pauses = pauses_raw if isinstance(pauses_raw, Mapping) else {}
    for node_id in active_node_ids:
        pause_raw = pauses.get(node_id)
        if isinstance(pause_raw, Mapping) and pause_raw.get("kind") == "hitl":
            return True
    return False


def record_has_hitl_pause(record: DurableRunRecord) -> bool:
    """Whether the record's durable frontier holds at least one human pause."""
    return has_active_hitl_pause(record.graph_state.active_node_ids, record.graph_state.metadata)


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


def pending_hitl_node_ids(record: DurableRunRecord) -> tuple[str, ...]:
    """The frontier nodes waiting on a person, per canonical state.

    A durable human pause on a PAUSED NodeRun — the same predicate the
    discovery door discloses under: the projected row only nominates a
    candidate, and this re-derives eligibility from the record itself, so a
    degraded or stale projection can nominate but never disclose. Several
    nodes may wait independently on one Run; each is returned individually.
    """
    pauses_raw = record.graph_state.metadata.get("pauses")
    if not isinstance(pauses_raw, Mapping):
        return ()
    paused_nodes = {
        node_run.node_id for node_run in record.node_runs if node_run.status is RunStatus.PAUSED
    }
    pending: list[str] = []
    for node_id, pause in pauses_raw.items():
        if str(node_id) not in paused_nodes:
            continue
        if isinstance(pause, Mapping) and pause.get("kind") == "hitl":
            pending.append(str(node_id))
    return tuple(pending)


#: Ceiling on projected records one pending-discovery scope walk inspects,
#: independent of how many turn out to carry human work. With the pause-kind
#: projection (#1109) the store pages only rows whose durable frontier
#: declares a human pause, so this is a defensive bound on degraded rows, not
#: the thing that stands between a person and their work.
MAX_PENDING_SCAN_RECORDS = 2000

#: Minimum rows requested per page, regardless of how small the caller's item
#: target is, so a small target does not force one projected row per round
#: trip.
PENDING_SCAN_PAGE_SIZE = 100


@dataclass(frozen=True)
class PendingHitlScan:
    """What one bounded pending-discovery walk read (#1109).

    ``records`` are the projected, membership-revalidated records still
    carrying pending human work at read time. ``exhausted`` says whether the
    walk ended because the projection ran out (True) rather than because the
    inspection ceiling or the item limit stopped it with ordering left — the
    caller's signal that a later read may find more. The store reports its
    own progress separately (:class:`ScanPage`), so a page that assembles to
    nothing eligible — foreign-workspace rows on a Workspace-wide walk, or a
    stale projected row — advances the walk instead of reading as the end.
    """

    records: tuple[DurableRunRecord, ...] = ()
    exhausted: bool = False


async def pending_hitl_records(
    store: DurableRunStore,
    *,
    authorization: HitlAuthorization,
    workspace_id: str,
    project_id: str | None,
    limit: int,
) -> PendingHitlScan:
    """One authorized scope's pending human pauses, bounded (#1109).

    ``limit`` bounds pending *items* (a Run can wait on a person at several
    nodes), not a prefix of the PAUSED Runs in the store. The walk pages the
    store's pause-kind projection — human eligibility decided before any page
    is cut, so machine-only pauses and other Projects' work cannot occupy a
    page that real human work behind them needs — and revalidates live
    membership per item-carrying record before including it: the caller's
    Workspace-id snapshot is a candidate page, never the disclosure decision
    (#364).

    ``project_id`` narrows the walk to one Project; ``None`` walks the whole
    Workspace. The store's index cannot carry Workspace scope, so the store
    filters it from each assembled page and keeps paging — a page that
    assembles to nothing eligible moves ``resume_after`` past the foreign
    rows instead of ending the walk, which is what keeps this Workspace's
    work behind another tenant's readable. Rows beyond the store's per-call
    inspection ceiling are the one thing that can still stop a Workspace-wide
    walk short, and the returned ``exhausted`` says so honestly.

    The walk stops at ``limit`` items, ``MAX_PENDING_SCAN_RECORDS`` inspected
    rows, or the end of the projection — the same bounded-scan contract
    ``expire_hitl_pauses`` uses (#1056). No scan position is consumed, so a
    repeated request — or one that starts after a restart — cannot make a
    pending item unreachable.
    """
    if limit <= 0 or not authorization.workspace_ids:
        return PendingHitlScan()
    cursor: tuple[str, str] | None = None
    inspected = 0
    items = 0
    found: list[DurableRunRecord] = []
    while items < limit and inspected < MAX_PENDING_SCAN_RECORDS:
        page_size = min(
            max(limit, PENDING_SCAN_PAGE_SIZE),
            MAX_PENDING_SCAN_RECORDS - inspected,
        )
        page = await store.list_hitl_paused(
            limit=page_size,
            project_id=project_id,
            workspace_id=workspace_id,
            after=cursor,
        )
        inspected += page.inspected or 0
        if page.resume_after is not None:
            cursor = page.resume_after
        filled = False
        for record in page.items:
            node_ids = pending_hitl_node_ids(record)
            if not node_ids:
                # A projected row that canonical state disqualifies: it
                # carries nothing a revocation could withhold, and only its
                # place in the page is spent.
                continue
            if not await authorization.permits(record.run.workspace_id):
                continue
            found.append(record)
            items += len(node_ids)
            if items >= limit:
                filled = True
                break
        if filled:
            # The item limit stopped the walk with ordering left — including
            # any unread remainder of this page — so a later read may find
            # more, whatever the page's own exhaustion said.
            break
        if page.exhausted:
            return PendingHitlScan(records=tuple(found), exhausted=True)
    return PendingHitlScan(records=tuple(found))


async def _due_candidates(
    store: DurableRunStore,
    *,
    moment: datetime,
    limit: int,
    authorization: HitlAuthorization,
    project_ids: Collection[str] | None = None,
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
            if record.run.workspace_id not in authorization.workspace_ids:
                continue
            if project_ids is not None and record.run.project_id not in project_ids:
                continue
            candidates.append(record)
        if len(candidates) >= limit or len(page) < requested:
            return candidates[:limit]
        requested *= 2


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


async def expire_hitl_pauses(
    store: DurableRunStore,
    *,
    now: datetime | None = None,
    limit: int = 100,
    authorization: HitlAuthorization,
    project_ids: Collection[str] | None = None,
) -> list[DurableRunRecord]:
    """Settle at most ``limit`` paused Runs whose persisted deadline elapsed.

    This is an operator-scheduled tick, not a background task. It derives no
    deadline from process-local time or node configuration: only the absolute
    timestamp already present in the durable pause is authoritative. A
    product-supplied authorization binds the effective principal (or explicit
    delegation evidence) to canonical Workspace scope before any timeout
    mutation is requested. The authorization is mandatory even for an
    internal operator, which must provide explicit delegation evidence.

    ``limit`` bounds *expired-HITL* PAUSED Runs settled by this call, not a
    fixed prefix of every PAUSED Run in the store (#1056). Candidates come from
    the deadline index, which contains only due rows, so an arbitrarily large
    run of non-HITL or not-yet-due PAUSED Runs ahead of an expired one cannot
    hide it behind a fixed-size query. The index is a projection, so each
    candidate is still revalidated below against the durable pause itself.
    """
    if limit <= 0:
        return []
    if not authorization.workspace_ids:
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
    # ``project_ids``, when supplied, narrows the tick to Projects the caller
    # holds settlement authority over (#1110): the tick settles human
    # decisions, so it must not cross a Project the requesting principal could
    # not settle through the door itself. Workspace scope is always enforced
    # through the authorization's own live membership predicate.
    candidates = await _due_candidates(
        store,
        moment=moment,
        limit=limit,
        authorization=authorization,
        project_ids=project_ids,
    )
    settled: list[DurableRunRecord] = []
    for record in candidates:
        expired_node_id = _expired_hitl_node_id(record, moment)
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
    "MAX_PENDING_SCAN_RECORDS",
    "PENDING_SCAN_PAGE_SIZE",
    "HitlAuthorization",
    "HitlAuthorizationRequired",
    "HitlDeadlineElapsed",
    "HitlDeadlinePending",
    "HitlDelegationEvidence",
    "HitlSettlementError",
    "PendingHitlScan",
    "earliest_hitl_deadline",
    "expire_hitl_pauses",
    "has_active_hitl_pause",
    "hitl_deadline",
    "hitl_pause",
    "pending_hitl_node_ids",
    "pending_hitl_records",
    "record_has_hitl_pause",
    "settlement_time",
]

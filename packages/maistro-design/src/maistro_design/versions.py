"""Versioned human+AI artifact state for Design Studio (#780).

One durable change/version model under every material change to a creative
artifact, whether the change came from a person or from a canonical Run. The
model is an *extension* of the canonical artifact/provenance contract —
`DesignOutput` and the Run/NodeRun/Attempt ids it carries (#709,
SPEC-083026-b2b5) — not a competing artifact store: a version row embeds the
same content shape and the same producer provenance, and adds the identity a
product needs to preserve history:

* lineage (``lineage_id``) + monotone ``version`` — supersession, never
  destructive overwrite (content is append-only; there is no update path);
* the parent/base version and explicit fork relationships;
* the producing human principal or the canonical Run/NodeRun/Attempt;
* the CreativeBrief reference and shared-decision inputs consumed;
* draft/accepted/rejected state and explicit user locks;
* durable user guidance and per-branch control mode.

Execution truth stays canonical. Branch control is product state projected
onto it: ``BranchStateView`` carries a `maistro.runs.model.RunStatus` verbatim
rather than a second lifecycle vocabulary, and pausing/cancelling work happens
through the canonical Run, not here (#777 owns the mixed-control surface; the
CreativeBrief store itself is #774 — this module records only the versioned
*reference identity* a version consumed, forward-compatible with either).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from maistro.observability.correlation import observed_provenance
from maistro.runs.model import TERMINAL_RUN_STATUSES, RunStatus
from maistro_design.types import DesignError, DesignOutput

if TYPE_CHECKING:
    from maistro_design.version_store import ArtifactVersionStore


class ChangeOrigin(StrEnum):
    """Who produced a version: a person or a canonical execution."""

    HUMAN = "human"
    AGENT = "agent"


class ChangeKind(StrEnum):
    """What kind of material change a version records."""

    GENERATION = "generation"  # first agent-produced artifact on a lineage
    MANUAL_EDIT = "manual_edit"  # a person edited content directly
    REFINEMENT = "refinement"  # an agent continued from an existing version
    FORK = "fork"  # new branch copied from an existing version


class VersionState(StrEnum):
    """Review state of one version. draft → accepted/rejected is terminal."""

    DRAFT = "draft"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class LockScope(StrEnum):
    """What a user lock protects."""

    VERSION = "version"  # one whole artifact version (lineage + version)
    REGION = "region"  # a stable component address within a version
    DECISION = "decision"  # a shared decision/message/claim reference
    BRANCH = "branch"  # a whole artifact lineage, e.g. pending review


class ControlMode(StrEnum):
    """Who drives a branch — the human↔agent control continuum (#777)."""

    DIRECT = "direct"
    COLLABORATIVE = "collaborative"
    AUTONOMOUS = "autonomous"


# ─── Domain errors ────────────────────────────────────────────────────────────


class ArtifactVersionError(DesignError):
    code = "ARTIFACT_VERSION_ERROR"


class ArtifactVersionNotFoundError(ArtifactVersionError):
    code = "ARTIFACT_VERSION_NOT_FOUND"


class ArtifactVersionExistsError(ArtifactVersionError):
    """First-writer-wins on (project, lineage, version)."""

    code = "ARTIFACT_VERSION_EXISTS"


class ArtifactLockConflict(DesignError):
    """A requested change runs into a user lock.

    Raised, never worked around: an autonomous refinement that hits a lock
    must surface the conflict — naming every lock it hit — rather than
    silently rewriting locked state or pretending the refinement succeeded.
    """

    code = "ARTIFACT_LOCK_CONFLICT"

    def __init__(self, detail: str, *, conflicts: tuple[tuple[str, str], ...] = ()) -> None:
        super().__init__(detail)
        #: (lock_id, LockScope value) for every lock that blocked the change.
        self.conflicts = conflicts


class LockStateError(DesignError):
    code = "ARTIFACT_LOCK_STATE_ERROR"


class VersionStateError(ArtifactVersionError):
    """A state transition outside draft → accepted/rejected was requested."""

    code = "ARTIFACT_VERSION_STATE_ERROR"


# ─── Models ───────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(UTC)


def content_hash(fmt: str | None, content: str, url: str | None) -> str:
    """Stable digest of the carried content (or its stored URL for blobs)."""
    digest = hashlib.sha256()
    digest.update((fmt or "").encode())
    digest.update(b"\x00")
    digest.update(content.encode() if content else (url or "").encode())
    return digest.hexdigest()


@dataclass(frozen=True)
class ArtifactVersion:
    """One immutable, attributed state of a creative artifact.

    ``content``/``format``/``url`` mirror the canonical `DesignOutput` shape so
    manual and agent edits share one representation and one export path. For an
    agent change the producer is the canonical Run/NodeRun/Attempt triple (a
    human change carries no run ids — it must not pretend to be model output);
    for a human change the ``author`` principal is the producer.
    """

    org_id: str
    project_id: str
    lineage_id: str
    version: int
    kind: ChangeKind
    origin: ChangeOrigin
    title: str = ""
    format: str | None = None
    content: str = ""
    url: str | None = None
    trust_tier: str = "t3"
    state: VersionState = VersionState.DRAFT
    parent_version: int | None = None
    fork_lineage_id: str | None = None
    fork_version: int | None = None
    #: Versioned CreativeBrief reference identity (e.g. "brief-lineage#3").
    #: A reference, never a copy — the brief store stays #774's.
    brief_ref: str | None = None
    #: Shared-decision references this version consumed: {decision_ref: digest}.
    decision_inputs: dict[str, str] = field(default_factory=dict)
    author: str = ""
    run_id: str = ""
    node_run_id: str = ""
    attempt_id: str = ""
    content_sha: str = ""
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.content_sha:
            object.__setattr__(
                self, "content_sha", content_hash(self.format, self.content, self.url)
            )

    @classmethod
    def from_output(
        cls,
        *,
        org_id: str,
        project_id: str,
        lineage_id: str,
        version: int,
        kind: ChangeKind,
        origin: ChangeOrigin,
        output: DesignOutput,
        **extra: Any,
    ) -> ArtifactVersion:
        """Wrap a canonical `DesignOutput` (engine-produced artifact) as a version.

        Provenance comes from the output's producer fields, resolved against
        the ambient execution context exactly as `PgDesignProjectStore` does.
        An explicit ``title=`` overrides the output metadata's, if any.
        """
        extra.setdefault("title", str(output.metadata.get("title", "")))
        extra.setdefault("run_id", output.run_id)
        extra.setdefault("node_run_id", output.node_run_id)
        extra.setdefault("attempt_id", output.attempt_id)
        return cls(
            org_id=org_id,
            project_id=project_id,
            lineage_id=lineage_id,
            version=version,
            kind=kind,
            origin=origin,
            format=output.format.value if output.format is not None else None,
            content=output.content
            if output.root.kind.value == "file" and isinstance(output.root.value, str)
            else "",
            url=output.url,
            trust_tier=output.trust_tier.value,
            **extra,
        )

    def to_dict(self) -> dict[str, Any]:
        """The one export path for a version, human- and agent-produced alike."""
        return {
            "org_id": self.org_id,
            "project_id": self.project_id,
            "lineage_id": self.lineage_id,
            "version": self.version,
            "kind": self.kind.value,
            "origin": self.origin.value,
            "state": self.state.value,
            "title": self.title,
            "format": self.format,
            "content": self.content,
            "url": self.url,
            "trust_tier": self.trust_tier,
            "parent_version": self.parent_version,
            "fork_lineage_id": self.fork_lineage_id,
            "fork_version": self.fork_version,
            "brief_ref": self.brief_ref,
            "decision_inputs": dict(self.decision_inputs),
            "author": self.author,
            "run_id": self.run_id or None,
            "node_run_id": self.node_run_id or None,
            "attempt_id": self.attempt_id or None,
            "content_sha": self.content_sha,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class ArtifactLock:
    """An explicit user lock/freeze over part of the creative state.

    Locks are never removed implicitly: releasing one records who released it
    and when. An autonomous refinement that hits a lock is refused with
    `ArtifactLockConflict` naming it — the lock is never silently rewritten.
    """

    org_id: str
    project_id: str
    lineage_id: str
    scope: LockScope
    lock_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    version: int | None = None
    address: str | None = None
    decision_ref: str | None = None
    decision_digest: str | None = None
    reason: str = ""
    created_by: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    released_at: datetime | None = None
    released_by: str | None = None

    @property
    def active(self) -> bool:
        return self.released_at is None

    def covers_address(self, address: str) -> bool:
        """Whether this region lock governs a change at `address`.

        A lock on "characters" covers "characters.joe-smith" (the whole
        component) and a lock on "characters.joe-smith" covers an edit that
        rewrites the parent component wholesale.
        """
        if self.scope is not LockScope.REGION or self.address is None:
            return False
        return (
            address == self.address
            or address.startswith(f"{self.address}.")
            or self.address.startswith(f"{address}.")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "lock_id": self.lock_id,
            "org_id": self.org_id,
            "project_id": self.project_id,
            "lineage_id": self.lineage_id,
            "scope": self.scope.value,
            "version": self.version,
            "address": self.address,
            "decision_ref": self.decision_ref,
            "decision_digest": self.decision_digest,
            "reason": self.reason,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "released_at": self.released_at.isoformat() if self.released_at else None,
            "released_by": self.released_by,
            "active": self.active,
        }


@dataclass(frozen=True)
class GuidanceRecord:
    """Durable user guidance recorded during active work.

    Guidance is project input, not chat scrollback: it survives refresh and
    reconnect, narrows/redirects subsequent eligible work, and invalidates
    dependent results by supersession — previous results are never deleted.
    """

    org_id: str
    project_id: str
    text: str
    guidance_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    lineage_id: str | None = None  # None = project-wide
    author: str = ""
    run_id: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    active: bool = True
    superseded_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "guidance_id": self.guidance_id,
            "org_id": self.org_id,
            "project_id": self.project_id,
            "lineage_id": self.lineage_id,
            "text": self.text,
            "author": self.author,
            "run_id": self.run_id or None,
            "created_at": self.created_at.isoformat(),
            "active": self.active,
            "superseded_by": self.superseded_by,
        }


@dataclass(frozen=True)
class BranchControl:
    """Per-branch control state: who drives it and which Run is attached.

    Durable product state. Pause/cancel/wait/approve remain canonical Run
    operations — this record names the Run, it does not re-execute it.
    """

    org_id: str
    project_id: str
    lineage_id: str
    mode: ControlMode
    run_id: str | None = None
    updated_by: str = ""
    updated_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "org_id": self.org_id,
            "project_id": self.project_id,
            "lineage_id": self.lineage_id,
            "mode": self.mode.value,
            "run_id": self.run_id,
            "updated_by": self.updated_by,
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class BranchStateView:
    """What a product shows for one branch: control mode + canonical truth.

    `execution` is the canonical `RunStatus` verbatim — paused/waiting/
    cancelling/complete are canonical states, not a second lifecycle. Locks
    overlay as product facts (`locked` + `lock_ids`).
    """

    lineage_id: str
    mode: ControlMode
    execution: RunStatus | None
    locked: bool
    lock_ids: tuple[str, ...] = ()
    control: BranchControl | None = None

    @property
    def paused(self) -> bool:
        return self.execution is RunStatus.PAUSED

    @property
    def awaiting_approval(self) -> bool:
        return self.execution is RunStatus.WAITING

    @property
    def complete(self) -> bool:
        return self.execution is RunStatus.COMPLETED

    @property
    def stopped(self) -> bool:
        return self.execution in TERMINAL_RUN_STATUSES and self.execution is not RunStatus.COMPLETED

    def to_dict(self) -> dict[str, Any]:
        return {
            "lineage_id": self.lineage_id,
            "mode": self.mode.value,
            "execution": self.execution.value if self.execution else None,
            "locked": self.locked,
            "lock_ids": list(self.lock_ids),
            "paused": self.paused,
            "awaiting_approval": self.awaiting_approval,
            "complete": self.complete,
            "stopped": self.stopped,
        }


@dataclass(frozen=True)
class AgentWorkInputs:
    """The bundle newly eligible agent work must consume for one branch.

    The tip (a human edit is visible here before any subsequent eligible work),
    the active guidance that narrows/redirects the work, the locks it must
    respect, and the branch's control mode.
    """

    project_id: str
    lineage_id: str
    tip: ArtifactVersion | None
    guidance: tuple[GuidanceRecord, ...] = ()
    active_locks: tuple[ArtifactLock, ...] = ()
    control: BranchControl | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "lineage_id": self.lineage_id,
            "tip": self.tip.to_dict() if self.tip else None,
            "guidance": [g.to_dict() for g in self.guidance],
            "active_locks": [lock.to_dict() for lock in self.active_locks],
            "control": self.control.to_dict() if self.control else None,
        }


def _address_conflict(lock: ArtifactLock, addresses: tuple[str, ...] | None) -> bool:
    """Whether an edit collides with a region lock.

    A caller that declares the addresses it changed is blocked only when one
    collides. A caller that declares nothing cannot prove the locked region
    untouched, so it is blocked too — declaring the change set is the price of
    editing inside a region-locked lineage.
    """
    if addresses is None:
        return True
    return any(lock.covers_address(address) for address in addresses)


class CreativeArtifactService:
    """Lock-checked, provenance-bearing writes over an `ArtifactVersionStore`.

    The one product path for material artifact changes: agent generations and
    refinements carry canonical run provenance, human edits carry the author's
    principal, and both append to the same lineage. Every write checks the
    branch's active locks first and refuses with `ArtifactLockConflict` —
    naming each conflicting lock — instead of rewriting locked state.
    """

    def __init__(self, store: ArtifactVersionStore) -> None:
        self._store = store

    # ── writes ────────────────────────────────────────────────────────────

    async def record_generation(
        self,
        *,
        org_id: str,
        project_id: str,
        lineage_id: str,
        output: DesignOutput,
        brief_ref: str | None = None,
        decision_inputs: dict[str, str] | None = None,
        title: str = "",
    ) -> ArtifactVersion:
        """Persist the first agent-produced artifact version on a lineage.

        An agent change must name its canonical producer: generation is
        recorded inside a Run (ambient context fills what the caller omits),
        and a write with no execution in scope at all is refused rather than
        shipped as an unattributed artifact.
        """
        provenance = observed_provenance(
            run_id=output.run_id, node_run_id=output.node_run_id, attempt_id=output.attempt_id
        )
        if not provenance.run_id:
            raise ArtifactVersionError(
                "an agent-generated artifact must be recorded inside a canonical Run"
            )
        version = ArtifactVersion.from_output(
            org_id=org_id,
            project_id=project_id,
            lineage_id=lineage_id,
            version=1,
            kind=ChangeKind.GENERATION,
            origin=ChangeOrigin.AGENT,
            output=output,
            run_id=provenance.run_id,
            node_run_id=provenance.node_run_id,
            attempt_id=provenance.attempt_id,
            title=title,
            brief_ref=brief_ref,
            decision_inputs=dict(decision_inputs or {}),
        )
        # Get active locks for lock checking
        locks = await self._store.active_locks(org_id, project_id, lineage_id)

        # For generation (version 1), check branch and decision locks
        # Version and region locks can't exist yet (version 1 doesn't exist)

        conflicts: list[tuple[str, str]] = []
        details: list[str] = []

        for lock in locks:
            blocked = False
            if lock.scope is LockScope.BRANCH:
                blocked = True
            elif lock.scope is LockScope.DECISION and lock.decision_ref is not None:
                cited = (decision_inputs or {}).get(lock.decision_ref)
                blocked = cited is not None and cited != lock.decision_digest

            if blocked:
                conflicts.append((lock.lock_id, lock.scope.value))
                details.append(f"{lock.scope.value} lock {lock.lock_id}")

        if conflicts:
            raise ArtifactLockConflict(
                f"change to lineage {lineage_id!r} v1 "
                f"conflicts with {len(conflicts)} active lock(s): {', '.join(details)}",
                conflicts=tuple(conflicts),
            )
        return await self._store.append_version(version)

    async def record_manual_edit(
        self,
        *,
        org_id: str,
        project_id: str,
        lineage_id: str,
        author: str,
        content: str,
        parent_version: int | None = None,
        changed_addresses: tuple[str, ...] | None = None,
        brief_ref: str | None = None,
        decision_inputs: dict[str, str] | None = None,
        title: str = "",
    ) -> ArtifactVersion:
        """Record a person's direct edit as the next version on a lineage.

        Manual edits are first-class: the previous versions remain inspectable,
        the edit lands as the new tip (so the Workspace Agent sees it before any
        subsequent eligible work), and it carries the human principal — never a
        run id pretending the user was model output.
        """
        if not author:
            raise ArtifactVersionError("a manual edit must name its author")
        parent = await self._require_parent(org_id, project_id, lineage_id, parent_version)
        self._assert_not_locked(
            await self._store.active_locks(org_id, project_id, lineage_id),
            origin=ChangeOrigin.HUMAN,
            parent=parent,
            changed_addresses=changed_addresses,
            decision_inputs=decision_inputs or {},
        )
        version = ArtifactVersion(
            org_id=org_id,
            project_id=project_id,
            lineage_id=lineage_id,
            version=parent.version + 1,
            kind=ChangeKind.MANUAL_EDIT,
            origin=ChangeOrigin.HUMAN,
            title=title,
            format=parent.format,
            content=content,
            url=parent.url,
            trust_tier=parent.trust_tier,
            parent_version=parent.version,
            brief_ref=brief_ref or parent.brief_ref,
            decision_inputs=dict(decision_inputs or {}),
            author=author,
        )
        return await self._store.append_version(version)

    async def record_refinement(
        self,
        *,
        org_id: str,
        project_id: str,
        lineage_id: str,
        output: DesignOutput,
        parent_version: int | None = None,
        brief_ref: str | None = None,
        decision_inputs: dict[str, str] | None = None,
        title: str = "",
    ) -> ArtifactVersion:
        """Persist an agent's continuation from an existing version.

        Refinement inherits what it refines (format/url/trust) and must
        attribute its canonical producer. A refinement aimed at a locked
        version or region is refused with the conflict named.
        """
        provenance = observed_provenance(
            run_id=output.run_id, node_run_id=output.node_run_id, attempt_id=output.attempt_id
        )
        if not provenance.run_id:
            raise ArtifactVersionError(
                "an agent refinement must be recorded inside a canonical Run"
            )
        parent = await self._require_parent(org_id, project_id, lineage_id, parent_version)
        self._assert_not_locked(
            await self._store.active_locks(org_id, project_id, lineage_id),
            origin=ChangeOrigin.AGENT,
            parent=parent,
            decision_inputs=decision_inputs or {},
        )
        version = ArtifactVersion.from_output(
            org_id=org_id,
            project_id=project_id,
            lineage_id=lineage_id,
            version=parent.version + 1,
            kind=ChangeKind.REFINEMENT,
            origin=ChangeOrigin.AGENT,
            output=output,
            run_id=provenance.run_id,
            node_run_id=provenance.node_run_id,
            attempt_id=provenance.attempt_id,
            title=title,
            parent_version=parent.version,
            brief_ref=brief_ref or parent.brief_ref,
            decision_inputs=dict(decision_inputs or {}),
        )
        return await self._store.append_version(version)

    async def fork(
        self,
        *,
        org_id: str,
        project_id: str,
        source_lineage_id: str,
        source_version: int | None = None,
        new_lineage_id: str,
        actor: str = "",
        origin: ChangeOrigin | None = None,
        title: str = "",
    ) -> ArtifactVersion:
        """Fork a creative direction into a new lineage without erasing the original.

        The fork copies the source version's content as the new lineage's v1
        and records the fork relationship; the source lineage keeps every
        version it had. Forking is read-over-write, so locks on the source do
        not block it — nothing on the source is rewritten.
        """
        source = await self._require_parent(org_id, project_id, source_lineage_id, source_version)
        forked = ArtifactVersion(
            org_id=org_id,
            project_id=project_id,
            lineage_id=new_lineage_id,
            version=1,
            kind=ChangeKind.FORK,
            origin=origin if origin is not None else source.origin,
            title=title or source.title,
            format=source.format,
            content=source.content,
            url=source.url,
            trust_tier=source.trust_tier,
            fork_lineage_id=source.lineage_id,
            fork_version=source.version,
            brief_ref=source.brief_ref,
            decision_inputs=dict(source.decision_inputs),
            author=actor,
            run_id=source.run_id,
            node_run_id=source.node_run_id,
            attempt_id=source.attempt_id,
        )
        return await self._store.append_version(forked)

    # ── state transitions ────────────────────────────────────────────────

    async def accept(
        self, *, org_id: str, project_id: str, lineage_id: str, version: int
    ) -> ArtifactVersion:
        return await self._store.set_version_state(
            org_id, project_id, lineage_id, version, VersionState.ACCEPTED
        )

    async def reject(
        self, *, org_id: str, project_id: str, lineage_id: str, version: int
    ) -> ArtifactVersion:
        return await self._store.set_version_state(
            org_id, project_id, lineage_id, version, VersionState.REJECTED
        )

    # ── locks ─────────────────────────────────────────────────────────────

    async def lock_version(
        self,
        *,
        org_id: str,
        project_id: str,
        lineage_id: str,
        version: int,
        created_by: str,
        reason: str = "",
    ) -> ArtifactLock:
        await self._require_version(org_id, project_id, lineage_id, version)
        return await self._store.add_lock(
            ArtifactLock(
                org_id=org_id,
                project_id=project_id,
                lineage_id=lineage_id,
                scope=LockScope.VERSION,
                version=version,
                reason=reason,
                created_by=created_by,
            )
        )

    async def lock_region(
        self,
        *,
        org_id: str,
        project_id: str,
        lineage_id: str,
        version: int,
        address: str,
        created_by: str,
        reason: str = "",
    ) -> ArtifactLock:
        await self._require_version(org_id, project_id, lineage_id, version)
        return await self._store.add_lock(
            ArtifactLock(
                org_id=org_id,
                project_id=project_id,
                lineage_id=lineage_id,
                scope=LockScope.REGION,
                version=version,
                address=address,
                reason=reason,
                created_by=created_by,
            )
        )

    async def lock_decision(
        self,
        *,
        org_id: str,
        project_id: str,
        lineage_id: str,
        decision_ref: str,
        decision_digest: str,
        created_by: str,
        reason: str = "",
    ) -> ArtifactLock:
        return await self._store.add_lock(
            ArtifactLock(
                org_id=org_id,
                project_id=project_id,
                lineage_id=lineage_id,
                scope=LockScope.DECISION,
                decision_ref=decision_ref,
                decision_digest=decision_digest,
                reason=reason,
                created_by=created_by,
            )
        )

    async def lock_branch(
        self,
        *,
        org_id: str,
        project_id: str,
        lineage_id: str,
        created_by: str,
        reason: str = "",
    ) -> ArtifactLock:
        await self._require_tip(org_id, project_id, lineage_id)
        return await self._store.add_lock(
            ArtifactLock(
                org_id=org_id,
                project_id=project_id,
                lineage_id=lineage_id,
                scope=LockScope.BRANCH,
                reason=reason,
                created_by=created_by,
            )
        )

    async def release_lock(
        self, *, org_id: str, project_id: str, lock_id: str, released_by: str
    ) -> ArtifactLock:
        """Release a lock — an explicit user (or separately authorized) action."""
        if not released_by:
            raise LockStateError("a lock release must name who released it")
        return await self._store.release_lock(org_id, project_id, lock_id, released_by)

    # ── guidance & control ────────────────────────────────────────────────

    async def add_guidance(
        self,
        *,
        org_id: str,
        project_id: str,
        text: str,
        lineage_id: str | None = None,
        author: str = "",
    ) -> GuidanceRecord:
        if not text.strip():
            raise ArtifactVersionError("guidance must carry text")
        provenance = observed_provenance()
        return await self._store.add_guidance(
            GuidanceRecord(
                org_id=org_id,
                project_id=project_id,
                lineage_id=lineage_id,
                text=text,
                author=author,
                run_id=provenance.run_id,
            )
        )

    async def supersede_guidance(
        self, *, org_id: str, project_id: str, guidance_id: str, by_guidance_id: str
    ) -> GuidanceRecord:
        return await self._store.supersede_guidance(org_id, project_id, guidance_id, by_guidance_id)

    async def set_control(
        self,
        *,
        org_id: str,
        project_id: str,
        lineage_id: str,
        mode: ControlMode,
        run_id: str | None = None,
        updated_by: str = "",
    ) -> BranchControl:
        return await self._store.set_control(
            BranchControl(
                org_id=org_id,
                project_id=project_id,
                lineage_id=lineage_id,
                mode=mode,
                run_id=run_id,
                updated_by=updated_by,
            )
        )

    # ── reads ─────────────────────────────────────────────────────────────

    async def versions(
        self, *, org_id: str, project_id: str, lineage_id: str
    ) -> list[ArtifactVersion]:
        return await self._store.versions(org_id, project_id, lineage_id)

    async def tip(self, *, org_id: str, project_id: str, lineage_id: str) -> ArtifactVersion | None:
        return await self._store.tip(org_id, project_id, lineage_id)

    async def get_version(
        self, *, org_id: str, project_id: str, lineage_id: str, version: int
    ) -> ArtifactVersion:
        return await self._require_version(org_id, project_id, lineage_id, version)

    async def active_locks(
        self, *, org_id: str, project_id: str, lineage_id: str | None = None
    ) -> list[ArtifactLock]:
        return await self._store.active_locks(org_id, project_id, lineage_id)

    async def guidance_history(
        self, *, org_id: str, project_id: str, lineage_id: str | None = None
    ) -> list[GuidanceRecord]:
        return await self._store.guidance_history(org_id, project_id, lineage_id)

    async def get_control(
        self, *, org_id: str, project_id: str, lineage_id: str
    ) -> BranchControl | None:
        return await self._store.get_control(org_id, project_id, lineage_id)

    async def agent_inputs(
        self, *, org_id: str, project_id: str, lineage_id: str
    ) -> AgentWorkInputs:
        """Everything newly eligible work for this branch must consume."""
        return AgentWorkInputs(
            project_id=project_id,
            lineage_id=lineage_id,
            tip=await self._store.tip(org_id, project_id, lineage_id),
            guidance=tuple(await self._store.active_guidance(org_id, project_id, lineage_id)),
            active_locks=tuple(await self._store.active_locks(org_id, project_id, lineage_id)),
            control=await self._store.get_control(org_id, project_id, lineage_id),
        )

    async def branch_state(
        self,
        *,
        org_id: str,
        project_id: str,
        lineage_id: str,
        run_status: RunStatus | None = None,
    ) -> BranchStateView:
        """Project one branch's product state onto canonical execution truth.

        `run_status` is the canonical `RunStatus` of the branch's attached Run
        (the caller reads it from the canonical Run store — #777 wires that).
        Passing `None` means no Run is attached; locks and control mode still
        project, because they are durable product rows, not execution state.
        """
        control = await self._store.get_control(org_id, project_id, lineage_id)
        locks = await self._store.active_locks(org_id, project_id, lineage_id)
        return BranchStateView(
            lineage_id=lineage_id,
            mode=control.mode if control else ControlMode.DIRECT,
            execution=run_status,
            locked=bool(locks),
            lock_ids=tuple(lock.lock_id for lock in locks),
            control=control,
        )

    # ── internal ──────────────────────────────────────────────────────────

    async def _require_parent(
        self,
        org_id: str,
        project_id: str,
        lineage_id: str,
        parent_version: int | None,
    ) -> ArtifactVersion:
        if parent_version is None:
            parent = await self._store.tip(org_id, project_id, lineage_id)
            if parent is None:
                raise ArtifactVersionNotFoundError(
                    f"lineage {lineage_id!r} has no versions to change in project {project_id!r}"
                )
            return parent
        return await self._require_version(org_id, project_id, lineage_id, parent_version)

    async def _require_tip(self, org_id: str, project_id: str, lineage_id: str) -> ArtifactVersion:
        tip = await self._store.tip(org_id, project_id, lineage_id)
        if tip is None:
            raise ArtifactVersionNotFoundError(
                f"lineage {lineage_id!r} has no versions in project {project_id!r}"
            )
        return tip

    async def _require_version(
        self, org_id: str, project_id: str, lineage_id: str, version: int
    ) -> ArtifactVersion:
        found = await self._store.get_version(org_id, project_id, lineage_id, version)
        if found is None:
            raise ArtifactVersionNotFoundError(
                f"version {version} of lineage {lineage_id!r} not found in project {project_id!r}"
            )
        return found

    def _assert_not_locked(
        self,
        locks: list[ArtifactLock],
        *,
        origin: ChangeOrigin,
        parent: ArtifactVersion,
        changed_addresses: tuple[str, ...] | None = None,
        decision_inputs: dict[str, str] | None = None,
    ) -> None:
        conflicts: list[tuple[str, str]] = []
        details: list[str] = []
        for lock in locks:
            blocked = False
            if lock.scope is LockScope.BRANCH:
                blocked = True
            elif lock.scope is LockScope.VERSION:
                # An accepted version is frozen: an autonomous refinement
                # aimed at it is replacement and is refused. A person editing
                # creates an explicit new version below it and is allowed —
                # the lock still protects the accepted version's content,
                # which nothing can overwrite.
                blocked = origin is ChangeOrigin.AGENT and lock.version == parent.version
            elif lock.scope is LockScope.REGION:
                blocked = _address_conflict(lock, changed_addresses)
            elif lock.scope is LockScope.DECISION and lock.decision_ref is not None:
                cited = (decision_inputs or {}).get(lock.decision_ref)
                # A locked decision constrains the descendants that reference
                # it: same content digest as when it was locked, or no
                # reference at all — never a quiet contradiction.
                blocked = cited is not None and cited != lock.decision_digest
            if blocked:
                conflicts.append((lock.lock_id, lock.scope.value))
                details.append(f"{lock.scope.value} lock {lock.lock_id}")
        if conflicts:
            raise ArtifactLockConflict(
                f"change to lineage {parent.lineage_id!r} v{parent.version + 1} "
                f"conflicts with {len(conflicts)} active lock(s): {', '.join(details)}",
                conflicts=tuple(conflicts),
            )


if TYPE_CHECKING:

    def _vulture_artifact_version_contract_usage(service: CreativeArtifactService) -> None:
        """Keep reflection-owned #780 contract surface visible to Vulture.

        ``CreativeArtifactService`` is the one product write path for material
        artifact changes (SPEC-092826-a780): its record/fork/lock/read methods
        are the public contract the mixed-control surface (#777) and the
        CreativeBrief store (#774) consume, and ``ControlMode.COLLABORATIVE``
        is one point of the control continuum that continuum is defined by.
        They are exercised by ``packages/maistro-design/tests/``
        ``test_artifact_versions.py`` today; none of this is dead code. The
        narrow ``packages/*/src`` production-only Vulture scan just cannot see
        the test- and downstream-product consumers. Follows the repo's
        ``_vulture_*_usage`` TYPE_CHECKING precedent (e1f16ddae, 632c24c78:
        "banking alone cannot pass this round" — banking would misrecord live
        contract surface as dead debt).

        Vulture matches by bare name, not per-symbol: referencing ``reject``
        here also marks identically-named in-scope methods as used (e.g.
        ``maistro.core`` ``memory/learnings/approval.py::reject``), which is
        why that reviewed ledger identity is pruned alongside this block.
        """
        _ = ControlMode.COLLABORATIVE
        _ = service.record_generation
        _ = service.record_manual_edit
        _ = service.record_refinement
        _ = service.fork
        _ = service.reject
        _ = service.lock_version
        _ = service.lock_region
        _ = service.lock_decision
        _ = service.lock_branch
        _ = service.agent_inputs
        _ = service.branch_state

    _ = _vulture_artifact_version_contract_usage


__all__ = [
    "AgentWorkInputs",
    "ArtifactLock",
    "ArtifactLockConflict",
    "ArtifactVersion",
    "ArtifactVersionError",
    "ArtifactVersionExistsError",
    "ArtifactVersionNotFoundError",
    "BranchControl",
    "BranchStateView",
    "ChangeKind",
    "ChangeOrigin",
    "ControlMode",
    "CreativeArtifactService",
    "GuidanceRecord",
    "LockScope",
    "LockStateError",
    "VersionState",
    "VersionStateError",
    "content_hash",
]

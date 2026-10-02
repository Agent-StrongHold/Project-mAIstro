"""Versioned CreativeBrief projection — Design Studio domain state (#773/#774).

A CreativeBrief is the versioned creative projection of one exact canonical
Goal revision. It elaborates the creative-production context needed to satisfy
that Goal through Design Studio — audience, success interpretation, source
truth, channel/artifact requirements, constraints — without ever replacing,
silently forking, or mutating canonical Goal identity. Changing the desired
outcome is a Goal revision (#458); changing only the creative interpretation
appends a CreativeBrief version against the same Goal revision.

Canonical identity stays canonical. Every brief validates its Workspace /
Project / Goal / Agent (+ optional Persona) references against the shared
interoperability registry (``maistro.interop``, #458), so Design Studio cannot
mint a second Goal, Agent, or Persona identity universe.

Execution stays canonical too. This module owns no scheduler, no Run lifecycle,
and no authorization: it only declares the provenance every produced artifact
must retain (#773) — the exact Goal revision + CreativeBrief version consumed,
plus the canonical Run/NodeRun/Attempt evidence that produced the artifact.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from maistro.interop import (
    INTEROP_ONTOLOGY_V1,
    InteropContractError,
    validate_projection,
    validate_reference_set,
)
from maistro_design.types import DesignError

# Vulture scans src trees only (packages/*/src, confidence >= 60), so it cannot
# see the consumers of this contract: the tests live outside the scan and the
# #774 persistence and #775 creative-Graph lanes have not landed yet. The
# retained API below carries vulture's V105 (unused method) suppression marker
# at the use site — declared external in ruff config, so debt is reviewed and
# recorded here instead of growing quality/vulture-baseline.json; the
# per-identity ledger only shrinks (same shape as the bare vulture noqa marker
# on maistro_registry.schema._validate_lifecycle_evidence).
__all__ = [
    "ArtifactProvenance",
    "ArtifactRequirement",
    "BriefRevision",
    "CreativeBrief",
    "CreativeBriefConflictError",
    "CreativeBriefError",
    "CreativeBriefNotFoundError",
    "CreativeBriefStore",
    "CreativeBriefVersion",
    "InMemoryCreativeBriefStore",
    "SharedCreativeContext",
    "validate_canonical_references",
]


# ── Domain errors ─────────────────────────────────────────────────────────────


class CreativeBriefError(DesignError):
    """Base error for CreativeBrief contract violations."""

    code = "CREATIVE_BRIEF_ERROR"


class CreativeBriefNotFoundError(CreativeBriefError):
    """Raised when a brief id is unknown or outside the caller's scope."""

    code = "CREATIVE_BRIEF_NOT_FOUND"


class CreativeBriefConflictError(CreativeBriefError):
    """Raised when an operation would fork or mutate canonical identity."""

    code = "CREATIVE_BRIEF_CONFLICT"


# ── Validation helpers ────────────────────────────────────────────────────────


def _require_non_blank(label: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        msg = f"{label} must be a non-blank string"
        raise CreativeBriefError(msg)
    return value


def _require_optional_non_blank(label: str, value: str | None) -> None:
    if value is not None:
        _require_non_blank(label, value)


def _require_str_tuple(label: str, value: object) -> None:
    if not isinstance(value, tuple):
        msg = f"{label} must be a tuple of strings"
        raise CreativeBriefError(msg)
    for item in value:
        _require_non_blank(label, item)


def validate_canonical_references(
    *,
    workspace_id: str,
    project_id: str,
    goal_id: str,
    goal_revision: str | int,
    owner_agent_id: str,
    persona_id: str | None = None,
) -> None:
    """Validate every canonical reference a brief carries against #458's registry.

    ``validate_reference_set`` enforces the canonical parent/scope lineage
    (Project requires Workspace; Goal requires Project; Agent requires
    Workspace); ``validate_projection`` enforces the exact ``goal_revision``
    the v1 contract requires on every Goal projection. Failures surface as
    :class:`CreativeBriefError` so the product boundary stays typed.
    """
    references: dict[str, str] = {
        "Workspace": _require_non_blank("workspace_id", workspace_id),
        "Project": _require_non_blank("project_id", project_id),
        "Goal": _require_non_blank("goal_id", goal_id),
        "Agent": _require_non_blank("owner_agent_id", owner_agent_id),
    }
    if persona_id is not None:
        references["Persona"] = _require_non_blank("persona_id", persona_id)
    try:
        validate_projection(
            INTEROP_ONTOLOGY_V1,
            "Goal",
            {"goal_id": references["Goal"], "goal_revision": goal_revision},
        )
        validate_reference_set(INTEROP_ONTOLOGY_V1, references)
    except InteropContractError as exc:
        msg = f"CreativeBrief violates the shared interoperability contract: {exc}"
        raise CreativeBriefError(msg) from exc


# ── Value objects ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ArtifactRequirement:
    """One channel/artifact-specific requirement (shared-context item 7, #773)."""

    branch: str
    requirement: str

    def __post_init__(self) -> None:
        _require_non_blank("branch", self.branch)
        _require_non_blank("requirement", self.requirement)


@dataclass(frozen=True)
class CreativeBriefVersion:
    """One immutable version of a CreativeBrief lineage.

    Frozen by design: a published brief version is durable context that Runs
    and artifacts point at; nothing may silently rewrite what already has
    readers. Evolution appends a new version via a store's ``revise``.
    """

    brief_id: str
    version: int
    goal_id: str
    goal_revision: str | int
    workspace_id: str
    project_id: str
    owner_agent_id: str
    persona_id: str | None
    design_system_slug: str | None
    design_system_version: str | None
    success_criteria: tuple[str, ...]
    audience: str
    source_references: tuple[str, ...]
    artifact_requirements: tuple[ArtifactRequirement, ...]
    creative_constraints: tuple[str, ...]
    summary: str
    created_at: datetime

    def __post_init__(self) -> None:
        _require_non_blank("brief_id", self.brief_id)
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            msg = "version must be a positive integer"
            raise CreativeBriefError(msg)
        validate_canonical_references(
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            goal_id=self.goal_id,
            goal_revision=self.goal_revision,
            owner_agent_id=self.owner_agent_id,
            persona_id=self.persona_id,
        )
        _require_optional_non_blank("design_system_slug", self.design_system_slug)
        _require_optional_non_blank("design_system_version", self.design_system_version)
        _require_non_blank("audience", self.audience)
        _require_non_blank("summary", self.summary)
        _require_str_tuple("success_criteria", self.success_criteria)
        _require_str_tuple("source_references", self.source_references)
        _require_str_tuple("creative_constraints", self.creative_constraints)
        if not isinstance(self.artifact_requirements, tuple) or any(
            not isinstance(item, ArtifactRequirement) for item in self.artifact_requirements
        ):
            msg = "artifact_requirements must be a tuple of ArtifactRequirement values"
            raise CreativeBriefError(msg)
        branch_names = [req.branch for req in self.artifact_requirements]
        if len(branch_names) != len(set(branch_names)):
            duplicates = sorted({name for name in branch_names if branch_names.count(name) > 1})
            msg = (
                "artifact_requirements must declare each branch at most once "
                f"(requirement_for returns the first match); duplicates: {duplicates}"
            )
            raise CreativeBriefError(msg)

    def requirement_for(self, branch: str) -> ArtifactRequirement | None:
        """The declared channel requirement for ``branch``, if the brief declares one."""
        _require_non_blank("branch", branch)
        return next((req for req in self.artifact_requirements if req.branch == branch), None)

    def shared_context(  # noqa: V105
        self, branch: str | None = None
    ) -> SharedCreativeContext:
        """The identical shared context every artifact branch of this brief receives.

        A website, coupon, deck, and video script produced from the same brief
        get the same canonical Goal identity/revision, the same CreativeBrief
        version, and the same Persona / Design System / source truth — outputs
        recognizably from one team and project, not unrelated generations that
        happen to share a prompt string.
        """
        requirement = self.requirement_for(branch) if branch is not None else None
        return SharedCreativeContext(
            goal_id=self.goal_id,
            goal_revision=self.goal_revision,
            brief_id=self.brief_id,
            brief_version=self.version,
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            owner_agent_id=self.owner_agent_id,
            persona_id=self.persona_id,
            design_system_slug=self.design_system_slug,
            design_system_version=self.design_system_version,
            success_criteria=self.success_criteria,
            audience=self.audience,
            source_references=self.source_references,
            creative_constraints=self.creative_constraints,
            branch=branch,
            requirement=requirement.requirement if requirement is not None else None,
        )

    def to_dict(self) -> dict[str, object]:
        """JSON-safe serialization of this version."""
        return {
            "brief_id": self.brief_id,
            "version": self.version,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "owner_agent_id": self.owner_agent_id,
            "persona_id": self.persona_id,
            "design_system_slug": self.design_system_slug,
            "design_system_version": self.design_system_version,
            "success_criteria": list(self.success_criteria),
            "audience": self.audience,
            "source_references": list(self.source_references),
            "artifact_requirements": [
                {"branch": req.branch, "requirement": req.requirement}
                for req in self.artifact_requirements
            ],
            "creative_constraints": list(self.creative_constraints),
            "summary": self.summary,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class SharedCreativeContext:
    """The shared context every artifact branch of one brief version receives.

    Derived from a validated :class:`CreativeBriefVersion` via
    ``CreativeBriefVersion.shared_context``; branch-specific state is limited
    to the declared channel requirement. All other fields are identical across
    branches by construction.
    """

    goal_id: str
    goal_revision: str | int
    brief_id: str
    brief_version: int
    workspace_id: str
    project_id: str
    owner_agent_id: str
    persona_id: str | None
    design_system_slug: str | None
    design_system_version: str | None
    success_criteria: tuple[str, ...]
    audience: str
    source_references: tuple[str, ...]
    creative_constraints: tuple[str, ...]
    branch: str | None
    requirement: str | None

    def __post_init__(self) -> None:
        _require_str_tuple("creative_constraints", self.creative_constraints)

    def to_dict(self) -> dict[str, object]:
        """JSON-safe serialization with the canonical interop field names."""
        return {
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "brief_id": self.brief_id,
            "brief_version": self.brief_version,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "owner_agent_id": self.owner_agent_id,
            "persona_id": self.persona_id,
            "design_system_slug": self.design_system_slug,
            "design_system_version": self.design_system_version,
            "success_criteria": list(self.success_criteria),
            "audience": self.audience,
            "source_references": list(self.source_references),
            "creative_constraints": list(self.creative_constraints),
            "branch": self.branch,
            "requirement": self.requirement,
        }


@dataclass(frozen=True)
class ArtifactProvenance:
    """Provenance every produced artifact must retain (#773 acceptance).

    One record joining the creative context consumed (exact Goal revision +
    CreativeBrief version) with the canonical execution evidence (Run /
    NodeRun / Attempt) that produced the artifact. This is not a second
    execution lifecycle: terminality and retries stay owned by
    Run/NodeRun/Attempt; this record only makes lineage recoverable.
    """

    goal_id: str
    goal_revision: str | int
    brief_id: str
    brief_version: int
    run_id: str
    node_run_id: str
    attempt_id: str

    @classmethod  # noqa: V105
    def bind(
        cls,
        version: CreativeBriefVersion,
        *,
        run_id: str,
        node_run_id: str,
        attempt_id: str,
    ) -> ArtifactProvenance:
        """Bind one artifact's execution evidence to the exact brief version consumed."""
        _require_non_blank("run_id", run_id)
        _require_non_blank("node_run_id", node_run_id)
        _require_non_blank("attempt_id", attempt_id)
        return cls(
            goal_id=version.goal_id,
            goal_revision=version.goal_revision,
            brief_id=version.brief_id,
            brief_version=version.version,
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
        )

    def assert_matches_goal(  # noqa: V105
        self, goal_id: str, goal_revision: str | int
    ) -> None:
        """Refuse provenance claimed against a different Goal identity/revision."""
        if self.goal_id != goal_id or self.goal_revision != goal_revision:
            msg = (
                f"artifact provenance names Goal {self.goal_id!r} revision "
                f"{self.goal_revision!r}, not {goal_id!r} revision {goal_revision!r}"
            )
            raise CreativeBriefConflictError(msg)

    def to_dict(self) -> dict[str, object]:
        """JSON-safe serialization of the provenance record."""
        return {
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "brief_id": self.brief_id,
            "brief_version": self.brief_version,
            "run_id": self.run_id,
            "node_run_id": self.node_run_id,
            "attempt_id": self.attempt_id,
        }


# ── Lineage and revisions ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class CreativeBrief:
    """A versioned CreativeBrief lineage bound to one exact Goal revision.

    The Goal identity/revision and scope are read from the immutable versions;
    all versions of a lineage necessarily agree because ``revise`` accepts no
    field that could change them.
    """

    brief_id: str
    versions: tuple[CreativeBriefVersion, ...]

    def __post_init__(self) -> None:
        _require_non_blank("brief_id", self.brief_id)
        if not self.versions or not all(
            isinstance(item, CreativeBriefVersion) for item in self.versions
        ):
            msg = "a CreativeBrief requires at least one CreativeBriefVersion"
            raise CreativeBriefError(msg)
        first = self.versions[0]
        for item in self.versions:
            if item.brief_id != self.brief_id:
                msg = "all versions of a lineage must share the brief_id"
                raise CreativeBriefError(msg)
            if (
                item.goal_id != first.goal_id
                or item.goal_revision != first.goal_revision
                or item.workspace_id != first.workspace_id
                or item.project_id != first.project_id
            ):
                msg = "all versions of a lineage must bind the same Goal revision and scope"
                raise CreativeBriefError(msg)
        ordered = tuple(sorted(self.versions, key=lambda item: item.version))
        if [item.version for item in ordered] != list(range(1, len(ordered) + 1)):
            msg = "versions must be contiguous starting at 1"
            raise CreativeBriefError(msg)
        object.__setattr__(self, "versions", ordered)

    @property
    def current(self) -> CreativeBriefVersion:
        """The latest published version of this lineage."""
        return self.versions[-1]

    def version(self, number: int) -> CreativeBriefVersion:
        """Return version ``number`` or raise :class:`CreativeBriefNotFoundError`."""
        for item in self.versions:
            if item.version == number:
                return item
        msg = f"CreativeBrief {self.brief_id} has no version {number}"
        raise CreativeBriefNotFoundError(msg)


@dataclass(frozen=True)
class BriefRevision:
    """Creative-context changes for one new CreativeBrief version.

    Deliberately carries no Goal identity, scope, owner, or version fields: a
    revision changes creative interpretation only. Changing the desired
    outcome is a Goal revision (#458); changing accountability is Agent-domain
    state; neither belongs to a brief. ``None`` carries the current value
    forward, so a bound Persona/Design System reference cannot be silently
    dropped — replacing it requires naming the new reference.
    """

    summary: str
    persona_id: str | None = None
    design_system_slug: str | None = None
    design_system_version: str | None = None
    success_criteria: tuple[str, ...] | None = None
    audience: str | None = None
    source_references: tuple[str, ...] | None = None
    artifact_requirements: tuple[ArtifactRequirement, ...] | None = None
    creative_constraints: tuple[str, ...] | None = None


# ── Store ─────────────────────────────────────────────────────────────────────


@runtime_checkable
class CreativeBriefStore(Protocol):
    """Scope-keyed CreativeBrief persistence.

    Every read takes the caller's scope as keyword-only arguments with no
    defaults (#326): a default is a scope check the next caller omits. Stores
    enforce single-lineage-per-Goal-revision so ``Goal + CreativeBrief resolve``
    stays unambiguous within a project.
    """

    async def create(
        self,
        *,
        workspace_id: str,
        project_id: str,
        goal_id: str,
        goal_revision: str | int,
        owner_agent_id: str,
        persona_id: str | None = None,
        design_system_slug: str | None = None,
        design_system_version: str | None = None,
        success_criteria: tuple[str, ...] = (),
        audience: str,
        source_references: tuple[str, ...] = (),
        artifact_requirements: tuple[ArtifactRequirement, ...] = (),
        creative_constraints: tuple[str, ...] = (),
        summary: str,
    ) -> CreativeBrief: ...

    async def revise(  # noqa: V105
        self,
        brief_id: str,
        *,
        workspace_id: str,
        project_id: str,
        revision: BriefRevision,
    ) -> CreativeBrief: ...

    async def get(
        self, brief_id: str, *, workspace_id: str, project_id: str
    ) -> CreativeBrief | None: ...

    async def history(
        self, brief_id: str, *, workspace_id: str, project_id: str
    ) -> tuple[CreativeBriefVersion, ...]: ...

    async def list_by_goal(  # noqa: V105
        self, goal_id: str, goal_revision: str | int, *, workspace_id: str, project_id: str
    ) -> list[CreativeBrief]: ...


class InMemoryCreativeBriefStore:
    """Reference in-memory ``CreativeBriefStore``.

    Not durable truth — PostgreSQL remains authoritative for durable state.
    This reference implementation exists so the #773 contract is executable
    before the #774 persistence lane lands, and it enforces every rule the
    protocol declares, including single-lineage-per-Goal-revision and
    scope-keyed reads.
    """

    def __init__(self) -> None:
        self._briefs: dict[str, CreativeBrief] = {}

    def _require(self, brief_id: str, workspace_id: str, project_id: str) -> CreativeBrief:
        """Resolve a brief inside the caller's scope, or raise not-found.

        A scope mismatch is indistinguishable from absence: nothing leaks
        across Workspaces or Projects through this store.
        """
        brief = self._briefs.get(brief_id)
        if (
            brief is None
            or brief.current.workspace_id != workspace_id
            or brief.current.project_id != project_id
        ):
            msg = f"no CreativeBrief {brief_id!r} in workspace {workspace_id!r} project {project_id!r}"
            raise CreativeBriefNotFoundError(msg)
        return brief

    async def create(
        self,
        *,
        workspace_id: str,
        project_id: str,
        goal_id: str,
        goal_revision: str | int,
        owner_agent_id: str,
        persona_id: str | None = None,
        design_system_slug: str | None = None,
        design_system_version: str | None = None,
        success_criteria: tuple[str, ...] = (),
        audience: str,
        source_references: tuple[str, ...] = (),
        artifact_requirements: tuple[ArtifactRequirement, ...] = (),
        creative_constraints: tuple[str, ...] = (),
        summary: str,
    ) -> CreativeBrief:
        """Mint a brief lineage at version 1 against one exact Goal revision."""
        validate_canonical_references(
            workspace_id=workspace_id,
            project_id=project_id,
            goal_id=goal_id,
            goal_revision=goal_revision,
            owner_agent_id=owner_agent_id,
            persona_id=persona_id,
        )
        for brief in self._briefs.values():
            current = brief.current
            if (
                current.goal_id == goal_id
                and current.goal_revision == goal_revision
                and current.workspace_id == workspace_id
                and current.project_id == project_id
            ):
                msg = (
                    f"CreativeBrief {brief.brief_id} already binds Goal {goal_id!r} revision "
                    f"{goal_revision!r} in this project; revise it instead of forking the lineage"
                )
                raise CreativeBriefConflictError(msg)
        brief_id = str(uuid.uuid4())
        version = CreativeBriefVersion(
            brief_id=brief_id,
            version=1,
            goal_id=goal_id,
            goal_revision=goal_revision,
            workspace_id=workspace_id,
            project_id=project_id,
            owner_agent_id=owner_agent_id,
            persona_id=persona_id,
            design_system_slug=design_system_slug,
            design_system_version=design_system_version,
            success_criteria=success_criteria,
            audience=audience,
            source_references=source_references,
            artifact_requirements=artifact_requirements,
            creative_constraints=creative_constraints,
            summary=summary,
            created_at=datetime.now(UTC),
        )
        brief = CreativeBrief(brief_id=brief_id, versions=(version,))
        self._briefs[brief_id] = brief
        return brief

    async def revise(  # noqa: V105
        self,
        brief_id: str,
        *,
        workspace_id: str,
        project_id: str,
        revision: BriefRevision,
    ) -> CreativeBrief:
        """Append version N+1 with creative-context changes; identity is not revisable."""
        brief = self._require(brief_id, workspace_id, project_id)
        current = brief.current
        _require_non_blank("summary", revision.summary)
        next_version = CreativeBriefVersion(
            brief_id=brief_id,
            version=current.version + 1,
            goal_id=current.goal_id,
            goal_revision=current.goal_revision,
            workspace_id=current.workspace_id,
            project_id=current.project_id,
            owner_agent_id=current.owner_agent_id,
            persona_id=(
                revision.persona_id if revision.persona_id is not None else current.persona_id
            ),
            design_system_slug=(
                revision.design_system_slug
                if revision.design_system_slug is not None
                else current.design_system_slug
            ),
            design_system_version=(
                revision.design_system_version
                if revision.design_system_version is not None
                else current.design_system_version
            ),
            success_criteria=(
                revision.success_criteria
                if revision.success_criteria is not None
                else current.success_criteria
            ),
            audience=revision.audience if revision.audience is not None else current.audience,
            source_references=(
                revision.source_references
                if revision.source_references is not None
                else current.source_references
            ),
            artifact_requirements=(
                revision.artifact_requirements
                if revision.artifact_requirements is not None
                else current.artifact_requirements
            ),
            creative_constraints=(
                revision.creative_constraints
                if revision.creative_constraints is not None
                else current.creative_constraints
            ),
            summary=revision.summary,
            created_at=datetime.now(UTC),
        )
        updated = CreativeBrief(brief_id=brief_id, versions=(*brief.versions, next_version))
        self._briefs[brief_id] = updated
        return updated

    async def get(
        self, brief_id: str, *, workspace_id: str, project_id: str
    ) -> CreativeBrief | None:
        """Return the brief inside the caller's scope, or ``None``."""
        try:
            return self._require(brief_id, workspace_id, project_id)
        except CreativeBriefNotFoundError:
            return None

    async def history(
        self, brief_id: str, *, workspace_id: str, project_id: str
    ) -> tuple[CreativeBriefVersion, ...]:
        """All versions of the brief, oldest first."""
        return self._require(brief_id, workspace_id, project_id).versions

    async def list_by_goal(  # noqa: V105
        self, goal_id: str, goal_revision: str | int, *, workspace_id: str, project_id: str
    ) -> list[CreativeBrief]:
        """Brief lineages bound to this exact Goal revision inside the caller's scope."""
        return [
            brief
            for brief in self._briefs.values()
            if brief.current.goal_id == goal_id
            and brief.current.goal_revision == goal_revision
            and brief.current.workspace_id == workspace_id
            and brief.current.project_id == project_id
        ]

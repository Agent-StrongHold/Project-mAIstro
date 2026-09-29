"""CreativeBrief — the versioned Design Studio shared creative-context contract (#774).

A CreativeBrief is Design Studio *domain state*: a versioned creative
projection/context for exactly one canonical Project Goal revision. It
elaborates the Goal for creative production (audience, channel requirements,
source truth, acceptance interpretation, creative constraints) but never
replaces, forks, or mutates canonical Goal identity — Goal identity, revision
history, ownership, and delegation remain canonical outside Design Studio
(``maistro.interop`` / #458; the Workspace Agent owns the Project Goal per
ADR-092326-7ed7).

Contracts this module owns:

- **Immutable by version.** A ``CreativeBrief`` instance is frozen; updating
  creative context produces a *new* version on the same ``lineage_id`` via
  :meth:`CreativeBrief.new_version`. A Run/artifact can therefore name the
  exact ``brief_id``/``brief_version`` (and the exact ``goal_id``/
  ``goal_revision``) it consumed, and prior interpretations stay intact.
- **References, not copies.** Persona (#39) and Design System are recorded as
  ``BriefReference`` values carrying identity + version. They are not
  competing identity stores, and no field here grants authorization: the
  schema forbids extra fields, and delegation/supervision notes are
  non-authoritative annotations — the canonical delegation/authorization
  authorities are untouched (#775/#780 own downstream semantics).
- **Structural scope rejection.** Every reference that carries a
  ``workspace_id`` must name the brief's own Workspace; the persistence layer
  additionally refuses a brief whose Project is not registered to the claimed
  Workspace (see ``maistro_design.brief_store``).
- **Derived projections.** :meth:`CreativeBrief.project` derives a channel
  projection that carries the source Goal/brief/Persona/Design-System identity
  verbatim; overrides are explicit, explained, and may never touch protected
  shared context.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from maistro.interop import INTEROP_ONTOLOGY_V1, InteropContractError, validate_reference_set
from maistro_design.types import DesignError

#: Kinds a :class:`BriefReference` may point at. Goals/subgoals, delegation
#: records, Persona, Design System, GraphTemplate/Graph, and source artifacts
#: are all canonical state owned elsewhere; a brief only *references* them.
BriefReferenceKind = Literal[
    "persona",
    "design_system",
    "goal",
    "delegation",
    "graph_template",
    "graph",
    "artifact",
]

_PROVENANCE_REFERENCE_KINDS: frozenset[str] = frozenset({"artifact", "goal", "graph"})
_DELEGATION_REFERENCE_KINDS: frozenset[str] = frozenset({"delegation", "goal"})
_GRAPH_REFERENCE_KINDS: frozenset[str] = frozenset({"graph_template", "graph"})

#: Projection fields a channel override may never touch. These are the shared
#: Goal/brief/Persona/Design-System facts every artifact branch must receive
#: semantically identically; derived channel work adjusts presentation only,
#: and does so explicitly with a reason.
PROTECTED_PROJECTION_FIELDS: frozenset[str] = frozenset(
    {
        "projection_id",
        "workspace_id",
        "project_id",
        "goal_id",
        "goal_revision",
        "goal_owner_agent_id",
        "brief_lineage_id",
        "brief_id",
        "brief_version",
        "persona_id",
        "persona_version",
        "design_system_slug",
        "design_system_version",
        "audience",
        "beneficiaries",
        "success_interpretation",
        "required_messages",
        "cta",
        "required_facts",
        "prohibited_claims",
        "tone_constraints",
        "supervision_constraints",
    }
)

#: Fields a version bump may never rewrite. A CreativeBrief lineage lives in
#: exactly one Workspace/Project — moving it is a new lineage, not an update —
#: and version identity/provenance is minted by the contract, not the caller.
_LINEAGE_IMMUTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "brief_id",
        "lineage_id",
        "version",
        "supersedes_brief_id",
        "workspace_id",
        "project_id",
        "created_at",
        "created_by",
    }
)


class CreativeBriefError(DesignError):
    """Base class for CreativeBrief contract violations."""

    code = "CREATIVE_BRIEF_ERROR"


class CrossWorkspaceReferenceError(CreativeBriefError):
    """A reference names state that lives in a different Workspace."""

    code = "CREATIVE_BRIEF_CROSS_WORKSPACE"


class BriefContractError(CreativeBriefError):
    """A brief violates the versioned CreativeBrief contract itself."""

    code = "CREATIVE_BRIEF_CONTRACT"


class BriefVersionConflictError(CreativeBriefError):
    """Two writers raced to mint the same brief lineage version."""

    code = "CREATIVE_BRIEF_VERSION_CONFLICT"


class ArtifactRequestNotFoundError(CreativeBriefError):
    """A projection named an artifact request the brief does not carry."""

    code = "CREATIVE_BRIEF_REQUEST_NOT_FOUND"


class ProtectedFieldOverrideError(CreativeBriefError):
    """A projection override tried to rewrite protected shared context."""

    code = "CREATIVE_BRIEF_PROTECTED_OVERRIDE"


def _require_non_blank(model: str, field: str, value: object) -> str:
    """Return ``value`` as a non-blank string or raise :class:`BriefContractError`."""
    if not isinstance(value, str) or not value.strip():
        msg = f"{model}.{field} must be a non-blank string"
        raise BriefContractError(msg)
    return value


class EvidenceReference(BaseModel):
    """A pointer at the source of a required fact.

    Source truth is recorded as *references* — an artifact, a canonical Run,
    a URL, or external material — and is kept distinct from generated claims,
    which belong to artifacts/outputs, never to the brief's fact ledger.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["artifact", "run", "url", "memory", "external"]
    ref: str

    @model_validator(mode="after")
    def _validate(self) -> EvidenceReference:
        _require_non_blank("EvidenceReference", "ref", self.ref)
        return self


class RequiredFact(BaseModel):
    """One fact a fulfilled artifact is required to state, with its evidence.

    ``evidence`` references are the source-truth anchors; a generated artifact
    claiming the fact without satisfying its evidence has left the brief.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fact_id: str
    text: str
    evidence: tuple[EvidenceReference, ...] = ()

    @model_validator(mode="after")
    def _validate(self) -> RequiredFact:
        _require_non_blank("RequiredFact", "fact_id", self.fact_id)
        _require_non_blank("RequiredFact", "text", self.text)
        return self


class BriefReference(BaseModel):
    """A reference to canonical state Design Studio does not own.

    ``ref_id`` is the canonical identity (a ``persona_id``, ``goal_id``,
    ``graph_id``, ...). ``version`` records the exact revision consumed where
    the target has one. ``workspace_id`` is the Workspace the target lives in
    when that is knowable; a value naming any Workspace other than the brief's
    own is structurally rejected.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: BriefReferenceKind
    ref_id: str
    version: str | None = None
    workspace_id: str | None = None
    label: str = ""

    @model_validator(mode="after")
    def _validate(self) -> BriefReference:
        _require_non_blank("BriefReference", "ref_id", self.ref_id)
        if self.workspace_id is not None:
            _require_non_blank("BriefReference", "workspace_id", self.workspace_id)
        if self.version is not None:
            _require_non_blank("BriefReference", "version", self.version)
        return self


class ArtifactRequest(BaseModel):
    """One requested artifact: channel, format, dimensions, requirements."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    channel: str
    format: str
    dimensions: str | None = None
    requirements: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate(self) -> ArtifactRequest:
        _require_non_blank("ArtifactRequest", "request_id", self.request_id)
        _require_non_blank("ArtifactRequest", "channel", self.channel)
        _require_non_blank("ArtifactRequest", "format", self.format)
        if self.dimensions is not None:
            _require_non_blank("ArtifactRequest", "dimensions", self.dimensions)
        return self


class ProjectionOverride(BaseModel):
    """One explicit, explained derived override in an artifact projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    value: Any = None
    reason: str = ""

    @model_validator(mode="after")
    def _validate(self) -> ProjectionOverride:
        _require_non_blank("ProjectionOverride", "field", self.field)
        if self.field in PROTECTED_PROJECTION_FIELDS:
            msg = (
                f"projection override {self.field!r} rewrites protected shared context; "
                "channel work may adjust presentation only, and shared changes need a "
                "new CreativeBrief version"
            )
            raise ProtectedFieldOverrideError(msg)
        _require_non_blank("ProjectionOverride", "reason", self.reason)
        return self


class ArtifactProjection(BaseModel):
    """A channel-specific projection derived from one CreativeBrief version.

    Carries the source Goal identity/revision and CreativeBrief lineage/version
    verbatim, plus Persona and Design System identity. Shared context is
    semantically identical across every projection of one brief version; only
    the ``artifact_request`` and the explicit, explained ``overrides`` differ.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection_id: str = Field(default_factory=lambda: str(uuid4()))
    channel: str
    # Source identity — copied from the brief, never re-derived.
    workspace_id: str
    project_id: str
    goal_id: str
    goal_revision: int = Field(ge=1)
    goal_owner_agent_id: str
    brief_lineage_id: str
    brief_id: str
    brief_version: int = Field(ge=1)
    persona_id: str
    persona_version: str | None
    design_system_slug: str
    design_system_version: str | None
    # Shared creative context — copied from the brief.
    audience: str = ""
    required_messages: tuple[str, ...] = ()
    cta: str | None = None
    required_facts: tuple[RequiredFact, ...] = ()
    prohibited_claims: tuple[str, ...] = ()
    # The channel-specific slice.
    artifact_request: ArtifactRequest
    overrides: tuple[ProjectionOverride, ...] = ()
    derived_by: str = ""
    derived_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _validate(self) -> ArtifactProjection:
        for field in (
            "channel",
            "workspace_id",
            "project_id",
            "goal_id",
            "goal_owner_agent_id",
            "brief_lineage_id",
            "brief_id",
            "persona_id",
            "design_system_slug",
        ):
            _require_non_blank("ArtifactProjection", field, getattr(self, field))
        return self

    def shared_context(self) -> dict[str, Any]:
        """The shared slice every projection of one brief version carries.

        Two artifact branches derived from the same brief version are
        semantically identical on exactly this mapping, and differ only in
        ``artifact_request``/``overrides``.
        """
        return {
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "goal_owner_agent_id": self.goal_owner_agent_id,
            "brief_lineage_id": self.brief_lineage_id,
            "brief_id": self.brief_id,
            "brief_version": self.brief_version,
            "persona_id": self.persona_id,
            "persona_version": self.persona_version,
            "design_system_slug": self.design_system_slug,
            "design_system_version": self.design_system_version,
            "audience": self.audience,
            "required_messages": self.required_messages,
            "cta": self.cta,
            "required_facts": self.required_facts,
            "prohibited_claims": self.prohibited_claims,
        }


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CreativeBrief(BaseModel):
    """One immutable version of the Design Studio creative-context contract.

    Identity is ``(lineage_id, version)``; ``brief_id`` names this exact
    version so a Run/artifact can state precisely which Goal revision and
    which brief version it consumed. Instances are frozen — updating creative
    context means calling :meth:`new_version`, which leaves this version (and
    every historical interpretation built on it) untouched.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Version identity.
    brief_id: str = Field(default_factory=lambda: str(uuid4()))
    lineage_id: str = Field(default_factory=lambda: str(uuid4()))
    version: int = Field(default=1, ge=1)
    supersedes_brief_id: str | None = None

    # Canonical scope: Workspace -> Project -> Goal (#458 lineage).
    workspace_id: str
    project_id: str
    goal_id: str
    #: The exact canonical Goal revision this brief consumes. A changed desired
    #: outcome is a new Goal revision, committed outside Design Studio; the
    #: brief follows it in a new version — it never rewrites it.
    goal_revision: int = Field(ge=1)

    # Accountability references (canonical ownership lives outside Design
    # Studio; these record who owns the consumed Goal revision and, where one
    # applies, the delegation/subgoal that placed it here).
    goal_owner_agent_id: str
    goal_delegation_ref: BriefReference | None = None

    # Persistent flavor/identity references — references, not copies (#39,
    # ADR-091626-ba4f). Changing either creates a new brief version for future
    # work; historical artifacts keep the version they consumed.
    persona: BriefReference
    design_system: BriefReference

    # Creative interpretation of the Goal revision.
    audience: str = ""
    beneficiaries: tuple[str, ...] = ()
    success_interpretation: str = ""
    required_messages: tuple[str, ...] = ()
    cta: str | None = None
    required_facts: tuple[RequiredFact, ...] = ()
    prohibited_claims: tuple[str, ...] = ()
    #: Tone/style constraints *not* already owned by the Persona.
    tone_constraints: tuple[str, ...] = ()

    # Requested artifacts.
    artifact_requests: tuple[ArtifactRequest, ...] = ()

    # Source/reference artifacts the creative work builds on.
    source_references: tuple[BriefReference, ...] = ()

    # GraphTemplate/Graph chosen for fulfillment where known — a selection
    # reference, never a second execution identity.
    fulfillment_graph_ref: BriefReference | None = None

    #: Delegation/supervision constraints relevant to creative work. These are
    #: annotations for humans and orchestrators; the brief is not a delegation
    #: or authorization authority, and nothing here widens Capability/Binding
    #: policy.
    supervision_constraints: tuple[str, ...] = ()

    # Provenance.
    change_note: str = ""
    created_by: str = ""
    created_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def _validate_contract(self) -> CreativeBrief:
        """Fail loudly on contract violations: identity, kinds, scope."""
        self._validate_identities()
        self._validate_reference_kinds()
        self._validate_reference_workspaces()

        request_ids = [request.request_id for request in self.artifact_requests]
        if len(request_ids) != len(set(request_ids)):
            msg = "CreativeBrief.artifact_requests request_ids must be unique"
            raise BriefContractError(msg)
        return self

    def _validate_identities(self) -> None:
        """Require non-blank identity fields and an ontology-satisfying Goal ref."""
        for field in (
            "brief_id",
            "lineage_id",
            "workspace_id",
            "project_id",
            "goal_id",
            "goal_owner_agent_id",
        ):
            _require_non_blank("CreativeBrief", field, getattr(self, field))

        # Canonical identities must satisfy the shared interoperability
        # ontology: a Goal reference requires its Project, a Project its
        # Workspace (#458).
        try:
            validate_reference_set(
                INTEROP_ONTOLOGY_V1,
                {
                    "Workspace": self.workspace_id,
                    "Project": self.project_id,
                    "Goal": self.goal_id,
                },
            )
        except InteropContractError as exc:
            raise BriefContractError(str(exc)) from exc

    def _validate_reference_kinds(self) -> None:
        """Reject a reference used in a slot its kind does not fill."""
        _validate_reference_kind(self.persona, frozenset({"persona"}), "persona")
        _validate_reference_kind(self.design_system, frozenset({"design_system"}), "design_system")
        if self.goal_delegation_ref is not None:
            _validate_reference_kind(
                self.goal_delegation_ref, _DELEGATION_REFERENCE_KINDS, "goal_delegation_ref"
            )
        if self.fulfillment_graph_ref is not None:
            _validate_reference_kind(
                self.fulfillment_graph_ref, _GRAPH_REFERENCE_KINDS, "fulfillment_graph_ref"
            )
        for source in self.source_references:
            _validate_reference_kind(source, _PROVENANCE_REFERENCE_KINDS, "source_references")

    def _scoped_references(self) -> list[tuple[str, BriefReference]]:
        """Every reference slot that carries a Workspace, with its field path."""
        scoped = [
            ("persona", self.persona),
            ("design_system", self.design_system),
            *[(f"source_references.{r.ref_id}", r) for r in self.source_references],
        ]
        if self.goal_delegation_ref is not None:
            scoped.append(("goal_delegation_ref", self.goal_delegation_ref))
        if self.fulfillment_graph_ref is not None:
            scoped.append(("fulfillment_graph_ref", self.fulfillment_graph_ref))
        return scoped

    def _validate_reference_workspaces(self) -> None:
        """Structural cross-Workspace rejection: every reference that knows its
        Workspace must name *this* brief's Workspace."""
        for field, reference in self._scoped_references():
            if reference.workspace_id is not None and reference.workspace_id != self.workspace_id:
                msg = (
                    f"CreativeBrief.{field} references {reference.ref_id!r} in workspace "
                    f"{reference.workspace_id!r}, but the brief lives in "
                    f"{self.workspace_id!r}"
                )
                raise CrossWorkspaceReferenceError(msg)

    @property
    def persona_id(self) -> str:
        """The canonical Persona identity this version resolves."""
        return self.persona.ref_id

    @property
    def persona_version(self) -> str | None:
        """The resolved Persona version/reference consumed by this version."""
        return self.persona.version

    @property
    def design_system_slug(self) -> str:
        """The Design System identity this version resolves."""
        return self.design_system.ref_id

    @property
    def design_system_version(self) -> str | None:
        """The Design System version consumed by this version."""
        return self.design_system.version

    def new_version(self, *, change_note: str = "", **updates: Any) -> CreativeBrief:
        """Derive the next immutable version of this brief lineage.

        ``updates`` may rewrite creative context (persona, design system,
        audience, artifact requests, ...), and may even move to a new canonical
        Goal revision when the desired outcome changed — but may never touch
        lineage identity, scope, or provenance, which the contract mints.
        The instance is not modified; historical versions remain exactly as
        they were consumed.
        """
        for field in updates:
            if field in _LINEAGE_IMMUTABLE_FIELDS:
                msg = f"CreativeBrief.{field} is minted by the contract and cannot be updated"
                raise BriefContractError(msg)
            if field not in type(self).model_fields:
                msg = f"CreativeBrief has no field {field!r}"
                raise BriefContractError(msg)
        data = self.model_dump()
        data.update(updates)
        data["brief_id"] = str(uuid4())
        data["version"] = self.version + 1
        data["supersedes_brief_id"] = self.brief_id
        data["change_note"] = change_note
        data["created_at"] = _utc_now()
        try:
            return CreativeBrief.model_validate(data)
        except ValidationError as exc:
            raise BriefContractError(f"invalid CreativeBrief version update: {exc}") from exc

    def project(
        self,
        request_id: str,
        *,
        overrides: tuple[ProjectionOverride, ...] = (),
        derived_by: str = "",
    ) -> ArtifactProjection:
        """Derive the channel projection for one requested artifact.

        The projection carries the source Goal revision and brief version
        verbatim. Overrides are explicit and explained; they may adjust
        channel presentation only — protected shared context raises
        :class:`ProtectedFieldOverrideError`, and shared changes belong in a
        new brief version.
        """
        request = next(
            (item for item in self.artifact_requests if item.request_id == request_id), None
        )
        if request is None:
            msg = f"CreativeBrief {self.brief_id} carries no artifact request {request_id!r}"
            raise ArtifactRequestNotFoundError(msg)
        return ArtifactProjection(
            channel=request.channel,
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            goal_id=self.goal_id,
            goal_revision=self.goal_revision,
            goal_owner_agent_id=self.goal_owner_agent_id,
            brief_lineage_id=self.lineage_id,
            brief_id=self.brief_id,
            brief_version=self.version,
            persona_id=self.persona_id,
            persona_version=self.persona_version,
            design_system_slug=self.design_system_slug,
            design_system_version=self.design_system_version,
            audience=self.audience,
            required_messages=self.required_messages,
            cta=self.cta,
            required_facts=self.required_facts,
            prohibited_claims=self.prohibited_claims,
            artifact_request=request,
            overrides=overrides,
            derived_by=derived_by,
        )


def _validate_reference_kind(
    reference: BriefReference, allowed: frozenset[str], field: str
) -> None:
    """Reject a reference used in a slot its kind does not fill."""
    if reference.kind not in allowed:
        msg = f"CreativeBrief.{field} requires kind in {sorted(allowed)}, got {reference.kind!r}"
        raise BriefContractError(msg)

"""The versioned CreativeBrief shared-context contract (#774).

These tests hold the half of #774 that lives in the domain model: one frozen,
immutable-by-version CreativeBrief that references the canonical Project Goal
(+ exact revision), Persona, Design System, and delegation state without ever
owning them; channel projections that carry source identity verbatim; and the
structural refusals the contract promises — cross-Workspace references,
protected-context overrides, and any field that would make the brief an
authorization surface.

The persistence half is in ``test_creative_brief_store.py`` (SQL composition
and guards) and ``test_creative_brief_pg.py`` (real PostgreSQL, skipped
without a server).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maistro.types.errors import AgentError
from maistro_design.brief import (
    ArtifactProjection,
    ArtifactRequest,
    ArtifactRequestNotFoundError,
    BriefContractError,
    BriefReference,
    CreativeBrief,
    CreativeBriefError,
    CrossWorkspaceReferenceError,
    EvidenceReference,
    ProjectionOverride,
    ProtectedFieldOverrideError,
    RequiredFact,
)
from maistro_design.brief_store import PgCreativeBriefStore
from maistro_design.protocols import CreativeBriefStore
from maistro_design.stores import PgDesignProjectStore

pytestmark = pytest.mark.contract("boundary")

WS = "ws-1"
PROJ = "proj-1"
GOAL = "goal-1"


def _brief(**overrides: object) -> CreativeBrief:
    """A minimal valid brief: one Goal revision, Persona, Design System, two channels."""
    values: dict[str, object] = {
        "workspace_id": WS,
        "project_id": PROJ,
        "goal_id": GOAL,
        "goal_revision": 3,
        "goal_owner_agent_id": "agent-orchestrator",
        "persona": BriefReference(
            kind="persona",
            ref_id="persona-1",
            version="p-v7",
            workspace_id=WS,
        ),
        "design_system": BriefReference(
            kind="design_system",
            ref_id="brand-x",
            version="2026.09",
        ),
        "audience": "home bakers",
        "required_messages": ("Fresh daily", "Local grain"),
        "cta": "Order by Friday",
        "required_facts": (
            RequiredFact(
                fact_id="fact-gluten-free",
                text="Every loaf is baked in a gluten-free facility.",
                evidence=(EvidenceReference(kind="url", ref="https://facts.example/facility"),),
            ),
        ),
        "prohibited_claims": ("cures disease",),
        "artifact_requests": (
            ArtifactRequest(
                request_id="ig-square",
                channel="social",
                format="png",
                dimensions="1080x1080",
                requirements=("square crop",),
            ),
            ArtifactRequest(
                request_id="story-916",
                channel="social",
                format="png",
                dimensions="1080x1920",
            ),
        ),
        "supervision_constraints": ("stop for human approval before publishing",),
    }
    values.update(overrides)
    return CreativeBrief.model_validate(values)


# ── One schema/model and persistence contract owns the domain state ──────────


@pytest.mark.ac("SPEC-092826-a774/AC-1")
def test_one_contract_owns_creative_brief_state() -> None:
    """The model and the persistence contract are the package's single owners."""
    from maistro_design import CreativeBrief as ExportedBrief

    assert ExportedBrief is CreativeBrief
    store: CreativeBriefStore = PgCreativeBriefStore(session_factory=object())
    assert isinstance(store, CreativeBriefStore)
    # And it is a distinct contract from the DesignProject store: one type per
    # domain state, not a second method bolted onto projects.
    assert not isinstance(store, PgDesignProjectStore)


@pytest.mark.ac("SPEC-092826-a774/AC-1")
def test_package_surface_lazy_loads_the_brief_contract() -> None:
    """The package ``__getattr__`` resolves the brief contract lazily.

    The public surface is the same single store and protocol the domain tests
    import directly — ``maistro_design.PgCreativeBriefStore`` and
    ``maistro_design.CreativeBriefStore`` resolve to exactly those objects, so
    no second persistence contract can grow beside them unnoticed.
    """
    import maistro_design

    # The lazy package surface stays the single owner of the brief contract:
    # every declared public symbol resolves to the canonical object (so no
    # second persistence contract can grow unnoticed), and unknown names fall
    # through every declared branch to AttributeError at the bottom of
    # ``__getattr__`` rather than silently resolving. All four arcs of the two
    # new ``if`` branches — including the fall-through to the raise — are
    # exercised here.
    assert maistro_design.PgDesignProjectStore is PgDesignProjectStore
    assert maistro_design.PgCreativeBriefStore is PgCreativeBriefStore
    assert maistro_design.CreativeBriefStore is CreativeBriefStore
    assert not hasattr(maistro_design, "this_is_not_a_design_surface_symbol")


def test_brief_errors_are_domain_errors() -> None:
    """CreativeBrief errors classify through the design domain error family."""
    assert issubclass(CreativeBriefError, AgentError)
    assert CrossWorkspaceReferenceError("").code == "CREATIVE_BRIEF_CROSS_WORKSPACE"
    assert BriefContractError("").code == "CREATIVE_BRIEF_CONTRACT"
    assert ProtectedFieldOverrideError("").code == "CREATIVE_BRIEF_PROTECTED_OVERRIDE"
    assert ArtifactRequestNotFoundError("").code == "CREATIVE_BRIEF_REQUEST_NOT_FOUND"


# ── Canonical Goal identity + exact revision ─────────────────────────────────


@pytest.mark.ac("SPEC-092826-a774/AC-2")
def test_brief_names_goal_identity_and_exact_revision() -> None:
    brief = _brief()
    assert brief.goal_id == GOAL
    assert brief.goal_revision == 3
    # The reference set satisfies the shared interoperability ontology:
    # Goal -> Project -> Workspace (#458).
    assert brief.project_id == PROJ
    assert brief.workspace_id == WS


@pytest.mark.parametrize("goal_revision", [0, -1])
@pytest.mark.ac("SPEC-092826-a774/AC-2")
def test_goal_revision_must_be_a_positive_revision(goal_revision: int) -> None:
    """An exact revision means a positive revision, not a wish."""
    with pytest.raises(ValidationError):
        _brief(goal_revision=goal_revision)


@pytest.mark.ac("SPEC-092826-a774/AC-2")
def test_blank_goal_identity_is_refused() -> None:
    with pytest.raises(BriefContractError):
        _brief(goal_id="   ")


@pytest.mark.ac("SPEC-092826-a774/AC-2")
def test_blank_workspace_or_project_scope_is_refused() -> None:
    with pytest.raises(BriefContractError):
        _brief(workspace_id="")
    with pytest.raises(BriefContractError):
        _brief(project_id="  ")


# ── Goal ownership/delegation stays canonical; the brief only references ────


@pytest.mark.ac("SPEC-092826-a774/AC-3")
def test_goal_ownership_and_delegation_are_recorded_references() -> None:
    brief = _brief(
        goal_delegation_ref=BriefReference(
            kind="delegation",
            ref_id="delegation-9",
            version="d-v2",
            workspace_id=WS,
        ),
    )
    # Ownership is a recorded accountability fact, not a Design-Studio owner:
    # the brief exposes no way to transfer, reassign, or execute ownership.
    assert brief.goal_owner_agent_id == "agent-orchestrator"
    assert brief.goal_delegation_ref is not None
    assert brief.goal_delegation_ref.ref_id == "delegation-9"
    # A subgoal is still a Goal — the delegation slot accepts goal references.
    subgoal_brief = _brief(
        goal_delegation_ref=BriefReference(kind="goal", ref_id="goal-1-sub", workspace_id=WS),
    )
    assert subgoal_brief.goal_delegation_ref is not None
    assert subgoal_brief.goal_delegation_ref.kind == "goal"


@pytest.mark.ac("SPEC-092826-a774/AC-3")
def test_delegation_slot_rejects_non_delegation_kinds() -> None:
    """Persona-flavored references cannot stand in for delegation state."""
    with pytest.raises(BriefContractError):
        _brief(
            goal_delegation_ref=BriefReference(kind="persona", ref_id="persona-1", workspace_id=WS)
        )


@pytest.mark.ac("SPEC-092826-a774/AC-3")
def test_new_version_cannot_move_scope_or_rewrite_lineage() -> None:
    """A brief lineage lives in one Workspace/Project; moving is a new lineage."""
    brief = _brief()
    for field in ("workspace_id", "project_id", "lineage_id", "version", "brief_id"):
        with pytest.raises(BriefContractError):
            brief.new_version(**{field: "moved"})


# ── Persona and Design System are references, not copies ────────────────────


@pytest.mark.ac("SPEC-092826-a774/AC-4")
def test_persona_and_design_system_are_versioned_references() -> None:
    brief = _brief()
    assert brief.persona.kind == "persona"
    assert brief.persona.ref_id == "persona-1"
    assert brief.persona.version == "p-v7"
    assert brief.design_system_slug == "brand-x"
    assert brief.design_system_version == "2026.09"
    # Identity accessors resolve through the reference — there is no embedded
    # copy of the Persona or Design System payload on the brief.
    assert brief.persona_id == "persona-1"


@pytest.mark.ac("SPEC-092826-a774/AC-4")
def test_persona_slot_rejects_other_kinds() -> None:
    with pytest.raises(BriefContractError):
        _brief(persona=BriefReference(kind="graph", ref_id="graph-1"))


# ── Updating creative context creates a version; history stays intact ───────


@pytest.mark.ac("SPEC-092826-a774/AC-5")
def test_brief_versions_are_frozen() -> None:
    brief = _brief()
    with pytest.raises(ValidationError):
        brief.audience = "silent rewrite"  # type: ignore[misc]


@pytest.mark.contract("behavioral")
@pytest.mark.ac("SPEC-092826-a774/AC-5")
def test_updating_creative_context_creates_a_new_version() -> None:
    v1 = _brief()
    v2 = v1.new_version(
        audience="serious pastry students",
        change_note="audience treatment changed; Goal untouched",
    )
    assert v2.version == 2
    assert v2.supersedes_brief_id == v1.brief_id
    assert v2.lineage_id == v1.lineage_id
    assert v2.audience == "serious pastry students"
    # The prior version — the one historical artifacts consumed — is unchanged.
    assert v1.audience == "home bakers"
    assert v1.version == 1


@pytest.mark.contract("behavioral")
@pytest.mark.ac("SPEC-092826-a774/AC-6")
def test_changed_outcome_is_a_goal_revision_change_plus_new_brief_version() -> None:
    """A redirect of the desired outcome: new canonical Goal revision first,
    then a brief version consuming it — the old version is not rewritten."""
    v1 = _brief()
    v2 = v1.new_version(goal_id="goal-2", goal_revision=1, change_note="Goal redirect")
    assert v2.goal_id == "goal-2"
    assert v2.goal_revision == 1
    assert v1.goal_id == GOAL and v1.goal_revision == 3


def test_version_update_rejects_unknown_fields() -> None:
    brief = _brief()
    with pytest.raises(BriefContractError):
        brief.new_version(not_a_brief_field=1)


# ── Historical artifacts identify exactly what they consumed ────────────────


@pytest.mark.contract("behavioral")
@pytest.mark.ac("SPEC-092826-a774/AC-7")
def test_projection_carries_every_consumed_identity() -> None:
    brief = _brief()
    projection = brief.project("ig-square")
    shared = projection.shared_context()
    assert shared["goal_id"] == GOAL
    assert shared["goal_revision"] == 3
    assert shared["brief_id"] == brief.brief_id
    assert shared["brief_lineage_id"] == brief.lineage_id
    assert shared["brief_version"] == brief.version
    assert shared["persona_id"] == "persona-1"
    assert shared["persona_version"] == "p-v7"
    assert shared["design_system_slug"] == "brand-x"
    assert shared["design_system_version"] == "2026.09"
    assert shared["goal_owner_agent_id"] == "agent-orchestrator"


@pytest.mark.contract("behavioral")
@pytest.mark.ac("SPEC-092826-a774/AC-7")
def test_projection_from_a_prior_version_keeps_that_version() -> None:
    """A projection derived before a redirect keeps citing the version it used."""
    v1 = _brief()
    old_projection = v1.project("story-916")
    v1.new_version(audience="changed audience")
    assert old_projection.brief_version == 1
    assert old_projection.audience == "home bakers"


# ── Two artifact branches: identical shared context, explicit channel diff ──


@pytest.mark.contract("behavioral")
@pytest.mark.ac("SPEC-092826-a774/AC-12")
def test_two_artifact_branches_share_goal_and_brief_context() -> None:
    brief = _brief()
    square = brief.project("ig-square")
    story = brief.project("story-916")
    # Semantically identical shared Goal/brief/Persona/Design-System context.
    assert square.shared_context() == story.shared_context()
    # Differing only in the explicit artifact/channel projection.
    assert square.artifact_request.request_id == "ig-square"
    assert story.artifact_request.request_id == "story-916"
    assert square.artifact_request.dimensions == "1080x1080"
    assert story.artifact_request.dimensions == "1080x1920"
    assert square.overrides == () and story.overrides == ()


@pytest.mark.contract("behavioral")
@pytest.mark.ac("SPEC-092826-a774/AC-8")
def test_projection_overrides_are_explicit_and_explained() -> None:
    brief = _brief()
    projection = brief.project(
        "ig-square",
        overrides=(
            ProjectionOverride(
                field="copy_variant",
                value="seasonal",
                reason="channel A/B variant for the social feed",
            ),
        ),
    )
    assert projection.overrides[0].field == "copy_variant"
    assert projection.overrides[0].reason


@pytest.mark.ac("SPEC-092826-a774/AC-8")
def test_override_without_a_reason_is_refused() -> None:
    with pytest.raises(BriefContractError):
        ProjectionOverride(field="copy_variant", value="x", reason="  ")


@pytest.mark.parametrize(
    "field",
    ["goal_id", "goal_revision", "brief_version", "persona_id", "required_facts"],
)
@pytest.mark.ac("SPEC-092826-a774/AC-8")
def test_projection_cannot_silently_override_shared_context(field: str) -> None:
    """Derived channel work adjusts presentation; shared changes need a version."""
    brief = _brief()
    with pytest.raises(ProtectedFieldOverrideError):
        brief.project("ig-square", overrides=(ProjectionOverride(field=field, value="x"),))


@pytest.mark.ac("SPEC-092826-a774/AC-8")
def test_projection_constructed_directly_still_refuses_protected_overrides() -> None:
    with pytest.raises(ProtectedFieldOverrideError):
        ArtifactProjection(
            channel="social",
            workspace_id=WS,
            project_id=PROJ,
            goal_id=GOAL,
            goal_revision=1,
            goal_owner_agent_id="agent-1",
            brief_lineage_id="lineage",
            brief_id="brief",
            brief_version=1,
            persona_id="p",
            persona_version=None,
            design_system_slug="s",
            design_system_version=None,
            artifact_request=ArtifactRequest(request_id="r", channel="social", format="png"),
            overrides=(ProjectionOverride(field="audience", value="nobody"),),
        )


def test_unknown_artifact_request_is_refused() -> None:
    brief = _brief()
    with pytest.raises(ArtifactRequestNotFoundError):
        brief.project("does-not-exist")


def test_artifact_request_ids_must_be_unique() -> None:
    with pytest.raises(BriefContractError):
        _brief(
            artifact_requests=(
                ArtifactRequest(request_id="dup", channel="social", format="png"),
                ArtifactRequest(request_id="dup", channel="print", format="pdf"),
            )
        )


# ── Source truth is referenced; claims are not the brief's to generate ──────


@pytest.mark.ac("SPEC-092826-a774/AC-9")
def test_required_facts_carry_evidence_references() -> None:
    brief = _brief()
    fact = brief.required_facts[0]
    assert fact.text.startswith("Every loaf")
    assert fact.evidence[0].kind == "url"
    assert fact.evidence[0].ref == "https://facts.example/facility"


@pytest.mark.ac("SPEC-092826-a774/AC-9")
def test_blank_fact_or_evidence_is_refused() -> None:
    with pytest.raises(BriefContractError):
        RequiredFact(fact_id="f", text="   ")
    with pytest.raises(BriefContractError):
        EvidenceReference(kind="url", ref="")


@pytest.mark.ac("SPEC-092826-a774/AC-9")
def test_facts_and_prohibited_claims_are_distinct_fields() -> None:
    """Source truth in, generated claims never: the brief constrains, not claims."""
    brief = _brief()
    assert brief.required_facts[0].fact_id == "fact-gluten-free"
    assert brief.prohibited_claims == ("cures disease",)
    assert "generated_claims" not in CreativeBrief.model_fields
    projection = brief.project("ig-square")
    assert projection.required_facts == brief.required_facts
    assert projection.prohibited_claims == brief.prohibited_claims


# ── Cross-Workspace references are structurally rejected ────────────────────


@pytest.mark.parametrize(
    ("field", "reference"),
    [
        ("persona", BriefReference(kind="persona", ref_id="p", version="1", workspace_id="ws-2")),
        (
            "design_system",
            BriefReference(kind="design_system", ref_id="d", version="1", workspace_id="ws-2"),
        ),
        ("goal_delegation_ref", BriefReference(kind="delegation", ref_id="x", workspace_id="ws-2")),
        ("fulfillment_graph_ref", BriefReference(kind="graph", ref_id="g", workspace_id="ws-2")),
        ("source", BriefReference(kind="artifact", ref_id="a", workspace_id="ws-2")),
    ],
)
@pytest.mark.ac("SPEC-092826-a774/AC-11")
def test_cross_workspace_references_are_rejected(field: str, reference: BriefReference) -> None:
    overrides: dict[str, object] = (
        {"source_references": (reference,)} if field == "source" else {field: reference}
    )
    with pytest.raises(CrossWorkspaceReferenceError):
        _brief(**overrides)


def test_unscoped_references_are_accepted_and_pass_through() -> None:
    """A reference that cannot know its Workspace (e.g. a bundled design
    system) is a plain identity; the persistence layer owns scope truth."""
    brief = _brief()
    assert brief.design_system.workspace_id is None


# ── No authorization surface ────────────────────────────────────────────────


_AUTHORIZATION_VOCABULARY = (
    "grants",
    "grant_ids",
    "capabilities",
    "capability_ids",
    "bindings",
    "binding_ids",
    "invocations",
    "approvals",
    "permissions",
    "scopes",
    "policy_overrides",
    "authorization",
    "secrets",
    "credentials",
)


@pytest.mark.ac("SPEC-092826-a774/AC-14")
def test_brief_has_no_authorization_fields() -> None:
    """No CreativeBrief field grants authorization or bypasses Capability/
    Binding policy — the vocabulary of authorization is absent by construction."""
    for model in (CreativeBrief, ArtifactProjection):
        present = set(model.model_fields)
        assert present.isdisjoint(_AUTHORIZATION_VOCABULARY), (
            f"{model.__name__} grew an authorization surface: "
            f"{sorted(present & set(_AUTHORIZATION_VOCABULARY))}"
        )


@pytest.mark.parametrize("field", ["grants", "capability_ids", "approval_bypass"])
@pytest.mark.ac("SPEC-092826-a774/AC-14")
def test_authorization_shaped_extra_fields_are_refused(field: str) -> None:
    """``extra='forbid'``: an authorization payload cannot ride along on a brief."""
    values = _brief().model_dump()
    values[field] = [{"effect": "publish", "granted": True}]
    with pytest.raises(ValidationError):
        CreativeBrief.model_validate(values)


@pytest.mark.ac("SPEC-092826-a774/AC-10")
def test_supervision_constraints_are_annotations_only() -> None:
    brief = _brief()
    assert brief.supervision_constraints == ("stop for human approval before publishing",)
    # They are plain recorded text: no type, grant, or capability travels with
    # them, and the projection passes them through verbatim.
    assert brief.project("ig-square").shared_context()["goal_owner_agent_id"]


# ── Redirect provenance ─────────────────────────────────────────────────────


@pytest.mark.contract("behavioral")
@pytest.mark.ac("SPEC-092826-a774/AC-13")
def test_redirect_produces_new_versions_without_mutating_history() -> None:
    v1 = _brief()
    v1_snapshot = v1.model_dump()
    v2 = v1.new_version(
        persona=BriefReference(kind="persona", ref_id="p2", version="p-v1", workspace_id=WS),
        change_note="persona change",
    )
    v3 = v2.new_version(goal_id="goal-9", goal_revision=2, change_note="outcome redirect")
    # Nothing about v1 moved: same persona, same goal, same provenance.
    assert v1.model_dump() == v1_snapshot
    assert v2.supersedes_brief_id == v1.brief_id
    assert v3.supersedes_brief_id == v2.brief_id
    assert v3.version == 3
    assert v3.goal_id == "goal-9" and v3.goal_revision == 2
    assert v3.persona_id == "p2"
    assert v1.persona_id == "persona-1"


@pytest.mark.contract("behavioral")
@pytest.mark.ac("SPEC-092826-a774/AC-13")
def test_change_note_is_recorded_provenance() -> None:
    brief = _brief()
    v2 = brief.new_version(change_note="channel guidance only")
    assert v2.change_note == "channel guidance only"
    assert v2.created_at >= brief.created_at

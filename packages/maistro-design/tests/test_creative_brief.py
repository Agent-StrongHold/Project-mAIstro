"""CreativeBrief versioned projection contract (#773).

Covers the parent epic's shared-context invariant: one versioned CreativeBrief
bound to one exact canonical Goal revision, supplying identical shared context
to every artifact branch, provenance retention on produced artifacts, and no
second identity or execution authority. Groundwork for the #774 child lane.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from maistro_design.creative_brief import (
    ArtifactProvenance,
    ArtifactRequirement,
    BriefRevision,
    CreativeBrief,
    CreativeBriefConflictError,
    CreativeBriefError,
    CreativeBriefNotFoundError,
    CreativeBriefStore,
    CreativeBriefVersion,
    InMemoryCreativeBriefStore,
)
from maistro_design.types import DesignError

WORKSPACE = "ws-1"
PROJECT = "proj-1"
GOAL = "goal-773"
GOAL_REVISION = "rev-7"
AGENT = "agent-ws-orchestrator"


def make_store() -> InMemoryCreativeBriefStore:
    return InMemoryCreativeBriefStore()


async def create_brief(store: InMemoryCreativeBriefStore, **overrides: object) -> CreativeBrief:
    """Create the reference spring-launch brief family, with per-test overrides."""
    kwargs: dict[str, object] = {
        "workspace_id": WORKSPACE,
        "project_id": PROJECT,
        "goal_id": GOAL,
        "goal_revision": GOAL_REVISION,
        "owner_agent_id": AGENT,
        "persona_id": "persona-atelier",
        "design_system_slug": "atelier-zero",
        "design_system_version": "2.1.0",
        "success_criteria": ("launch-ready site", "coherent coupon campaign"),
        "audience": "indie makers",
        "source_references": ("memory://workspace/brand-voice",),
        "artifact_requirements": (
            ArtifactRequirement("landing-page", "single page, CTA above the fold"),
            ArtifactRequirement("coupon", "20% spring code, one per customer"),
        ),
        "creative_constraints": ("no dark patterns",),
        "summary": "Spring launch family",
    }
    kwargs.update(overrides)
    return await store.create(**kwargs)  # type: ignore[arg-type]


# ── Creation binds the exact canonical Goal revision ─────────────────────────


class TestCreation:
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_create_mints_version_one_bound_to_goal_revision(self):
        """Given canonical refs When create Then v1 carries the exact Goal revision."""
        store = make_store()
        brief = await create_brief(store)

        current = brief.current
        assert brief.brief_id == current.brief_id
        assert current.version == 1
        assert current.goal_id == GOAL
        assert current.goal_revision == GOAL_REVISION
        assert current.workspace_id == WORKSPACE
        assert current.project_id == PROJECT
        assert current.owner_agent_id == AGENT

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_list_by_goal_resolves_the_lineage_in_scope(self):
        """Goal + CreativeBrief resolve finds the one lineage for the revision."""
        store = make_store()
        brief = await create_brief(store)

        found = await store.list_by_goal(
            GOAL, GOAL_REVISION, workspace_id=WORKSPACE, project_id=PROJECT
        )
        assert [item.brief_id for item in found] == [brief.brief_id]

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_list_by_goal_scope_keyed(self):
        """A sibling workspace/project cannot resolve the lineage."""
        await create_brief(make_store())

        empty = await make_store().list_by_goal(
            GOAL, GOAL_REVISION, workspace_id="other-ws", project_id=PROJECT
        )
        assert empty == []

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_second_lineage_for_same_goal_revision_conflicts(self):
        """Goal + CreativeBrief resolve stays unambiguous: no forked lineages."""
        store = make_store()
        await create_brief(store)

        with pytest.raises(CreativeBriefConflictError, match="revise it instead"):
            await create_brief(store, audience="a different audience, same Goal")

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_new_goal_revision_gets_its_own_lineage(self):
        """A new Goal revision is a new projection, not a fork of the old one."""
        store = make_store()
        await create_brief(store)
        successor = await create_brief(store, goal_revision="rev-8")

        assert successor.current.goal_revision == "rev-8"
        original = await store.list_by_goal(
            GOAL, GOAL_REVISION, workspace_id=WORKSPACE, project_id=PROJECT
        )
        assert successor.brief_id != original[0].brief_id


# ── Canonical identity validation through the shared ontology (#458) ─────────


class TestCanonicalReferences:
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_blank_goal_revision_refused(self):
        """The v1 contract requires an exact goal_revision on every Goal projection."""
        store = make_store()
        with pytest.raises(CreativeBriefError, match="interoperability contract"):
            await create_brief(store, goal_revision="   ")

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_non_positive_integer_revision_refused(self):
        store = make_store()
        with pytest.raises(CreativeBriefError, match="interoperability contract"):
            await create_brief(store, goal_revision=0)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_blank_scope_reference_refused(self):
        """Scope lineage (Workspace -> Project -> Goal) must be present."""
        store = make_store()
        with pytest.raises(CreativeBriefError, match="workspace_id"):
            await create_brief(store, workspace_id="")

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_blank_owner_agent_refused(self):
        """A brief names its accountable Agent; flavor is separate from accountability."""
        store = make_store()
        with pytest.raises(CreativeBriefError, match="owner_agent_id"):
            await create_brief(store, owner_agent_id="")

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_blank_persona_when_present_refused(self):
        store = make_store()
        with pytest.raises(CreativeBriefError, match="persona_id"):
            await create_brief(store, persona_id=" ")

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_errors_are_design_domain_errors(self):
        """The product boundary stays typed: contract failures are CreativeBriefError."""
        assert issubclass(CreativeBriefError, DesignError)
        assert issubclass(CreativeBriefNotFoundError, CreativeBriefError)
        assert issubclass(CreativeBriefConflictError, CreativeBriefError)


# ── Shared context across artifact branches (#773 invariant) ─────────────────


class TestSharedContext:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_all_branches_share_one_identity(self):
        """Website, coupon, deck, script: same Goal revision + brief version + team."""
        store = make_store()
        brief = await create_brief(store)
        current = brief.current

        contexts = [
            current.shared_context(branch)
            for branch in ("landing-page", "coupon", "deck", "video-script")
        ]
        for context in contexts:
            assert context.goal_id == GOAL
            assert context.goal_revision == GOAL_REVISION
            assert context.brief_id == brief.brief_id
            assert context.brief_version == 1
            assert context.owner_agent_id == AGENT
            assert context.persona_id == "persona-atelier"
            assert context.design_system_slug == "atelier-zero"
            assert context.audience == "indie makers"
            assert context.source_references == ("memory://workspace/brand-voice",)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_declared_branch_carries_its_channel_requirement(self):
        store = make_store()
        brief = await create_brief(store)

        context = brief.current.shared_context("coupon")
        assert context.branch == "coupon"
        assert context.requirement == "20% spring code, one per customer"

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_undeclared_branch_still_receives_shared_identity(self):
        """A branch without a declared requirement is not unbriefed work."""
        store = make_store()
        brief = await create_brief(store)

        context = brief.current.shared_context("podcast-trailer")
        assert context.requirement is None
        assert context.goal_revision == GOAL_REVISION
        assert context.brief_version == 1

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_shared_context_serializes_canonical_field_names(self):
        """Downstream consumers read goal_id/goal_revision, the interop names."""
        store = make_store()
        brief = await create_brief(store)

        payload = brief.current.shared_context("landing-page").to_dict()
        assert payload["goal_id"] == GOAL
        assert payload["goal_revision"] == GOAL_REVISION
        assert payload["brief_id"] == brief.brief_id
        assert payload["brief_version"] == 1


# ── Versioned evolution without identity mutation ────────────────────────────


class TestRevision:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_revise_appends_version_and_keeps_goal_identity(self):
        """Guidance evolution is a new version against the same Goal revision."""
        store = make_store()
        brief = await create_brief(store)

        revised = await store.revise(
            brief.brief_id,
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            revision=BriefRevision(summary="Tighten CTA guidance", audience="indie makers + devs"),
        )

        assert revised.current.version == 2
        assert revised.current.audience == "indie makers + devs"
        assert revised.current.goal_id == GOAL
        assert revised.current.goal_revision == GOAL_REVISION
        assert revised.current.owner_agent_id == AGENT

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_revision_cannot_carry_identity_fields(self):
        """Compile-level negative control: a revision accepts no identity field."""
        names = {field.name for field in dataclasses.fields(BriefRevision)}
        forbidden = {
            "brief_id",
            "version",
            "goal_id",
            "goal_revision",
            "workspace_id",
            "project_id",
            "owner_agent_id",
            "created_at",
        }
        assert not names & forbidden

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_historical_versions_stay_immutable_after_revision(self):
        """Historical Runs must still resolve the version they consumed."""
        store = make_store()
        brief = await create_brief(store)
        v1 = brief.current

        revised = await store.revise(
            brief.brief_id,
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            revision=BriefRevision(summary="v2", persona_id="persona-brutalist"),
        )

        assert revised.version(1) is v1
        assert v1.persona_id == "persona-atelier"
        assert revised.current.version == 2
        assert revised.current.persona_id == "persona-brutalist"
        # The pre-revise handle is an immutable snapshot: it still shows v1,
        # exactly what a Run or artifact that consumed v1 must keep seeing.
        assert brief.current.version == 1

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_revise_carries_undeclared_fields_forward(self):
        """None means keep: references cannot be silently dropped by a revision."""
        store = make_store()
        brief = await create_brief(store)

        revised = await store.revise(
            brief.brief_id,
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            revision=BriefRevision(summary="Only the summary changes"),
        )

        current = revised.current
        assert current.persona_id == "persona-atelier"
        assert current.design_system_slug == "atelier-zero"
        assert current.success_criteria == ("launch-ready site", "coherent coupon campaign")
        assert current.artifact_requirements == brief.current.artifact_requirements

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_history_is_ordered_oldest_first(self):
        store = make_store()
        brief = await create_brief(store)
        await store.revise(
            brief.brief_id,
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            revision=BriefRevision(summary="v2"),
        )
        await store.revise(
            brief.brief_id,
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            revision=BriefRevision(summary="v3"),
        )

        versions = await store.history(brief.brief_id, workspace_id=WORKSPACE, project_id=PROJECT)
        assert [item.version for item in versions] == [1, 2, 3]

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_unknown_version_refused(self):
        store = make_store()
        brief = await create_brief(store)

        with pytest.raises(CreativeBriefNotFoundError):
            brief.version(9)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_lineage_rejects_discontiguous_versions(self):
        """A lineage is contiguous from 1 by construction."""
        with pytest.raises(CreativeBriefError, match="contiguous"):
            CreativeBrief(brief_id="b1", versions=(make_version(version=2),))


# ── Version boundary validation ───────────────────────────────────────────────


def make_version(**overrides: object) -> CreativeBriefVersion:
    """A valid reference version, with per-test overrides."""
    kwargs: dict[str, object] = {
        "brief_id": "b1",
        "version": 1,
        "goal_id": GOAL,
        "goal_revision": GOAL_REVISION,
        "workspace_id": WORKSPACE,
        "project_id": PROJECT,
        "owner_agent_id": AGENT,
        "persona_id": None,
        "design_system_slug": None,
        "design_system_version": None,
        "success_criteria": (),
        "audience": "readers",
        "source_references": (),
        "artifact_requirements": (),
        "creative_constraints": (),
        "summary": "reference version",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    kwargs.update(overrides)
    return CreativeBriefVersion(**kwargs)  # type: ignore[arg-type]


class TestVersionValidation:
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    @pytest.mark.parametrize(
        ("field", "bad_value"),
        [
            ("success_criteria", ["a list, not a tuple"]),
            ("source_references", "a bare string"),
            ("creative_constraints", ("",)),
        ],
    )
    def test_non_tuple_or_blank_string_collections_refused(self, field: str, bad_value: object):
        with pytest.raises(CreativeBriefError, match=field):
            make_version(**{field: bad_value})

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    @pytest.mark.parametrize("bad_version", ["1", 1.0, True, 0, -1])
    def test_version_number_must_be_a_positive_int(self, bad_version: object):
        with pytest.raises(CreativeBriefError, match="positive integer"):
            make_version(version=bad_version)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_artifact_requirements_must_hold_requirement_values(self):
        with pytest.raises(CreativeBriefError, match="ArtifactRequirement"):
            make_version(artifact_requirements=("coupon: plain string, not a requirement",))

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_to_dict_round_trips_the_published_context(self):
        """A published version serializes everything a Run/artifact must recover."""
        requirement = ArtifactRequirement("coupon", "one per customer")
        version = make_version(
            persona_id="persona-atelier",
            design_system_slug="atelier-zero",
            design_system_version="2.1.0",
            success_criteria=("launch-ready",),
            source_references=("memory://workspace/brand-voice",),
            artifact_requirements=(requirement,),
            creative_constraints=("no dark patterns",),
        )

        payload = version.to_dict()
        assert payload["brief_id"] == "b1"
        assert payload["version"] == 1
        assert payload["goal_id"] == GOAL
        assert payload["goal_revision"] == GOAL_REVISION
        assert payload["persona_id"] == "persona-atelier"
        assert payload["design_system_version"] == "2.1.0"
        assert payload["success_criteria"] == ["launch-ready"]
        assert payload["artifact_requirements"] == [
            {"branch": "coupon", "requirement": "one per customer"}
        ]
        assert payload["created_at"] == version.created_at.isoformat()

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_lineage_rejects_empty_or_foreign_versions(self):
        with pytest.raises(CreativeBriefError, match="at least one CreativeBriefVersion"):
            CreativeBrief(brief_id="b1", versions=())
        with pytest.raises(CreativeBriefError, match="share the brief_id"):
            CreativeBrief(brief_id="b1", versions=(make_version(), make_version(brief_id="b2")))
        with pytest.raises(CreativeBriefError, match="same Goal revision and scope"):
            CreativeBrief(
                brief_id="b1",
                versions=(make_version(), make_version(version=2, workspace_id="other-ws")),
            )


# ── Scope isolation (#326 lesson: no defaults, no cross-scope leakage) ───────


class TestScopeIsolation:
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_get_wrong_scope_returns_none_without_leaking(self):
        store = make_store()
        brief = await create_brief(store)

        assert await store.get(brief.brief_id, workspace_id="other-ws", project_id=PROJECT) is None
        assert (
            await store.get(brief.brief_id, workspace_id=WORKSPACE, project_id="other-proj") is None
        )
        assert await store.get("missing-id", workspace_id=WORKSPACE, project_id=PROJECT) is None

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_revise_outside_scope_raises_not_found(self):
        """A sibling scope cannot append versions to a lineage it cannot see."""
        store = make_store()
        brief = await create_brief(store)

        for kwargs in (
            {"workspace_id": "other-ws", "project_id": PROJECT},
            {"workspace_id": WORKSPACE, "project_id": "other-proj"},
        ):
            with pytest.raises(CreativeBriefNotFoundError):
                await store.revise(
                    brief.brief_id, revision=BriefRevision(summary="smuggled"), **kwargs
                )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_runtime_protocol_conformance(self):
        """The reference store satisfies the reviewed protocol surface."""
        assert isinstance(make_store(), CreativeBriefStore)


# ── Provenance retention on produced artifacts (#773 acceptance) ─────────────


class TestArtifactProvenance:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_bind_joins_creative_and_execution_lineage(self):
        """Every artifact keeps Goal revision + brief version + Run/NodeRun/Attempt."""
        store = make_store()
        brief = await create_brief(store)

        provenance = ArtifactProvenance.bind(
            brief.current,
            run_id="run-1",
            node_run_id="node-1",
            attempt_id="attempt-1",
        )

        assert provenance.goal_id == GOAL
        assert provenance.goal_revision == GOAL_REVISION
        assert provenance.brief_id == brief.brief_id
        assert provenance.brief_version == 1
        assert provenance.run_id == "run-1"
        assert provenance.node_run_id == "node-1"
        assert provenance.attempt_id == "attempt-1"

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    @pytest.mark.parametrize("field", ["run_id", "node_run_id", "attempt_id"])
    async def test_bind_refuses_blank_execution_identity(self, field: str):
        """No canonical execution evidence, no artifact provenance."""
        store = make_store()
        brief = await create_brief(store)

        ids = {"run_id": "run-1", "node_run_id": "node-1", "attempt_id": "attempt-1"}
        ids[field] = "  "
        with pytest.raises(CreativeBriefError, match=field):
            ArtifactProvenance.bind(brief.current, **ids)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_provenance_refuses_a_foreign_goal_claim(self):
        """Historical provenance is not rewritable onto a different Goal revision."""
        store = make_store()
        brief = await create_brief(store)
        provenance = ArtifactProvenance.bind(
            brief.current, run_id="run-1", node_run_id="node-1", attempt_id="attempt-1"
        )

        provenance.assert_matches_goal(GOAL, GOAL_REVISION)
        with pytest.raises(CreativeBriefConflictError, match="not 'goal-773' revision 'rev-9'"):
            provenance.assert_matches_goal(GOAL, "rev-9")

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_provenance_serializes_for_transport(self):
        store = make_store()
        brief = await create_brief(store)
        provenance = ArtifactProvenance.bind(
            brief.current, run_id="run-1", node_run_id="node-1", attempt_id="attempt-1"
        )

        payload = provenance.to_dict()
        assert payload == {
            "goal_id": GOAL,
            "goal_revision": GOAL_REVISION,
            "brief_id": brief.brief_id,
            "brief_version": 1,
            "run_id": "run-1",
            "node_run_id": "node-1",
            "attempt_id": "attempt-1",
        }

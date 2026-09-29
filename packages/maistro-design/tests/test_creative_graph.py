"""The creative Graph for multi-artifact fan-out and targeted regeneration (#775).

These tests hold #775's acceptance against reachable production behavior:
one canonical GraphTemplate plans and executes every requested artifact
branch from one canonical Goal + CreativeBrief through the canonical durable
executor (``maistro.graph.durable_runs``) — shared decisions persisted once
and cited by every branch, parallel branches actually concurrent, a failed
branch retried/refined in isolation through canonical NodeRun/Attempt
seams, invalidation that follows the real dependency shape, and provenance
inspection that explains each artifact's lineage from persisted state alone.

No model calls, no provider traffic: every stage is a deterministic
registered node kind. The Graph/Run/NodeRun/Attempt machinery exercised is
the canonical one, not a test double.
"""

from __future__ import annotations

import asyncio
import gc
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph.durable_runs import InMemoryDurableRunStore, resume_durable_graph
from maistro.graph.durable_runs.stores import SqliteDurableRunStore
from maistro.graph.nodes import get_node
from maistro.runs.model import RunStatus
from maistro_design.brief import (
    ArtifactRequest,
    BriefReference,
    CreativeBrief,
    EvidenceReference,
    RequiredFact,
)
from maistro_design.creative_graph import (
    SHARED_STAGE_NODE_IDS,
    ArtifactProvenanceRecord,
    InvalidationReport,
    artifact_provenance,
    channel_family,
    instantiate_creative_graph,
    invalidated_requests,
    plan_creative_graph,
    run_creative_graph,
)
from maistro_design.creative_nodes import (
    CreativeArtifactGenerate,
    shared_context_from_brief,
    shared_decision_digest,
)

WS = "ws-creative"
PROJ = "proj-campaign"
GOAL = "goal-spring-launch"


def _brief(**overrides: object) -> CreativeBrief:
    """One Goal revision, one brief version, three artifact branches."""
    values: dict[str, object] = {
        "workspace_id": WS,
        "project_id": PROJ,
        "goal_id": GOAL,
        "goal_revision": 4,
        "goal_owner_agent_id": "agent-orchestrator",
        "goal_delegation_ref": BriefReference(
            kind="delegation", ref_id="delegation-launch-family", workspace_id=WS
        ),
        "persona": BriefReference(
            kind="persona", ref_id="persona-bakery", version="p-v2", workspace_id=WS
        ),
        "design_system": BriefReference(kind="design_system", ref_id="brand-x", version="2026.09"),
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
        "artifact_requests": (
            ArtifactRequest(
                request_id="landing-page",
                channel="website",
                format="html",
                requirements=("hero section", "menu"),
            ),
            ArtifactRequest(
                request_id="launch-deck",
                channel="deck",
                format="pdf",
                requirements=("10 slides",),
            ),
            ArtifactRequest(
                request_id="poster-launch",
                channel="poster",
                format="png",
                dimensions="A2",
            ),
        ),
    }
    values.update(overrides)
    return CreativeBrief.model_validate(values)


def _artifact_records(record: Any) -> dict[str, dict[str, Any]]:
    """Persisted per-branch artifact records, parsed from the annotations."""
    import json as _json

    parsed: dict[str, dict[str, Any]] = {}
    for key, value in (
        record.graph_state.blackboard_snapshot.get("node_annotations") or {}
    ).items():
        assert key.startswith("artifact::")
        parsed[str(key)[len("artifact::") :]] = _json.loads(value)
    return parsed


def _stage_runs(record: Any, *stage_names: str) -> list[Any]:
    """A record's NodeRuns for the named shared stages (stage survives as the
    node's name/definition metadata; instantiation mints fresh node ids)."""
    graph = record.run.graph.materialize()
    uuids = {node.node_id for node in graph.nodes if node.name in stage_names}
    return [nr for nr in record.node_runs if nr.node_id in uuids]


def _branch_runs(record: Any, *request_ids: str) -> list[Any]:
    """A record's NodeRuns for the named artifact branches (branch survives in
    node metadata; instantiation mints fresh node identities)."""
    graph = record.run.graph.materialize()
    uuids = {
        node.node_id
        for node in graph.nodes
        if node.metadata.get("stage") == "artifact.generate"
        and str(node.metadata.get("branch")) in request_ids
    }
    return [nr for nr in record.node_runs if nr.node_id in uuids]


def _resolver_for(**overrides: type[BaseModel]) -> Any:
    """Resolver mapping artifact branches to test doubles, stages to production kinds."""

    def resolve(node_id: str, graph: Any) -> Any:
        spec = next(node for node in graph.nodes if node.node_id == node_id)
        override = overrides.get(spec.node_type)
        if override is not None:
            return override()
        return get_node(spec.node_type)()

    return resolve


# ── AC 1 + 2: one template plans/executes three branches, retaining provenance ─


async def test_one_template_plans_and_executes_three_branches() -> None:
    brief = _brief()
    plan = plan_creative_graph(brief)

    # The template carries the full reference spine plus one branch per request.
    node_ids = {node.node_id for node in plan.template.nodes}
    assert {
        "brief.resolve",
        "research.evidence",
        "message.architecture",
        "copy.platform",
        "visual.direction",
        "artifact.plan",
        "artifact.generate.landing-page",
        "artifact.generate.launch-deck",
        "artifact.generate.poster-launch",
        "cross.critique",
        "targeted.refinement",
        "acceptance",
        "publish.export",
    } <= node_ids
    # Template identity is versioned and content-addressed like any canonical template.
    assert plan.template.name == "creative-production"
    assert plan.template.version == 1
    assert plan.template.content_hash

    store = InMemoryDurableRunStore()
    record = await run_creative_graph(brief, store=store, plan=plan)

    assert record.run.status is RunStatus.COMPLETED
    executed_branches = {
        node_run.node_run_id
        for node_run in _branch_runs(record, "landing-page", "launch-deck", "poster-launch")
    }
    assert len(executed_branches) == 3
    # Acceptance passed on every planned branch, and export recorded the family.
    assert set(_artifact_records(record)) == {"landing-page", "launch-deck", "poster-launch"}


async def test_updated_brief_version_registers_as_new_template_version() -> None:
    """A second brief version in one lineage registers cleanly (Codex review).

    The default template version follows the brief version: re-planning an
    updated brief with documented defaults mints the next template version
    under the lineage's template id instead of colliding with the already
    registered v1 definition in a canonical ``GraphTemplateStore``.
    """
    from maistro.graph.templates import InMemoryGraphTemplateStore

    v1 = _brief()
    v2 = v1.new_version(change_note="audience narrowed", audience="professional pastry chefs")
    assert v1.lineage_id == v2.lineage_id
    assert v2.version == 2

    store = InMemoryGraphTemplateStore()
    plan_v1 = plan_creative_graph(v1)
    plan_v2 = plan_creative_graph(v2)

    assert plan_v1.template.template_id == plan_v2.template.template_id
    assert (plan_v1.template.version, plan_v2.template.version) == (1, 2)
    assert plan_v1.template.content_hash != plan_v2.template.content_hash

    await store.put(plan_v1.template)
    # The documented-default re-plan of the updated brief must not raise.
    await store.put(plan_v2.template)
    assert await store.versions(plan_v2.template.template_id) == [1, 2]

    # An explicit version still wins, for same-brief re-plans.
    assert plan_creative_graph(v1, version=3).template.version == 3


async def test_updated_brief_version_registers_as_new_template_version_conflict_guard() -> None:
    """Without the brief-derived default, the same call would conflict."""
    from maistro.graph.templates import GraphTemplateConflict, InMemoryGraphTemplateStore

    v1 = _brief()
    v2 = v1.new_version(change_note="audience narrowed", audience="professional pastry chefs")
    store = InMemoryGraphTemplateStore()
    await store.put(plan_creative_graph(v1).template)
    stale = plan_creative_graph(v2, version=1)
    assert stale.template.content_hash != plan_creative_graph(v1).template.content_hash
    with pytest.raises(GraphTemplateConflict):
        await store.put(stale.template)


async def test_selected_graph_and_run_retain_goal_revision_and_agent_provenance() -> None:
    brief = _brief()
    plan = plan_creative_graph(brief)
    graph = instantiate_creative_graph(brief, plan=plan)

    # The instantiated Graph carries the exact Goal revision and brief version.
    graph_provenance = graph.metadata["creative_provenance"]
    assert graph_provenance["goal_id"] == GOAL
    assert graph_provenance["goal_revision"] == 4
    assert graph_provenance["brief_id"] == brief.brief_id
    assert graph_provenance["brief_version"] == 1
    assert graph_provenance["goal_owner_agent_id"] == "agent-orchestrator"
    assert graph_provenance["goal_delegation_ref"]["ref_id"] == "delegation-launch-family"
    # ... and it is a selection reference back to the exact template content.
    assert graph_provenance["graph_template"]["template_id"] == plan.template.template_id
    assert graph_provenance["graph_template"]["content_hash"] == plan.template.content_hash
    # The template itself stays a reusable plan: no run/attempt identity in it.
    assert "run_id" not in plan.template.metadata

    store = InMemoryDurableRunStore()
    record = await run_creative_graph(brief, store=store, plan=plan, graph=graph)

    run_provenance = record.run.provenance
    assert run_provenance["goal_id"] == GOAL
    assert run_provenance["goal_revision"] == 4
    assert run_provenance["brief_id"] == brief.brief_id
    assert run_provenance["brief_version"] == 1
    assert run_provenance["goal_owner_agent_id"] == "agent-orchestrator"
    assert run_provenance["goal_delegation_ref"]["ref_id"] == "delegation-launch-family"
    # The accountable owner is the executing principal of record on the Run.
    assert record.run.actor_principal_id == "agent-orchestrator"
    assert record.run.project_id == PROJ
    assert record.run.workspace_id == WS


# ── AC 3: artifact branches run concurrently when ready ───────────────────────


class _ConcurrentGenerate(CreativeArtifactGenerate):
    """Two branches that can only finish if the executor runs them together."""

    kind: ClassVar[str] = "test_creative.concurrent_generate"


async def test_artifact_branches_run_concurrently_when_ready() -> None:
    enter_a = asyncio.Event()
    enter_b = asyncio.Event()

    class _PairedGenerate(_ConcurrentGenerate):
        async def _execute(self, inputs: Any, ctx: Any) -> Any:
            # Each side signals entry, then waits for the other side. Under a
            # sequential executor this deadlocks; wait_for turns the deadlock
            # into a loud failure instead of a hung test.
            if inputs.request["request_id"] == "launch-deck":
                enter_a.set()
                await asyncio.wait_for(enter_b.wait(), timeout=10)
            else:
                enter_b.set()
                await asyncio.wait_for(enter_a.wait(), timeout=10)
            return await super()._execute(inputs, ctx)

    brief = _brief()
    plan = plan_creative_graph(brief)
    store = InMemoryDurableRunStore()
    record = await run_creative_graph(
        brief,
        store=store,
        plan=plan,
        node_resolver=_resolver_for(**{"creative.artifact_generate": _PairedGenerate}),
    )

    assert record.run.status is RunStatus.COMPLETED
    # Both paired branches completed in the same frontier wave.
    branch_runs = _branch_runs(record, "launch-deck", "poster-launch")
    assert {node_run.status for node_run in branch_runs} == {RunStatus.COMPLETED}


# ── AC 4: shared decisions persisted once, referenced by every branch ─────────


async def test_shared_decisions_persisted_once_and_referenced_by_branches() -> None:
    brief = _brief()
    plan = plan_creative_graph(brief)
    store = InMemoryDurableRunStore()
    record = await run_creative_graph(brief, store=store, plan=plan)

    # Exactly one durable message-architecture and visual-direction stage.
    for stage in ("message.architecture", "visual.direction"):
        stage_runs = _stage_runs(record, stage)
        assert len(stage_runs) == 1, f"{stage} must be decided once"
        assert stage_runs[0].status is RunStatus.COMPLETED

    # Every branch consumed the same shared decision identities — cited in the
    # branch's own durable record, read back from the persisted annotations.
    records = _artifact_records(record)
    message_ids = {item["consumed_message_decision_id"] for item in records.values()}
    visual_ids = {item["consumed_visual_decision_id"] for item in records.values()}
    assert len(message_ids) == 1
    assert len(visual_ids) == 1
    # The cited decision is the one the single shared stage produced.
    message_stage = _stage_runs(record, "message.architecture")[0]
    assert next(iter(message_ids)) == message_stage.result["message_decision_id"]


# ── AC 5 + 8: planted failure isolates its branch; every try is an Attempt ────


_FAIL_COUNTS: dict[str, int] = {}


class _FlakyGenerate(CreativeArtifactGenerate):
    """Fails the first try of one planted branch, succeeds afterwards."""

    kind: ClassVar[str] = "test_creative.flaky_generate"

    async def _execute(self, inputs: Any, ctx: Any) -> Any:
        request_id = inputs.request["request_id"]
        _FAIL_COUNTS[request_id] = _FAIL_COUNTS.get(request_id, 0) + 1
        if request_id == "poster-launch" and _FAIL_COUNTS[request_id] == 1:
            raise RuntimeError("planted provider failure: poster render")
        return await super()._execute(inputs, ctx)


class _AlwaysFailGenerate(CreativeArtifactGenerate):
    kind: ClassVar[str] = "test_creative.always_fail_generate"

    async def _execute(self, inputs: Any, ctx: Any) -> Any:
        if inputs.request["request_id"] == "poster-launch":
            raise RuntimeError("planned permanent failure: poster render")
        return await super()._execute(inputs, ctx)


async def test_planted_failure_retries_only_its_branch_and_leaves_siblings_accepted() -> None:
    _FAIL_COUNTS.clear()
    brief = _brief()
    plan = plan_creative_graph(brief)
    store = InMemoryDurableRunStore()
    record = await run_creative_graph(
        brief,
        store=store,
        plan=plan,
        node_resolver=_resolver_for(**{"creative.artifact_generate": _FlakyGenerate}),
    )

    assert record.run.status is RunStatus.COMPLETED
    poster_runs = sorted(_branch_runs(record, "poster-launch"), key=lambda nr: nr.ordinal)
    sibling_runs = _branch_runs(record, "landing-page", "launch-deck")
    # Only the failed branch went through retry: two visits (fail, succeed).
    assert [node_run.status for node_run in poster_runs] == [RunStatus.FAILED, RunStatus.COMPLETED]
    # The unrelated siblings were visited exactly once and accepted.
    assert {node_run.status for node_run in sibling_runs} == {RunStatus.COMPLETED}
    assert all(len(node_run.node_id) for node_run in sibling_runs)
    sibling_ids = {node_run.node_run_id for node_run in sibling_runs}
    assert len(sibling_ids) == 2

    # AC 8: every physical try — including the planted failure — is one
    # canonical Attempt through the execution seam, with the kind as executor.
    attempts_by_branch: dict[str, int] = {}
    graph = record.run.graph.materialize()
    branch_by_uuid = {
        node.node_id: str(node.metadata.get("branch"))
        for node in graph.nodes
        if node.metadata.get("stage") == "artifact.generate"
    }
    for attempt in record.attempts:
        branch = branch_by_uuid.get(
            next(nr.node_id for nr in record.node_runs if nr.node_run_id == attempt.node_run_id)
        )
        attempts_by_branch[branch] = attempts_by_branch.get(branch, 0) + 1
        assert attempt.executor_id
    assert attempts_by_branch["poster-launch"] == 2
    assert attempts_by_branch["landing-page"] == 1
    assert attempts_by_branch["launch-deck"] == 1
    # The failed try's evidence is the Attempt's own result envelope plus the
    # failed NodeRun — canonical Attempt evidence for the physical failure.
    failed_envelopes = [
        attempt
        for attempt in record.attempts
        if isinstance(attempt.result, dict) and attempt.result.get("success") is False
    ]
    assert any(
        "planted provider failure" in str(envelope.result.get("error_message") or "")
        for envelope in failed_envelopes
    )
    failed_node_runs = [nr for nr in record.node_runs if nr.status is RunStatus.FAILED]
    assert len(failed_node_runs) == 1
    assert "planted provider failure" in (failed_node_runs[0].error or "")

    # The provenance surface reports the full history per artifact.
    provenance = {item.request_id: item for item in artifact_provenance(record)}
    assert provenance["poster-launch"].attempt_count == 2
    assert provenance["landing-page"].attempt_count == 1
    assert all(item.status == "completed" for item in provenance.values())


async def test_exhausted_branch_fails_its_run_and_never_replays_accepted_siblings() -> None:
    """A branch that spends its whole budget fails its own Run; the accepted
    siblings stay accepted, and canonical recovery never rewinds a terminal
    Run — new Goal work is a new Run, not a replay of the failed one."""
    brief = _brief()
    plan = plan_creative_graph(brief)
    store = InMemoryDurableRunStore()
    failed = await run_creative_graph(
        brief,
        store=store,
        plan=plan,
        node_resolver=_resolver_for(**{"creative.artifact_generate": _AlwaysFailGenerate}),
    )

    assert failed.run.status is RunStatus.FAILED
    siblings = _branch_runs(failed, "landing-page", "launch-deck")
    assert len(siblings) == 2
    assert all(node_run.status is RunStatus.COMPLETED for node_run in siblings)
    assert all(node_run.accepted_outcome is not None for node_run in siblings)
    # The exhausted branch spent its declared budget: three visits, three Attempts.
    poster = _branch_runs(failed, "poster-launch")
    assert [node_run.status for node_run in sorted(poster, key=lambda nr: nr.ordinal)] == [
        RunStatus.FAILED
    ] * 3
    assert sum(1 for _ in (a for a in failed.attempts)) >= 5

    # A terminal Run cannot be rewound through the canonical resume path.
    with pytest.raises(ValueError, match="cannot resume run"):
        await resume_durable_graph(
            failed.run.run_id,
            store=store,
            node_resolver=_resolver_for(),
        )


# ── AC 9: refresh reconstructs real state from the canonical store ────────────


async def test_refresh_reconstructs_state_from_persisted_canonical_record(
    tmp_path: Any,
) -> None:
    """Refresh during fan-out reconstructs real canonical state — a fresh
    process reads the same accepted artifacts, the same failure evidence and
    the same Goal/brief provenance from the store alone, and re-fulfillment
    is a new Run that never mutates the historical one."""
    brief = _brief()
    plan = plan_creative_graph(brief)
    db_path = tmp_path / "creative-runs.db"

    store = SqliteDurableRunStore(db_path)
    failed = await run_creative_graph(
        brief,
        store=store,
        plan=plan,
        node_resolver=_resolver_for(**{"creative.artifact_generate": _AlwaysFailGenerate}),
    )
    failed_run_id = failed.run.run_id
    failed_provenance = {item.request_id: item for item in artifact_provenance(failed)}
    # Simulate process loss: drop every executor reference and let the
    # sqlite connections actually close before the fresh store opens.
    del store, failed
    gc.collect()

    reopened = SqliteDurableRunStore(db_path)
    recovered = await reopened.get(failed_run_id)
    assert recovered is not None
    after_reopen = {item.request_id: item for item in artifact_provenance(recovered)}
    # Reconstruction explains real state, identical to what the dying process saw.
    assert after_reopen["landing-page"].status == "completed"
    assert after_reopen["launch-deck"].status == "completed"
    assert after_reopen["landing-page"].artifact_id == failed_provenance["landing-page"].artifact_id
    assert after_reopen["poster-launch"].status == "failed"
    assert after_reopen["poster-launch"].goal_revision == 4
    assert after_reopen["poster-launch"].brief_version == 1

    # Re-fulfillment is a NEW canonical Run for the same Goal + brief
    # (its own store file: the historical one stays read-only evidence).
    retried = await run_creative_graph(
        brief, store=SqliteDurableRunStore(tmp_path / "creative-rerun.db"), plan=plan
    )
    assert retried.run.status is RunStatus.COMPLETED
    assert retried.run.run_id != failed_run_id
    after = {item.request_id: item for item in artifact_provenance(retried)}
    assert all(item.status == "completed" for item in after.values())
    # Same shared decisions produce the same artifacts, and the historical
    # failed Run's record is untouched.
    assert after["landing-page"].artifact_id == failed_provenance["landing-page"].artifact_id
    reread = await reopened.get(failed_run_id)
    assert reread is not None
    assert reread.run.status is RunStatus.FAILED
    assert {item.request_id: item for item in artifact_provenance(reread)} == after_reopen


# ── AC 6 + 7: invalidation follows the real dependency shape ──────────────────


def test_channel_families_specialize_branches() -> None:
    assert channel_family("website") == "website_code"
    assert channel_family("landing-page") == "website_code"
    assert channel_family("deck") == "deck"
    assert channel_family("poster") == "fixed_page_visual"
    assert channel_family("script") == "script_video_media"
    assert channel_family("skywriting") == "generic"
    plan = plan_creative_graph(_brief())
    families = {
        node.metadata["channel_family"]
        for node in plan.template.nodes
        if node.metadata.get("stage") == "artifact.generate"
    }
    assert families == {"website_code", "deck", "fixed_page_visual"}


def test_changing_a_shared_decision_invalidates_all_descendants() -> None:
    old = _brief()
    new = old.new_version(change_note="audience narrowed", audience="professional pastry chefs")
    report = invalidated_requests(old, new)

    assert isinstance(report, InvalidationReport)
    assert report.goal_revision_changed is False
    assert report.shared_context_changed is True
    assert report.invalidated_request_ids == ("landing-page", "launch-deck", "poster-launch")
    assert report.unchanged_request_ids == ()
    assert "audience" in report.reasons["*"]
    # The invalidation names the planned nodes, shared stages first.
    assert report.invalidated_node_ids[0] == "brief.resolve"
    assert "artifact.generate.poster-launch" in report.invalidated_node_ids


def test_changing_one_poster_dimension_does_not_regenerate_website_copy() -> None:
    old = _brief()
    new = old.new_version(
        change_note="poster resize",
        artifact_requests=(
            ArtifactRequest(
                request_id="landing-page",
                channel="website",
                format="html",
                requirements=("hero section", "menu"),
            ),
            ArtifactRequest(
                request_id="launch-deck",
                channel="deck",
                format="pdf",
                requirements=("10 slides",),
            ),
            ArtifactRequest(
                request_id="poster-launch",
                channel="poster",
                format="png",
                dimensions="A1",
            ),
        ),
    )
    report = invalidated_requests(old, new)

    assert report.goal_revision_changed is False
    assert report.shared_context_changed is False
    assert report.invalidated_request_ids == ("poster-launch",)
    assert report.unchanged_request_ids == ("landing-page", "launch-deck")
    assert "dimensions" in report.reasons["poster-launch"]
    # Branch-local change: shared decision stages must not rerun, only the
    # changed branch plus the fan-in stages that consume its output.
    assert not any(node_id in report.invalidated_node_ids for node_id in SHARED_STAGE_NODE_IDS)
    assert "artifact.generate.poster-launch" in report.invalidated_node_ids
    assert "cross.critique" in report.invalidated_node_ids


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("beneficiaries", ("creative small teams",), id="beneficiaries"),
        pytest.param("goal_owner_agent_id", "agent-delegate-design", id="goal_owner_agent_id"),
        pytest.param("goal_delegation_ref", None, id="delegation-removed"),
        pytest.param(
            "goal_delegation_ref",
            BriefReference(kind="delegation", ref_id="delegation-other", workspace_id=WS),
            id="delegation-moved",
        ),
        pytest.param(
            "success_interpretation",
            "success = 500 preorders in week one",
            id="success-interpretation",
        ),
        pytest.param(
            "source_references",
            (BriefReference(kind="artifact", ref_id="research-pack-9", workspace_id=WS),),
            id="source-references",
        ),
        pytest.param(
            "supervision_constraints",
            ("legal review before publish",),
            id="supervision-constraints",
        ),
    ],
)
def test_relayed_shared_field_changes_invalidate_every_descendant(
    field: str, value: object
) -> None:
    """Every field the shared-decision identity covers invalidates everything.

    ``beneficiaries``, ``goal_owner_agent_id`` and ``goal_delegation_ref`` are
    relayed to every branch through the shared context and digested into the
    message-decision identity (:func:`shared_decision_digest`), so a change to
    any of them is a shared-decision change: the invalidation signature and
    the decision identities the message/visual stages cite are one authority.
    Under-invalidating them would re-plan branches whose durable records cite
    decision ids that no longer match the brief version they claim to fulfill
    (#775 repair).
    """
    old = _brief()
    new = old.new_version(change_note=f"{field} changed", **{field: value})
    report = invalidated_requests(old, new)

    assert report.goal_revision_changed is False
    assert report.shared_context_changed is True
    assert report.invalidated_request_ids == ("landing-page", "launch-deck", "poster-launch")
    assert report.unchanged_request_ids == ()
    assert field in report.reasons["*"]


def test_shared_decision_identity_covers_the_relayed_agent_and_beneficiary_fields() -> None:
    """The decision-identity side of the agreement: holding the brief fixed,
    each relayed shared field moves the message-decision digest. Combined
    with the invalidation tests above, this pins that neither authority
    covers a field the other ignores."""
    base_context = shared_context_from_brief(_brief())
    base_digest = shared_decision_digest(base_context)

    for field, value in (
        ("beneficiaries", ["creative small teams"]),
        ("goal_owner_agent_id", "agent-delegate-design"),
        ("goal_delegation_ref", {"kind": "delegation", "ref_id": "delegation-other"}),
        ("success_interpretation", "success = 500 preorders in week one"),
        (
            "source_references",
            [{"kind": "artifact", "ref_id": "research-pack-9", "workspace_id": WS}],
        ),
        ("supervision_constraints", ["legal review before publish"]),
    ):
        mutated = {**base_context, field: value}
        assert shared_decision_digest(mutated) != base_digest, field


def test_new_version_with_unchanged_decisions_invalidates_nothing() -> None:
    """Version minting alone is not a semantic change: same audience,
    messages, persona, owner and delegation means nothing is invalidated and
    no branch is re-planned."""
    old = _brief()
    new = old.new_version(change_note="editorial note only")
    report = invalidated_requests(old, new)

    assert report.goal_revision_changed is False
    assert report.shared_context_changed is False
    assert report.invalidated_request_ids == ()
    assert report.unchanged_request_ids == ("landing-page", "launch-deck", "poster-launch")


def _goal_revision_brief() -> tuple[CreativeBrief, CreativeBrief]:
    old = _brief()
    new = old.new_version(change_note="outcome now in-store launch", goal_revision=5)
    return old, new


def test_goal_revision_change_produces_explicit_invalidation() -> None:
    old, new = _goal_revision_brief()
    report = invalidated_requests(old, new)

    assert report.goal_revision_changed is True
    assert report.shared_context_changed is True
    assert report.invalidated_request_ids == ("landing-page", "launch-deck", "poster-launch")
    assert "Goal revision changed 4 -> 5" in report.reasons["*"]


async def test_goal_revision_invalidation_does_not_mutate_historical_provenance() -> None:
    import copy

    old, new = _goal_revision_brief()

    # Run the fulfillment of the OLD Goal revision to completion.
    store = InMemoryDurableRunStore()
    record = await run_creative_graph(old, store=store)
    before = copy.deepcopy(record.run.provenance)
    assert before["goal_revision"] == 4

    # The new Goal revision invalidates downstream work explicitly...
    assert invalidated_requests(old, new).goal_revision_changed is True
    # ...and mutates nothing: the historical brief, run record and artifacts
    # keep the exact provenance they were produced under.
    assert old.goal_revision == 4
    assert old.brief_id != new.brief_id
    assert new.supersedes_brief_id == old.brief_id
    reread = await store.get(record.run.run_id)
    assert reread is not None
    assert reread.run.provenance == before
    assert reread.run.status is RunStatus.COMPLETED


# ── AC 10: inspection explains each artifact's full lineage ───────────────────


async def test_inspection_explains_goal_brief_decisions_and_delegation_per_artifact() -> None:
    brief = _brief()
    plan = plan_creative_graph(brief)
    store = InMemoryDurableRunStore()
    record = await run_creative_graph(brief, store=store, plan=plan)

    provenance = artifact_provenance(record)
    assert len(provenance) == 3
    by_request: dict[str, ArtifactProvenanceRecord] = {item.request_id: item for item in provenance}
    for request_id, item in by_request.items():
        assert item.goal_id == GOAL
        assert item.goal_revision == 4
        assert item.brief_id == brief.brief_id
        assert item.brief_version == 1
        assert item.goal_owner_agent_id == "agent-orchestrator"
        assert item.goal_delegation_ref is not None
        assert item.goal_delegation_ref["ref_id"] == "delegation-launch-family"
        assert item.consumed_message_decision_id
        assert item.consumed_visual_decision_id
        assert item.status == "completed"
        assert item.attempt_count == 1
        assert item.node_run_ids
        assert (
            item.channel
            == {"landing-page": "website", "launch-deck": "deck", "poster-launch": "poster"}[
                request_id
            ]
        )
    # The branches cite one shared message decision and one shared visual decision.
    assert len({item.consumed_message_decision_id for item in provenance}) == 1
    assert len({item.consumed_visual_decision_id for item in provenance}) == 1

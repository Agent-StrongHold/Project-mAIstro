"""M7-A2 (#791): the Project-scoped, ontology-backed Rubric store.

Binding invariants under test: live-Goal-revision requirement, Project/Workspace
scope match, immutable revisions (new revision on dimension change, prior
readable), run binding persistence naming exact revisions, and pack catalog
instantiation without pack ownership.
"""

from __future__ import annotations

import pytest

from maistro.ontology import (
    InMemoryOntology,
    NumericScale,
    PackRubricCatalog,
    RubricDimension,
    RubricGate,
    RubricProvenance,
    RubricScale,
)
from maistro.projects.rubric_store import (
    GoalRevisionSnapshot,
    RubricGoalNotLiveError,
    RubricNotFoundError,
    RubricRevisionConflictError,
    RubricRunBindingConflictError,
    RubricScopeMismatchError,
    RubricStore,
)

WS = "ws-1"
PROJECT = "proj-1"


class InMemoryGoalRevisionCatalog:
    """Dict-backed test double of the store's ``GoalRevisionCatalog`` seam.

    Lives with the tests that inject it: the store itself only knows the
    Protocol, and canonical Goal persistence (#458) will implement it.
    """

    def __init__(self) -> None:
        self._goals: dict[tuple[str, int], GoalRevisionSnapshot] = {}

    def register_goal(self, snapshot: GoalRevisionSnapshot) -> GoalRevisionSnapshot:
        """Publish one live Goal revision, retiring older revisions of the
        same Goal so only the exact revision published last resolves as live."""
        for revision in [
            r
            for (goal_id, r) in self._goals
            if goal_id == snapshot.goal_id and r != snapshot.goal_revision
        ]:
            del self._goals[(snapshot.goal_id, revision)]
        self._goals[(snapshot.goal_id, snapshot.goal_revision)] = snapshot.model_copy(deep=True)
        return snapshot

    def resolve(self, goal_id: str, goal_revision: int) -> GoalRevisionSnapshot | None:
        snap = self._goals.get((goal_id, goal_revision))
        return snap.model_copy(deep=True) if snap is not None else None


def dim(dim_id: str, weight: float = 1.0) -> RubricDimension:
    return RubricDimension(
        id=dim_id,
        name=dim_id.title(),
        weight=weight,
        scale=RubricScale(numeric=NumericScale(min_value=0.0, max_value=100.0)),
        method="deterministic",
        evidence_required=False,
    )


def authored(by: str = "user-1") -> RubricProvenance:
    return RubricProvenance(authored_by=by)


def live_goal(
    catalog: InMemoryGoalRevisionCatalog,
    goal_id: str = "goal-1",
    revision: int = 1,
    workspace_id: str = WS,
    project_id: str = PROJECT,
) -> GoalRevisionSnapshot:
    return catalog.register_goal(
        GoalRevisionSnapshot(
            goal_id=goal_id,
            goal_revision=revision,
            workspace_id=workspace_id,
            project_id=project_id,
        )
    )


def harness(
    goal_id: str = "goal-1",
    goal_revision: int = 1,
    workspace_id: str = WS,
    project_id: str = PROJECT,
) -> tuple[RubricStore, InMemoryOntology, InMemoryGoalRevisionCatalog]:
    catalog = InMemoryGoalRevisionCatalog()
    live_goal(catalog, goal_id, goal_revision, workspace_id, project_id)
    ontology = InMemoryOntology()
    return RubricStore(ontology, catalog), ontology, catalog


async def make_rubric(store: RubricStore, rubric_id: str = "rubric-a"):
    return await store.create(
        workspace_id=WS,
        project_id=PROJECT,
        goal_id="goal-1",
        goal_revision=1,
        dimensions=[dim("accuracy"), dim("voice", weight=2.0)],
        gate=RubricGate(pass_threshold=80.0),
        provenance=authored(),
        rubric_id=rubric_id,
    )


# -- creation requires a live Goal revision in the same Project -------------


async def test_create_without_any_goal_revision_fails() -> None:
    """Acceptance: creating a Rubric without a live Goal revision in the Project fails."""
    store = RubricStore(InMemoryOntology(), InMemoryGoalRevisionCatalog())
    with pytest.raises(RubricGoalNotLiveError, match="not live"):
        await make_rubric(store)


async def test_create_with_superseded_goal_revision_fails() -> None:
    """Only the exact revision named is bindable — not 'some revision of the goal'."""
    store, _, catalog = harness(goal_revision=2)
    live_goal(catalog, "goal-1", 2)
    with pytest.raises(RubricGoalNotLiveError):
        await store.create(
            workspace_id=WS,
            project_id=PROJECT,
            goal_id="goal-1",
            goal_revision=1,  # superseded
            dimensions=[dim("accuracy")],
            gate=RubricGate(pass_threshold=80.0),
            provenance=authored(),
        )


async def test_registering_new_revision_supersedes_older_revision() -> None:
    """Registering goal@2 after goal@1 retires goal@1: it stops resolving and
    can no longer back a new Rubric binding."""
    store, _, catalog = harness(goal_revision=1)
    assert catalog.resolve("goal-1", 1) is not None
    live_goal(catalog, "goal-1", 2)
    assert catalog.resolve("goal-1", 1) is None
    assert catalog.resolve("goal-1", 2) is not None
    with pytest.raises(RubricGoalNotLiveError):
        await store.create(
            workspace_id=WS,
            project_id=PROJECT,
            goal_id="goal-1",
            goal_revision=1,  # superseded by the goal@2 registration
            dimensions=[dim("accuracy")],
            gate=RubricGate(pass_threshold=80.0),
            provenance=authored(),
        )


async def test_reregistering_same_revision_is_idempotent() -> None:
    """Re-publishing the same revision supersedes nothing and stays live."""
    store, _, catalog = harness(goal_revision=1)
    live_goal(catalog, "goal-1", 1)
    assert catalog.resolve("goal-1", 1) is not None
    await make_rubric(store)


async def test_create_binds_goal_id_and_revision() -> None:
    store, _, _ = harness(goal_revision=7)
    semantic = await store.create(
        workspace_id=WS,
        project_id=PROJECT,
        goal_id="goal-1",
        goal_revision=7,
        dimensions=[dim("accuracy")],
        gate=RubricGate(pass_threshold=80.0),
        provenance=authored(),
    )
    assert semantic.revision == 1
    assert semantic.goal_id == "goal-1"
    assert semantic.goal_revision == 7
    latest = await store.get(semantic.rubric_id)
    assert latest is not None
    assert (latest.goal_id, latest.goal_revision) == ("goal-1", 7)


# -- cross-Project / cross-Workspace binds are rejected ----------------------


async def test_cross_project_bind_rejected() -> None:
    """Acceptance: the Goal is live, but the Rubric claims a different Project."""
    store, _, _ = harness()  # goal lives in ws-1/proj-1
    with pytest.raises(RubricScopeMismatchError, match="project"):
        await store.create(
            workspace_id=WS,
            project_id="proj-OTHER",
            goal_id="goal-1",
            goal_revision=1,
            dimensions=[dim("accuracy")],
            gate=RubricGate(pass_threshold=80.0),
            provenance=authored(),
        )


async def test_cross_workspace_bind_rejected() -> None:
    """Acceptance: cross-Workspace Goal/Rubric reference is structurally rejected."""
    store, _, _ = harness()
    with pytest.raises(RubricScopeMismatchError, match="workspace"):
        await store.create(
            workspace_id="ws-OTHER",
            project_id=PROJECT,
            goal_id="goal-1",
            goal_revision=1,
            dimensions=[dim("accuracy")],
            gate=RubricGate(pass_threshold=80.0),
            provenance=authored(),
        )


async def test_unknown_goal_in_scope_is_not_live_error() -> None:
    store, _, _ = harness()
    with pytest.raises(RubricGoalNotLiveError):
        await store.create(
            workspace_id=WS,
            project_id=PROJECT,
            goal_id="goal-MISSING",
            goal_revision=1,
            dimensions=[dim("accuracy")],
            gate=RubricGate(pass_threshold=80.0),
            provenance=authored(),
        )


# -- revisions: immutable, minted, readable ---------------------------------


async def test_update_dimensions_mints_new_revision_prior_readable() -> None:
    """Acceptance: updating dimensions mints a revision; the prior stays readable."""
    store, _, _ = harness()
    first = await make_rubric(store)

    second = await store.update_dimensions("rubric-a", dimensions=[dim("accuracy", weight=3.0)])

    assert first.revision == 1
    assert second.revision == 2
    assert [d.weight for d in second.dimensions] == [3.0]

    prior = await store.get_revision("rubric-a", 1)
    assert prior is not None
    assert [d.weight for d in prior.dimensions] == [1.0, 2.0]
    latest = await store.get("rubric-a")
    assert latest is not None and latest.revision == 2


async def test_revision_binds_exactly_one_goal_revision() -> None:
    """Acceptance: one Rubric revision binds exactly one Goal revision; history
    is immutable; a new Goal revision may mint a new Rubric revision."""
    store, _, catalog = harness(goal_revision=1)
    first = await make_rubric(store)
    assert first.goal_revision == 1

    # Scoring change without desired-outcome change: same Goal revision.
    rescored = await store.update_dimensions("rubric-a", dimensions=[dim("accuracy")])
    assert rescored.revision == 2
    assert rescored.goal_revision == 1

    # New Goal revision: may mint a new Rubric revision, bound to it exactly.
    live_goal(catalog, "goal-1", 2)
    rebound = await store.update_dimensions(
        "rubric-a", dimensions=[dim("accuracy")], goal_revision=2
    )
    assert rebound.revision == 3
    assert rebound.goal_revision == 2

    # Revision 2 still names Goal revision 1: history is not rewritten.
    historical = await store.get_revision("rubric-a", 2)
    assert historical is not None and historical.goal_revision == 1


async def test_update_dimensions_with_unlive_goal_revision_fails() -> None:
    store, _ontology, _catalog = harness(goal_revision=1)
    await make_rubric(store)
    with pytest.raises(RubricGoalNotLiveError):
        await store.update_dimensions("rubric-a", dimensions=[dim("accuracy")], goal_revision=9)


async def test_update_unknown_rubric_is_not_found() -> None:
    store, _, _ = harness()
    with pytest.raises(RubricNotFoundError):
        await store.update_dimensions("rubric-GHOST", dimensions=[dim("accuracy")])


async def test_same_revision_conflicting_content_is_rejected() -> None:
    """Revision payloads are immutable: (rubric_id, revision) cannot be rewritten."""
    store, _, _ = harness()
    await make_rubric(store)
    with pytest.raises(RubricRevisionConflictError, match="immutable"):
        await store.create(
            workspace_id=WS,
            project_id=PROJECT,
            goal_id="goal-1",
            goal_revision=1,
            dimensions=[dim("accuracy", weight=9.0)],
            gate=RubricGate(pass_threshold=80.0),
            provenance=authored(),
            rubric_id="rubric-a",
        )


async def test_rubric_scope_cannot_move_between_projects() -> None:
    """A Rubric bound to proj-1 cannot be re-scoped to another Project later."""
    store, ontology, catalog = harness()
    await make_rubric(store)
    live_goal(catalog, "goal-1", 1, workspace_id=WS, project_id="proj-2")
    fresh = RubricStore(ontology, catalog)
    with pytest.raises(RubricScopeMismatchError):
        await fresh.update_dimensions("rubric-a", dimensions=[dim("accuracy")])


# -- Run bindings: exact revisions persist -----------------------------------


async def test_run_binding_persists_exact_goal_and_rubric_revisions() -> None:
    """Acceptance: a Run can persist goal_id + Goal revision + rubric_id + Rubric
    revision, and keeps naming them after newer revisions exist."""
    store, _, _ = harness()
    semantic = await make_rubric(store)
    await store.update_dimensions("rubric-a", dimensions=[dim("accuracy")])

    binding = await store.record_run_binding("run-1", semantic.rubric_id, rubric_revision=1)

    stored = await store.binding_for_run("run-1")
    assert stored == binding
    assert binding.rubric_id == "rubric-a"
    assert binding.rubric_revision == 1
    assert binding.goal_id == "goal-1"
    assert binding.goal_revision == 1

    # Latest at record time when no revision is named.
    latest_binding = await store.record_run_binding("run-2", semantic.rubric_id)
    assert latest_binding.rubric_revision == 2
    # Historical bindings keep naming the revision they recorded.
    old = await store.binding_for_run("run-1")
    assert old is not None and old.rubric_revision == 1


async def test_run_binding_survives_store_restart_over_same_ontology() -> None:
    """Acceptance: bindings are ontology entities, not process memory — a new
    RubricStore over the same durable ontology resolves historical bindings."""
    store, ontology, catalog = harness()
    semantic = await make_rubric(store)
    binding = await store.record_run_binding("run-1", semantic.rubric_id, rubric_revision=1)

    restarted = RubricStore(ontology, catalog)
    stored = await restarted.binding_for_run("run-1")
    assert stored == binding
    # Re-recording the same binding is idempotent; a conflicting one is rejected.
    assert (
        await restarted.record_run_binding("run-1", semantic.rubric_id, rubric_revision=1)
        == binding
    )
    await store.update_dimensions("rubric-a", dimensions=[dim("accuracy")])
    with pytest.raises(RubricRunBindingConflictError):
        await store.record_run_binding("run-1", semantic.rubric_id, rubric_revision=2)


async def test_run_binding_requires_known_revision() -> None:
    store, _, _ = harness()
    with pytest.raises(RubricNotFoundError):
        await store.record_run_binding("run-1", "rubric-GHOST")
    semantic = await make_rubric(store)
    with pytest.raises(RubricNotFoundError):
        await store.record_run_binding("run-1", semantic.rubric_id, rubric_revision=99)


# -- pack catalogs supply defaults without ownership --------------------------


async def test_pack_catalog_instantiates_rubric_without_owning_it() -> None:
    """Acceptance: pack default catalogs instantiate a Rubric without owning it."""
    store, ontology, _ = harness()
    catalog = PackRubricCatalog(
        pack_id="pack-pm",
        name="PM acceptance defaults",
        dimensions=[dim("accuracy"), dim("voice", weight=2.0)],
        gate=RubricGate(pass_threshold=75.0),
    )

    semantic = await store.instantiate_from_catalog(
        catalog,
        workspace_id=WS,
        project_id=PROJECT,
        goal_id="goal-1",
        goal_revision=1,
        adopted_by="user-1",
    )

    # The pack supplied defaults; the adopter owns the Rubric.
    assert semantic.provenance.origin == "pack"
    assert semantic.provenance.pack_id == "pack-pm"
    assert semantic.provenance.authored_by == "user-1"
    assert semantic.rubric_id.startswith("rubric-") and semantic.rubric_id != "pack-pm"
    assert semantic.gate.pass_threshold == 75.0
    assert [d.id for d in semantic.dimensions] == ["accuracy", "voice"]

    # The catalog is never persisted and registers no ontology identity.
    entities = ontology.query("rubric")
    assert len(entities) == 1
    assert entities[0].get_semantic()["rubric_id"] == semantic.rubric_id

    # Later catalog edits cannot leak into the persisted Rubric.
    catalog.dimensions[0].weight = 42.0
    persisted = await store.get(semantic.rubric_id)
    assert persisted is not None
    assert persisted.dimensions[0].weight == 1.0

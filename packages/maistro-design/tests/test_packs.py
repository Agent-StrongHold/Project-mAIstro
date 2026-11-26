"""Domain packs (M7-A4, #793) — the pack contract and its canonical execution.

Issue-acceptance mapping (each test class names the criterion it proves):

- AC-1 "Three pack manifests exist and load through one registry"
  → `TestOneRegistry`
- AC-2 "Each pack can instantiate a Rubric catalog onto a Goal without
  owning Rubric identity" → `TestRubricCatalogOntoGoal`
- AC-3 "Each pack selects a Graph template that still executes as canonical
  Run/NodeRun/Attempt" → `TestCanonicalExecution`
- AC-4 "A CI test runs the same Goal through two packs and proves
  Goal/Project identity is shared while Graph/Rubric catalogs differ"
  → `TestSameGoalThroughTwoPacks`
- AC-5 "Canvas is referenced as a backend binding, never as pack_id"
  → `TestCanvasIsABinding`
- AC-6 "Design Studio can list packs without a pack-specific route becoming
  the product identity" → `TestSelectorListing` (substrate side; the HTTP
  route lives in hive-conductor's design routes)

The Graph execution fixtures follow the established durable-runs test
pattern (`tests/graph/durable_runs/test_durable_runs.py`): deterministic
stub node classes + the real `run_durable_graph` executor + an
`InMemoryDurableRunStore`. The pack loop's real phase executors are loop-
runtime bindings (M7 follow-up); what is proven here is that every pack's
Graph shape executes through the canonical spine unchanged.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from pydantic import BaseModel, ValidationError

from maistro.graph.definitions import GraphTemplate
from maistro.graph.durable_runs import (
    DurableRunRecord,
    InMemoryDurableRunStore,
    RunStatus,
)
from maistro.graph.durable_runs.attempt_executor import run_durable_graph
from maistro.graph.nodes import BaseNode, NodeContext
from maistro.interop.contract import INTEROP_ONTOLOGY_V1, InteropContractError
from maistro.ontology import InMemoryOntology
from maistro.ontology.rubric import ScoringMethod
from maistro.ontology.types import KindAlreadyRegisteredError
from maistro.projects.rubric_store import RubricStore
from maistro.runs.model import Attempt, NodeRun
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro_design.packs import (
    BookPages,
    DomainPack,
    ExecuteBackend,
    ForeignArtifactKindError,
    GameLoop,
    GoalRubricCatalog,
    PackArtifactError,
    PackArtifactKind,
    PackArtifactRecord,
    PackId,
    PackManifestError,
    PackRegistry,
    PackRegistryError,
    PackSummary,
    ProductSpec,
    UnknownPackError,
    pack_graph_template,
    parse_manifest,
    parse_pack_artifact,
    parse_thesis_artifact,
    persist_thesis_artifact,
)
from maistro_design.packs import registry as packs_registry
from maistro_design.proof import (
    InMemoryGoalRevisionCatalog,
    pack_rubric_catalog,
    pack_rubric_dimensions,
)

WORKSPACE_ID = "ws-793-packs"
PROJECT_ID = "proj-793-packs"
GOAL_ID = "goal-793-shared"
GOAL_REVISION = 2


@pytest.fixture(scope="module")
def registry() -> PackRegistry:
    return PackRegistry.builtin()


# --- Canonical execution fixtures: deterministic phase stubs ----------------


class _PhaseIn(BaseModel):
    text: str = ""


class _PhaseOut(BaseModel):
    text: str


class _ExploreNode(BaseNode):
    kind: ClassVar[str] = "pack.explore"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _PhaseIn
    output_schema: ClassVar[type[BaseModel]] = _PhaseOut

    async def _execute(self, inputs: _PhaseIn, ctx: NodeContext) -> _PhaseOut:
        return _PhaseOut(text=inputs.text)


class _ExecuteNode(BaseNode):
    kind: ClassVar[str] = "pack.execute"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _PhaseIn
    output_schema: ClassVar[type[BaseModel]] = _PhaseOut

    async def _execute(self, inputs: _PhaseIn, ctx: NodeContext) -> _PhaseOut:
        return _PhaseOut(text=inputs.text)


class _EvaluateNode(BaseNode):
    kind: ClassVar[str] = "pack.evaluate"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _PhaseIn
    output_schema: ClassVar[type[BaseModel]] = _PhaseOut

    async def _execute(self, inputs: _PhaseIn, ctx: NodeContext) -> _PhaseOut:
        return _PhaseOut(text=inputs.text)


class _RefineNode(BaseNode):
    kind: ClassVar[str] = "pack.refine"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _PhaseIn
    output_schema: ClassVar[type[BaseModel]] = _PhaseOut

    async def _execute(self, inputs: _PhaseIn, ctx: NodeContext) -> _PhaseOut:
        return _PhaseOut(text=inputs.text)


_STUB_KINDS: dict[str, type[BaseNode[Any, Any]]] = {
    stub.kind: stub for stub in (_ExploreNode, _ExecuteNode, _EvaluateNode, _RefineNode)
}


def _thick_dimension(
    dimension_id: str = "d", name: str = "D", weight: float = 1.0
) -> dict[str, Any]:
    """A thick catalog dimension (M7-A9, #985): weight + named 1-5 anchors."""
    return {
        "dimension_id": dimension_id,
        "name": name,
        "weight": weight,
        "low_anchor": "low",
        "high_anchor": "high",
    }


def _stub_resolver(node_id: str, graph: Any) -> BaseNode[Any, Any]:
    """Resolve every pack phase kind to its deterministic stub executor."""
    node_type = next(node.node_type for node in graph.nodes if node.node_id == node_id)
    stub = _STUB_KINDS.get(node_type)
    if stub is None:
        raise KeyError(f"no stub executor for node kind {node_type!r}")
    return stub()


async def _run_pack_graph(
    pack: DomainPack,
    *,
    run_id: str | None = None,
    goal_id: str = GOAL_ID,
    goal_revision: int = GOAL_REVISION,
) -> DurableRunRecord:
    """Instantiate the pack's template and execute it on the canonical spine."""
    template = pack_graph_template(pack, workspace_id=WORKSPACE_ID)
    graph = template.instantiate(project_id=PROJECT_ID)
    return await run_durable_graph(
        graph,
        store=InMemoryDurableRunStore(),
        node_resolver=_stub_resolver,
        inputs={"text": f"brief for {pack.pack_id.value}"},
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        provenance={"goal_id": goal_id, "goal_revision": goal_revision},
        run_id=run_id,
    )


# --- AC-1: one registry, three manifests ------------------------------------


class TestOneRegistry:
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("integration")
    def test_three_manifests_load_through_one_registry(self, registry: PackRegistry) -> None:
        packs = registry.list()
        assert [pack.pack_id for pack in packs] == [
            PackId.BOOK,
            PackId.GAME,
            PackId.PRODUCT,
        ]
        for pack in packs:
            assert pack.name
            assert pack.summary

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_every_pack_id_member_has_a_manifest(self) -> None:
        # The extension rule: one enum member + one manifest. A member
        # without a manifest is a loud PackManifestError, not a missing pack.
        registry = PackRegistry.builtin()
        assert set(PackId) == {pack.pack_id for pack in registry.list()}

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_unknown_pack_id_is_rejected(self, registry: PackRegistry) -> None:
        with pytest.raises(UnknownPackError):
            registry.get("canvas")
        with pytest.raises(UnknownPackError):
            registry.get("screenplay")

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_manifest_violating_the_contract_is_a_loud_error(self) -> None:
        # A manifest shaped like a product — "canvas" as a pack id, invented
        # ids — cannot load: PackId is a closed enum and parse_manifest is the
        # single parse path, so the failure is a loud PackManifestError no
        # matter where the text came from.
        product_like_canvas_manifest = """
pack_id: canvas
name: The Canvas Pack
explore_focus: [pixels]
execute_backends: [canvas]
artifact_kinds: [poster]
rubric_dimensions:
  - dimension_id: d
    name: D
graph:
  name: g
  entry_node: explore.a
  nodes:
    - {node_id: explore.a, kind: pack.explore, phase: explore}
    - {node_id: execute.a, kind: pack.execute, phase: execute}
    - {node_id: evaluate.a, kind: pack.evaluate, phase: evaluate}
    - {node_id: refine.a, kind: pack.refine, phase: refine}
  edges: [[explore.a, execute.a], [execute.a, evaluate.a], [evaluate.a, refine.a]]
"""
        with pytest.raises(PackManifestError):
            parse_manifest(PackId.PRODUCT, product_like_canvas_manifest)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_model_rejects_ids_outside_the_closed_enum_directly(self) -> None:
        with pytest.raises(ValidationError):
            DomainPack.model_validate({"pack_id": "canvas"})

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_duplicate_pack_manifests_are_rejected(self) -> None:
        packs = list(PackRegistry.builtin().list())
        with pytest.raises(PackRegistryError):
            PackRegistry((*packs, packs[0].model_copy(deep=True)))

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_a_member_without_a_manifest_is_a_loud_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The loader iterates the closed enum, so a member whose manifest file
        # is missing fails the whole load with the member named — never a
        # silently absent pack.
        monkeypatch.setattr(packs_registry, "_MANIFESTS_DIR", "manifests-absent")
        with pytest.raises(PackManifestError, match="no manifest shipped for pack"):
            PackRegistry.builtin()

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_manifest_text_that_is_not_yaml_is_a_loud_error(self) -> None:
        with pytest.raises(PackManifestError, match="does not satisfy the pack contract"):
            parse_manifest(PackId.PRODUCT, "pack_id: [never, closed")

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_a_registry_missing_a_member_reports_it_as_unknown(self) -> None:
        # get() distinguishes "not shipped" from "not a pack": an enum member
        # with no manifest in THIS registry is an UnknownPackError, exactly
        # like a name outside the closed enum.
        registry = PackRegistry(())
        with pytest.raises(UnknownPackError, match="no pack registered under 'product'"):
            registry.get(PackId.PRODUCT)


# --- AC-2: rubric catalog onto a Goal, identity never pack-owned ------------


class TestRubricCatalogOntoGoal:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    @pytest.mark.parametrize("pack_id", [PackId.PRODUCT, PackId.GAME, PackId.BOOK])
    def test_catalog_is_instantiated_onto_canonical_goal_identity(
        self, registry: PackRegistry, pack_id: PackId
    ) -> None:
        pack = registry.get(pack_id)
        catalog = pack.instantiate_rubric_catalog(goal_id=GOAL_ID, goal_revision=GOAL_REVISION)
        assert isinstance(catalog, GoalRubricCatalog)
        assert catalog.goal_id == GOAL_ID
        assert catalog.goal_revision == GOAL_REVISION
        # Dimensions are the pack defaults, grounded unchanged.
        assert [d.dimension_id for d in catalog.dimensions] == [
            d.dimension_id for d in pack.rubric_dimensions
        ]

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_catalog_identity_is_minted_per_instantiation(self, registry: PackRegistry) -> None:
        pack = registry.get(PackId.PRODUCT)
        first = pack.instantiate_rubric_catalog(goal_id=GOAL_ID, goal_revision=1)
        second = pack.instantiate_rubric_catalog(goal_id=GOAL_ID, goal_revision=1)
        assert first.catalog_id and second.catalog_id
        assert first.catalog_id != second.catalog_id

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_the_pack_owns_no_rubric_identity(self, registry: PackRegistry) -> None:
        pack = registry.get(PackId.GAME)
        model_fields = set(type(pack).model_fields)
        assert "catalog_id" not in model_fields
        assert "rubric_catalog_id" not in model_fields
        assert "rubric_id" not in model_fields

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_goal_projection_uses_the_canonical_ontology_shape(
        self, registry: PackRegistry
    ) -> None:
        pack = registry.get(PackId.BOOK)
        # Blank id: the ontology contract's own error, not a pack-local one.
        with pytest.raises(InteropContractError):
            pack.instantiate_rubric_catalog(goal_id="   ", goal_revision=1)
        with pytest.raises(InteropContractError):
            pack.instantiate_rubric_catalog(goal_id=GOAL_ID, goal_revision=0)
        # And the identity the catalog carries is exactly what the ontology
        # validator returns for the same projection.
        assert (
            INTEROP_ONTOLOGY_V1.validate_projection(
                "Goal", {"goal_id": GOAL_ID, "goal_revision": GOAL_REVISION}
            )
            == GOAL_ID
        )


# --- AC-3: every pack's template executes the canonical spine ---------------


class TestCanonicalExecution:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    @pytest.mark.parametrize("pack_id", [PackId.PRODUCT, PackId.GAME, PackId.BOOK])
    async def test_pack_template_executes_as_run_noderun_attempt(
        self, registry: PackRegistry, pack_id: PackId
    ) -> None:
        pack = registry.get(pack_id)
        record = await _run_pack_graph(pack, run_id=f"run-{pack_id.value}")

        # Canonical Run identity scheme, terminal in the canonical lifecycle.
        assert record.run.run_id == f"run-{pack_id.value}"
        assert record.run.status is RunStatus.COMPLETED
        assert record.run.workspace_id == WORKSPACE_ID
        assert record.run.project_id == PROJECT_ID
        assert record.run.provenance["goal_id"] == GOAL_ID

        # One NodeRun + Attempt per shape node, all linked to the Run.
        template = pack_graph_template(pack, workspace_id=WORKSPACE_ID)
        assert len(record.node_runs) == len(template.nodes)
        node_run_ids = {node_run.node_run_id for node_run in record.node_runs}
        assert all(isinstance(node_run, NodeRun) for node_run in record.node_runs)
        assert all(node_run.run_id == record.run.run_id for node_run in record.node_runs)
        assert all(isinstance(attempt, Attempt) for attempt in record.attempts)
        assert all(attempt.node_run_id in node_run_ids for attempt in record.attempts)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_template_is_a_canonical_workspace_bound_template(self, registry: PackRegistry) -> None:
        for pack in registry.list():
            template = pack_graph_template(pack, workspace_id=WORKSPACE_ID)
            assert isinstance(template, GraphTemplate)
            assert template.workspace_id == WORKSPACE_ID
            assert template.template_id == f"pack.{pack.pack_id.value}"
            # Backend bindings ride only on execute-phase node binding ids
            # and template metadata — never as pack or graph identity.
            for node in template.nodes:
                if node.metadata["pack.phase"] == "execute":
                    assert set(node.binding_ids) == {
                        backend.value for backend in pack.execute_backends
                    }
                else:
                    assert node.binding_ids == []
            # The explore contract rides with the template, like every other
            # pack field.
            assert template.metadata["explore_focus"] == list(pack.explore_focus)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_pack_shapes_genuinely_differ(self, registry: PackRegistry) -> None:
        templates = [
            pack_graph_template(pack, workspace_id=WORKSPACE_ID) for pack in registry.list()
        ]
        hashes = {template.content_hash for template in templates}
        assert len(hashes) == 3
        # Fence placement is shape too, and it differs per pack: the loop is
        # gated at different phases (product: explore+evaluate, game:
        # explore+execute, book: explore+refine).
        fence_patterns = {
            tuple(
                node.metadata["pack.phase"]
                for node in template.nodes
                if node.metadata["pack.fenced"]
            )
            for template in templates
        }
        assert len(fence_patterns) == 3


# --- AC-4: same Goal through two packs, shared identity, differing catalogs --


class TestSameGoalThroughTwoPacks:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_same_goal_through_product_and_book(self, registry: PackRegistry) -> None:
        product = registry.get(PackId.PRODUCT)
        book = registry.get(PackId.BOOK)

        product_record = await _run_pack_graph(product, run_id="run-product-793")
        book_record = await _run_pack_graph(book, run_id="run-book-793")

        # One Workspace / Project / Goal ontology across both runs.
        assert product_record.run.workspace_id == book_record.run.workspace_id
        assert product_record.run.project_id == book_record.run.project_id
        assert (
            product_record.run.provenance["goal_id"]
            == book_record.run.provenance["goal_id"]
            == GOAL_ID
        )
        assert (
            product_record.run.provenance["goal_revision"]
            == book_record.run.provenance["goal_revision"]
            == GOAL_REVISION
        )
        assert product_record.run.status is RunStatus.COMPLETED
        assert book_record.run.status is RunStatus.COMPLETED

        # ...while the Graphs and Rubric catalogs genuinely differ.
        product_catalog = product.instantiate_rubric_catalog(
            goal_id=GOAL_ID, goal_revision=GOAL_REVISION, catalog_id="rubric-product"
        )
        book_catalog = book.instantiate_rubric_catalog(
            goal_id=GOAL_ID, goal_revision=GOAL_REVISION, catalog_id="rubric-book"
        )
        assert product_catalog.goal_id == book_catalog.goal_id
        assert {d.dimension_id for d in product_catalog.dimensions} != {
            d.dimension_id for d in book_catalog.dimensions
        }
        assert (
            pack_graph_template(product, workspace_id=WORKSPACE_ID).content_hash
            != pack_graph_template(book, workspace_id=WORKSPACE_ID).content_hash
        )
        # Canvas binding differs per pack without either becoming a product.
        assert ExecuteBackend.CANVAS in product.execute_backends
        assert ExecuteBackend.CANVAS not in book.execute_backends


# --- AC-5: canvas is a binding, never a pack --------------------------------


class TestCanvasIsABinding:
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_no_pack_id_names_a_backend(self, registry: PackRegistry) -> None:
        backend_names = {backend.value for backend in ExecuteBackend}
        # The invariant is typed, not policed: PackId and ExecuteBackend are
        # two closed enums, and their members must stay disjoint — a future
        # pack id equal to a backend name would break AC-5 at the type level.
        assert {pack_id.value for pack_id in PackId}.isdisjoint(backend_names)
        for pack in registry.list():
            assert pack.pack_id.value not in backend_names

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_canvas_appears_only_as_a_backend_binding(self, registry: PackRegistry) -> None:
        for pack in registry.list():
            # canvas may appear only in execute_backends
            assert pack.pack_id.value != "canvas"
            for artifact_kind in pack.artifact_kinds:
                assert "canvas" not in artifact_kind
        product = registry.get(PackId.PRODUCT)
        book = registry.get(PackId.BOOK)
        assert ExecuteBackend.CANVAS in product.execute_backends
        assert ExecuteBackend.CANVAS not in book.execute_backends

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_bindings_surface_only_on_execute_nodes(self, registry: PackRegistry) -> None:
        for pack in registry.list():
            template = pack_graph_template(pack, workspace_id=WORKSPACE_ID)
            bound = [node for node in template.nodes if node.metadata["pack.phase"] == "execute"]
            assert bound, f"{pack.pack_id.value} has no execute-phase node"
            assert all(node.binding_ids for node in bound)


# --- AC-6 (substrate side): the uniform selector listing --------------------


class TestSelectorListing:
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_summaries_are_uniform_across_packs(self, registry: PackRegistry) -> None:
        summaries = registry.summaries()
        assert len(summaries) == 3
        assert all(isinstance(summary, PackSummary) for summary in summaries)
        shapes = {frozenset(type(s).model_fields) for s in summaries}
        assert len(shapes) == 1  # one listing shape, no per-pack fields

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_summary_carries_no_product_identity(self, registry: PackRegistry) -> None:
        for summary in registry.summaries():
            payload = summary.model_dump(mode="json")
            assert set(payload) == {
                "pack_id",
                "name",
                "summary",
                "execute_backends",
                "artifact_kinds",
            }
            assert payload["pack_id"] in {"product", "game", "book"}


# --- contract edges: malformed manifests and shapes -------------------------


class TestContractEdges:
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_shape_missing_a_loop_phase_is_rejected(self) -> None:
        base: dict[str, Any] = {
            "pack_id": "product",
            "version": "1.0.0",
            "name": "Broken",
            "explore_focus": ["x"],
            "execute_backends": ["builders"],
            "artifact_kinds": ["a"],
            "artifact_payload_kind": "a",
            "rubric_dimensions": [_thick_dimension()],
        }
        graph: dict[str, Any] = {
            "name": "g",
            "entry_node": "explore.a",
            "nodes": [
                {"node_id": "explore.a", "kind": "pack.explore", "phase": "explore"},
                {"node_id": "execute.a", "kind": "pack.execute", "phase": "execute"},
            ],
            "edges": [["explore.a", "execute.a"]],
        }
        with pytest.raises(ValidationError):
            DomainPack.model_validate({**base, "graph": graph})

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_fenced_node_requires_its_declared_fence_point(self) -> None:
        base: dict[str, Any] = {
            "pack_id": "product",
            "version": "1.0.0",
            "name": "Unfenced",
            "explore_focus": ["x"],
            "execute_backends": ["builders"],
            "artifact_kinds": ["a"],
            "artifact_payload_kind": "a",
            "rubric_dimensions": [_thick_dimension()],
            "graph": {
                "name": "g",
                "entry_node": "explore.a",
                "nodes": [
                    {
                        "node_id": "explore.a",
                        "kind": "pack.explore",
                        "phase": "explore",
                        "fenced": True,
                    },
                    {"node_id": "execute.a", "kind": "pack.execute", "phase": "execute"},
                    {"node_id": "evaluate.a", "kind": "pack.evaluate", "phase": "evaluate"},
                    {"node_id": "refine.a", "kind": "pack.refine", "phase": "refine"},
                ],
                "edges": [
                    ["explore.a", "execute.a"],
                    ["execute.a", "evaluate.a"],
                    ["evaluate.a", "refine.a"],
                ],
            },
        }
        with pytest.raises(ValidationError):
            DomainPack.model_validate(base)
        base["fence_points"] = ["explore.accept"]
        pack = DomainPack.model_validate(base)
        assert pack.graph.nodes[0].fenced is True

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_unreachable_shape_node_is_rejected(self) -> None:
        graph: dict[str, Any] = {
            "name": "g",
            "entry_node": "explore.a",
            "nodes": [
                {"node_id": "explore.a", "kind": "pack.explore", "phase": "explore"},
                {"node_id": "execute.a", "kind": "pack.execute", "phase": "execute"},
                {"node_id": "evaluate.a", "kind": "pack.evaluate", "phase": "evaluate"},
                {"node_id": "refine.a", "kind": "pack.refine", "phase": "refine"},
            ],
            "edges": [["explore.a", "execute.a"], ["execute.a", "evaluate.a"]],
        }
        with pytest.raises(ValidationError):
            DomainPack.model_validate(
                {
                    "pack_id": "book",
                    "name": "Disconnected",
                    "explore_focus": ["x"],
                    "execute_backends": ["text_artifact_tree"],
                    "artifact_kinds": ["a"],
                    "artifact_payload_kind": "a",
                    "rubric_dimensions": [_thick_dimension()],
                    "graph": graph,
                }
            )

    @staticmethod
    def _valid_pack_dict() -> dict[str, Any]:
        """A minimal contract-satisfying pack dict, for one-mutation boundaries."""
        return {
            "pack_id": "product",
            "version": "1.0.0",
            "name": "Boundary Pack",
            "explore_focus": ["x"],
            "execute_backends": ["builders"],
            "artifact_kinds": ["a"],
            "artifact_payload_kind": "a",
            "rubric_dimensions": [_thick_dimension()],
            "graph": {
                "name": "g",
                "entry_node": "explore.a",
                "nodes": [
                    {"node_id": "explore.a", "kind": "pack.explore", "phase": "explore"},
                    {"node_id": "execute.a", "kind": "pack.execute", "phase": "execute"},
                    {"node_id": "evaluate.a", "kind": "pack.evaluate", "phase": "evaluate"},
                    {"node_id": "refine.a", "kind": "pack.refine", "phase": "refine"},
                ],
                "edges": [
                    ["explore.a", "execute.a"],
                    ["execute.a", "evaluate.a"],
                    ["evaluate.a", "refine.a"],
                ],
            },
        }

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_duplicate_ids_within_a_pack_are_rejected(self) -> None:
        pack = self._valid_pack_dict()
        pack["artifact_kinds"] = ["a", "a"]
        with pytest.raises(ValidationError, match="artifact_kinds must be unique"):
            DomainPack.model_validate(pack)

        pack = self._valid_pack_dict()
        pack["rubric_dimensions"] = [
            _thick_dimension("d", "D", 0.5),
            _thick_dimension("d", "D again", 0.5),
        ]
        with pytest.raises(ValidationError, match="dimension_ids must be unique"):
            DomainPack.model_validate(pack)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_shape_with_duplicate_node_ids_is_rejected(self) -> None:
        pack = self._valid_pack_dict()
        pack["graph"]["nodes"] = [*pack["graph"]["nodes"], dict(pack["graph"]["nodes"][0])]
        with pytest.raises(ValidationError, match="node_ids must be unique"):
            DomainPack.model_validate(pack)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_shape_edge_to_a_node_outside_the_shape_is_rejected(self) -> None:
        pack = self._valid_pack_dict()
        pack["graph"]["edges"] = [["explore.a", "ghost"]]
        with pytest.raises(ValidationError, match="references a node outside the shape"):
            DomainPack.model_validate(pack)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_shape_entry_outside_the_shape_is_rejected(self) -> None:
        pack = self._valid_pack_dict()
        pack["graph"]["entry_node"] = "ghost"
        with pytest.raises(ValidationError, match="not a shape node"):
            DomainPack.model_validate(pack)


# --- M7-A9 (#985): thick catalogs as Rubric revisions, payload schemas -------
# Acceptance mapping (each class names the criterion it proves):
#
# - AC-1 "Three catalogs load and instantiate onto a Goal as Rubric revisions
#   without the pack owning rubric_id" → `TestThickCatalogsAsRubricRevisions`
# - AC-2 "Weights sum to 1; missing required artifact fields fail closed"
#   → `TestThickCatalogContract` + `TestArtifactPayloadSchemas`
# - AC-3 "A book thesis can persist BookPages; a game thesis GameLoop; a
#   product thesis ProductSpec" → `TestArtifactPayloadSchemas`
# - AC-4 "The same Goal identity can take product then book catalogs with
#   different Graph/Rubric, same Project" → `TestSameGoalTakesBothCatalogs`
# - AC-5 "Canvas is a backend binding on product and optional on book; never
#   pack_id" → `TestCanvasStaysABinding`
# - AC-6 "Contract test fails if a pack registers a competing Goal/Rubric/Run
#   kind" → `TestPacksCannotRegisterCompetingKinds`

#: The thick catalogs, verbatim from #985: dimension id → (weight, low, high).
_THICK_CATALOGS: dict[PackId, dict[str, tuple[float, str, str]]] = {
    PackId.PRODUCT: {
        "job": (0.22, "Vague ambition", "Named job"),
        "metric": (0.20, "Vibes KPI", "Falsifiable"),
        "scope": (0.18, "Scope soup", "Hard fence"),
        "surface": (0.16, "Chrome for chrome", "Job-shaped"),
        "empty": (0.12, "Blank page", "Guided"),
        "authority": (0.12, "Anonymous", "Auditable"),
    },
    PackId.GAME: {
        "verb": (0.22, "Busywork", "One clean verb"),
        "feel": (0.20, "Numb", "Tactile"),
        "session": (0.18, "Endless mush", "Closed arc"),
        "fail": (0.16, "Punitive", "Curious fail"),
        "toy": (0.14, "Chore", "Keep touching"),
        "teach": (0.10, "Manual first", "Learned in-hand"),
    },
    PackId.BOOK: {
        "turn": (0.22, "Filler pages", "Inevitable turns"),
        "cadence": (0.18, "Prose lump", "Spoken music"),
        "arc": (0.18, "Flat or preachy", "Earned feeling"),
        "age": (0.16, "Wrong room", "Sits in the lap"),
        "contract": (0.14, "Redundant", "Two channels"),
        "voice": (0.12, "Tone drift", "One instrument"),
    },
}

#: Thesis-slot JSON bodies shaped to each pack's judged payload schema.
_THESIS_BODIES: dict[PackId, str] = {
    PackId.PRODUCT: (
        '{"job": "Keep one hydration promise on a single-SKU store page", '
        '"metrics": ["Return rate under 2% in 30 days"], '
        '"surfaces": ["store"], "non_goals": ["No B2B pricing"]}'
    ),
    PackId.GAME: (
        '{"verb": "grapple", "loop": "swing, latch, pivot, release", '
        '"session": "one tower, three falls, done", '
        '"fail": "a fall respawns you mid-climb, curious not punished", '
        '"feel": ["weight in the swing", "snap on the latch"]}'
    ),
    PackId.BOOK: (
        '{"spreads": ['
        '{"n": 1, "text": "Moss was small. The hill was not.", "art": "a tiny fox at a huge hill", "turn": true}, '
        '{"n": 2, "text": "One step, said Moss, then one more.", "art": "the first foothold"}'
        "]}"
    ),
}


class TestThickCatalogContract:
    """The shipped defaults are whole judgments: thick, weighted, anchored."""

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    @pytest.mark.parametrize("pack_id", list(_THICK_CATALOGS))
    def test_shipped_catalogs_are_thick_exactly_as_specified(
        self, registry: PackRegistry, pack_id: PackId
    ) -> None:
        pack = registry.get(pack_id)
        expected = _THICK_CATALOGS[pack_id]
        assert [d.dimension_id for d in pack.rubric_dimensions] == list(expected)
        for dimension in pack.rubric_dimensions:
            weight, low, high = expected[dimension.dimension_id]
            assert dimension.weight == weight
            assert dimension.low_anchor == low
            assert dimension.high_anchor == high
            # Method defaults to model_judge; a manifest must mark a
            # `human`/`deterministic` dimension explicitly.
            assert dimension.method is ScoringMethod.MODEL_JUDGE

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    @pytest.mark.parametrize("pack_id", list(_THICK_CATALOGS))
    def test_shipped_weights_sum_to_exactly_one(
        self, registry: PackRegistry, pack_id: PackId
    ) -> None:
        from math import fsum

        pack = registry.get(pack_id)
        assert fsum(d.weight for d in pack.rubric_dimensions) == 1.0
        catalog = pack.instantiate_rubric_catalog(goal_id=GOAL_ID, goal_revision=1)
        assert catalog.weight_sum == 1.0

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_a_catalog_whose_weights_do_not_sum_to_one_is_rejected(self) -> None:
        pack = TestContractEdges._valid_pack_dict()
        pack["rubric_dimensions"] = [
            _thick_dimension("d", "D", 0.7),
            _thick_dimension("e", "E", 0.2),  # sums to 0.9, not 1
        ]
        with pytest.raises(ValidationError, match="must sum to 1"):
            DomainPack.model_validate(pack)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_a_dimension_can_be_marked_human_or_deterministic(self) -> None:
        pack = TestContractEdges._valid_pack_dict()
        pack["rubric_dimensions"] = [
            _thick_dimension("d", "D", 0.5) | {"method": "human"},
            _thick_dimension("e", "E", 0.5) | {"method": "deterministic"},
        ]
        validated = DomainPack.model_validate(pack)
        assert validated.rubric_dimensions[0].method is ScoringMethod.HUMAN
        assert validated.rubric_dimensions[1].method is ScoringMethod.DETERMINISTIC
        # And the canonical vocabulary is the only vocabulary: a pack cannot
        # invent a fourth scoring method.
        pack["rubric_dimensions"] = [_thick_dimension() | {"method": "vibes"}]
        with pytest.raises(ValidationError):
            DomainPack.model_validate(pack)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_the_payload_kind_must_be_one_of_the_packs_own_kinds(self) -> None:
        pack = TestContractEdges._valid_pack_dict()
        pack["artifact_payload_kind"] = "some_other_packs_kind"
        with pytest.raises(ValidationError, match="must be one of the pack's declared"):
            DomainPack.model_validate(pack)


async def _catalog_spine() -> tuple[RubricStore, InMemoryGoalRevisionCatalog, str]:
    """An in-memory scope store + Goal seam + project id, for catalog adoptions."""
    from maistro.projects.scope_store import InMemoryProjectScopeStore

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE_ID)
    project = await projects.create(
        workspace_id=WORKSPACE_ID, parent_project_id=root.project_id, name="Catalogs"
    )
    goals = InMemoryGoalRevisionCatalog()
    goals.register_goal(GOAL_SNAPSHOT(WORKSPACE_ID, project.project_id))
    return RubricStore(InMemoryOntology(), goals), goals, project.project_id


def GOAL_SNAPSHOT(
    workspace_id: str, project_id: str, goal_id: str = GOAL_ID, goal_revision: int = GOAL_REVISION
):
    """A canonical Goal revision snapshot on the proof's seam, for adoptions."""
    from maistro.projects.rubric_store import GoalRevisionSnapshot

    return GoalRevisionSnapshot(
        goal_id=goal_id,
        goal_revision=goal_revision,
        workspace_id=workspace_id,
        project_id=project_id,
    )


class TestThickCatalogsAsRubricRevisions:
    """AC-1: catalogs instantiate onto a Goal as store-minted revisions.

    The pack supplies defaults; the `RubricStore` mints the Rubric revision
    and owns its identity. The pack object never carries a `rubric_id`.
    """

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    @pytest.mark.parametrize("pack_id", list(_THICK_CATALOGS))
    async def test_catalog_becomes_a_pack_origin_rubric_revision(
        self, registry: PackRegistry, pack_id: PackId
    ) -> None:
        store, _goals, project_id = await _catalog_spine()
        pack = registry.get(pack_id)
        rubric = await store.instantiate_from_catalog(
            pack_rubric_catalog(pack_id.value, pack_rubric_dimensions(pack)),
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
            adopted_by="adopter-985",
        )
        # The revision is store-minted, Goal-bound, and pack-provenanced —
        # and the pack itself still owns no rubric identity.
        assert rubric.revision == 1
        assert (rubric.goal_id, rubric.goal_revision) == (GOAL_ID, GOAL_REVISION)
        assert rubric.provenance.pack_id == pack_id.value
        assert not hasattr(pack, "rubric_id")
        assert "rubric_id" not in type(pack).model_fields
        # The thickness survives the projection into the canonical Rubric.
        expected = _THICK_CATALOGS[pack_id]
        assert [d.id for d in rubric.dimensions] == list(expected)
        assert [d.weight for d in rubric.dimensions] == [
            expected[d.id][0] for d in rubric.dimensions
        ]
        assert rubric.dimensions[0].scale.numeric is not None
        assert rubric.dimensions[0].scale.numeric.min_value == 1.0
        assert rubric.dimensions[0].scale.numeric.max_value == 5.0

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_adoptions_mint_revisions_and_history_is_kept(
        self, registry: PackRegistry
    ) -> None:
        store, _goals, project_id = await _catalog_spine()
        pack = registry.get(PackId.PRODUCT)
        catalog = pack_rubric_catalog(PackId.PRODUCT.value, pack_rubric_dimensions(pack))
        first = await store.instantiate_from_catalog(
            catalog,
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
            adopted_by="adopter-985",
            rubric_id="rubric-985-fixed",
        )
        # Locking/editing the catalog's dimensions mints a new Rubric
        # revision (#985 invariant); revision 1 is never mutated and stays
        # readable for the historical Runs that scored against it.
        revised_dimensions = [d.model_copy(deep=True) for d in first.dimensions]
        revised_dimensions[0] = revised_dimensions[0].model_copy(update={"weight": 0.24})
        revised_dimensions[1] = revised_dimensions[1].model_copy(update={"weight": 0.18})
        second = await store.update_dimensions("rubric-985-fixed", dimensions=revised_dimensions)
        assert (first.revision, second.revision) == (1, 2)
        historical = await store.get_revision("rubric-985-fixed", 1)
        assert historical is not None
        assert historical.dimensions[0].weight == 0.22
        assert second.dimensions[0].weight == 0.24
        # And a retried identical adoption stays idempotent on revision 1.
        retried = await store.instantiate_from_catalog(
            catalog,
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
            adopted_by="adopter-985",
            rubric_id="rubric-985-fixed",
        )
        assert retried.revision == 1


class TestArtifactPayloadSchemas:
    """AC-2 (fail-closed fields) + AC-3 (thesis persist) + the foreign-kind fence."""

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_missing_required_fields_fail_closed(self) -> None:
        full_specs: dict[type[BaseModel], dict[str, Any]] = {
            ProductSpec: {
                "job": "Keep one hydration promise",
                "metrics": ["Return rate under 2%"],
                "surfaces": ["store"],
                "non_goals": ["No B2B pricing"],
            },
            GameLoop: {
                "verb": "grapple",
                "loop": "swing, latch, pivot, release",
                "session": "one tower, three falls",
                "fail": "a curious fall, not a punishment",
                "feel": ["weight in the swing"],
            },
            BookPages: {
                "spreads": [
                    {"n": 1, "text": "Moss was small.", "art": "a tiny fox at a huge hill"},
                    {"n": 2, "text": "One step, then one more.", "art": "the first foothold"},
                ]
            },
        }
        for model, full in full_specs.items():
            for field in model.model_fields:
                partial = {k: v for k, v in full.items() if k != field}
                with pytest.raises(ValidationError):
                    model.model_validate(partial)
            # Empty-but-present is not present: strings and lists must carry
            # content, and unknown fields are refused, not ignored.
            with pytest.raises(ValidationError):
                model.model_validate({**full, "___extra___": 1})

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_book_pages_must_be_ordered_spreads_from_one(self) -> None:
        spread = {"text": "t", "art": "a"}
        BookPages.model_validate({"spreads": [{**spread, "n": 1}, {**spread, "n": 2}]})
        # Gaps, repeats, and reordering all refuse the ordering contract...
        for ns in ([1, 3], [1, 1], [2, 1]):
            with pytest.raises(ValidationError, match=r"ordered spreads numbered 1\.\.N"):
                BookPages.model_validate({"spreads": [{**spread, "n": n} for n in ns]})
        # ...and zero-basing fails the spread model itself.
        with pytest.raises(ValidationError):
            BookPages.model_validate({"spreads": [{**spread, "n": 0}]})
        # `turn` is the optional page-turn marker, defaulting off.
        pages = BookPages.model_validate({"spreads": [{**spread, "n": 1}]})
        assert pages.spreads[0].turn is False
        marked = BookPages.model_validate({"spreads": [{**spread, "n": 1, "turn": True}]})
        assert marked.spreads[0].turn is True

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    @pytest.mark.parametrize("pack_id", list(_THICK_CATALOGS))
    def test_a_thesis_persists_its_own_packs_artifact(
        self, registry: PackRegistry, pack_id: PackId
    ) -> None:
        pack = registry.get(pack_id)
        record = persist_thesis_artifact(
            pack,
            artifact_kind=pack.artifact_payload_kind,
            body=_THESIS_BODIES[pack_id],
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
        )
        # The persisted record carries the pack release and the Goal identity
        # it serves — provenance references, never a minted identity.
        assert record.pack_id is pack_id
        assert record.pack_version == pack.version == "2.0.0"
        assert (record.goal_id, record.goal_revision) == (GOAL_ID, GOAL_REVISION)
        # Reading it back re-validates the bytes into the typed payload.
        payload = record.read()
        expected_models = {
            PackId.PRODUCT: ProductSpec,
            PackId.GAME: GameLoop,
            PackId.BOOK: BookPages,
        }
        assert isinstance(payload, expected_models[pack_id])
        assert PackArtifactRecord.model_validate_json(record.model_dump_json()).read() == payload

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_a_thesis_with_a_missing_field_fails_closed_at_persist(
        self, registry: PackRegistry
    ) -> None:
        pack = registry.get(PackId.BOOK)
        body = '{"spreads": [{"n": 1, "text": "no art note"}]}'
        with pytest.raises(ValidationError):
            persist_thesis_artifact(
                pack,
                artifact_kind="book_pages",
                body=body,
                goal_id=GOAL_ID,
                goal_revision=GOAL_REVISION,
            )
        with pytest.raises(PackArtifactError, match="not valid JSON"):
            persist_thesis_artifact(
                pack,
                artifact_kind="book_pages",
                body="not json at all",
                goal_id=GOAL_ID,
                goal_revision=GOAL_REVISION,
            )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_a_pack_cannot_emit_a_foreign_artifact_kind(self, registry: PackRegistry) -> None:
        product = registry.get(PackId.PRODUCT)
        book = registry.get(PackId.BOOK)
        # Another pack's judged payload kind is foreign to this pack.
        with pytest.raises(ForeignArtifactKindError, match="cannot emit artifact kind"):
            parse_thesis_artifact(product, artifact_kind="book_pages", body='{"spreads": []}')
        # A kind nothing declares is foreign everywhere.
        with pytest.raises(ForeignArtifactKindError):
            parse_thesis_artifact(book, artifact_kind="audio_shader", body="{}")
        # A declared-but-unstructured kind has no schema to judge with.
        with pytest.raises(PackArtifactError, match="carries no payload schema"):
            parse_pack_artifact(product, artifact_kind="deck", payload={})
        # A declared payload kind with no registered schema fails closed too.
        synthetic = DomainPack.model_validate(
            {
                **TestContractEdges._valid_pack_dict(),
                "artifact_kinds": ["novel_spec"],
                "artifact_payload_kind": "novel_spec",
            }
        )
        with pytest.raises(PackArtifactError, match="no registered payload schema"):
            parse_pack_artifact(synthetic, artifact_kind="novel_spec", payload={})

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_artifact_kind_vocabulary_is_closed_and_disjoint_from_packs(self) -> None:
        pack_values = {pack.value for pack in PackId}
        backend_values = {backend.value for backend in ExecuteBackend}
        for kind in PackArtifactKind:
            assert kind.value not in pack_values
            assert kind.value not in backend_values
        # Every shipped manifest's payload kind is a registered kind.
        registry = PackRegistry.builtin()
        for pack in registry.list():
            assert PackArtifactKind(pack.artifact_payload_kind) in set(PackArtifactKind)


class TestSameGoalTakesBothCatalogs:
    """AC-4: one Goal identity, product then book, same Project, new judgment."""

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_product_then_book_on_the_same_goal(self, registry: PackRegistry) -> None:
        store, _goals, project_id = await _catalog_spine()
        product = registry.get(PackId.PRODUCT)
        book = registry.get(PackId.BOOK)

        product_rubric = await store.instantiate_from_catalog(
            pack_rubric_catalog(PackId.PRODUCT.value, pack_rubric_dimensions(product)),
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
            adopted_by="adopter-985",
        )
        book_rubric = await store.instantiate_from_catalog(
            pack_rubric_catalog(PackId.BOOK.value, pack_rubric_dimensions(book)),
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
            adopted_by="adopter-985",
        )
        # Same Goal identity and Project across both catalog adoptions.
        for rubric in (product_rubric, book_rubric):
            assert (rubric.goal_id, rubric.goal_revision) == (GOAL_ID, GOAL_REVISION)
            assert rubric.project_id == project_id
            assert rubric.workspace_id == WORKSPACE_ID
        # ...while the Rubrics genuinely differ: identity and dimensions.
        assert product_rubric.rubric_id != book_rubric.rubric_id
        assert {d.id for d in product_rubric.dimensions} != {d.id for d in book_rubric.dimensions}
        # ...and so do the Graphs the two packs materialize.
        assert (
            pack_graph_template(product, workspace_id=WORKSPACE_ID).content_hash
            != pack_graph_template(book, workspace_id=WORKSPACE_ID).content_hash
        )
        # Each pack's payload schema stays its own: product persists a
        # ProductSpec on this Goal, book persists BookPages on the same one.
        product_record = persist_thesis_artifact(
            product,
            artifact_kind="product_spec",
            body=_THESIS_BODIES[PackId.PRODUCT],
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
        )
        book_record = persist_thesis_artifact(
            book,
            artifact_kind="book_pages",
            body=_THESIS_BODIES[PackId.BOOK],
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
        )
        assert isinstance(product_record.read(), ProductSpec)
        assert isinstance(book_record.read(), BookPages)


class TestCanvasStaysABinding:
    """AC-5: canvas is a backend binding on product, optional on book."""

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_product_binds_canvas_and_book_does_not_yet_may(self, registry: PackRegistry) -> None:
        product = registry.get(PackId.PRODUCT)
        book = registry.get(PackId.BOOK)
        assert ExecuteBackend.CANVAS in product.execute_backends
        assert ExecuteBackend.CANVAS not in book.execute_backends
        # "Optional" is a binding decision a later manifest revision may take
        # without the pack stopping being the book pack: adding the binding
        # changes no identity — pack_id, template id, and payload kind stay.
        book_with_canvas = book.model_copy(
            update={"execute_backends": (*book.execute_backends, ExecuteBackend.CANVAS)}
        )
        assert book_with_canvas.pack_id is PackId.BOOK
        assert book_with_canvas.artifact_payload_kind == book.artifact_payload_kind
        assert pack_graph_template(book_with_canvas, workspace_id=WORKSPACE_ID).template_id == (
            pack_graph_template(book, workspace_id=WORKSPACE_ID).template_id
        )
        # The binding surfaces as execute-node binding_ids — never a pack_id.
        template = pack_graph_template(book_with_canvas, workspace_id=WORKSPACE_ID)
        assert "canvas" in template.metadata["execute_backends"]
        assert template.metadata["pack_id"] == "book"
        for node in template.nodes:
            if node.metadata["pack.phase"] != "execute":
                assert "canvas" not in node.binding_ids

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_canvas_never_appears_as_a_pack_identity(self, registry: PackRegistry) -> None:
        for pack in registry.list():
            assert pack.pack_id.value != ExecuteBackend.CANVAS.value
            assert ExecuteBackend.CANVAS.value not in pack.artifact_kinds
            assert pack.artifact_payload_kind != ExecuteBackend.CANVAS.value
            summary = pack.to_summary()
            assert summary.pack_id is pack.pack_id


class TestPacksCannotRegisterCompetingKinds:
    """AC-6: packs cannot register a competing Goal/Rubric/Run kind.

    The ontology's kind slugs are registered by canonical owners only (the
    `RubricStore` constructor registers the ``rubric`` and
    ``rubric_run_binding`` kinds); a pack-supplied model cannot overwrite
    one, and the pack surface exposes no registration seam or identity
    field a competing kind could mint through.
    """

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_a_pack_supplied_model_cannot_overwrite_a_canonical_kind(self) -> None:
        from maistro.ontology.rubric import RUBRIC_KIND

        ontology = InMemoryOntology()
        RubricStore(ontology, InMemoryGoalRevisionCatalog())
        # The canonical kind is registered, and a pack-shaped model cannot
        # take its slug: the ontology refuses the overwrite loudly.
        assert ontology.query(RUBRIC_KIND) == []
        with pytest.raises(KindAlreadyRegisteredError):
            ontology.register(RUBRIC_KIND, DomainPack)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_the_pack_surface_exposes_no_kind_registration_seam(
        self, registry: PackRegistry
    ) -> None:
        # No registry or pack object offers a register/declare-kind API: a
        # pack is a bundle of defaults, never an ontology kind owner.
        for owner in (PackRegistry, DomainPack, GoalRubricCatalog):
            assert not any(
                name.startswith("register") or name.startswith("declare")
                for name in dir(owner)
                if not name.startswith("_")
            )
        # And no pack manifest field mints canonical identity: Goal/Rubric/
        # Run identity fields belong to the canonical semantic models alone.
        identity_fields = {
            "goal_id",
            "goal_revision",
            "rubric_id",
            "rubric_revision",
            "run_id",
            "node_run_id",
            "attempt_id",
        }
        pack_fields = set(DomainPack.model_fields)
        assert not identity_fields & pack_fields
        for pack in registry.list():
            assert not identity_fields & set(type(pack).model_fields)

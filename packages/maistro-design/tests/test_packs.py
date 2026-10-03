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
from maistro.runs.model import Attempt, NodeRun
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro_design.packs import (
    DomainPack,
    ExecuteBackend,
    GoalRubricCatalog,
    PackId,
    PackManifestError,
    PackRegistry,
    PackRegistryError,
    PackSummary,
    UnknownPackError,
    pack_graph_template,
    parse_manifest,
)
from maistro_design.packs import registry as packs_registry

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
            "name": "Broken",
            "explore_focus": ["x"],
            "execute_backends": ["builders"],
            "artifact_kinds": ["a"],
            "rubric_dimensions": [{"dimension_id": "d", "name": "D"}],
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
            "name": "Unfenced",
            "explore_focus": ["x"],
            "execute_backends": ["builders"],
            "artifact_kinds": ["a"],
            "rubric_dimensions": [{"dimension_id": "d", "name": "D"}],
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
                    "rubric_dimensions": [{"dimension_id": "d", "name": "D"}],
                    "graph": graph,
                }
            )

    @staticmethod
    def _valid_pack_dict() -> dict[str, Any]:
        """A minimal contract-satisfying pack dict, for one-mutation boundaries."""
        return {
            "pack_id": "product",
            "name": "Boundary Pack",
            "explore_focus": ["x"],
            "execute_backends": ["builders"],
            "artifact_kinds": ["a"],
            "rubric_dimensions": [{"dimension_id": "d", "name": "D"}],
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
            {"dimension_id": "d", "name": "D"},
            {"dimension_id": "d", "name": "D again"},
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

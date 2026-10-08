"""Installable domain-pack contracts (#966, M9-F1) — the canonical-object proof.

Issue-acceptance mapping (each test class names the criterion it proves):

- AC-1 "two out-of-tree packs can install side-by-side and instantiate
  canonical objects" → `TestSideBySideInstall`
- AC-2 "pack assets are version-addressable and retain publisher/version
  provenance" → `TestVersionAddressableProvenance`
- AC-3 "pack-local IDs cannot replace canonical object IDs after
  instantiation" → `TestCanonicalIdentityWins`
- AC-4 "pack disable stops new use without deleting historical objects or
  Runs" → `TestDisableStopsNewUseOnly`
- AC-5 "dependencies are resolved through M9 compatibility machinery" →
  `TestCompatibilityThroughM9Machinery`
- AC-6 "no pack introduces a product-private executor, Goal store, Persona
  store, or Rubric authority" → `TestNoPrivateAuthority`

`TestManifestInspection` pins the fail-closed parse matrix, including the
inspection-time canonical probe: every asset payload is constructed as the
canonical object it declares (GraphTemplate / Persona / RubricSemantic) and
discarded, so a pack cannot carry a payload canonical validation refuses.

The Graph execution fixtures follow the established durable-runs pattern
(`tests/graph/durable_runs/`, reused by `maistro-design` #793): deterministic
stub node classes + the real `run_durable_graph` executor + an
`InMemoryDurableRunStore`. What is proven is that out-of-tree pack assets are
ordinary canonical objects — same GraphTemplate model, same Run/NodeRun/
Attempt spine, no second identity scheme anywhere.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.extensions.compatibility import (
    CompatibilityPolicy,
    evaluate_compatibility,
)
from maistro.extensions.packs import (
    SUPPORTED_PACK_MANIFEST_VERSION,
    InstallablePackRegistry,
    PackAssetUnknown,
    PackDisabledError,
    PackIdentityConflict,
    PackIncompatible,
    PackInstallRecord,
    PackManifest,
    PackManifestRejected,
    PackState,
    evaluate_pack_compatibility,
    inspect_pack_manifest,
    instantiate_graph_asset,
    instantiate_persona_asset,
    instantiate_rubric_asset,
    pack_extension_view,
)
from maistro.graph.definitions import GraphTemplate
from maistro.graph.durable_runs import InMemoryDurableRunStore, RunStatus
from maistro.graph.durable_runs.attempt_executor import run_durable_graph
from maistro.graph.nodes import BaseNode, NodeContext
from maistro.ontology.rubric import ProvenanceOrigin, RubricSemantic
from maistro.personas.model import Persona
from maistro.runs.model import Attempt, NodeRun
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

WORKSPACE_ID = "ws-966-packs"
PROJECT_ID = "proj-966-packs"
GOAL_ID = "goal-966-shared"
GOAL_REVISION = 3


# --- Out-of-tree pack fixtures ------------------------------------------------


def _graph_asset(
    asset_id: str = "critique-graph",
    version: str = "1.0.0",
    *,
    explore_kind: str = "pack.explore",
    execute_kind: str = "pack.execute",
) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "version": version,
        "kind": "graph",
        "graph": {
            "name": "Critique loop",
            "description": "explore → execute",
            "entry_node": "explore",
            "nodes": [
                {"node_id": "explore", "node_type": explore_kind, "name": "Explore"},
                {"node_id": "execute", "node_type": execute_kind, "name": "Execute"},
            ],
            "edges": [["explore", "execute"]],
        },
    }


def _persona_asset(asset_id: str = "critic", version: str = "1.0.0") -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "version": version,
        "kind": "persona",
        "persona": {
            "name": "The Critic",
            "purpose": "judge scenes against the rubric",
            "style_guidance": "specific, evidence-first",
            "surfaces": ["ui"],
            "defaults": {"tone": "dry"},
            "behavior": {"ask_before_override": True},
        },
    }


def _rubric_asset(asset_id: str = "scene", version: str = "1.0.0") -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "version": version,
        "kind": "rubric",
        "rubric": {
            "name": "Scene rubric",
            "gate_pass_threshold": 70.0,
            "dimensions": [
                {
                    "id": "pace",
                    "name": "Pace",
                    "weight": 0.6,
                    "method": "model_judge",
                    "scale": {"numeric": {"min_value": 0, "max_value": 100}},
                },
                {
                    "id": "voice",
                    "name": "Voice consistency",
                    "weight": 0.4,
                    "method": "human",
                    "scale": {"pass_fail": {}},
                },
            ],
            "veto_dimension_ids": ["voice"],
        },
    }


def _pack_bytes(
    *,
    pack_id: str,
    publisher: str,
    version: str = "1.0.0",
    api_version: str = "1.0.0",
    assets: list[dict[str, Any]] | None = None,
    capabilities: list[str] | None = None,
    dependencies: list[dict[str, str]] | None = None,
    **extra: Any,
) -> bytes:
    document: dict[str, Any] = {
        "manifest_version": SUPPORTED_PACK_MANIFEST_VERSION,
        "kind": "domain-pack",
        "pack_id": pack_id,
        "name": pack_id,
        "version": version,
        "publisher": publisher,
        "api_version": api_version,
        "assets": assets
        if assets is not None
        else [_graph_asset(), _persona_asset(), _rubric_asset()],
    }
    if capabilities is not None:
        document["capabilities"] = capabilities
    if dependencies is not None:
        document["dependencies"] = dependencies
    document.update(extra)
    return json.dumps(document).encode()


ACME_PACK = _pack_bytes(
    pack_id="acme.film_critique",
    publisher="acme",
    capabilities=["run.read"],
)
VERTEX_PACK = _pack_bytes(
    pack_id="vertex.product_lab",
    publisher="vertex",
    version="2.1.0",
    assets=[
        _graph_asset("lab-graph", "2.1.0", explore_kind="pack.explore"),
        _persona_asset("pm"),
        _rubric_asset("launch"),
    ],
)


def _active_registry(**kwargs: Any) -> InstallablePackRegistry:
    registry = InstallablePackRegistry(platform_api_version="1.0.0", **kwargs)
    registry.install(ACME_PACK)
    registry.install(VERTEX_PACK)
    return registry


# --- Canonical execution fixtures: deterministic phase stubs ----------------


class _TextIn(BaseModel):
    text: str = ""


class _TextOut(_TextIn):
    text: str


class _ExploreNode(BaseNode):
    kind: ClassVar[str] = "pack.explore"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type] = _TextIn
    output_schema: ClassVar[type] = _TextOut

    async def _execute(self, inputs: _TextIn, ctx: NodeContext) -> _TextOut:
        return _TextOut(text=inputs.text)


class _ExecuteNode(BaseNode):
    kind: ClassVar[str] = "pack.execute"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type] = _TextIn
    output_schema: ClassVar[type] = _TextOut

    async def _execute(self, inputs: _TextIn, ctx: NodeContext) -> _TextOut:
        return _TextOut(text=inputs.text)


_STUB_KINDS: dict[str, type[BaseNode[Any, Any]]] = {
    stub.kind: stub for stub in (_ExploreNode, _ExecuteNode)
}


def _stub_resolver(node_id: str, graph: Any) -> BaseNode[Any, Any]:
    node_type = next(node.node_type for node in graph.nodes if node.node_id == node_id)
    stub = _STUB_KINDS.get(node_type)
    if stub is None:
        raise KeyError(f"no stub executor for node kind {node_type!r}")
    return stub()


# --- AC-1: two out-of-tree packs, side by side, canonical objects ------------


class TestSideBySideInstall:
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_two_publishers_install_into_one_registry(self) -> None:
        registry = _active_registry()
        records = registry.records()
        assert [record.manifest.pack_id for record in records] == [
            "acme.film_critique",
            "vertex.product_lab",
        ]
        assert all(record.state is PackState.ACTIVE for record in records)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_both_packs_instantiate_canonical_objects_into_one_workspace(self) -> None:
        registry = _active_registry()
        template_a = registry.instantiate_graph(
            "acme.film_critique", "critique-graph", workspace_id=WORKSPACE_ID
        )
        template_b = registry.instantiate_graph(
            "vertex.product_lab", "lab-graph", workspace_id=WORKSPACE_ID
        )
        persona_a = registry.instantiate_persona(
            "acme.film_critique", "critic", workspace_id=WORKSPACE_ID
        )
        persona_b = registry.instantiate_persona(
            "vertex.product_lab", "pm", workspace_id=WORKSPACE_ID
        )
        rubric_a = registry.instantiate_rubric(
            "acme.film_critique",
            "scene",
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            authored_by="principal-1",
        )
        rubric_b = registry.instantiate_rubric(
            "vertex.product_lab",
            "launch",
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            authored_by="principal-1",
        )

        # Every object is the canonical model, bound to the one Workspace.
        for template in (template_a, template_b):
            assert isinstance(template, GraphTemplate)
            assert template.workspace_id == WORKSPACE_ID
        for persona in (persona_a, persona_b):
            assert isinstance(persona, Persona)
            assert persona.workspace_id == WORKSPACE_ID
        for rubric in (rubric_a, rubric_b):
            assert isinstance(rubric, RubricSemantic)
            assert (rubric.workspace_id, rubric.project_id) == (WORKSPACE_ID, PROJECT_ID)
            assert rubric.goal_id == GOAL_ID and rubric.goal_revision == GOAL_REVISION
        # Side-by-side means distinct identities, not shared ones.
        assert template_a.template_id != template_b.template_id
        assert persona_a.id != persona_b.id
        assert rubric_a.rubric_id != rubric_b.rubric_id

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    @pytest.mark.parametrize(
        ("pack_id", "asset_id"),
        [("acme.film_critique", "critique-graph"), ("vertex.product_lab", "lab-graph")],
    )
    async def test_pack_graph_assets_execute_the_canonical_spine(
        self, pack_id: str, asset_id: str
    ) -> None:
        registry = _active_registry()
        template = registry.instantiate_graph(pack_id, asset_id, workspace_id=WORKSPACE_ID)
        graph = template.instantiate(project_id=PROJECT_ID)
        record = await run_durable_graph(
            graph,
            store=InMemoryDurableRunStore(),
            node_resolver=_stub_resolver,
            inputs={"text": f"brief for {pack_id}"},
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
            provenance={"goal_id": GOAL_ID, "goal_revision": GOAL_REVISION},
        )
        # Canonical Run/NodeRun/Attempt identity, terminal in the canonical
        # lifecycle — the pack minted no identity of its own.
        assert record.run.status is RunStatus.COMPLETED
        assert record.run.workspace_id == WORKSPACE_ID
        assert record.run.project_id == PROJECT_ID
        assert record.run.provenance["goal_id"] == GOAL_ID
        assert len(record.node_runs) == len(template.nodes)
        assert all(node_run.run_id == record.run.run_id for node_run in record.node_runs)
        node_run_ids = {node_run.node_run_id for node_run in record.node_runs}
        assert all(isinstance(node_run, NodeRun) for node_run in record.node_runs)
        assert all(isinstance(attempt, Attempt) for attempt in record.attempts)
        assert all(attempt.node_run_id in node_run_ids for attempt in record.attempts)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_a_pack_can_ship_only_the_kinds_it_needs(self) -> None:
        registry = InstallablePackRegistry(platform_api_version="1.0.0")
        record = registry.install(
            _pack_bytes(
                pack_id="solo.rubrics",
                publisher="solo",
                assets=[_rubric_asset("only")],
            )
        )
        assert record.manifest.assets[0].asset_id == "only"


# --- AC-2: version-addressable assets with publisher/version provenance ------


class TestVersionAddressableProvenance:
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_assets_resolve_at_exact_declared_versions(self) -> None:
        registry = _active_registry()
        manifest = registry.record("vertex.product_lab").manifest
        asset = manifest.asset("lab-graph", "2.1.0")
        assert asset.version == "2.1.0"
        with pytest.raises(PackAssetUnknown):
            manifest.asset("lab-graph", "9.9.9")
        with pytest.raises(PackAssetUnknown):
            manifest.asset("no-such-asset")

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_multiple_versions_of_one_asset_stay_addressable(self) -> None:
        registry = InstallablePackRegistry(platform_api_version="1.0.0")
        registry.install(
            _pack_bytes(
                pack_id="acme.film_critique",
                publisher="acme",
                assets=[
                    _graph_asset("critique-graph", "1.0.0"),
                    _graph_asset("critique-graph", "1.1.0"),
                ],
            )
        )
        manifest = registry.record("acme.film_critique").manifest
        assert manifest.asset("critique-graph", "1.0.0").version == "1.0.0"
        assert manifest.asset("critique-graph", "1.1.0").version == "1.1.0"
        # Unpinned resolution is deterministic: the highest version.
        assert manifest.asset("critique-graph").version == "1.1.0"

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_instantiated_objects_carry_publisher_and_version_provenance(self) -> None:
        registry = _active_registry()
        template = registry.instantiate_graph(
            "acme.film_critique", "critique-graph", workspace_id=WORKSPACE_ID
        )
        persona = registry.instantiate_persona(
            "acme.film_critique", "critic", workspace_id=WORKSPACE_ID
        )
        rubric = registry.instantiate_rubric(
            "acme.film_critique",
            "scene",
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            authored_by="principal-1",
        )

        pack_meta = template.metadata["pack"]
        assert pack_meta["pack.id"] == "acme.film_critique"
        assert pack_meta["pack.publisher"] == "acme"
        assert pack_meta["pack.version"] == "1.0.0"
        assert len(pack_meta["pack.manifest_sha256"]) == 64
        assert template.metadata["pack.asset_version"] == "1.0.0"

        assert persona.source_template_version == "1.0.0"
        persona_meta = persona.extension_metadata["pack"]
        assert persona_meta["pack.publisher"] == "acme"
        assert persona_meta["pack.manifest_sha256"] == pack_meta["pack.manifest_sha256"]

        assert rubric.provenance.origin is ProvenanceOrigin.PACK
        assert rubric.provenance.pack_id == "acme.film_critique"

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_versions_install_side_by_side_and_stay_individually_addressable(
        self,
    ) -> None:
        registry = InstallablePackRegistry(platform_api_version="1.0.0")
        registry.install(
            _pack_bytes(pack_id="acme.film_critique", publisher="acme", version="1.0.0")
        )
        registry.install(
            _pack_bytes(pack_id="acme.film_critique", publisher="acme", version="1.1.0")
        )
        assert registry.record("acme.film_critique", "1.0.0").manifest.version == "1.0.0"
        assert registry.record("acme.film_critique", "1.1.0").manifest.version == "1.1.0"
        assert len(registry.records()) == 2

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_reinstalling_identical_bytes_is_idempotent(self) -> None:
        registry = InstallablePackRegistry(platform_api_version="1.0.0")
        first = registry.install(ACME_PACK)
        second = registry.install(ACME_PACK)
        assert first is second
        assert len(registry.records()) == 1


# --- AC-3: pack-local ids never become canonical ids -------------------------


class TestCanonicalIdentityWins:
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_pack_local_ids_never_become_canonical_object_ids(self) -> None:
        registry = _active_registry()
        template = registry.instantiate_graph(
            "acme.film_critique", "critique-graph", workspace_id=WORKSPACE_ID
        )
        persona = registry.instantiate_persona(
            "acme.film_critique", "critic", workspace_id=WORKSPACE_ID
        )
        rubric = registry.instantiate_rubric(
            "acme.film_critique",
            "scene",
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            authored_by="principal-1",
        )
        # Canonical ids are canonical mints; the pack-local names survive only
        # in provenance, never as identity.
        assert template.template_id != "critique-graph"
        assert persona.id != "critic"
        assert rubric.rubric_id != "scene"
        assert template.template_id not in {"critique-graph", "acme.film_critique"}
        assert persona.source_template_id == "pack:acme.film_critique:critic"
        assert persona.source_template_id != persona.id

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_each_instantiation_mints_a_distinct_canonical_identity(self) -> None:
        registry = _active_registry()
        first = registry.instantiate_persona(
            "acme.film_critique", "critic", workspace_id=WORKSPACE_ID
        )
        second = registry.instantiate_persona(
            "acme.film_critique", "critic", workspace_id=WORKSPACE_ID
        )
        assert first.id != second.id

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_the_caller_supplies_canonical_identity_when_it_must_pin_one(self) -> None:
        registry = _active_registry()
        template = registry.instantiate_graph(
            "acme.film_critique",
            "critique-graph",
            workspace_id=WORKSPACE_ID,
            template_id="template-caller-pinned",
        )
        persona = registry.instantiate_persona(
            "acme.film_critique",
            "critic",
            workspace_id=WORKSPACE_ID,
            persona_id="persona-caller-pinned",
        )
        rubric = registry.instantiate_rubric(
            "acme.film_critique",
            "scene",
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            authored_by="principal-1",
            rubric_id="rubric-caller-pinned",
        )
        assert template.template_id == "template-caller-pinned"
        assert persona.id == "persona-caller-pinned"
        assert rubric.rubric_id == "rubric-caller-pinned"


# --- AC-4: disable stops new use, deletes nothing ----------------------------


class TestDisableStopsNewUseOnly:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    def test_disable_refuses_every_instantiation_of_that_pack(self) -> None:
        registry = _active_registry()
        registry.disable("acme.film_critique", note="operator hold")
        for call in (
            lambda: registry.instantiate_graph(
                "acme.film_critique", "critique-graph", workspace_id=WORKSPACE_ID
            ),
            lambda: registry.instantiate_persona(
                "acme.film_critique", "critic", workspace_id=WORKSPACE_ID
            ),
            lambda: registry.instantiate_rubric(
                "acme.film_critique",
                "scene",
                goal_id=GOAL_ID,
                goal_revision=GOAL_REVISION,
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                authored_by="principal-1",
            ),
        ):
            with pytest.raises(PackDisabledError, match="operator hold"):
                call()
        # The other pack is untouched.
        template = registry.instantiate_graph(
            "vertex.product_lab", "lab-graph", workspace_id=WORKSPACE_ID
        )
        assert template.workspace_id == WORKSPACE_ID

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_disable_deletes_nothing(self) -> None:
        registry = _active_registry()
        record_before = registry.record("acme.film_critique")
        registry.disable("acme.film_critique")
        # The record and its immutable manifest snapshot remain queryable.
        record_after = registry.record("acme.film_critique")
        assert record_after.state is PackState.DISABLED
        assert record_after.manifest is record_before.manifest
        assert record_after.manifest.raw == record_before.manifest.raw
        assert record_after.installed_at == record_before.installed_at

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_objects_instantiated_before_disable_survive_untouched(self) -> None:
        registry = _active_registry()
        template = registry.instantiate_graph(
            "acme.film_critique", "critique-graph", workspace_id=WORKSPACE_ID
        )
        graph = template.instantiate(project_id=PROJECT_ID)
        historical = await run_durable_graph(
            graph,
            store=InMemoryDurableRunStore(),
            node_resolver=_stub_resolver,
            inputs={"text": "before the hold"},
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
        assert historical.run.status is RunStatus.COMPLETED

        registry.disable("acme.film_critique")

        # The historical template still instantiates Runs and the completed
        # record is unchanged: disable is a use gate, not a deletion.
        graph_after = template.instantiate(project_id=PROJECT_ID)
        late = await run_durable_graph(
            graph_after,
            store=InMemoryDurableRunStore(),
            node_resolver=_stub_resolver,
            inputs={"text": "historical template, later run"},
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
        assert late.run.status is RunStatus.COMPLETED
        assert historical.run.run_id != late.run.run_id
        assert historical.run.status is RunStatus.COMPLETED

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_activate_restores_new_use(self) -> None:
        registry = _active_registry()
        registry.disable("acme.film_critique")
        registry.activate("acme.film_critique")
        template = registry.instantiate_graph(
            "acme.film_critique", "critique-graph", workspace_id=WORKSPACE_ID
        )
        assert template.workspace_id == WORKSPACE_ID

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_disable_can_pin_one_version_of_a_pack(self) -> None:
        registry = InstallablePackRegistry(platform_api_version="1.0.0")
        registry.install(
            _pack_bytes(pack_id="acme.film_critique", publisher="acme", version="1.0.0")
        )
        registry.install(
            _pack_bytes(pack_id="acme.film_critique", publisher="acme", version="1.1.0")
        )
        registry.disable("acme.film_critique", version="1.0.0")
        assert registry.record("acme.film_critique", "1.0.0").state is PackState.DISABLED
        assert registry.record("acme.film_critique", "1.1.0").state is PackState.ACTIVE
        # Unpinned new use resolves to the highest *active* version.
        manifest = registry.active_manifest("acme.film_critique")
        assert manifest.version == "1.1.0"


# --- AC-5: dependencies resolve through the M9 machinery ---------------------


class TestCompatibilityThroughM9Machinery:
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_resolution_is_literally_the_m9_evaluator(self) -> None:
        manifest = inspect_pack_manifest(
            _pack_bytes(
                pack_id="acme.film_critique",
                publisher="acme",
                dependencies=[{"id": "vertex.product_lab", "range": "^2.0.0"}],
            )
        )
        policy = CompatibilityPolicy(
            platform_api_version="1.0.0",
            installed_versions={"vertex.product_lab": "2.1.0"},
        )
        assert evaluate_pack_compatibility(manifest, policy) == evaluate_compatibility(
            pack_extension_view(manifest), policy
        )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_missing_dependency_is_refused_at_install(self) -> None:
        registry = InstallablePackRegistry(platform_api_version="1.0.0")
        with pytest.raises(PackIncompatible, match=r"missing dependency: vertex\.product_lab"):
            registry.install(
                _pack_bytes(
                    pack_id="acme.film_critique",
                    publisher="acme",
                    dependencies=[{"id": "vertex.product_lab", "range": "^2.0.0"}],
                )
            )
        assert registry.records() == ()

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_dependency_on_another_installed_pack_is_satisfied(self) -> None:
        registry = InstallablePackRegistry(platform_api_version="1.0.0")
        registry.install(VERTEX_PACK)
        record = registry.install(
            _pack_bytes(
                pack_id="acme.film_critique",
                publisher="acme",
                dependencies=[{"id": "vertex.product_lab", "range": "^2.0.0"}],
            )
        )
        assert record.state is PackState.ACTIVE

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_dependency_resolution_is_independent_of_install_order(self) -> None:
        # Several versions install side by side, but the evaluator resolves a
        # dependency id against one version: the highest active one — the same
        # default lookup everywhere else in the registry. Installing v1 after
        # v2 must not make a ^2.0.0 dependent fail; insertion order is not
        # resolution order.
        for install_order in (("2.1.0", "1.0.0"), ("1.0.0", "2.1.0")):
            registry = InstallablePackRegistry(platform_api_version="1.0.0")
            for version in install_order:
                registry.install(
                    _pack_bytes(
                        pack_id="vertex.product_lab",
                        publisher="vertex",
                        version=version,
                    )
                )
            record = registry.install(
                _pack_bytes(
                    pack_id="acme.film_critique",
                    publisher="acme",
                    dependencies=[{"id": "vertex.product_lab", "range": "^2.0.0"}],
                )
            )
            assert record.state is PackState.ACTIVE

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_dependency_on_a_plain_extension_is_satisfied(self) -> None:
        # Capability providers are extensions installed through the M9-B2
        # service; a pack names them exactly like any other dependency.
        registry = InstallablePackRegistry(
            platform_api_version="1.0.0",
            active_extensions={"acme.capability_core": "1.4.0"},
        )
        record = registry.install(
            _pack_bytes(
                pack_id="acme.film_critique",
                publisher="acme",
                dependencies=[{"id": "acme.capability_core", "range": "^1.0.0"}],
            )
        )
        assert record.state is PackState.ACTIVE

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_api_version_major_mismatch_is_refused(self) -> None:
        registry = InstallablePackRegistry(platform_api_version="1.0.0")
        with pytest.raises(PackIncompatible, match="api_version major mismatch"):
            registry.install(
                _pack_bytes(pack_id="acme.film_critique", publisher="acme", api_version="2.0.0")
            )
        assert registry.records() == ()

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_dependency_range_grammar_stays_the_m9_grammar(self) -> None:
        registry = InstallablePackRegistry(platform_api_version="1.0.0")
        registry.install(VERTEX_PACK)
        # An unknown range grammar fails closed, exactly as the M9 evaluator
        # treats it: unsatisfiable, never leniently matched.
        with pytest.raises(PackIncompatible, match="does not satisfy"):
            registry.install(
                _pack_bytes(
                    pack_id="acme.film_critique",
                    publisher="acme",
                    dependencies=[{"id": "vertex.product_lab", "range": "~2.0.0"}],
                )
            )


# --- AC-6: no private executor, store, or authority --------------------------


class TestNoPrivateAuthority:
    @pytest.mark.parametrize(
        "smuggled_key",
        [
            "executor",
            "goal_store",
            "persona_store",
            "rubric_authority",
            "run_store",
            "stores",
            "authority",
            "permissions",
        ],
    )
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_the_manifest_schema_has_no_authority_field(self, smuggled_key: str) -> None:
        # A pack cannot declare an executor, a store, or an authority: the
        # schema is closed, so the field is an unknown-key rejection, never an
        # ignored line the operator never saw.
        with pytest.raises(PackManifestRejected, match="unknown manifest keys"):
            inspect_pack_manifest(
                _pack_bytes(pack_id="acme.film_critique", publisher="acme", **{smuggled_key: {}})
            )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_execution_state_cannot_smuggle_into_a_graph_asset(self) -> None:
        # The R12 runtime-state scan runs at inspection through the canonical
        # probe: a template carrying one execution's state would replay it.
        smuggled = _pack_bytes(
            pack_id="acme.film_critique",
            publisher="acme",
            assets=[
                {
                    "asset_id": "critique-graph",
                    "version": "1.0.0",
                    "kind": "graph",
                    "graph": {
                        "name": "Smuggler",
                        "nodes": [{"node_id": "explore", "node_type": "pack.explore"}],
                        "edges": [],
                        "entry_node": "explore",
                    },
                }
            ],
        )
        document = json.loads(smuggled)
        document["assets"][0]["graph"]["nodes"][0]["run_id"] = "run-replay-attack"
        with pytest.raises(PackManifestRejected):
            inspect_pack_manifest(json.dumps(document).encode())

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_instantiation_is_pure_and_persistence_stays_canonical(self) -> None:
        registry = _active_registry()
        template = registry.instantiate_graph(
            "acme.film_critique", "critique-graph", workspace_id=WORKSPACE_ID
        )
        persona = registry.instantiate_persona(
            "acme.film_critique", "critic", workspace_id=WORKSPACE_ID
        )
        # Instantiation returns plain canonical objects the caller persists
        # through canonical stores (the durable-runs tests execute exactly
        # that path); the registry itself keeps only manifest records and
        # their use state — no stores, no executors, no object authority.
        assert isinstance(template, GraphTemplate)
        assert isinstance(persona, Persona)
        for record in registry.records():
            assert isinstance(record, PackInstallRecord)
            assert isinstance(record.manifest, PackManifest)
        assert not any(
            name.startswith(("store", "executor", "goal", "persona", "rubric"))
            for name in dir(registry)
            if not name.startswith("_")
        )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_rubric_provenance_names_the_pack_as_supplier_not_owner(self) -> None:
        registry = _active_registry()
        rubric = registry.instantiate_rubric(
            "acme.film_critique",
            "scene",
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            authored_by="principal-1",
        )
        # The pack supplied defaults; identity and revision ownership are the
        # canonical Rubric store's — provenance records the supplier only.
        assert rubric.provenance.origin is ProvenanceOrigin.PACK
        assert rubric.provenance.pack_id == "acme.film_critique"
        assert rubric.provenance.authored_by == "principal-1"
        assert rubric.revision == 1

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_a_pack_cannot_ship_another_publishers_identity(self) -> None:
        with pytest.raises(PackManifestRejected, match="own publisher namespace"):
            inspect_pack_manifest(_pack_bytes(pack_id="vertex.film_critique", publisher="acme"))


# --- Fail-closed manifest inspection ----------------------------------------


class TestManifestInspection:
    def _rejected(self, raw: bytes, match: str) -> None:
        with pytest.raises(PackManifestRejected, match=match):
            inspect_pack_manifest(raw)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_valid_manifest_round_trips(self) -> None:
        manifest = inspect_pack_manifest(ACME_PACK)
        assert manifest.pack_id == "acme.film_critique"
        assert manifest.version == "1.0.0"
        assert manifest.publisher == "acme"
        assert manifest.kind == "domain-pack"
        assert manifest.capabilities == ("run.read",)
        assert [asset.asset_id for asset in manifest.assets] == [
            "critique-graph",
            "critic",
            "scene",
        ]
        assert manifest.source_sha256 == hashlib.sha256(ACME_PACK).hexdigest()

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_not_json_is_rejected(self) -> None:
        self._rejected(b"not json at all", "not valid UTF-8 JSON")

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_non_object_document_is_rejected(self) -> None:
        self._rejected(b"[1, 2]", "top-level document must be an object")

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_unsupported_envelope_version_is_rejected(self) -> None:
        document = json.loads(ACME_PACK)
        document["manifest_version"] = 2
        self._rejected(json.dumps(document).encode(), "unsupported manifest_version: 2")

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_manifest_version_must_be_a_literal_integer(self) -> None:
        # Python's `True == 1` and `1.0 == 1`: an equality-only check accepts
        # both as the supported version and the snapshot silently normalizes
        # the malformed value. The envelope must refuse non-integers by type.
        for forged in (True, 1.0):
            document = json.loads(ACME_PACK)
            document["manifest_version"] = forged
            self._rejected(
                json.dumps(document).encode(),
                "manifest_version must be an integer",
            )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_wrong_subtype_is_rejected(self) -> None:
        document = json.loads(ACME_PACK)
        document["kind"] = "ui-pack"
        self._rejected(json.dumps(document).encode(), "unsupported manifest kind: 'ui-pack'")

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_missing_required_keys_is_rejected(self) -> None:
        document = json.loads(ACME_PACK)
        del document["publisher"]
        self._rejected(json.dumps(document).encode(), "missing manifest keys")

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_pack_id_must_be_publisher_namespaced(self) -> None:
        self._rejected(
            _pack_bytes(pack_id="film_critique", publisher="acme"),
            "pack_id must be publisher.name",
        )
        self._rejected(
            _pack_bytes(pack_id="acme.film.critique", publisher="acme"),
            "pack_id must be publisher.name",
        )
        self._rejected(
            _pack_bytes(pack_id="pub-1.film-critique", publisher="pub-1"),
            "pack_id name segment must be a slug",
        )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_hyphenated_publisher_slug_is_accepted(self) -> None:
        # Publisher slugs follow the extension-manifest grammar, so a
        # publisher like ``pub-1`` must be able to namespace its packs.
        accepted = _pack_bytes(pack_id="pub-1.film_critique", publisher="pub-1")
        manifest = inspect_pack_manifest(accepted)
        assert manifest.pack_id == "pub-1.film_critique"
        assert manifest.publisher == "pub-1"

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_semver_fields_are_strict(self) -> None:
        self._rejected(
            _pack_bytes(pack_id="acme.film_critique", publisher="acme", version="1.0"),
            "version must be semver",
        )
        self._rejected(
            _pack_bytes(pack_id="acme.film_critique", publisher="acme", api_version="v1"),
            "api_version must be semver",
        )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_duplicate_and_malformed_capabilities_are_rejected(self) -> None:
        self._rejected(
            _pack_bytes(
                pack_id="acme.film_critique",
                publisher="acme",
                capabilities=["run.read", "run.read"],
            ),
            "duplicate capability",
        )
        self._rejected(
            _pack_bytes(pack_id="acme.film_critique", publisher="acme", capabilities=["Run Read"]),
            "malformed capability token",
        )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_duplicate_dependencies_are_rejected(self) -> None:
        dependency = {"id": "vertex.product_lab", "range": "*"}
        self._rejected(
            _pack_bytes(
                pack_id="acme.film_critique",
                publisher="acme",
                dependencies=[dependency, dict(dependency)],
            ),
            "duplicate dependency",
        )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_duplicate_asset_identity_is_rejected(self) -> None:
        self._rejected(
            _pack_bytes(
                pack_id="acme.film_critique",
                publisher="acme",
                assets=[_graph_asset(), _graph_asset()],
            ),
            "duplicate asset identity",
        )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_unknown_or_mismatched_asset_payload_is_rejected(self) -> None:
        asset = _graph_asset()
        asset["persona"] = _persona_asset()["persona"]
        self._rejected(
            _pack_bytes(pack_id="acme.film_critique", publisher="acme", assets=[asset]),
            "must declare exactly the 'graph' payload",
        )
        bare = {"asset_id": "x", "version": "1.0.0", "kind": "rubric"}
        self._rejected(
            _pack_bytes(pack_id="acme.film_critique", publisher="acme", assets=[bare]),
            "must declare exactly the 'rubric' payload",
        )
        self._rejected(
            _pack_bytes(
                pack_id="acme.film_critique",
                publisher="acme",
                assets=[{**_graph_asset(), "kind": "workflow"}],
            ),
            "unknown asset kind: 'workflow'",
        )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_graph_payload_structure_is_rejected_fail_closed(self) -> None:
        def with_graph(graph: dict[str, Any]) -> bytes:
            return _pack_bytes(
                pack_id="acme.film_critique",
                publisher="acme",
                assets=[
                    {
                        "asset_id": "g",
                        "version": "1.0.0",
                        "kind": "graph",
                        "graph": graph,
                    }
                ],
            )

        self._rejected(
            with_graph({"nodes": [{"node_id": "a", "node_type": "t"}], "edges": []}),
            "missing graph payload keys",
        )
        self._rejected(
            with_graph({"nodes": [{"node_type": "t"}], "edges": [], "name": "g"}),
            "missing graph node keys",
        )
        self._rejected(
            with_graph({"nodes": [{}], "edges": [], "name": "g"}),
            "missing graph node keys: \\['node_id', 'node_type'\\]",
        )
        self._rejected(
            with_graph(
                {
                    "name": "g",
                    "nodes": [],
                    "edges": [],
                }
            ),
            "graph nodes must be a non-empty list",
        )
        self._rejected(
            with_graph(
                {
                    "name": "g",
                    "nodes": [
                        {"node_id": "a", "node_type": "t"},
                        {"node_id": "a", "node_type": "t"},
                    ],
                    "edges": [],
                }
            ),
            "duplicate graph node_id",
        )
        self._rejected(
            with_graph(
                {
                    "name": "g",
                    "nodes": [{"node_id": "a", "node_type": "t"}],
                    "edges": [["a", "ghost"]],
                }
            ),
            "is not a node of this graph",
        )
        self._rejected(
            with_graph(
                {
                    "name": "g",
                    "entry_node": "ghost",
                    "nodes": [{"node_id": "a", "node_type": "t"}],
                    "edges": [],
                }
            ),
            "entry_node 'ghost' is not a node",
        )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_persona_payload_is_rejected_fail_closed(self) -> None:
        self._rejected(
            _pack_bytes(
                pack_id="acme.film_critique",
                publisher="acme",
                assets=[
                    {
                        "asset_id": "p",
                        "version": "1.0.0",
                        "kind": "persona",
                        "persona": {"purpose": "no name"},
                    }
                ],
            ),
            "missing persona payload keys",
        )
        self._rejected(
            _pack_bytes(
                pack_id="acme.film_critique",
                publisher="acme",
                assets=[
                    {
                        "asset_id": "p",
                        "version": "1.0.0",
                        "kind": "persona",
                        "persona": {"name": "Critic", "surfaces": ["  "]},
                    }
                ],
            ),
            "persona surfaces must be non-empty",
        )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_rubric_payload_is_rejected_fail_closed(self) -> None:
        def with_rubric(rubric: dict[str, Any]) -> bytes:
            return _pack_bytes(
                pack_id="acme.film_critique",
                publisher="acme",
                assets=[
                    {
                        "asset_id": "r",
                        "version": "1.0.0",
                        "kind": "rubric",
                        "rubric": rubric,
                    }
                ],
            )

        dimensions = _rubric_asset()["rubric"]["dimensions"]
        self._rejected(
            with_rubric({"gate_pass_threshold": 1.0, "dimensions": dimensions}),
            "missing rubric payload keys",
        )
        self._rejected(
            with_rubric({"name": "r", "gate_pass_threshold": "high", "dimensions": dimensions}),
            "gate_pass_threshold must be a finite number",
        )
        self._rejected(
            with_rubric({"name": "r", "gate_pass_threshold": 1.0, "dimensions": []}),
            "rubric dimensions must be a non-empty list",
        )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_non_finite_rubric_numbers_are_rejected(self) -> None:
        # ``json.loads`` turns ``1e400``/``Infinity``/``NaN`` into non-finite
        # floats that ``gt=0``-style Pydantic bounds do not all catch, so every
        # pack-supplied scoring number is checked with ``math.isfinite``.
        def with_dimension(dimension: dict[str, Any]) -> bytes:
            rubric = _rubric_asset()["rubric"]
            rubric["dimensions"] = [dimension]
            return _pack_bytes(
                pack_id="acme.film_critique",
                publisher="acme",
                assets=[
                    {
                        "asset_id": "r",
                        "version": "1.0.0",
                        "kind": "rubric",
                        "rubric": rubric,
                    }
                ],
            )

        base = _rubric_asset()["rubric"]["dimensions"][0]
        cases: list[tuple[dict[str, Any], str]] = [
            (dict(base, weight=1e400), "rubric dimension weight must be a finite number"),
            (
                dict(base, weight=float("nan")),
                "rubric dimension weight must be a finite number",
            ),
            (
                dict(base, scale={"numeric": {"min_value": 0, "max_value": 1e400}}),
                "numeric max_value must be a finite number",
            ),
            (
                dict(base, scale={"pass_fail": {"pass_value": float("inf")}}),
                "pass_fail pass_value must be a finite number",
            ),
        ]
        for dimension, message in cases:
            self._rejected(with_dimension(dimension), message)

        rubric = _rubric_asset()["rubric"]
        rubric["gate_pass_threshold"] = 1e400
        self._rejected(
            _pack_bytes(
                pack_id="acme.film_critique",
                publisher="acme",
                assets=[{"asset_id": "r", "version": "1.0.0", "kind": "rubric", "rubric": rubric}],
            ),
            "rubric gate_pass_threshold must be a finite number",
        )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_evidence_required_must_be_a_json_boolean(self) -> None:
        # bool() coerces any truthy junk — `bool("false")` is True — so a
        # string must be refused rather than silently inverted or coerced.
        rubric = _rubric_asset()["rubric"]
        rubric["dimensions"][0]["evidence_required"] = "false"
        self._rejected(
            _pack_bytes(
                pack_id="acme.film_critique",
                publisher="acme",
                assets=[{"asset_id": "r", "version": "1.0.0", "kind": "rubric", "rubric": rubric}],
            ),
            "rubric evidence_required must be a boolean",
        )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_canonical_validation_refuses_what_the_models_refuse(self) -> None:
        # The canonical probe: a rubric whose veto names a non-dimension and a
        # numeric scale with min >= max both fail at inspection, via the
        # canonical models — not via pack-local re-implementations.
        dimensions = _rubric_asset()["rubric"]["dimensions"]
        inverted_scale = dict(_rubric_asset())
        inverted_scale["rubric"] = dict(inverted_scale["rubric"])
        inverted_scale["rubric"]["dimensions"] = [
            dict(dimensions[0], scale={"numeric": {"min_value": 100, "max_value": 0}})
        ]
        with pytest.raises(PackManifestRejected):
            inspect_pack_manifest(
                _pack_bytes(
                    pack_id="acme.film_critique",
                    publisher="acme",
                    assets=[inverted_scale],
                )
            )
        vetoed = dict(_rubric_asset())
        vetoed["rubric"] = dict(vetoed["rubric"], veto_dimension_ids=["no-such-dimension"])
        with pytest.raises(PackManifestRejected):
            inspect_pack_manifest(
                _pack_bytes(
                    pack_id="acme.film_critique",
                    publisher="acme",
                    assets=[vetoed],
                )
            )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_unknown_asset_or_version_in_instantiation_is_a_typed_error(self) -> None:
        manifest = inspect_pack_manifest(ACME_PACK)
        with pytest.raises(PackAssetUnknown):
            instantiate_graph_asset(manifest, "critique-graph", version="9.9.9", workspace_id="ws")
        with pytest.raises(PackAssetUnknown):
            instantiate_persona_asset(manifest, "not-an-asset", workspace_id="ws")
        with pytest.raises(PackAssetUnknown, match="is not a rubric asset"):
            instantiate_rubric_asset(
                manifest,
                "critique-graph",
                goal_id=GOAL_ID,
                goal_revision=1,
                workspace_id="ws",
                project_id="p",
                authored_by="principal-1",
            )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_same_version_different_bytes_is_an_identity_conflict(self) -> None:
        registry = InstallablePackRegistry(platform_api_version="1.0.0")
        registry.install(ACME_PACK)
        tampered = json.loads(ACME_PACK)
        tampered["name"] = "A Different Pack Wearing The Same Version"
        with pytest.raises(PackIdentityConflict, match="different manifest bytes"):
            registry.install(json.dumps(tampered).encode())


# --- Fail-closed refusal matrix: every degenerate parse/lookup path ----------


class TestInspectionRefusalMatrix:
    """Each refusal branch in ``packs.py`` answers with ITS OWN detail.

    The happy path and a handful of headline rejections are pinned by
    ``TestManifestInspection``; this matrix walks the rest of the fail-closed
    surface one branch at a time. Each case asserts the specific detail
    fragment — a test that only asserted "some rejection happened" would pass
    for the wrong reason the day the parser started refusing the wrong thing.
    """

    @staticmethod
    def _poisoned(pack_changes: dict[str, Any] | None = None) -> bytes:
        document = json.loads(ACME_PACK)
        document.update(pack_changes or {})
        return json.dumps(document).encode()

    @staticmethod
    def _poisoned_asset(asset_id: str, changes: dict[str, Any]) -> bytes:
        document = json.loads(ACME_PACK)
        for asset in document["assets"]:
            if asset["asset_id"] == asset_id:
                asset.update(changes)
                return json.dumps(document).encode()
        raise AssertionError(f"fixture bug: no asset {asset_id!r}")

    @staticmethod
    def _poisoned_payload(asset_id: str, changes: dict[str, Any]) -> bytes:
        document = json.loads(ACME_PACK)
        kind_keys = {"graph": "graph", "persona": "persona", "rubric": "rubric"}
        for asset in document["assets"]:
            if asset["asset_id"] == asset_id:
                payload_key = kind_keys[asset["kind"]]
                asset[payload_key].update(changes)
                return json.dumps(document).encode()
        raise AssertionError(f"fixture bug: no asset {asset_id!r}")

    @pytest.mark.parametrize(
        ("poison", "match"),
        [
            # -- envelope / identity -------------------------------------------------
            (lambda d: d.update({"name": ""}), r"name must be a non-empty string"),
            (lambda d: d.update({"assets": []}), r"assets must be a non-empty list"),
            (lambda d: d.update({"publisher": "Acme"}), r"malformed publisher id"),
            (lambda d: d.update({"dependencies": "a.b"}), r"dependencies must be a list"),
            (
                lambda d: d.update({"dependencies": [{"id": "a.b", "range": "*", "note": "x"}]}),
                r"exactly id and range",
            ),
            (
                lambda d: d.update({"dependencies": [{"id": "9bad", "range": "*"}]}),
                r"malformed dependency id",
            ),
            (
                lambda d: d.update({"dependencies": [{"id": "a.b", "range": "   "}]}),
                r"malformed dependency range for 'a\.b'",
            ),
            (lambda d: d.update({"capabilities": "run.read"}), r"capabilities must be a list"),
            # -- asset envelope ------------------------------------------------------
            (lambda d: d.update({"assets": ["graph"]}), r"each asset must be an object"),
            (
                lambda d: d.update(
                    {"assets": [_graph_asset(), {**_persona_asset(), "executor": "x"}]}
                ),
                r"unknown asset keys",
            ),
            (
                lambda d: d.update(
                    {"assets": [{k: v for k, v in _graph_asset().items() if k != "version"}]}
                ),
                r"missing asset keys",
            ),
            (
                lambda d: d.update(
                    {"assets": [_graph_asset(asset_id="Bad_ID"), _persona_asset(), _rubric_asset()]}
                ),
                r"malformed asset_id",
            ),
            (
                lambda d: d.update({"assets": [{**_persona_asset(), "kind": "graph"}]}),
                r"must declare exactly the 'graph' payload",
            ),
            # -- graph payload -------------------------------------------------------
            (
                lambda d: TestInspectionRefusalMatrix._swap_payload(d, "graph", "nope"),
                r"graph payload must be an object",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_payload(d, "graph", {"stores": {}}),
                r"unknown graph payload keys",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_payload(
                    d, "graph", {"description": 42}
                ),
                r"graph description must be a string",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_payload(
                    d, "graph", {"entry_node": 42}
                ),
                r"graph entry_node must be a non-empty string when present",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_payload(
                    d, "graph", {"nodes": [{"node_id": "Explore", "node_type": "pack.explore"}]}
                ),
                r"malformed graph node_id",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_payload(
                    d,
                    "graph",
                    {
                        "nodes": [
                            {"node_id": "explore", "node_type": "pack.explore", "name": 42},
                            {"node_id": "execute", "node_type": "pack.execute"},
                        ]
                    },
                ),
                r"graph node name must be a string",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_payload(d, "graph", {"edges": "x"}),
                r"graph edges must be a list",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_payload(
                    d, "graph", {"edges": [["explore"], ["execute"]]}
                ),
                r"each graph edge must be a \[from_node, to_node\] pair",
            ),
            # -- persona payload -----------------------------------------------------
            (
                lambda d: TestInspectionRefusalMatrix._swap_payload(d, "persona", "nope"),
                r"persona payload must be an object",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_payload(
                    d, "persona", {"persona_store": {}}
                ),
                r"unknown persona payload keys",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_payload(
                    d, "persona", {"surfaces": "ui"}
                ),
                r"persona surfaces must be a list of strings",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_payload(
                    d, "persona", {"defaults": ["x"]}
                ),
                r"persona defaults must be an object",
            ),
            # -- rubric payload ------------------------------------------------------
            (
                lambda d: TestInspectionRefusalMatrix._swap_payload(d, "rubric", "nope"),
                r"rubric payload must be an object",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_payload(
                    d, "rubric", {"rubric_authority": {}}
                ),
                r"unknown rubric payload keys",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_payload(
                    d, "rubric", {"veto_dimension_ids": "voice"}
                ),
                r"veto_dimension_ids must be a list of strings",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_payload(
                    d,
                    "rubric",
                    {"dimensions": [_rubric_asset()["rubric"]["dimensions"][0], "pace"]},
                ),
                r"each rubric dimension must be an object",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_dimension(d, {"veto": 1}),
                r"unknown rubric dimension keys",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_dimension(d, {}, drop=("scale",)),
                r"missing rubric dimension keys",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_dimension(d, {"method": "vibes"}),
                r"unknown rubric scoring method",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_dimension(d, {"scale": {}}),
                r"scale must be a non-empty object",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_dimension(
                    d, {"scale": {"numeric": {"min_value": 0, "max_value": 100}, "stars": 5}}
                ),
                r"unknown rubric scale keys",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_dimension(
                    d,
                    {
                        "scale": {
                            "numeric": {
                                "min_value": 0,
                                "max_value": 100,
                                "step": 1,
                            }
                        }
                    },
                ),
                r"numeric scale must have only min_value and max_value",
            ),
            (
                lambda d: TestInspectionRefusalMatrix._poison_dimension(
                    d,
                    {
                        "scale": {
                            "pass_fail": {
                                "pass_value": 1,
                                "fail_value": 0,
                                "bonus": 2,
                            }
                        }
                    },
                ),
                r"pass_fail scale must have only pass_value and fail_value",
            ),
        ],
    )
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_each_refusal_names_its_own_reason(self, poison: Any, match: str) -> None:
        document = json.loads(ACME_PACK)
        poison(document)
        with pytest.raises(PackManifestRejected, match=match):
            inspect_pack_manifest(json.dumps(document).encode())

    # -- document surgery helpers (staticmethods so parametrize can reach them) --

    @staticmethod
    def _swap_payload(document: dict[str, Any], payload_key: str, value: Any) -> None:
        for asset in document["assets"]:
            if payload_key in asset:
                asset[payload_key] = value
                return
        raise AssertionError(f"fixture bug: no {payload_key!r} payload")

    @staticmethod
    def _poison_payload(
        document: dict[str, Any], payload_key: str, changes: dict[str, Any]
    ) -> None:
        for asset in document["assets"]:
            if payload_key in asset:
                asset[payload_key].update(changes)
                return
        raise AssertionError(f"fixture bug: no {payload_key!r} payload")

    @staticmethod
    def _poison_dimension(
        document: dict[str, Any], changes: dict[str, Any], drop: tuple[str, ...] = ()
    ) -> None:
        for asset in document["assets"]:
            if "rubric" in asset:
                dimension = asset["rubric"]["dimensions"][0]
                dimension.update(changes)
                for key in drop:
                    dimension.pop(key, None)
                return
        raise AssertionError("fixture bug: no rubric payload")


class TestInstantiationRefusals:
    """The degenerate lookup/validation paths of instantiation and the registry."""

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_unknown_pack_with_pinned_version_names_the_version(self) -> None:
        registry = _active_registry()
        with pytest.raises(PackDisabledError, match=r"at version '9\.9\.9'"):
            registry.instantiate_graph(
                "ghost.pack", "any-asset", workspace_id=WORKSPACE_ID, version="9.9.9"
            )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_blank_explicit_canonical_id_is_refused(self) -> None:
        manifest = inspect_pack_manifest(ACME_PACK)
        with pytest.raises(
            ValueError, match="template_id must be a non-empty string when supplied"
        ):
            instantiate_graph_asset(
                manifest, "critique-graph", workspace_id=WORKSPACE_ID, template_id="   "
            )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_blank_workspace_id_is_refused_for_graphs(self) -> None:
        manifest = inspect_pack_manifest(ACME_PACK)
        with pytest.raises(ValueError, match="workspace_id must be a non-empty string"):
            instantiate_graph_asset(manifest, "critique-graph", workspace_id="   ")

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_wrong_kind_asset_is_refused_for_graph_instantiation(self) -> None:
        manifest = inspect_pack_manifest(ACME_PACK)
        with pytest.raises(PackAssetUnknown, match="is not a graph asset"):
            instantiate_graph_asset(manifest, "critic", workspace_id=WORKSPACE_ID)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_blank_workspace_id_is_refused_for_personas(self) -> None:
        manifest = inspect_pack_manifest(ACME_PACK)
        with pytest.raises(ValueError, match="workspace_id must be a non-empty string"):
            instantiate_persona_asset(manifest, "critic", workspace_id="")

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_wrong_kind_asset_is_refused_for_persona_instantiation(self) -> None:
        manifest = inspect_pack_manifest(ACME_PACK)
        with pytest.raises(PackAssetUnknown, match="is not a persona asset"):
            instantiate_persona_asset(manifest, "critique-graph", workspace_id=WORKSPACE_ID)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_blank_scope_field_is_refused_for_rubric_instantiation(self) -> None:
        manifest = inspect_pack_manifest(ACME_PACK)
        with pytest.raises(ValueError, match="project_id must be a non-empty string"):
            instantiate_rubric_asset(
                manifest,
                "scene",
                goal_id=GOAL_ID,
                goal_revision=GOAL_REVISION,
                workspace_id=WORKSPACE_ID,
                project_id="  ",
                authored_by=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
            )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_instantiated_rubric_revalidates_caller_supplied_counts(self) -> None:
        # model_copy(update=...) skips validation, so a caller-supplied
        # revision/goal_revision of 0 must be refused by re-running the
        # canonical model's own ge=1 constraints on the final object —
        # never returned as a RubricSemantic the rest of the system would
        # trust.
        manifest = inspect_pack_manifest(ACME_PACK)
        with pytest.raises(ValueError, match="violates the canonical model"):
            instantiate_rubric_asset(
                manifest,
                "scene",
                goal_id=GOAL_ID,
                goal_revision=GOAL_REVISION,
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                authored_by=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
                revision=0,
            )
        with pytest.raises(ValueError, match="violates the canonical model"):
            instantiate_rubric_asset(
                manifest,
                "scene",
                goal_id=GOAL_ID,
                goal_revision=0,
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                authored_by=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
            )

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    def test_record_provenance_is_the_manifests_provenance(self) -> None:
        registry = _active_registry()
        record = registry.record("acme.film_critique")
        provenance = record.provenance
        assert provenance.pack_id == "acme.film_critique"
        assert provenance.publisher == "acme"
        assert provenance.version == "1.0.0"
        assert provenance.manifest_sha256 == hashlib.sha256(ACME_PACK).hexdigest()

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    def test_activating_an_active_pack_is_the_same_record(self) -> None:
        registry = _active_registry()
        before = registry.record("acme.film_critique")
        after = registry.activate("acme.film_critique")
        assert after is before
        assert after.state is PackState.ACTIVE

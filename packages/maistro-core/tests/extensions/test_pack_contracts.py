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

import dataclasses
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel, ValidationError

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
        assert rubric.provenance.publisher == "acme"
        assert rubric.provenance.pack_version == "1.0.0"
        assert rubric.provenance.manifest_sha256 == pack_meta["pack.manifest_sha256"]
        assert rubric.provenance.asset_id == "scene"
        assert rubric.provenance.asset_version == "1.0.0"

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

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_caller_rubric_bindings_are_revalidated(self) -> None:
        registry = _active_registry()
        kwargs: dict[str, Any] = {
            "goal_id": GOAL_ID,
            "goal_revision": GOAL_REVISION,
            "workspace_id": WORKSPACE_ID,
            "project_id": PROJECT_ID,
            "authored_by": "principal-1",
        }
        # model_copy(update=...) skips validation; caller-supplied identity
        # fields must still satisfy the canonical constraints.
        manifest = registry.active_manifest("acme.film_critique")
        base = {k: v for k, v in kwargs.items() if k != "goal_revision"}
        with pytest.raises(ValidationError):
            instantiate_rubric_asset(manifest, "scene", revision=0, **kwargs)
        with pytest.raises(ValidationError):
            instantiate_rubric_asset(manifest, "scene", goal_revision=0, **base)
        with pytest.raises(ValidationError):
            instantiate_rubric_asset(manifest, "scene", goal_revision=None, **base)  # type: ignore[arg-type]


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
    def test_activate_on_an_active_pack_changes_nothing(self) -> None:
        # The gate's reversal is a no-op on a pack that was never disabled:
        # the same record comes back, still active, nothing re-installed.
        registry = _active_registry()
        record = registry.record("acme.film_critique")
        assert registry.activate("acme.film_critique") is record
        assert record.state is PackState.ACTIVE
        assert len(registry.records()) == 2

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

    def test_a_disabled_pack_does_not_satisfy_dependencies(self) -> None:
        # Disable stops new use — including as the dependency answer for a
        # later install: the active-version view the M9 evaluator resolves
        # against skips disabled records entirely, so a pack cannot keep
        # satisfying dependents from beyond its own disable gate.
        registry = InstallablePackRegistry(platform_api_version="1.0.0")
        registry.install(ACME_PACK)
        registry.disable("acme.film_critique", note="operator hold")
        with pytest.raises(PackIncompatible, match=r"missing dependency: acme\.film_critique"):
            registry.install(
                _pack_bytes(
                    pack_id="vertex.dependent",
                    publisher="vertex",
                    dependencies=[{"id": "acme.film_critique", "range": "*"}],
                )
            )
        # The refused dependent is recorded nowhere; the disabled pack is
        # still installed, still queryable — deleted nothing.
        assert [
            record.manifest.pack_id
            for record in registry.records()
            if record.manifest.pack_id == "vertex.dependent"
        ] == []
        assert registry.record("acme.film_critique").state is PackState.DISABLED

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

    @pytest.mark.parametrize("version", [True, False])
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_boolean_envelope_version_is_rejected(self, version: bool) -> None:
        document = json.loads(ACME_PACK)
        document["manifest_version"] = version
        self._rejected(json.dumps(document).encode(), "unsupported manifest_version:")

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

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_publisher_slugs_allowed_by_manifests_can_publish(self) -> None:
        # Hyphenated and dotted publisher slugs are valid per _PUBLISHER_RE;
        # their namespaced pack ids must parse too.
        for publisher, pack_id in (("pub-1", "pub-1.my_pack"), ("a.b", "a.b.my_pack")):
            manifest = inspect_pack_manifest(_pack_bytes(pack_id=pack_id, publisher=publisher))
            assert manifest.pack_id == pack_id
            assert manifest.publisher == publisher

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
            with_graph(
                {
                    "name": "g",
                    "nodes": [{"node_type": "t"}],
                    "edges": [],
                }
            ),
            "graph node missing required keys: \\[\\'node_id\\'\\]",
        )
        self._rejected(
            with_graph(
                {
                    "name": "g",
                    "nodes": [{"node_id": "a"}],
                    "edges": [],
                }
            ),
            "graph node missing required keys: \\[\\'node_type\\'\\]",
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
            with_rubric({"name": "r", "gate_pass_threshold": 1e400, "dimensions": dimensions}),
            "gate_pass_threshold must be a finite number",
        )
        self._rejected(
            with_rubric(
                {
                    "name": "r",
                    "gate_pass_threshold": 1.0,
                    "dimensions": [
                        {
                            "id": "d",
                            "name": "D",
                            "weight": 1e400,
                            "method": "model_judge",
                            "scale": {"numeric": {"min_value": 0.0, "max_value": 1.0}},
                        }
                    ],
                }
            ),
            "weight must be a finite number",
        )
        self._rejected(
            with_rubric(
                {
                    "name": "r",
                    "gate_pass_threshold": 1.0,
                    "dimensions": [
                        {
                            "id": "d",
                            "name": "D",
                            "weight": 1.0,
                            "method": "model_judge",
                            "scale": {"pass_fail": {"pass_value": float("nan")}},
                        }
                    ],
                }
            ),
            "pass_value must be a finite number",
        )
        self._rejected(
            with_rubric({"name": "r", "gate_pass_threshold": 1.0, "dimensions": []}),
            "rubric dimensions must be a non-empty list",
        )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_evidence_required_must_be_a_json_boolean(self) -> None:
        # A truthy string like "false" must not be coerced by bool() into
        # ``True`` (that would silently invert the evidence requirement);
        # only an explicit JSON boolean is accepted.
        dimension = dict(_rubric_asset()["rubric"]["dimensions"][0])
        dimension["evidence_required"] = "false"
        self._rejected(
            _pack_bytes(
                pack_id="acme.film_critique",
                publisher="acme",
                assets=[
                    {
                        "asset_id": "r",
                        "version": "1.0.0",
                        "kind": "rubric",
                        "rubric": {
                            "name": "r",
                            "gate_pass_threshold": 1.0,
                            "dimensions": [dimension],
                        },
                    }
                ],
            ),
            "evidence_required must be a boolean",
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
    def test_manifest_snapshot_is_deep_frozen(self) -> None:
        """Post-inspection mutation of the snapshot is impossible.

        Provenance must keep describing the instantiated content: a
        consumer holding ``manifest`` cannot alter an asset payload and
        have later instantiations drift from ``source_sha256``.
        """
        manifest = inspect_pack_manifest(ACME_PACK)
        persona = next(a for a in manifest.assets if a.asset_id == "critic")
        rubric = next(a for a in manifest.assets if a.asset_id == "scene")
        # Mappings — top-level and nested — reject writes.
        with pytest.raises(TypeError):
            persona.persona.payload["purpose"] = "tampered"  # type: ignore[index]
        with pytest.raises(TypeError):
            persona.persona.payload["defaults"]["tone"] = "tampered"  # type: ignore[index]
        # Arrays are frozen as tuples.
        assert isinstance(persona.persona.payload["surfaces"], tuple)
        # Canonical Pydantic objects never live in the snapshot: the
        # pack-local frozen dataclass refuses attribute writes.
        with pytest.raises(dataclasses.FrozenInstanceError):
            rubric.rubric.dimensions[0].weight = 99.0  # type: ignore[misc]
        # Instantiation still produces the original, sha-consistent content.
        minted = instantiate_persona_asset(manifest, "critic", workspace_id=WORKSPACE_ID)
        assert minted.purpose == "judge scenes against the rubric"
        assert minted.extension_metadata["pack"]["pack.manifest_sha256"] == (manifest.source_sha256)

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

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_pack_id_occupied_by_an_active_extension_is_rejected(self) -> None:
        # A pack sharing an id with an already-active extension would let
        # _active_versions() overwrite the extension's version with the
        # pack's, silently retargeting dependency resolution; refuse instead.
        registry = InstallablePackRegistry(
            platform_api_version="1.0.0",
            active_extensions={"acme.film_critique": "1.0.0"},
        )
        with pytest.raises(PackIdentityConflict, match="already an active extension"):
            registry.install(ACME_PACK)
        assert registry.records() == ()


# The fail-closed parse matrix: one mutation per row, each pinning a distinct
# rejection the parser promises. Every branch outcome of the manifest/asset/
# payload validators is exercised here — a malformed pack must fail closed
# with its specific reason, never parse "well enough".
#
# Each row mutates the ACME document in exactly one place and asserts the
# rejection message fragment. Indices: assets[0] graph, [1] persona, [2] rubric.


def _mutated(mutate: Callable[[dict[str, Any]], None]) -> bytes:
    document = json.loads(ACME_PACK)
    mutate(document)
    return json.dumps(document).encode()


def _asset(document: dict[str, Any], index: int) -> dict[str, Any]:
    return document["assets"][index]


FAIL_CLOSED_PARSE_MATRIX: tuple[tuple[str, Callable[[dict[str, Any]], None], str], ...] = (
    # -- envelope / identity -------------------------------------------------
    (
        "required-string-fields-reject-non-strings",
        lambda doc: doc.update(pack_id=7),
        "pack_id must be a non-empty string",
    ),
    (
        "required-string-fields-reject-blanks",
        lambda doc: doc.update(name="   "),
        "name must be a non-empty string",
    ),
    ("malformed-publisher-id", lambda doc: doc.update(publisher="Bad"), "malformed publisher id"),
    ("assets-must-be-a-list", lambda doc: doc.update(assets={}), "assets must be a non-empty list"),
    (
        "assets-must-be-non-empty",
        lambda doc: doc.update(assets=[]),
        "assets must be a non-empty list",
    ),
    (
        "each-asset-must-be-an-object",
        lambda doc: doc.update(assets=["critique-graph"]),
        "each asset must be an object",
    ),
    (
        "assets-reject-unknown-keys",
        lambda doc: _asset(doc, 0).update(exec="local"),
        "unknown asset keys",
    ),
    (
        "assets-require-the-identity-keys",
        lambda doc: doc["assets"].__setitem__(
            0, {"asset_id": "g", "kind": "graph", "graph": _graph_asset()["graph"]}
        ),
        "missing asset keys",
    ),
    (
        "malformed-asset-id",
        lambda doc: _asset(doc, 0).update(asset_id="Bad Asset"),
        "malformed asset_id",
    ),
    # -- graph payload -------------------------------------------------------
    (
        "graph-payload-must-be-an-object",
        lambda doc: _asset(doc, 0).update(graph=[]),
        "graph payload must be an object",
    ),
    (
        "graph-payload-rejects-unknown-keys",
        lambda doc: _asset(doc, 0)["graph"].update(exec="local"),
        "unknown graph payload keys",
    ),
    (
        "graph-description-must-be-a-string",
        lambda doc: _asset(doc, 0)["graph"].update(description=7),
        "graph description must be a string",
    ),
    (
        "graph-entry-node-must-be-non-empty-when-present",
        lambda doc: _asset(doc, 0)["graph"].update(entry_node=""),
        "graph entry_node must be a non-empty string when present",
    ),
    (
        "graph-entry-node-must-be-a-string-when-present",
        lambda doc: _asset(doc, 0)["graph"].update(entry_node=7),
        "graph entry_node must be a non-empty string when present",
    ),
    (
        "graph-node-id-grammar",
        lambda doc: _asset(doc, 0)["graph"]["nodes"][0].update(node_id="Bad_Node"),
        "malformed graph node_id",
    ),
    (
        "graph-node-name-must-be-a-string",
        lambda doc: _asset(doc, 0)["graph"]["nodes"][0].update(name=7),
        "graph node name must be a string",
    ),
    (
        "graph-edges-must-be-a-list",
        lambda doc: _asset(doc, 0)["graph"].update(edges={"explore": "execute"}),
        "graph edges must be a list",
    ),
    (
        "graph-edge-must-be-a-pair",
        lambda doc: _asset(doc, 0)["graph"].update(edges=["explore->execute"]),
        "each graph edge must be a",
    ),
    (
        "graph-edge-pair-must-have-two-ends",
        lambda doc: _asset(doc, 0)["graph"].update(edges=[["explore", "execute", "again"]]),
        "each graph edge must be a",
    ),
    (
        "graph-edge-ends-must-be-strings",
        lambda doc: _asset(doc, 0)["graph"].update(edges=[["explore", 2]]),
        "each graph edge must be a",
    ),
    # -- persona payload ------------------------------------------------------
    (
        "persona-payload-must-be-an-object",
        lambda doc: _asset(doc, 1).update(persona=[]),
        "persona payload must be an object",
    ),
    (
        "persona-payload-rejects-unknown-keys",
        lambda doc: _asset(doc, 1)["persona"].update(rubric_authority="local"),
        "unknown persona payload keys",
    ),
    (
        "persona-surfaces-must-be-a-list",
        lambda doc: _asset(doc, 1)["persona"].update(surfaces="ui"),
        "persona surfaces must be a list of strings",
    ),
    (
        "persona-surfaces-items-must-be-strings",
        lambda doc: _asset(doc, 1)["persona"].update(surfaces=[1]),
        "persona surfaces must be a list of strings",
    ),
    (
        "persona-defaults-must-be-an-object",
        lambda doc: _asset(doc, 1)["persona"].update(defaults=[]),
        "persona defaults must be an object",
    ),
    (
        "persona-behavior-must-be-an-object",
        lambda doc: _asset(doc, 1)["persona"].update(behavior=[]),
        "persona behavior must be an object",
    ),
    # -- rubric payload -------------------------------------------------------
    (
        "rubric-payload-must-be-an-object",
        lambda doc: _asset(doc, 2).update(rubric=[]),
        "rubric payload must be an object",
    ),
    (
        "rubric-payload-rejects-unknown-keys",
        lambda doc: _asset(doc, 2)["rubric"].update(gate_authority="local"),
        "unknown rubric payload keys",
    ),
    (
        "veto-ids-must-be-a-list",
        lambda doc: _asset(doc, 2)["rubric"].update(veto_dimension_ids="voice"),
        "veto_dimension_ids must be a list of strings",
    ),
    (
        "veto-ids-items-must-be-strings",
        lambda doc: _asset(doc, 2)["rubric"].update(veto_dimension_ids=[1]),
        "veto_dimension_ids must be a list of strings",
    ),
    (
        "each-rubric-dimension-must-be-an-object",
        lambda doc: _asset(doc, 2)["rubric"].update(dimensions=["pace"]),
        "each rubric dimension must be an object",
    ),
    (
        "rubric-dimension-rejects-unknown-keys",
        lambda doc: _asset(doc, 2)["rubric"]["dimensions"][0].update(veto=True),
        "unknown rubric dimension keys",
    ),
    (
        "rubric-dimension-requires-its-keys",
        lambda doc: _asset(doc, 2)["rubric"]["dimensions"][0].pop("weight"),
        "missing rubric dimension keys",
    ),
    (
        "rubric-method-in-the-closed-vocabulary",
        lambda doc: _asset(doc, 2)["rubric"]["dimensions"][0].update(method="vibes"),
        "unknown rubric scoring method",
    ),
    (
        "dimension-scale-must-be-an-object",
        lambda doc: _asset(doc, 2)["rubric"]["dimensions"][0].update(scale=[]),
        "rubric dimension scale must be a non-empty object",
    ),
    (
        "dimension-scale-must-be-non-empty",
        lambda doc: _asset(doc, 2)["rubric"]["dimensions"][0].update(scale={}),
        "rubric dimension scale must be a non-empty object",
    ),
    (
        "dimension-scale-rejects-unknown-keys",
        lambda doc: _asset(doc, 2)["rubric"]["dimensions"][0]["scale"].update(celsius=1),
        "unknown rubric scale keys",
    ),
    (
        "numeric-scale-must-be-an-object",
        lambda doc: _asset(doc, 2)["rubric"]["dimensions"][0].update(scale={"numeric": []}),
        "numeric scale must have only min_value and max_value",
    ),
    (
        "numeric-scale-rejects-unknown-keys",
        lambda doc: _asset(doc, 2)["rubric"]["dimensions"][0].update(
            scale={"numeric": {"min_value": 0, "max_value": 100, "step": 1}}
        ),
        "numeric scale must have only min_value and max_value",
    ),
    (
        "pass-fail-scale-must-be-an-object",
        lambda doc: _asset(doc, 2)["rubric"]["dimensions"][0].update(scale={"pass_fail": []}),
        "pass_fail scale must have only pass_value and fail_value",
    ),
    (
        "pass-fail-scale-rejects-unknown-keys",
        lambda doc: _asset(doc, 2)["rubric"]["dimensions"][0].update(
            scale={"pass_fail": {"pass_value": 1, "fail_value": 0, "either": 0.5}}
        ),
        "pass_fail scale must have only pass_value and fail_value",
    ),
    # -- dependencies / capabilities -------------------------------------------
    (
        "dependencies-must-be-a-list",
        lambda doc: doc.update(dependencies={"acme.film_critique": "*"}),
        "dependencies must be a list",
    ),
    (
        "dependency-must-be-an-id-range-object",
        lambda doc: doc.update(dependencies=["acme.film_critique"]),
        "each dependency must be an object with exactly id and range",
    ),
    (
        "dependency-must-have-exactly-id-and-range",
        lambda doc: doc.update(dependencies=[{"id": "x.y", "range": "*", "optional": True}]),
        "each dependency must be an object with exactly id and range",
    ),
    (
        "dependency-id-must-be-a-string",
        lambda doc: doc.update(dependencies=[{"id": 7, "range": "*"}]),
        "malformed dependency id",
    ),
    (
        "dependency-id-grammar",
        lambda doc: doc.update(dependencies=[{"id": "Bad Id", "range": "*"}]),
        "malformed dependency id",
    ),
    (
        "dependency-range-must-be-a-string",
        lambda doc: doc.update(dependencies=[{"id": "x.y", "range": 7}]),
        "malformed dependency range",
    ),
    (
        "dependency-range-must-be-non-empty",
        lambda doc: doc.update(dependencies=[{"id": "x.y", "range": "  "}]),
        "malformed dependency range",
    ),
    (
        "capabilities-must-be-a-list",
        lambda doc: doc.update(capabilities="run.read"),
        "capabilities must be a list of strings",
    ),
    (
        "capabilities-items-must-be-strings",
        lambda doc: doc.update(capabilities=[1]),
        "capabilities must be a list of strings",
    ),
)


class TestFailClosedParseMatrix:
    """Every branch outcome of the manifest/asset/payload validators.

    A malformed pack must fail closed with its specific reason — each row
    takes the rejection branch its id names, so no unknown-key, shape, or
    grammar violation can pass inspection by falling through a hole in the
    matrix.
    """

    @pytest.mark.parametrize(
        ("mutation", "expected"),
        [(row[1], row[2]) for row in FAIL_CLOSED_PARSE_MATRIX],
        ids=[row[0] for row in FAIL_CLOSED_PARSE_MATRIX],
    )
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_each_mutation_is_rejected_with_its_reason(
        self, mutation: Callable[[dict[str, Any]], None], expected: str
    ) -> None:
        with pytest.raises(PackManifestRejected, match=expected):
            inspect_pack_manifest(_mutated(mutation))

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_a_graph_asset_may_omit_the_entry_node(self) -> None:
        # The positive arm of the entry-node branches: entry_node is optional,
        # and an asset without one must still inspect and instantiate.
        asset = _graph_asset()
        del asset["graph"]["entry_node"]
        manifest = inspect_pack_manifest(
            _pack_bytes(pack_id="acme.entryless", publisher="acme", assets=[asset])
        )
        template = instantiate_graph_asset(manifest, "critique-graph", workspace_id=WORKSPACE_ID)
        assert "entry_node" not in template.metadata
        assert template.name == "Critique loop"


class TestInstantiationInputValidation:
    """Instantiation input guard rails on top of the identity rules (AC-3).

    Canonical identity is the caller's: blank caller-side scope/id values are
    refused rather than coerced, and a wrong-kind asset names its kind in the
    typed error.
    """

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_wrong_kind_assets_are_refused_with_the_kind_named(self) -> None:
        manifest = inspect_pack_manifest(ACME_PACK)
        with pytest.raises(PackAssetUnknown, match="is not a graph asset"):
            instantiate_graph_asset(manifest, "critic", workspace_id=WORKSPACE_ID)
        with pytest.raises(PackAssetUnknown, match="is not a persona asset"):
            instantiate_persona_asset(manifest, "scene", workspace_id=WORKSPACE_ID)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_workspace_ids_are_refused(self, blank: str) -> None:
        manifest = inspect_pack_manifest(ACME_PACK)
        with pytest.raises(ValueError, match="workspace_id must be a non-empty string"):
            instantiate_graph_asset(manifest, "critique-graph", workspace_id=blank)
        with pytest.raises(ValueError, match="workspace_id must be a non-empty string"):
            instantiate_persona_asset(manifest, "critic", workspace_id=blank)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    @pytest.mark.parametrize("field", ["goal_id", "workspace_id", "project_id", "authored_by"])
    def test_blank_rubric_bindings_are_refused(self, field: str) -> None:
        manifest = inspect_pack_manifest(ACME_PACK)
        kwargs: dict[str, Any] = {
            "goal_id": GOAL_ID,
            "workspace_id": WORKSPACE_ID,
            "project_id": PROJECT_ID,
            "authored_by": "principal-1",
        }
        kwargs[field] = "  "
        with pytest.raises(ValueError, match=f"{field} must be a non-empty string"):
            instantiate_rubric_asset(manifest, "scene", goal_revision=GOAL_REVISION, **kwargs)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_blank_caller_pinned_ids_are_refused(self) -> None:
        manifest = inspect_pack_manifest(ACME_PACK)
        with pytest.raises(ValueError, match="template_id must be a non-empty string"):
            instantiate_graph_asset(
                manifest, "critique-graph", workspace_id=WORKSPACE_ID, template_id="   "
            )
        with pytest.raises(ValueError, match="persona_id must be a non-empty string"):
            instantiate_persona_asset(
                manifest, "critic", workspace_id=WORKSPACE_ID, persona_id="   "
            )
        with pytest.raises(ValueError, match="rubric_id must be a non-empty string"):
            instantiate_rubric_asset(
                manifest,
                "scene",
                goal_id=GOAL_ID,
                goal_revision=GOAL_REVISION,
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                authored_by="principal-1",
                rubric_id="   ",
            )


class TestModuleImportPosture:
    """The pack module must not close the recipes ↔ personas import cycle.

    Regression: ``packs.py`` originally imported ``Persona`` at module level,
    which closed the cycle
    ``maistro.agents.recipes → maistro.graph → (node auto-import) →
    maistro.runs → maistro.runtime → maistro.extensions → packs.py →
    maistro.personas → personas.expander → maistro.agents.recipes`` and made
    a bare ``import maistro.agents.recipes`` fail with
    ``ImportError: cannot import name 'AgentRecipe' from partially initialized
    module`` whenever the interpreter reached ``recipes`` first (e.g. the
    ``tests/agents/recipes`` suite collecting before anything imported
    personas). The runtime import now lives inside ``_probe_persona``; this
    test pins both import orders in fresh interpreters, where prior-module
    import order inside the test process cannot mask the cycle.
    """

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    @pytest.mark.parametrize("first", ["maistro.agents.recipes", "maistro.personas"])
    def test_both_import_orders_reach_the_pack_module(self, first: str) -> None:
        code = (
            "import importlib\n"
            f"importlib.import_module({first!r})\n"
            "import maistro.extensions.packs\n"
            "import maistro.agents.recipes\n"
            "import maistro.personas\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr

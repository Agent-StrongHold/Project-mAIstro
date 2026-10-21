"""Fixtures for the maistro-design suite, including the M7-A11 governed harness.

The governed harness composes the *production* wiring at test scale: canonical
Project/Run/NodeRun/Attempt stores, the canonical durable Graph walker, and the
canonical effect context — with only the LLM gateway's HTTP faked by the tests
themselves (the same ``httpx.AsyncClient`` patch the core governed-egress tests
use). This suite runs under ``--import-mode=importlib``, so shared helpers are
exposed as fixtures rather than sibling imports.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import pytest

os.environ.setdefault("MAISTRO_DRY_RUN", "1")

DESIGN_WORKSPACE = "ws-design"
MODEL_ALIAS = "thesis-model"

#: Canonical Goal/Rubric identity the governed Runs are admitted for and the
#: judge scores against. The Run's admission binding and the judge's inputs
#: must agree, so the harness keeps one pair of constants for both.
GOAL_ID = "goal-design-1"
GOAL_REVISION = 7
GOAL_DESIRED_STATE = "A compelling, well-scoped design thesis"
GOAL_SUCCESS_CONDITIONS = ("clear narrative", "measurable outcome")
RUBRIC_ID = "rubric-design-1"
RUBRIC_REVISION = 3
RUBRIC_CRITERIA = "novelty 0.5, feasibility 0.5; gate: all dimensions"


# --------------------------------------------------------------------------
# Original design-engine fixtures
# --------------------------------------------------------------------------


@pytest.fixture()
def skill_registry():
    from maistro_design.skills.builtins import load_builtins
    from maistro_design.skills.registry import InMemoryDesignSkillRegistry

    r = InMemoryDesignSkillRegistry()
    load_builtins(r)
    return r


@pytest.fixture()
def system_registry():
    from maistro_design.systems.registry import InMemoryDesignSystemRegistry
    from maistro_design.trust import TrustTier
    from maistro_design.types import DesignSystem

    r = InMemoryDesignSystemRegistry()
    r.register(
        DesignSystem(
            slug="default",
            name="Default",
            description="Neutral default system",
            trust_tier=TrustTier.T0,
        )
    )
    return r


@pytest.fixture()
def engine(skill_registry, system_registry):
    from maistro_design.engine import DesignEngine

    return DesignEngine(skill_registry=skill_registry, system_registry=system_registry)


# --------------------------------------------------------------------------
# M7-A11 governed explore/judge harness (#987)
# --------------------------------------------------------------------------


@dataclass
class GovernedDesign:
    """One canonical scope: workspace/project/run stores plus one Binding."""

    project_store: Any
    run_store: Any
    durable_store: Any
    effects: Any
    binding: Any
    registry: Any
    router: Any
    workspace_id: str
    project_id: str


async def _build_governed(*, policy_evaluator: Any | None = None) -> GovernedDesign:
    """Compose the canonical stores and one authorized model.chat Binding.

    The Binding is registered against the *actual* canonical Project id, so
    Workspace/Project scope checks are real, not stubbed. Omitted policy uses
    the explicit M1 ``binding_scope_policy`` baseline (#846: no policy, no
    authorization).
    """

    from maistro.capabilities.binding import Binding
    from maistro.capabilities.effect_context import (
        binding_scope_policy,
        new_in_memory_effect_context,
    )
    from maistro.capabilities.providers.llm_gateway import (
        DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
        MODEL_CHAT_CAPABILITY,
        MODEL_GATEWAY_CREDENTIAL_PROVIDER,
    )
    from maistro.credentials.types import CredentialRecord
    from maistro.graph.durable_runs import (
        CanonicalDurableRunStore,
        InMemoryGraphContinuationStore,
    )
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.providers.registry import InMemoryProviderRegistry
    from maistro.providers.router import CostAwareRouter
    from maistro.runs.store import InMemoryRunStore

    project_store = InMemoryProjectScopeStore()
    await project_store.create_root(DESIGN_WORKSPACE)
    project = await project_store.root_for_workspace(DESIGN_WORKSPACE)

    effects = new_in_memory_effect_context(
        policy_evaluator=policy_evaluator if policy_evaluator is not None else binding_scope_policy,
    )
    effects.credentials.add(
        workspace_id=DESIGN_WORKSPACE,
        project_id=project.project_id,
        record=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="test-litellm-key",
        ),
    )
    binding = Binding(
        binding_id="binding-design-model",
        workspace_id=DESIGN_WORKSPACE,
        project_id=project.project_id,
        capability=MODEL_CHAT_CAPABILITY,
        credential_refs=(DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,),
    )
    effects.bindings.register(binding)

    provider_registry = InMemoryProviderRegistry(models=[_model_metadata(MODEL_ALIAS)])
    run_store = InMemoryRunStore(project_store=project_store)
    return GovernedDesign(
        project_store=project_store,
        run_store=run_store,
        durable_store=CanonicalDurableRunStore(
            run_store,
            InMemoryGraphContinuationStore(),
        ),
        effects=effects,
        binding=binding,
        registry=provider_registry,
        router=CostAwareRouter(provider_registry),
        workspace_id=DESIGN_WORKSPACE,
        project_id=project.project_id,
    )


def _model_metadata(name: str) -> Any:
    from maistro.providers.types import ModelMetadata

    return ModelMetadata(
        name=name,
        provider="test-gw",
        cost_per_1k_input=0.5,
        cost_per_1k_output=1.0,
        latency_p50_ms=50,
    )


@pytest.fixture()
async def governed() -> GovernedDesign:
    return await _build_governed()


@pytest.fixture()
def governed_factory():
    """Async factory for scopes with a custom policy evaluator (Sentinel tests)."""

    return _build_governed


def _wave_graph(governed: GovernedDesign, *, width: int = 2, binding_id: str = "", **inputs: Any):
    """A width=N explore wave: coordinator followed by N thesis slots.

    Width is graph structure — the canonical Run stores refuse NodeRuns whose
    node_id is absent from the admitted Graph snapshot, which is precisely why
    the wave is synthesized this way instead of inventing slots at runtime.
    """

    from maistro.graph.definitions import Edge, Graph, Node

    parameters: dict[str, Any] = {
        "goal_id": GOAL_ID,
        "goal_revision": GOAL_REVISION,
        "goal_desired_state": GOAL_DESIRED_STATE,
        "goal_success_conditions": list(GOAL_SUCCESS_CONDITIONS),
        "rubric_id": RUBRIC_ID,
        "rubric_revision": RUBRIC_REVISION,
        "rubric_criteria": RUBRIC_CRITERIA,
        "width": width,
        "exploration_policy": "diverse",
        "artifact_kind": "design.thesis",
        "binding_id": binding_id or governed.binding.binding_id,
        "model": MODEL_ALIAS,
        **inputs,
    }
    nodes = [Node(node_id="explore", node_type="design.explore", parameters=parameters)]
    edges: list[Any] = []
    for index in range(width):
        nodes.append(
            Node(
                node_id=f"thesis-{index}",
                node_type="design.thesis",
                parameters={**parameters, "thesis_index": index},
            )
        )
        edges.append(
            Edge(
                from_node="explore",
                to_node=f"thesis-{index}",
                # The wave fans out: every thesis slot runs in the frontier.
                metadata={"parallel": True},
            )
        )
    return Graph(
        workspace_id=governed.workspace_id,
        project_id=governed.project_id,
        name="design explore wave",
        nodes=nodes,
        edges=edges,
    )


async def _run_wave(governed: GovernedDesign, graph: Any, *, nodes_by_kind: dict[str, Any]) -> Any:
    """Admit one canonical Run for the wave and walk it durably.

    Returns the DurableRunRecord; the canonical Run/NodeRun/Attempt rows live
    in ``governed.run_store``.
    """

    from maistro.graph.durable_runs import run_durable_graph
    from maistro.graph.durable_runs.launch import durable_graph_launch_provenance
    from maistro.runs.model import RunStatus
    from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

    def node_resolver(node_id: str, walk_graph: Any) -> Any:
        spec = next(node for node in walk_graph.nodes if node.node_id == node_id)
        return nodes_by_kind[spec.node_type]

    run = await governed.run_store.create_run(
        graph,
        provenance=durable_graph_launch_provenance(inputs={}, blackboard_metadata={}),
        initial_status=RunStatus.QUEUED,
        # The canonical admission requirements: an admitted actor, and the
        # Goal revision this Run works on — the revision the judge's #792 eval
        # rows must name.
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        goal_id=GOAL_ID,
        goal_revision=GOAL_REVISION,
    )
    return await run_durable_graph(
        graph,
        store=governed.durable_store,
        node_resolver=node_resolver,
        run_store=governed.run_store,
        run_id=run.run_id,
    )


def _design_nodes(governed: GovernedDesign) -> dict[str, Any]:
    """The explore wave's node instances on the governed authorities."""

    from maistro_design.explore import DesignExploreNode, DesignThesisNode

    return {
        "design.explore": DesignExploreNode(
            effect_context=governed.effects,
            registry=governed.registry,
            router=governed.router,
        ),
        "design.thesis": DesignThesisNode(
            effect_context=governed.effects,
            registry=governed.registry,
            router=governed.router,
        ),
    }


def _judge_node(governed: GovernedDesign) -> Any:
    from maistro_design.judge import DesignJudgeNode

    return DesignJudgeNode(
        effect_context=governed.effects,
        registry=governed.registry,
        router=governed.router,
        # The canonical Run store is where the #792 eval rows live; a judge
        # without it has nowhere to persist evidence.
        run_store=governed.run_store,
    )


@pytest.fixture(autouse=True)
def _gateway_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured gateway endpoint for the governed egress env seam."""

    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://gateway.test/v1")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "env-test-key")


@pytest.fixture()
def patch_gateway(monkeypatch: pytest.MonkeyPatch):
    """Fake the gateway HTTP transport the approved Provider actually uses.

    Returns a callable ``(bodies) -> sent`` where ``sent`` records every
    physical gateway effect, in order, so tests can assert zero-effect
    fail-closed paths as well as governed ones. The seam patched is the
    shared-client factory (``maistro.http``), bypassing the per-loop client
    pool so every test gets its own fake.
    """

    def _patch(bodies: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        sent: list[dict[str, Any]] = []
        responses = list(bodies or [])

        class _Resp:
            status_code = 200

            def json(self) -> Any:
                return responses[min(len(sent) - 1, len(responses) - 1)]

        class _Client:
            is_closed = False

            def __init__(self, *a: Any, **kw: Any) -> None: ...

            async def __aenter__(self) -> _Client:
                return self

            async def __aexit__(self, *a: Any) -> None: ...

            async def post(self, url: str, *a: Any, **kw: Any) -> _Resp:
                sent.append({"url": url, **(kw.get("json") or {})})
                return _Resp()

        import maistro.http

        monkeypatch.setattr(
            maistro.http, "get_shared_client", lambda *a, **kw: _Client(), raising=False
        )
        return sent

    return _patch


@dataclass
class GovernedKit:
    """The harness callables, bound for ``--import-mode=importlib`` suites."""

    build: Any
    wave_graph: Any
    run_wave: Any
    design_nodes: Any
    judge_node: Any
    model_alias: str
    goal_id: str
    goal_revision: int
    rubric_id: str
    rubric_revision: int


@pytest.fixture()
def governed_kit() -> GovernedKit:
    return GovernedKit(
        build=_build_governed,
        wave_graph=_wave_graph,
        run_wave=_run_wave,
        design_nodes=_design_nodes,
        judge_node=_judge_node,
        model_alias=MODEL_ALIAS,
        goal_id=GOAL_ID,
        goal_revision=GOAL_REVISION,
        rubric_id=RUBRIC_ID,
        rubric_revision=RUBRIC_REVISION,
    )

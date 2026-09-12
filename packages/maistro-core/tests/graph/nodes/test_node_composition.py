"""Node dependency declarations and the resolver that obeys them (#1193, #1082).

Three production nodes have now been found constructed without an authority
they required — `llm.summarize` (#1079), `agent.delegate_remote` (#147) and
`agent.synth_dag` (#1193) — each because the constructor's permissive default
let the resolver's generic fallback build a success-shaped node that did no
work. The repair is structural: a node declares its authorities on the class,
`register_node` refuses a declaration the resolver could not honour, and
`compose_node` refuses to build a kind whose required authority is missing.
The guards here enumerate every registered kind, so the next node cannot
recreate the class of defect without failing this file.
"""

from __future__ import annotations

import inspect
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.container import build_node_resolver
from maistro.graph.nodes import (
    AUTHORITY_NAMES,
    BaseNode,
    NodeCompositionError,
    NodeContext,
    compose_node,
    get_node,
    list_kinds,
    register_node,
)

_SYNTH_DAG = {"nodes": [{"id": "s", "kind": "agent.synth_dag"}]}


def _sentinel_authorities() -> dict[str, object]:
    """One distinct object per authority, so identity can be asserted."""
    return {name: object() for name in AUTHORITY_NAMES}


# --- the declarations themselves ----------------------------------------------


@pytest.mark.parametrize("kind", list_kinds())
def test_every_declared_authority_is_one_the_resolver_can_supply(kind: str) -> None:
    """A declaration naming an authority nothing supplies would be a
    dependency that is always missing — refused at registration, and pinned
    here for every kind that is registered."""
    node_cls = get_node(kind)
    declared = {**node_cls.required_authorities, **node_cls.optional_authorities}
    assert set(declared.values()) <= AUTHORITY_NAMES
    parameters = inspect.signature(node_cls.__init__).parameters
    for keyword in declared:
        assert keyword in parameters, f"{kind} declares {keyword!r} but does not accept it"


def test_registration_refuses_an_unknown_authority() -> None:
    class _In(BaseModel):
        pass

    class _Wrong(BaseNode[_In, _In]):
        kind: ClassVar[str] = "test.composition.unknown_authority"
        input_schema: ClassVar[type[BaseModel]] = _In
        output_schema: ClassVar[type[BaseModel]] = _In
        required_authorities: ClassVar[dict[str, str]] = {"store": "not_an_authority"}

        def __init__(self, store: object = None) -> None:
            self._store = store

    with pytest.raises(ValueError, match="unknown authority 'not_an_authority'"):
        register_node(_Wrong)


def test_registration_refuses_a_keyword_the_constructor_does_not_take() -> None:
    class _In(BaseModel):
        pass

    class _Wrong(BaseNode[_In, _In]):
        kind: ClassVar[str] = "test.composition.unknown_keyword"
        input_schema: ClassVar[type[BaseModel]] = _In
        output_schema: ClassVar[type[BaseModel]] = _In
        required_authorities: ClassVar[dict[str, str]] = {"store": "run_store"}

    with pytest.raises(ValueError, match="no parameter named 'store'"):
        register_node(_Wrong)


# --- composition -------------------------------------------------------------------


@pytest.mark.parametrize("kind", list_kinds())
def test_a_fully_wired_resolver_hands_every_kind_its_exact_authorities(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The production identity proof, generically: with every authority
    supplied, each kind constructs and receives — as the very objects the
    resolver holds — everything it declared, required and optional alike."""
    node_cls = get_node(kind)
    authorities = _sentinel_authorities()
    received: dict[str, Any] = {}
    real_init = node_cls.__init__

    def _recording_init(self: Any, *args: Any, **kwargs: Any) -> None:
        received.update(kwargs)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(node_cls, "__init__", _recording_init)
    compose_node(kind, authorities)

    declared = {**node_cls.required_authorities, **node_cls.optional_authorities}
    for keyword, authority in declared.items():
        assert received[keyword] is authorities[authority], (
            f"{kind} did not receive the resolver's {authority!r} as {keyword!r}"
        )
    # And nothing beyond the declaration is passed: the declaration *is* the
    # wiring, so an undeclared constructor parameter keeps its own default.
    assert set(received) == set(declared)


@pytest.mark.parametrize("kind", list_kinds())
def test_a_bare_resolver_refuses_every_kind_that_requires_an_authority(kind: str) -> None:
    """Generic fallback construction is forbidden for a node that declares a
    required authority: nothing supplied means `NodeCompositionError`, never a
    node built from the constructor's permissive default."""
    node_cls = get_node(kind)
    unwired = dict.fromkeys(AUTHORITY_NAMES)
    if not node_cls.required_authorities:
        assert isinstance(compose_node(kind, unwired), node_cls)
        return
    with pytest.raises(NodeCompositionError) as excinfo:
        compose_node(kind, unwired)
    assert excinfo.value.kind == kind
    assert set(excinfo.value.missing) == set(node_cls.required_authorities.values())


def test_a_missing_required_authority_is_named_in_the_refusal() -> None:
    with pytest.raises(NodeCompositionError, match="requires graph_run_store"):
        compose_node("agent.synth_dag", {"graph_run_store": None})


# --- #1193: agent.synth_dag through build_node_resolver ---------------------------


def test_the_resolver_hands_synth_dag_both_stores_and_itself() -> None:
    from maistro.graph.durable_runs import InMemoryDurableRunStore
    from maistro.graph.nodes.agent_synth_dag import AgentSynthDagNode
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs.store import InMemoryRunStore

    store = InMemoryDurableRunStore()
    canonical = InMemoryRunStore(project_store=InMemoryProjectScopeStore())
    resolver = build_node_resolver(graph_run_store=store, run_store=canonical)

    node = resolver("s", _SYNTH_DAG)

    assert isinstance(node, AgentSynthDagNode)
    assert node._run_store is store
    assert node._canonical_run_store is canonical
    # The child graph's nodes are built by the same wired resolver, not the
    # bare registry.
    assert node._node_resolver is resolver


def test_the_resolver_refuses_synth_dag_without_the_store() -> None:
    """The regression for #1193: `build_node_resolver()` used to fall through
    to `get_node(kind)()`, constructing this node with `run_store=None`, and
    the node then completed with `success=True` and a message saying nothing
    ran. Refused before construction now."""
    with pytest.raises(NodeCompositionError, match=r"agent\.synth_dag"):
        build_node_resolver()("s", _SYNTH_DAG)


def test_neither_store_stands_in_for_the_other() -> None:
    """`RunStore` and `DurableRunStore` are one word apart and share no
    method; the node needs both, and supplying one leaves the other missing."""
    with pytest.raises(NodeCompositionError, match="graph_run_store"):
        build_node_resolver(run_store=object())("s", _SYNTH_DAG)  # type: ignore[arg-type]
    with pytest.raises(NodeCompositionError, match="run_store") as excinfo:
        build_node_resolver(graph_run_store=object())("s", _SYNTH_DAG)  # type: ignore[arg-type]
    assert excinfo.value.missing == ("run_store",)


# --- production composition ---------------------------------------------------------


class _ChildIn(BaseModel):
    pass


class _ChildOut(BaseModel):
    text: str


class _CompositionChild(BaseNode[_ChildIn, _ChildOut]):
    kind: ClassVar[str] = "test.composition.child"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _ChildIn
    output_schema: ClassVar[type[BaseModel]] = _ChildOut

    async def _execute(self, inputs: _ChildIn, ctx: NodeContext) -> _ChildOut:
        return _ChildOut(text="done")


register_node(_CompositionChild)


class _OneStep:
    """A synthesizer that proposes the registered child kind above."""

    async def synthesize(self, request: Any) -> Any:
        from maistro.graph.synth import SynthResult
        from maistro.graph.types import GraphConfig

        return SynthResult(
            graph_config=GraphConfig(
                nodes=[_CompositionChild.kind], edges=[], entry=_CompositionChild.kind
            ),
            rationale="one registered step",
        )


class _Justified:
    async def judge(self, shape: Any) -> Any:
        from maistro.security.dag_shape.proportionality import ProportionalityVerdict

        return ProportionalityVerdict(justified=True, add=(), drop=(), reason="fine")


async def _production_container() -> Any:
    from maistro.container import create_container
    from maistro.types import AgentConfig

    return await create_container(AgentConfig(router_api_key="test-key"))  # type: ignore[arg-type]


async def test_the_container_resolver_composes_synth_dag_from_its_own_graph_store() -> None:
    """Obtained through the real resolver, not constructed in the test: the
    node's store *is* the Container's `graph_run_store`, and its children are
    built by the Container's own resolver."""
    from maistro.graph.nodes.agent_synth_dag import AgentSynthDagNode

    container = await _production_container()
    resolver = container.node_resolver()

    node = resolver("s", _SYNTH_DAG)

    assert isinstance(node, AgentSynthDagNode)
    assert node._run_store is container.graph_run_store
    assert node._canonical_run_store is container.run_store
    assert node._node_resolver is resolver


async def test_the_container_composed_node_admits_canonical_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The proof #1193 asks for: resolved through production composition, the
    node actually files a child Run on the Container's spine rather than
    reporting success for nothing."""
    from maistro.graph.definitions import Graph, Node
    from maistro.graph.nodes.agent_synth_dag import AgentSynthDagNode
    from maistro.runs.model import RunStatus

    container = await _production_container()
    projects = container.project_scope_store
    root = await projects.create_root("ws-composition")
    # The parent is a real canonical Run with a NodeRun for the synth node,
    # the way the durable executor would have filed it before dispatching.
    parent = await container.run_store.create_run(
        Graph(
            workspace_id="ws-composition",
            project_id=root.project_id,
            name="parent",
            nodes=[Node(node_id="s", node_type="agent.synth_dag")],
        ),
        initial_status=RunStatus.QUEUED,
    )
    parent = await container.run_store.transition_run(parent.run_id, RunStatus.RUNNING)
    parent_node_run = await container.run_store.create_node_run(parent.run_id, node_id="s")

    node = container.node_resolver()("s", _SYNTH_DAG)
    assert isinstance(node, AgentSynthDagNode)
    # The synthesizer and judge are the node's own strategy seams, swapped
    # for deterministic ones; the store and resolver are the ones production
    # composition supplied.
    monkeypatch.setattr(node, "_synthesizer", _OneStep())
    monkeypatch.setattr(node, "_proportionality_judge", _Justified())

    result = await node.run(
        {"objective": "one canonical step"},
        NodeContext(
            run_id=parent.run_id,
            dag_id="composition",
            node_id="s",
            node_run_id=parent_node_run.node_run_id,
            workspace_id="ws-composition",
            project_id=root.project_id,
        ),
    )

    assert result.status == "completed", result.error_message
    assert result.output.dispatched is True, result.output.run_output
    # The child is a Run on the canonical spine, filed under the parent.
    child_run = await container.run_store.get_run(result.output.child_run_id)
    assert child_run is not None
    assert child_run.parent_run_id == parent.run_id
    assert child_run.parent_node_run_id == parent_node_run.node_run_id
    assert child_run.provenance["admission_source"] == "agent.synth_dag"
    assert child_run.status is RunStatus.COMPLETED
    child = await container.graph_run_store.get(result.output.child_run_id)
    assert child is not None
    assert child.run.workspace_id == "ws-composition"
    assert child.run.project_id == root.project_id
    assert [nr.node_id for nr in child.node_runs] == [_CompositionChild.kind]


async def test_omitting_the_store_from_production_wiring_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The class of defect, mechanically closed: a Container whose graph store
    is not wired cannot resolve the node into a degraded mode; the
    constructor's permissive default is unreachable from here."""
    container = await _production_container()
    monkeypatch.setattr(container, "graph_run_store", None)

    with pytest.raises(NodeCompositionError, match="graph_run_store"):
        container.node_resolver()("s", _SYNTH_DAG)

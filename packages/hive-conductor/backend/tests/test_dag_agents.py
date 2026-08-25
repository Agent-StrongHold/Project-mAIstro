"""Tests for the shared DAG-as-agent execution service."""

from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from services.dag_agents import get_registry, run_registered_dag  # noqa: E402

from maistro.graph.durable_runs import RunStatus  # noqa: E402

_SYNTH_DAG = {
    "id": "synth-noop",
    "name": "Synth Noop",
    "description": "single alias node for execution tests",
    "entry_node": "only",
    "nodes": [{"id": "only", "kind": "transform.alias_keys", "config": {"mapping": {}}}],
    "edges": [],
}


@pytest.fixture()
def synth_dag_id():
    registry = get_registry()
    registry.register(dict(_SYNTH_DAG))
    try:
        yield "synth-noop"
    finally:
        registry.deregister("synth-noop")


def test_get_registry_is_shared_and_seeded() -> None:
    a = get_registry()
    b = get_registry()
    assert a is b
    assert "daily-status" in a


def test_run_registered_dag_unknown_id_raises_key_error() -> None:
    with pytest.raises(KeyError):
        asyncio.run(run_registered_dag("no-such-dag", workspace_id="w1", project_id="p1"))


def test_run_registered_dag_produces_provenanced_completed_run(synth_dag_id: str) -> None:
    graph, record = asyncio.run(
        run_registered_dag(synth_dag_id, workspace_id="w1", project_id="p1", user_id="u1")
    )
    assert record.run.status is RunStatus.COMPLETED
    assert record.run.workspace_id == "w1"
    assert record.run.project_id == "p1"
    assert graph.source_template is not None
    assert graph.source_template.template_id == synth_dag_id
    # The Run's persisted Graph snapshot carries the same provenance.
    assert record.run.graph.materialize().source_template == graph.source_template


def test_configure_hook_touches_the_instantiated_graph_only(synth_dag_id: str) -> None:
    def configure(graph) -> None:
        graph.nodes[0].inputs["extra"] = "value"

    graph, record = asyncio.run(
        run_registered_dag(synth_dag_id, workspace_id="w1", project_id="p1", configure=configure)
    )
    assert graph.nodes[0].inputs["extra"] == "value"
    assert record.run.status is RunStatus.COMPLETED
    # The registered snapshot is untouched — a later run starts clean.
    graph_again, _ = asyncio.run(
        run_registered_dag(synth_dag_id, workspace_id="w1", project_id="p1")
    )
    assert "extra" not in graph_again.nodes[0].inputs


# --- #147: the shipped path supplies the delegate node's dependencies ---

_DELEGATE_DAG = {"nodes": [{"id": "d", "kind": "agent.delegate_remote"}]}


class _StubContainer:
    """Stands in for the core Container the bridge exposes."""

    def __init__(self, delegator=None, peers=None, runs=None) -> None:
        # Distinct sentinels, built here rather than in the signature: the tests
        # assert identity, so each field must be its own object.
        self.a2a_delegator = delegator if delegator is not None else object()
        self.guest_peers = peers if peers is not None else object()
        self.run_store = runs if runs is not None else object()


def _with_container(monkeypatch, container) -> None:
    """Point `services.engine.get_engine()` at a bridge holding `container`."""
    import services.engine as engine_module

    port = type("_Port", (), {"container": container})()
    monkeypatch.setattr(
        engine_module, "get_engine", lambda: type("_Engine", (), {"_agent_port": port})()
    )


@pytest.mark.ac("ADR-082526-3ca6/AC-1")
def test_the_container_constructs_both_delegation_dependencies() -> None:
    """Not `None` placeholders: ADR-082526-3ca6 says there is no configuration
    decision behind either, so both are built."""
    from maistro.a2a.delegate import A2ADelegator
    from maistro.a2a.guest_peers import GuestPeerManager
    from maistro.container import Container

    fields = Container.__dataclass_fields__
    assert "a2a_delegator" in fields
    assert "guest_peers" in fields
    # Cheap and dependency-free, which is why they are not optional.
    assert A2ADelegator() is not None
    assert GuestPeerManager() is not None


@pytest.mark.ac("ADR-082526-3ca6/AC-4")
def test_the_delegate_node_is_wired_from_the_container(monkeypatch) -> None:
    """The defect this issue was reopened for.

    Before #147's second half, this path built its resolver at import time with
    no arguments, so the node arrived with a2a_delegator=None, guest_peers=None
    and run_store=None — every delegation refused for want of a delegator, and
    delegated work could not be filed as a child Run.
    """
    import services.dag_agents as dag_agents

    container = _StubContainer()
    _with_container(monkeypatch, container)

    node = dag_agents._resolve_nodes_with()("d", _DELEGATE_DAG)

    assert node._a2a_delegator is container.a2a_delegator
    assert node._guest_peers is container.guest_peers
    assert node._run_store is container.run_store


@pytest.mark.ac("ADR-082526-3ca6/AC-4")
def test_the_node_gets_the_canonical_run_store_not_the_durable_one(monkeypatch) -> None:
    """Two stores whose names are one word apart and whose methods share nothing.

    `build_node_resolver`'s docstring records that passing the durable
    executor's store type-checks and then raises AttributeError on the first
    accepted delegation — after the work has already been dispatched. This
    module holds both, so the wrong one is one line away.
    """
    import services.dag_agents as dag_agents

    container = _StubContainer()
    _with_container(monkeypatch, container)

    node = dag_agents._resolve_nodes_with()("d", _DELEGATE_DAG)

    assert node._run_store is container.run_store
    assert node._run_store is not dag_agents.get_run_store(), (
        "the durable executor's store must not reach the delegate node"
    )


@pytest.mark.ac("ADR-082526-3ca6/AC-5")
def test_without_a_bridge_the_path_still_resolves_nodes(monkeypatch) -> None:
    """A Conductor running standalone must behave as it did, not fail to start."""
    import services.dag_agents as dag_agents
    import services.engine as engine_module

    port = type("_Port", (), {"container": None})()
    monkeypatch.setattr(
        engine_module, "get_engine", lambda: type("_Engine", (), {"_agent_port": port})()
    )

    resolver = dag_agents._resolve_nodes_with()
    assert resolver is dag_agents._fallback_node_resolver
    node = resolver("d", _DELEGATE_DAG)
    assert node._a2a_delegator is None


@pytest.mark.ac("ADR-082526-3ca6/AC-5")
def test_an_engine_that_raises_falls_back_rather_than_propagating(monkeypatch) -> None:
    """Resolving a node must not be the thing that breaks a DAG execution."""
    import services.dag_agents as dag_agents
    import services.engine as engine_module

    def _boom():
        raise RuntimeError("engine unavailable")

    monkeypatch.setattr(engine_module, "get_engine", _boom)
    assert dag_agents._resolve_nodes_with() is dag_agents._fallback_node_resolver


@pytest.mark.ac("ADR-082526-3ca6/AC-4")
def test_ordinary_node_kinds_are_unaffected_by_the_wiring(monkeypatch) -> None:
    """The delegate special case must not change how everything else resolves."""
    import services.dag_agents as dag_agents

    _with_container(monkeypatch, _StubContainer())
    node = dag_agents._resolve_nodes_with()(
        "only", {"nodes": [{"id": "only", "kind": "transform.alias_keys", "config": {}}]}
    )
    assert type(node).__name__ == "TransformAliasKeysNode"

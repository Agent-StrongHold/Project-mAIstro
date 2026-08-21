"""Tests for the DAG-as-agent registry."""

from __future__ import annotations

import contextlib
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph.dag_registry import (
    DagAgentDescriptor,
    DagRegistry,
    invoke_dag_agent,
)
from maistro.graph.nodes import BaseNode, NodeContext, register_node

# --- Fixture node + DAGs --------------------------------------------------


class _RegIn(BaseModel):
    x: str = ""


class _RegOut(BaseModel):
    y: str


class _RegNode(BaseNode[_RegIn, _RegOut]):
    kind: ClassVar[str] = "test.dag_registry_node"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _RegIn
    output_schema: ClassVar[type[BaseModel]] = _RegOut

    async def _execute(self, inputs: _RegIn, ctx: NodeContext) -> _RegOut:
        return _RegOut(y=inputs.x.upper())


with contextlib.suppress(ValueError):
    register_node(_RegNode)


def _ok_dag(dag_id: str = "ok-dag", *, use_case: str = "generic") -> dict[str, Any]:
    return {
        "id": dag_id,
        "name": f"DAG {dag_id}",
        "description": "test",
        "use_case": use_case,
        "nodes": [{"id": "n1", "kind": "test.dag_registry_node"}],
        "edges": [],
        "entry_node": "n1",
    }


# --- Registration ---------------------------------------------------------


def test_register_valid_dag_yields_dag_prefixed_agent_id() -> None:
    reg = DagRegistry()
    desc = reg.register(_ok_dag("alpha"))
    assert isinstance(desc, DagAgentDescriptor)
    assert desc.agent_id == "dag:alpha"
    assert desc.dag_id == "alpha"
    assert desc.version == 1
    assert "alpha" in reg
    assert "dag:alpha" in reg
    assert len(reg) == 1


def test_register_invalid_dag_raises_value_error() -> None:
    reg = DagRegistry()
    bad = {"id": "bad", "nodes": [], "edges": [], "entry_node": "x"}  # entry not in nodes
    with pytest.raises(ValueError, match="failed validation"):
        reg.register(bad)
    assert len(reg) == 0


def test_register_without_id_raises() -> None:
    """Registering a DAG with no id (and no nodes) fails validation first
    (no_entry), so the ValueError carries a validation message, not our
    `must have an id` guard. The guard catches the rare case where
    validation passes but the id is still empty (e.g. just an entry_node
    + dag-as-name-only)."""
    reg = DagRegistry()
    with pytest.raises(ValueError, match="failed validation"):
        reg.register({"nodes": [], "edges": []})


def test_register_with_only_name_uses_name_as_dag_id_fallback() -> None:
    """The registration guard says id falls back to name. With at least
    one valid node + entry, an id-less but name-set DAG should register."""
    reg = DagRegistry()
    desc = reg.register(
        {
            "name": "name-only-dag",
            "nodes": [{"id": "n1", "kind": "test.dag_registry_node"}],
            "edges": [],
            "entry_node": "n1",
        }
    )
    assert desc.dag_id == "name-only-dag"
    assert desc.agent_id == "dag:name-only-dag"


def test_register_unknown_kind_bubbles_up_as_value_error() -> None:
    reg = DagRegistry()
    dag = {
        "id": "unknown",
        "nodes": [{"id": "n", "kind": "not.a.real.kind"}],
        "edges": [],
        "entry_node": "n",
    }
    with pytest.raises(ValueError, match="failed validation"):
        reg.register(dag)


def test_re_register_bumps_version() -> None:
    reg = DagRegistry()
    d1 = reg.register(_ok_dag("v"))
    d2 = reg.register(_ok_dag("v"))  # same id again
    d3 = reg.register(_ok_dag("v"))
    assert d1.version == 1
    assert d2.version == 2
    assert d3.version == 3
    assert reg.get("v").version == 3


def test_register_carries_project_id_through() -> None:
    reg = DagRegistry()
    desc = reg.register(_ok_dag("scoped"), project_id="proj-a")
    assert desc.project_id == "proj-a"


# --- Lookup + listing -----------------------------------------------------


def test_get_accepts_short_and_prefixed_forms() -> None:
    reg = DagRegistry()
    reg.register(_ok_dag("a"))
    assert reg.get("a") is not None
    assert reg.get("dag:a") is not None
    assert reg.get("nonexistent") is None


def test_list_agents_filters_by_project_id() -> None:
    reg = DagRegistry()
    reg.register(_ok_dag("a"), project_id="p1")
    reg.register(_ok_dag("b"), project_id="p1")
    reg.register(_ok_dag("c"), project_id="p2")
    p1 = reg.list_agents(project_id="p1")
    p2 = reg.list_agents(project_id="p2")
    assert {d.dag_id for d in p1} == {"a", "b"}
    assert {d.dag_id for d in p2} == {"c"}


def test_list_agents_filters_by_use_case() -> None:
    reg = DagRegistry()
    reg.register(_ok_dag("pm-dag", use_case="pm_fleet"))
    reg.register(_ok_dag("art-dag", use_case="canvas_creative"))
    pm = reg.list_agents(use_case="pm_fleet")
    art = reg.list_agents(use_case="canvas_creative")
    assert {d.dag_id for d in pm} == {"pm-dag"}
    assert {d.dag_id for d in art} == {"art-dag"}


def test_list_agents_returns_sorted_by_agent_id() -> None:
    reg = DagRegistry()
    reg.register(_ok_dag("zeta"))
    reg.register(_ok_dag("alpha"))
    reg.register(_ok_dag("mu"))
    agents = reg.list_agents()
    assert [d.dag_id for d in agents] == ["alpha", "mu", "zeta"]


# --- Deregistration -------------------------------------------------------


def test_deregister_returns_true_when_existed() -> None:
    reg = DagRegistry()
    reg.register(_ok_dag("gone"))
    assert reg.deregister("gone") is True
    assert "gone" not in reg
    assert len(reg) == 0


def test_deregister_accepts_dag_prefixed_form_too() -> None:
    reg = DagRegistry()
    reg.register(_ok_dag("x"))
    assert reg.deregister("dag:x") is True


def test_deregister_returns_false_when_missing() -> None:
    reg = DagRegistry()
    assert reg.deregister("ghost") is False


# --- as_agent_catalog -----------------------------------------------------


def test_agent_catalog_serializes_shape_for_frontend() -> None:
    reg = DagRegistry()
    reg.register(_ok_dag("alpha"), project_id="p1")
    entries = reg.as_agent_catalog()
    assert len(entries) == 1
    e = entries[0]
    for required in ("id", "name", "description", "kind", "use_case", "project_id", "version"):
        assert required in e
    assert e["id"] == "dag:alpha"
    assert e["kind"] == "dag"
    assert e["project_id"] == "p1"


# --- invoke_dag_agent -----------------------------------------------------


async def test_invoke_passes_snapshot_to_runner_and_returns_result() -> None:
    reg = DagRegistry()
    reg.register(_ok_dag("ride"))

    captured: dict[str, Any] = {}

    async def _runner(snap: dict[str, Any]) -> dict[str, Any]:
        captured["snap"] = snap
        return {"status": "completed", "dag_id": snap["id"]}

    result = await invoke_dag_agent("dag:ride", registry=reg, runner=_runner, inputs={"x": "hello"})
    assert result == {"status": "completed", "dag_id": "ride"}
    assert captured["snap"]["id"] == "ride"
    # Inputs are attached under a runtime-only key the runner can lift.
    assert captured["snap"]["_runtime_inputs"] == {"x": "hello"}


async def test_invoke_unknown_agent_raises_keyerror() -> None:
    reg = DagRegistry()

    async def _noop(_: dict[str, Any]) -> dict[str, Any]:
        return {}

    with pytest.raises(KeyError, match="No DAG agent registered"):
        await invoke_dag_agent("dag:ghost", registry=reg, runner=_noop)


async def test_invoke_short_form_resolves_to_prefixed_descriptor() -> None:
    reg = DagRegistry()
    reg.register(_ok_dag("short"))

    async def _runner(snap: dict[str, Any]) -> dict[str, Any]:
        return {"id": snap["id"]}

    # Short form (without 'dag:') resolves to the same descriptor.
    res = await invoke_dag_agent("short", registry=reg, runner=_runner)
    assert res == {"id": "short"}


async def test_invoke_without_inputs_does_not_inject_runtime_key() -> None:
    reg = DagRegistry()
    reg.register(_ok_dag("noinputs"))

    captured: dict[str, Any] = {}

    async def _runner(snap: dict[str, Any]) -> dict[str, Any]:
        captured["snap"] = snap
        return {}

    await invoke_dag_agent("noinputs", registry=reg, runner=_runner)
    assert "_runtime_inputs" not in captured["snap"]

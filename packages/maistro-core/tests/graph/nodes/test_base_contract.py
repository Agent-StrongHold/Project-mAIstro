"""Contract tests for the Node base + registry.

These tests don't exercise any concrete node kind (those land in Phase 1b/1c
test files). They lock down the protocol: registration, retrieval, schema
serialization, sync execution path, error envelope, and the pause/resume
signal for wait/HITL kinds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph.nodes import (
    BaseNode,
    NodeContext,
    NodeResult,
    catalog_json,
    get_node,
    list_kinds,
    pause_until,
    register_node,
)

# --- Fixtures: minimal node kinds we register only for the test session. ----


class _EchoIn(BaseModel):
    value: str


class _EchoOut(BaseModel):
    echoed: str


class _EchoNode(BaseNode):
    kind: ClassVar[str] = "test.echo"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _EchoIn
    output_schema: ClassVar[type[BaseModel]] = _EchoOut
    cost_hint: ClassVar[float] = 0.0
    idempotent: ClassVar[bool] = True
    external_io: ClassVar[bool] = False
    display_name: ClassVar[str] = "Echo"
    description: ClassVar[str] = "Returns input as-is"

    async def _execute(self, inputs: _EchoIn, ctx: NodeContext) -> _EchoOut:
        return _EchoOut(echoed=inputs.value)


class _BoomNode(BaseNode):
    kind: ClassVar[str] = "test.boom"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _EchoIn
    output_schema: ClassVar[type[BaseModel]] = _EchoOut
    cost_hint: ClassVar[float] = 0.0
    idempotent: ClassVar[bool] = True

    async def _execute(self, inputs: _EchoIn, ctx: NodeContext) -> _EchoOut:
        raise RuntimeError("kaboom")


class _WaitNode(BaseNode):
    kind: ClassVar[str] = "test.wait"
    kind_category: ClassVar = "wait"
    input_schema: ClassVar[type[BaseModel]] = _EchoIn
    output_schema: ClassVar[type[BaseModel]] = _EchoOut
    cost_hint: ClassVar[float] = 0.0
    idempotent: ClassVar[bool] = True
    external_io: ClassVar[bool] = True

    async def _execute(self, inputs: _EchoIn, ctx: NodeContext) -> _EchoOut:
        resume_at = datetime.now(UTC) + timedelta(seconds=300)
        pause_until("waiting on test condition", resume_at=resume_at, metadata={"poll_id": "x"})
        # never reached
        return _EchoOut(echoed="should not get here")


# Register once at module import.
register_node(_EchoNode)
register_node(_BoomNode)
register_node(_WaitNode)


def _ctx() -> NodeContext:
    return NodeContext(run_id="r1", dag_id="d1", node_id="n1", user_id="u1", project_id="p1")


# --- Registration semantics -------------------------------------------------


def test_listed_kinds_contains_test_fixtures() -> None:
    kinds = list_kinds()
    assert "test.echo" in kinds
    assert "test.boom" in kinds
    assert "test.wait" in kinds


def test_get_node_returns_class() -> None:
    cls = get_node("test.echo")
    assert cls is _EchoNode


def test_get_node_unknown_raises_keyerror() -> None:
    with pytest.raises(KeyError, match="No node registered"):
        get_node("nope.does-not-exist")


def test_register_node_missing_kind_raises() -> None:
    class _Bad(BaseNode):
        # No `kind` set
        input_schema = _EchoIn
        output_schema = _EchoOut

    with pytest.raises(ValueError, match="missing required `kind`"):
        register_node(_Bad)


def test_register_node_collision_raises() -> None:
    class _AnotherEcho(BaseNode):
        kind: ClassVar[str] = "test.echo"
        input_schema: ClassVar[type[BaseModel]] = _EchoIn
        output_schema: ClassVar[type[BaseModel]] = _EchoOut

    with pytest.raises(ValueError, match="kind collision"):
        register_node(_AnotherEcho)


def test_register_node_idempotent_for_same_class() -> None:
    # Registering the same class twice is a no-op (defensive against re-imports).
    register_node(_EchoNode)  # already registered; same class — no error


# --- Run envelope -----------------------------------------------------------


@pytest.mark.asyncio
async def test_run_success_wraps_output_in_node_result() -> None:
    node = _EchoNode()
    result = await node.run(_EchoIn(value="hi"), _ctx())
    assert isinstance(result, NodeResult)
    assert result.success is True
    assert result.status == "completed"
    assert result.latency_ms >= 0
    assert isinstance(result.output, _EchoOut)
    assert result.output.echoed == "hi"


@pytest.mark.asyncio
async def test_run_validates_input_schema() -> None:
    """If the runtime passes a dict (not the typed model), the node coerces."""
    node = _EchoNode()
    result = await node.run({"value": "from-dict"}, _ctx())  # type: ignore[arg-type]
    assert result.success
    assert isinstance(result.output, _EchoOut)
    assert result.output.echoed == "from-dict"


@pytest.mark.asyncio
async def test_run_traps_exceptions_into_failed_envelope() -> None:
    node = _BoomNode()
    result = await node.run(_EchoIn(value="x"), _ctx())
    assert result.success is False
    assert result.status == "failed"
    assert result.error_code == "RuntimeError"
    assert "kaboom" in (result.error_message or "")
    assert result.output is None


@pytest.mark.asyncio
async def test_run_wait_node_surfaces_paused_status() -> None:
    node = _WaitNode()
    result = await node.run(_EchoIn(value="x"), _ctx())
    assert result.success is True  # paused != failed
    assert result.status == "paused"
    assert result.resume_at is not None
    assert result.resume_at > datetime.now(UTC)
    assert result.metadata.get("paused_reason") == "waiting on test condition"
    assert result.metadata.get("poll_id") == "x"


# --- Catalog serialization (for frontend palette) ---------------------------


def test_catalog_json_includes_test_kinds_with_required_fields() -> None:
    cat = catalog_json()
    by_kind = {e["kind"]: e for e in cat}
    assert "test.echo" in by_kind
    entry = by_kind["test.echo"]
    assert entry["kind_category"] == "sync.transform"
    assert entry["display_name"] == "Echo"
    assert entry["description"] == "Returns input as-is"
    assert entry["cost_hint"] == 0.0
    assert entry["idempotent"] is True
    assert entry["external_io"] is False
    # Schema summary is the minimum the UI uses for edge validation.
    assert entry["input_schema"]["name"] == "_EchoIn"
    assert any(f["name"] == "value" and f["required"] for f in entry["input_schema"]["fields"])
    assert entry["output_schema"]["name"] == "_EchoOut"
    assert any(f["name"] == "echoed" for f in entry["output_schema"]["fields"])


def test_catalog_json_sorted_by_category_then_kind() -> None:
    cat = catalog_json()
    keys = [(e["kind_category"], e["kind"]) for e in cat]
    assert keys == sorted(keys)

"""A typed node output survives the durable-store round trip (#566).

``NodeResult.output`` is declared ``dict[str, Any] | BaseModel | None``. Pydantic
serializes a union member typed as bare ``BaseModel`` through *that declared
schema*, which has no fields, so a node returning a typed model used to persist
as ``{}``. The logical outcome survived, because the executor dumps the model
explicitly before writing ``NodeRun.result``; the physical Attempt record --
what actually ran and what it produced -- did not.

These tests hold the serialization contract itself, not the call sites: the
first two go through ``NodeResult`` directly, and the rest push a real Attempt
through each concrete store.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, RootModel

from maistro.graph import Graph, Node
from maistro.graph.durable_runs.stores import InMemoryDurableRunStore, SqliteDurableRunStore
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes.base import NodeResult
from maistro.runs.model import Attempt, AttemptStatus, GraphSnapshot, NodeRun, Run


class TagsOutput(RootModel[list[str]]):
    """A node output whose root is a list, not an object."""


class ScoreOutput(RootModel[float]):
    """A node output whose root is a bare scalar."""


class TypedOutput(BaseModel):
    """A node's own output schema -- the shape the declared union erased."""

    text: str
    score: int = 7


def _record_with_attempt(result: object) -> DurableRunRecord:
    graph = Graph(
        workspace_id="ws-1",
        project_id="project-1",
        name="Typed output",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = Run(
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        graph=GraphSnapshot.from_graph(graph),
    )
    node_run = NodeRun(run_id=run.run_id, node_id="node-1", ordinal=1)
    attempt = Attempt(
        node_run_id=node_run.node_run_id,
        ordinal=1,
        status=AttemptStatus.CREATED,
        result=result,
    )
    return DurableRunRecord(
        run=run,
        graph_state=GraphExecutionState(run_id=run.run_id, active_node_ids=("node-1",)),
        node_runs=(node_run,),
        attempts=(attempt,),
    )


@pytest.mark.ac("SPEC-082926-2844/AC-1")
def test_a_typed_output_serializes_its_own_fields() -> None:
    result = NodeResult(success=True, output=TypedOutput(text="done"))

    assert '"text":"done"' in result.model_dump_json()
    assert result.model_dump(mode="json")["output"] == {"text": "done", "score": 7}


@pytest.mark.ac("SPEC-082926-2844/AC-1")
def test_a_typed_output_survives_a_nodresult_round_trip() -> None:
    result = NodeResult(success=True, output=TypedOutput(text="done"))

    revived = NodeResult.model_validate_json(result.model_dump_json())

    assert revived.output == {"text": "done", "score": 7}


@pytest.mark.ac("SPEC-082926-2844/AC-1")
def test_a_plain_mapping_output_is_unchanged() -> None:
    result = NodeResult(success=True, output={"text": "done"})

    assert NodeResult.model_validate_json(result.model_dump_json()).output == {"text": "done"}


@pytest.mark.ac("SPEC-082926-2844/AC-1")
def test_a_root_model_output_survives_its_own_shape() -> None:
    """The write side accepts every `BaseModel`, so the read side must too.

    A `RootModel` serializes to its root -- a list here, a bare scalar below.
    Against a dict-only read branch these serialized correctly and then failed
    validation coming back, which is worse than the loss being fixed: the old
    contract dropped them silently, a half-fixed one raises.
    """
    result = NodeResult(success=True, output=TagsOutput(["alpha", "beta"]))

    assert NodeResult.model_validate_json(result.model_dump_json()).output == ["alpha", "beta"]


@pytest.mark.ac("SPEC-082926-2844/AC-1")
def test_a_scalar_root_model_output_survives() -> None:
    result = NodeResult(success=True, output=ScoreOutput(1.5))

    assert NodeResult.model_validate_json(result.model_dump_json()).output == 1.5


@pytest.mark.ac("SPEC-082926-2844/AC-1")
def test_an_absent_output_is_unchanged() -> None:
    result = NodeResult(success=True)

    assert NodeResult.model_validate_json(result.model_dump_json()).output is None


@pytest.mark.ac("SPEC-082926-2844/AC-2")
async def test_in_memory_store_keeps_the_typed_attempt_output() -> None:
    record = _record_with_attempt(NodeResult(success=True, output=TypedOutput(text="done")))
    store = InMemoryDurableRunStore()

    await store.create(record)
    reread = await store.get(record.run_id)

    assert reread is not None
    assert reread.attempts[0].result["output"] == {"text": "done", "score": 7}


@pytest.mark.ac("SPEC-082926-2844/AC-2")
async def test_sqlite_store_keeps_the_typed_attempt_output(tmp_path: Path) -> None:
    record = _record_with_attempt(NodeResult(success=True, output=TypedOutput(text="done")))
    store = SqliteDurableRunStore(tmp_path / "runs.sqlite3")

    await store.create(record)
    reread = await store.get(record.run_id)

    assert reread is not None
    assert reread.attempts[0].result["output"] == {"text": "done", "score": 7}

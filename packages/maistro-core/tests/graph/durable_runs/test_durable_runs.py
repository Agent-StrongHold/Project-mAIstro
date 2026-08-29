"""Durable run state + executor tests.

Covers:
- InMemoryDurableRunStore: CRUD, optimistic concurrency, HITL answer flow.
- SqliteDurableRunStore: same surface via a tmp_path-backed file (proves
  the persistence layer round-trips records identically).
- Executor (run_durable_dag / resume_durable_dag):
  - sync DAG (all transforms) walks to completion in one call
  - HITL DAG pauses on first call; resumes after submit_hitl_answer
  - wait DAG pauses, resumes after a re-invoke (via the same resume path)
  - failed node halts the run
  - negative_signal compliance.block with halt_run=true halts the run
  - simulated container restart: drop the executor + store reference,
    rebuild from disk, resume; the run completes correctly.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph.durable_runs import (
    DurableRunRecord,
    DurableRunStore,
    InMemoryDurableRunStore,
    RunStatus,
    SqliteDurableRunStore,
)
from maistro.graph.nodes import (
    BaseNode,
    NodeContext,
    get_node,
    pause_until,
    register_node,
)

from .._canonical_helpers import (
    durable_record,
)
from .._canonical_helpers import (
    resume_legacy_dag_fixture as resume_durable_dag,
)
from .._canonical_helpers import (
    run_legacy_dag_fixture as run_durable_dag,
)

# --- Test fixtures: tiny nodes registered just for these tests -------------


class _UpperIn(BaseModel):
    text: str


class _UpperOut(BaseModel):
    text: str


class _UppercaseNode(BaseNode):
    kind: ClassVar[str] = "test.uppercase"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _UpperIn
    output_schema: ClassVar[type[BaseModel]] = _UpperOut

    async def _execute(self, inputs: _UpperIn, ctx: NodeContext) -> _UpperOut:
        return _UpperOut(text=inputs.text.upper())


class _AppendIn(BaseModel):
    text: str
    suffix: str = "!"


class _AppendOut(BaseModel):
    text: str


class _AppendNode(BaseNode):
    kind: ClassVar[str] = "test.append"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _AppendIn
    output_schema: ClassVar[type[BaseModel]] = _AppendOut

    async def _execute(self, inputs: _AppendIn, ctx: NodeContext) -> _AppendOut:
        return _AppendOut(text=inputs.text + inputs.suffix)


class _AskIn(BaseModel):
    question: str


class _AskOut(BaseModel):
    # Emit `text` so a downstream _AppendNode (which expects {text, suffix})
    # picks the answer up by name. This matches the executor's default
    # "upstream output wins" flow without needing an explicit input-map.
    text: str


class _MiniAskNode(BaseNode):
    """A HITL node small enough to drive without the full human.ask_question
    metadata machinery — pauses with `awaiting_human_answer`, resumes when
    the answer arrives in ctx.metadata['hitl_answers'][node_id]."""

    kind: ClassVar[str] = "test.mini_ask"
    kind_category: ClassVar = "hitl"
    input_schema: ClassVar[type[BaseModel]] = _AskIn
    output_schema: ClassVar[type[BaseModel]] = _AskOut

    async def _execute(self, inputs: _AskIn, ctx: NodeContext) -> _AskOut:
        answers = (ctx.metadata or {}).get("hitl_answers") or {}
        existing = answers.get(ctx.node_id)
        if existing is not None:
            return _AskOut(text=str(existing.get("answer") or ""))
        pause_until(
            "awaiting_human_answer",
            resume_at=datetime.now(UTC) + timedelta(seconds=300),
            metadata={"question": inputs.question},
        )
        return _AskOut(text="UNREACHABLE")


class _BoomIn(BaseModel):
    pass


class _BoomOut(BaseModel):
    pass


class _DurableBoomNode(BaseNode):
    # Distinct kind from the contract-test fixture so cross-file pytest
    # collection doesn't trip the registry's collision guard.
    kind: ClassVar[str] = "test.durable_boom"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _BoomIn
    output_schema: ClassVar[type[BaseModel]] = _BoomOut

    async def _execute(self, inputs: _BoomIn, ctx: NodeContext) -> _BoomOut:
        raise ValueError("intentional test failure")


for _cls in (_UppercaseNode, _AppendNode, _MiniAskNode, _DurableBoomNode):
    # Tests rerun in the same process; collision is fine.
    with contextlib.suppress(ValueError):
        register_node(_cls)


def _resolver(node_id: str, dag: dict[str, Any]) -> BaseNode:
    """Phase-1 resolver: find the kind in dag.nodes[*].kind, look it up."""
    for n in dag.get("nodes", []):
        if str(n.get("id")) == node_id:
            return get_node(n["kind"])()
    raise KeyError(node_id)


# --- InMemoryDurableRunStore CRUD + concurrency ----------------------------


@pytest.fixture
def mem_store() -> DurableRunStore:
    return InMemoryDurableRunStore()


def _record_for(run_id: str) -> DurableRunRecord:
    return durable_record(
        {"id": "d1", "nodes": [{"id": "n1"}], "edges": []},
        run_id=run_id,
    )


async def test_create_get_roundtrip(mem_store: DurableRunStore) -> None:
    await mem_store.create(_record_for("r-1"))
    got = await mem_store.get("r-1")
    assert got is not None
    assert got.run_id == "r-1"
    assert got.version == 1


async def test_create_collision_raises(mem_store: DurableRunStore) -> None:
    await mem_store.create(_record_for("r-1"))
    with pytest.raises(ValueError, match="collision"):
        await mem_store.create(_record_for("r-1"))


async def test_update_requires_higher_version(mem_store: DurableRunStore) -> None:
    rec = await mem_store.create(_record_for("r-1"))
    bumped = rec.model_copy(update={"version": 2})
    await mem_store.update(bumped)
    with pytest.raises(ValueError, match="version regression"):
        await mem_store.update(bumped)  # version still 2 — rejected


async def test_list_by_status_filters_correctly(mem_store: DurableRunStore) -> None:
    a = _record_for("a")
    b = durable_record(
        {"id": "d1", "nodes": [{"id": "n1"}], "edges": []},
        run_id="b",
        status=RunStatus.COMPLETED,
    )
    await mem_store.create(a)
    await mem_store.create(b)
    running = await mem_store.list_by_status(RunStatus.RUNNING)
    completed = await mem_store.list_by_status(RunStatus.COMPLETED)
    assert {r.run_id for r in running} == {"a"}
    assert {r.run_id for r in completed} == {"b"}


# --- SqliteDurableRunStore: same surface, persistence verified ------------


async def test_sqlite_store_roundtrips_across_reopen(tmp_path) -> None:
    db = tmp_path / "durable.db"
    store1 = SqliteDurableRunStore(db)
    rec = durable_record(
        {"id": "d1", "nodes": [{"id": "ask-1"}], "edges": []},
        run_id="r-sqlite-1",
        status=RunStatus.PAUSED,
        active_node_id="ask-1",
    )
    await store1.create(rec)

    # New store instance, same file — simulates process restart.
    store2 = SqliteDurableRunStore(db)
    got = await store2.get("r-sqlite-1")
    assert got is not None
    assert got.status == RunStatus.PAUSED
    assert got.active_node_id == "ask-1"


async def test_sqlite_store_optimistic_concurrency(tmp_path) -> None:
    store = SqliteDurableRunStore(tmp_path / "durable.db")
    rec = await store.create(_record_for("r-1"))
    bumped = rec.model_copy(update={"version": 2})
    await store.update(bumped)
    with pytest.raises(ValueError, match="version regression"):
        await store.update(bumped)


# --- Executor: sync DAG runs to completion in one call --------------------


def _sync_dag() -> dict[str, Any]:
    return {
        "id": "sync-dag",
        "name": "uppercase-then-append",
        "nodes": [
            {"id": "n1", "kind": "test.uppercase", "inputs": {"text": "hello"}},
            {"id": "n2", "kind": "test.append", "config": {"suffix": "!!"}},
        ],
        "edges": [{"from_node": "n1", "to_node": "n2"}],
        "entry_node": "n1",
    }


async def test_run_sync_dag_completes_in_one_walk(mem_store: DurableRunStore) -> None:
    result = await run_durable_dag(
        _sync_dag(),
        store=mem_store,
        node_resolver=_resolver,
        inputs={"text": "hello"},
        user_id="alice",
        project_id="proj-a",
    )
    assert result.status == RunStatus.COMPLETED
    assert result.run.finished_at is not None
    assert len(result.node_runs) == 2
    assert result.node_runs[0].node_id == "n1"
    assert result.node_runs[0].result == {"text": "HELLO"}
    assert result.node_runs[1].node_id == "n2"
    assert result.node_runs[1].result == {"text": "HELLO!!"}


async def test_run_sync_dag_persists_each_node_to_store(mem_store: DurableRunStore) -> None:
    result = await run_durable_dag(
        _sync_dag(),
        store=mem_store,
        node_resolver=_resolver,
        inputs={"text": "x"},
    )
    on_disk = await mem_store.get(result.run_id)
    assert on_disk is not None
    assert on_disk.status == RunStatus.COMPLETED
    assert len(on_disk.node_runs) == 2


async def test_ordinary_frontier_visit_bump_is_bridged_between_commits(
    mem_store: DurableRunStore,
) -> None:
    """Regression: a plain sync walk mutates durable state outside any commit.

    Materializing the next frontier's NodeRuns bumps ``visit_counts`` and
    persists that state before the frontier can advance. The resulting commit's
    ``prior_state_hash`` therefore cannot equal the previous commit's
    ``resulting_state_hash``, and without a persisted ``TraversalCheckpoint``
    bridge every multi-node walk fails ``DurableRunRecord`` validation with
    "adjacent TraversalCommits must link resulting and prior state hashes".

    No pause, wait, or HITL is involved here - this is the ordinary path.
    """
    result = await run_durable_dag(
        _sync_dag(),
        store=mem_store,
        node_resolver=_resolver,
        inputs={"text": "hello"},
        user_id="alice",
        project_id="proj-a",
    )

    assert result.status == RunStatus.COMPLETED
    assert len(result.traversal_commits) == 2
    first, second = result.traversal_commits

    # The n2 frontier bumped visit_counts after the first commit, so the second
    # commit must bridge that intervening state rather than link to it directly.
    assert second.prior_state_hash != first.resulting_state_hash
    assert second.checkpoint_id is not None

    bridge = next(
        checkpoint
        for checkpoint in result.traversal_checkpoints
        if checkpoint.traversal_checkpoint_id == second.checkpoint_id
    )
    assert bridge.state_hash == second.prior_state_hash


# --- Executor: HITL DAG pauses then resumes -------------------------------


def _hitl_dag() -> dict[str, Any]:
    return {
        "id": "hitl-dag",
        "name": "uppercase → ask → append",
        "nodes": [
            {"id": "u1", "kind": "test.uppercase", "inputs": {"text": "hi"}},
            {"id": "ask", "kind": "test.mini_ask", "inputs": {"question": "Continue?"}},
            {"id": "a1", "kind": "test.append", "config": {"suffix": " <done>"}},
        ],
        "edges": [
            {"from_node": "u1", "to_node": "ask"},
            {"from_node": "ask", "to_node": "a1"},
        ],
        "entry_node": "u1",
    }


async def test_hitl_dag_pauses_at_ask_node(mem_store: DurableRunStore) -> None:
    result = await run_durable_dag(
        _hitl_dag(),
        store=mem_store,
        node_resolver=_resolver,
        inputs={"text": "hi"},
        user_id="alice",
    )
    assert result.status == RunStatus.PAUSED
    assert result.active_node_id == "ask"
    # First node should have completed successfully.
    by_id = {nr.node_id: nr for nr in result.node_runs}
    assert by_id["u1"].status is RunStatus.COMPLETED
    assert by_id["u1"].result == {"text": "HI"}
    # Ask node recorded with phase=paused and the question metadata.
    assert by_id["ask"].status is RunStatus.PAUSED
    assert result.graph_state.metadata["pause"]["metadata"]["question"] == "Continue?"


async def test_hitl_dag_resumes_after_submit_answer(mem_store: DurableRunStore) -> None:
    started = await run_durable_dag(
        _hitl_dag(),
        store=mem_store,
        node_resolver=_resolver,
        inputs={"text": "hi"},
    )
    assert started.status == RunStatus.PAUSED

    await mem_store.submit_hitl_answer(started.run_id, "ask", {"answer": "yes"})
    resumed = await resume_durable_dag(
        started.run_id,
        store=mem_store,
        node_resolver=_resolver,
    )
    assert resumed.status == RunStatus.COMPLETED
    by_id = {nr.node_id: nr for nr in resumed.node_runs}
    assert by_id["ask"].status is RunStatus.COMPLETED
    # _MiniAskNode emits its `text` field so downstream nodes that expect
    # {text, suffix} (like _AppendNode) pick it up by name.
    assert by_id["ask"].result == {"text": "yes"}
    assert by_id["a1"].status is RunStatus.COMPLETED
    # Append got "yes" from upstream + suffix " <done>".
    assert by_id["a1"].result == {"text": "yes <done>"}


# --- Executor: failure halts the run --------------------------------------


def _boom_dag() -> dict[str, Any]:
    return {
        "id": "boom-dag",
        "name": "uppercase → boom",
        "nodes": [
            {"id": "u1", "kind": "test.uppercase", "inputs": {"text": "hi"}},
            {"id": "boom", "kind": "test.durable_boom"},
        ],
        "edges": [{"from_node": "u1", "to_node": "boom"}],
        "entry_node": "u1",
    }


async def test_failed_node_marks_run_failed(mem_store: DurableRunStore) -> None:
    result = await run_durable_dag(
        _boom_dag(),
        store=mem_store,
        node_resolver=_resolver,
    )
    assert result.status == RunStatus.FAILED
    assert result.run.error is not None
    assert result.run.error.startswith("ValueError:")
    assert "intentional test failure" in result.run.error
    by_id = {nr.node_id: nr for nr in result.node_runs}
    assert by_id["u1"].status is RunStatus.COMPLETED
    assert by_id["boom"].status is RunStatus.FAILED
    assert by_id["boom"].error is not None
    assert by_id["boom"].error.startswith("ValueError:")


# --- Executor: simulated container restart --------------------------------


async def test_sqlite_paused_run_resumes_after_simulated_restart(tmp_path) -> None:
    db = tmp_path / "durable.db"

    # Boot 1: start run, pause at HITL, drop the store reference.
    store1 = SqliteDurableRunStore(db)
    started = await run_durable_dag(
        _hitl_dag(),
        store=store1,
        node_resolver=_resolver,
        inputs={"text": "hi"},
        user_id="alice",
    )
    assert started.status == RunStatus.PAUSED
    run_id = started.run_id
    del store1

    # Boot 2: fresh store instance on the same file.
    store2 = SqliteDurableRunStore(db)
    persisted = await store2.get(run_id)
    assert persisted is not None
    assert persisted.status == RunStatus.PAUSED
    # Submit the answer.
    await store2.submit_hitl_answer(run_id, "ask", {"answer": "shipped"})
    final = await resume_durable_dag(run_id, store=store2, node_resolver=_resolver)
    assert final.status == RunStatus.COMPLETED
    # And the answer survived the restart through to the downstream node.
    by_id = {nr.node_id: nr for nr in final.node_runs}
    assert by_id["a1"].result == {"text": "shipped <done>"}


# --- Executor: compliance.block halt_run=True halts the run ---------------


async def test_compliance_block_with_halt_run_marks_run_failed(
    mem_store: DurableRunStore,
) -> None:
    dag = {
        "id": "halt-dag",
        "name": "uppercase → compliance.block(halt) → append",
        "nodes": [
            {"id": "u1", "kind": "test.uppercase", "inputs": {"text": "x"}},
            {
                "id": "block",
                "kind": "compliance.block",
                "inputs": {
                    "rule_id": "policy.test",
                    "severity": 5.0,
                    "halt_run": True,
                    "reason": "test halt",
                },
            },
            {"id": "a1", "kind": "test.append", "config": {"suffix": "!"}},
        ],
        "edges": [
            {"from_node": "u1", "to_node": "block"},
            {"from_node": "block", "to_node": "a1"},
        ],
        "entry_node": "u1",
    }
    result = await run_durable_dag(
        dag, store=mem_store, node_resolver=_resolver, inputs={"text": "x"}
    )
    # compliance.block emits halt_requested into the blackboard; the
    # executor lifts the blackboard mutation back into the durable snapshot
    # AFTER each node completes, then checks halt_requested before
    # advancing. So u1 ran, block ran (success), then halt fired before a1.
    assert result.status == RunStatus.FAILED
    assert result.run.error is not None
    assert result.run.error.startswith("HaltRequested:")
    assert "test halt" in result.run.error
    by_id = {nr.node_id: nr for nr in result.node_runs}
    assert by_id["u1"].status is RunStatus.COMPLETED
    assert by_id["block"].status is RunStatus.COMPLETED
    assert by_id["block"].result is not None
    assert by_id["block"].result["halt_run"] is True
    # a1 must NOT have run — the halt fired before advancing to it.
    assert "a1" not in by_id


# --- Executor: synth_depth propagation for agent.synth_dag / spawn_harness -


class _SynthDepthChildIn(BaseModel):
    pass


class _SynthDepthChildOut(BaseModel):
    text: str


class _SynthDepthChildNode(BaseNode):
    """Concrete child work dispatched by the real synth node in depth tests."""

    kind: ClassVar[str] = "test.synth_depth_child"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _SynthDepthChildIn
    output_schema: ClassVar[type[BaseModel]] = _SynthDepthChildOut

    async def _execute(self, inputs: _SynthDepthChildIn, ctx: NodeContext) -> _SynthDepthChildOut:
        return _SynthDepthChildOut(text="child work completed")


with contextlib.suppress(ValueError):
    register_node(_SynthDepthChildNode)


class _SynthDepthChildSynthesizer:
    async def synthesize(self, request: Any) -> Any:
        from maistro.graph.synth import SynthResult
        from maistro.graph.types import GraphConfig

        config = GraphConfig(
            nodes=[_SynthDepthChildNode.kind],
            edges=[],
            entry=_SynthDepthChildNode.kind,
        )
        return SynthResult(
            graph_config=config,
            rationale="dispatch one concrete child step",
            synthesized_kinds=[_SynthDepthChildNode.kind],
        )


class _AlwaysJustifySynthDepthChild:
    async def judge(self, shape: Any) -> Any:
        from maistro.security.dag_shape.proportionality import ProportionalityVerdict

        return ProportionalityVerdict(justified=True, reason="focused depth fixture")


def _genuinely_dispatching_synth(
    store: DurableRunStore,
    *,
    max_depth: int = 3,
) -> BaseNode:
    from maistro.graph.nodes.agent_synth_dag import AgentSynthDagNode

    return AgentSynthDagNode(
        synthesizer=_SynthDepthChildSynthesizer(),
        proportionality_judge=_AlwaysJustifySynthDepthChild(),
        max_depth=max_depth,
        run_store=store,
    )


async def _assert_genuine_synth_child_run(
    store: DurableRunStore,
    result: DurableRunRecord,
) -> None:
    """Prove dispatch evidence came from persisted child Run work, not a flag proxy."""
    parent_node_run = next(node_run for node_run in result.node_runs if node_run.node_id == "n1")
    output = parent_node_run.result
    assert output is not None
    assert output["dispatched"] is True
    assert output["child_run_id"]

    child = await store.get(output["child_run_id"])
    assert child is not None
    assert child.run.parent_run_id == result.run_id
    assert child.run.parent_node_run_id == parent_node_run.node_run_id
    assert [node_run.node_id for node_run in child.node_runs] == [_SynthDepthChildNode.kind]
    assert child.node_runs[0].result == {"text": "child work completed"}
    assert len(child.attempts) == 1


async def test_synth_depth_increments_for_the_node_after_a_synth_dag_node(
    mem_store: DurableRunStore,
) -> None:
    """A persisted child Run increments depth for the following node."""
    captured_depths: list[int] = []

    class _CaptureDepthIn(BaseModel):
        pass

    class _CaptureDepthOut(BaseModel):
        pass

    class _CaptureDepthNode(BaseNode):
        kind: ClassVar[str] = "test.capture_synth_depth"
        kind_category: ClassVar = "sync.transform"
        input_schema: ClassVar[type[BaseModel]] = _CaptureDepthIn
        output_schema: ClassVar[type[BaseModel]] = _CaptureDepthOut

        async def _execute(self, inputs: _CaptureDepthIn, ctx: NodeContext) -> _CaptureDepthOut:
            captured_depths.append(int((ctx.metadata or {}).get("synth_depth", 0)))
            return _CaptureDepthOut()

    def _local_resolver(node_id: str, dag: dict[str, Any]) -> BaseNode:
        if node_id == "n1":
            return _genuinely_dispatching_synth(mem_store)
        return _CaptureDepthNode()

    dag = {
        "id": "synth-depth-dag",
        "name": "synth-depth",
        "nodes": [
            {"id": "n1", "kind": "agent.synth_dag", "inputs": {"objective": "add caching"}},
            {"id": "n2", "kind": "test.capture_synth_depth"},
        ],
        "edges": [{"from_node": "n1", "to_node": "n2"}],
        "entry_node": "n1",
    }

    result = await run_durable_dag(dag, store=mem_store, node_resolver=_local_resolver)
    assert result.status == RunStatus.COMPLETED
    await _assert_genuine_synth_child_run(mem_store, result)
    assert captured_depths == [1]


async def test_agent_synth_dag_refuses_to_spawn_once_depth_reaches_cap_via_durable_walk(
    mem_store: DurableRunStore,
) -> None:
    """A real nested synth refuses once prior dispatch evidence reaches its cap."""
    from maistro.graph.nodes.agent_synth_dag import AgentSynthDagNode

    def _local_resolver(node_id: str, dag: dict[str, Any]) -> BaseNode:
        if node_id == "n1":
            return _genuinely_dispatching_synth(mem_store)
        return AgentSynthDagNode(max_depth=1)

    dag = {
        "id": "synth-depth-cap-dag",
        "name": "synth-depth-cap",
        "nodes": [
            {"id": "n1", "kind": "agent.synth_dag", "inputs": {"objective": "add caching"}},
            {"id": "n2", "kind": "agent.synth_dag", "inputs": {"objective": "nested work"}},
        ],
        "edges": [{"from_node": "n1", "to_node": "n2"}],
        "entry_node": "n1",
    }

    result = await run_durable_dag(dag, store=mem_store, node_resolver=_local_resolver)
    # A business-level refusal isn't an executor-level failure — n2's own
    # output says so, but the walk still completes normally.
    assert result.status == RunStatus.COMPLETED
    await _assert_genuine_synth_child_run(mem_store, result)
    n2_output = result.node_runs[-1].result
    assert n2_output is not None
    assert n2_output["success"] is False
    assert n2_output["dispatched"] is False
    assert "recursion depth cap reached" in n2_output["error"]


async def test_refused_synth_dag_does_not_increment_depth_for_the_next_node(
    mem_store: DurableRunStore,
) -> None:
    """A depth-cap refusal does not consume another recursion level."""
    from maistro.graph.nodes.agent_synth_dag import AgentSynthDagNode

    captured_depths: list[int] = []

    class _CaptureDepthIn(BaseModel):
        pass

    class _CaptureDepthOut(BaseModel):
        pass

    class _CaptureDepthNode(BaseNode):
        kind: ClassVar[str] = "test.capture_synth_depth_after_refusal"
        kind_category: ClassVar = "sync.transform"
        input_schema: ClassVar[type[BaseModel]] = _CaptureDepthIn
        output_schema: ClassVar[type[BaseModel]] = _CaptureDepthOut

        async def _execute(self, inputs: _CaptureDepthIn, ctx: NodeContext) -> _CaptureDepthOut:
            captured_depths.append(int((ctx.metadata or {}).get("synth_depth", 0)))
            return _CaptureDepthOut()

    def _local_resolver(node_id: str, dag: dict[str, Any]) -> BaseNode:
        if node_id == "n1":
            return _genuinely_dispatching_synth(mem_store)
        if node_id == "n2":
            return AgentSynthDagNode(max_depth=1)  # depth=1 here -> LEAF -> refuses
        return _CaptureDepthNode()

    dag = {
        "id": "synth-depth-refusal-dag",
        "name": "synth-depth-refusal",
        "nodes": [
            {"id": "n1", "kind": "agent.synth_dag", "inputs": {"objective": "add caching"}},
            {"id": "n2", "kind": "agent.synth_dag", "inputs": {"objective": "nested work"}},
            {"id": "n3", "kind": "test.capture_synth_depth_after_refusal"},
        ],
        "edges": [
            {"from_node": "n1", "to_node": "n2"},
            {"from_node": "n2", "to_node": "n3"},
        ],
        "entry_node": "n1",
    }

    result = await run_durable_dag(dag, store=mem_store, node_resolver=_local_resolver)
    assert result.status == RunStatus.COMPLETED
    await _assert_genuine_synth_child_run(mem_store, result)
    # n1 dispatched -> depth becomes 1 for n2. n2 refuses at the cap -> depth
    # must stay 1 for n3, not bump to 2.
    assert captured_depths == [1]


async def test_synth_dag_with_failed_subgraph_still_increments_depth_for_the_next_node(
    mem_store: DurableRunStore,
) -> None:
    """Contrast with the refusal case above: here the synth node actually
    dispatches its sub-graph as a canonical child Run (#520) -- but the
    child's own execution fails. That's a real spawn attempt, not a declined
    one, so depth must still burn a level for whatever runs next."""
    from maistro.graph.nodes.agent_synth_dag import AgentSynthDagNode
    from maistro.graph.synth import SynthRequest, SynthResult
    from maistro.graph.types import GraphConfig
    from maistro.security.dag_shape.proportionality import ProportionalityVerdict

    class _AlwaysJustified:
        async def judge(self, shape: Any) -> ProportionalityVerdict:
            return ProportionalityVerdict(justified=True, reason="fine")

    class _FailingChildIn(BaseModel):
        pass

    class _FailingChildOut(BaseModel):
        pass

    class _FailingChildNode(BaseNode):
        kind: ClassVar[str] = "test.synth_child_that_fails"
        kind_category: ClassVar = "sync.transform"
        input_schema: ClassVar[type[BaseModel]] = _FailingChildIn
        output_schema: ClassVar[type[BaseModel]] = _FailingChildOut

        async def _execute(self, inputs: _FailingChildIn, ctx: NodeContext) -> _FailingChildOut:
            raise RuntimeError("sub-graph blew up")

    with contextlib.suppress(ValueError):
        register_node(_FailingChildNode)

    class _FailingChildSynthesizer:
        async def synthesize(self, request: SynthRequest) -> SynthResult:
            config = GraphConfig(
                nodes=[_FailingChildNode.kind],
                edges=[],
                entry=_FailingChildNode.kind,
            )
            return SynthResult(
                graph_config=config,
                rationale="one failing step",
                synthesized_kinds=[_FailingChildNode.kind],
            )

    captured_depths: list[int] = []

    class _CaptureDepthIn(BaseModel):
        pass

    class _CaptureDepthOut(BaseModel):
        pass

    class _CaptureDepthNode(BaseNode):
        kind: ClassVar[str] = "test.capture_synth_depth_after_failed_subgraph"
        kind_category: ClassVar = "sync.transform"
        input_schema: ClassVar[type[BaseModel]] = _CaptureDepthIn
        output_schema: ClassVar[type[BaseModel]] = _CaptureDepthOut

        async def _execute(self, inputs: _CaptureDepthIn, ctx: NodeContext) -> _CaptureDepthOut:
            captured_depths.append(int((ctx.metadata or {}).get("synth_depth", 0)))
            return _CaptureDepthOut()

    def _local_resolver(node_id: str, dag: dict[str, Any]) -> BaseNode:
        if node_id == "n1":
            return AgentSynthDagNode(
                synthesizer=_FailingChildSynthesizer(),
                proportionality_judge=_AlwaysJustified(),
                run_store=InMemoryDurableRunStore(),
            )
        return _CaptureDepthNode()

    dag = {
        "id": "synth-depth-failed-subgraph-dag",
        "name": "synth-depth-failed-subgraph",
        "nodes": [
            {"id": "n1", "kind": "agent.synth_dag", "inputs": {"objective": "add caching"}},
            {"id": "n2", "kind": "test.capture_synth_depth_after_failed_subgraph"},
        ],
        "edges": [{"from_node": "n1", "to_node": "n2"}],
        "entry_node": "n1",
    }

    result = await run_durable_dag(dag, store=mem_store, node_resolver=_local_resolver)
    assert result.status == RunStatus.COMPLETED
    n1_output = result.node_runs[0].result
    assert n1_output is not None
    assert n1_output["success"] is False  # the sub-graph itself failed
    assert n1_output["dispatched"] is True  # but it WAS actually dispatched
    assert captured_depths == [1]  # depth still burns a level for n2

"""Graph re-entry carries the node's own current pause into its context (#1897).

The durable executor's ``_build_ctx`` used to reconstruct ``resumed_pause``
only from ``hitl_answers[node_id]['_pause']`` — the server-stamped copy of a
pause that an answer already settled. A node that pauses *again* after its
answer (an elapsed poll re-parking beside a stale answered approval) therefore
read the old answered pause instead of its own current one, and every pause
re-entry read through a shallow dict copy of frozen ``GraphExecutionState``
containers rather than detached JSON.

These tests drive the real durable Graph/Attempt path — ``run_durable_graph``,
``submit_hitl_answer``, ``resume_durable_graph`` — with a scripted probe node
and deterministic timestamps, plus one focused ``_build_ctx`` unit test that
pins the frozen ``MappingProxyType``/``tuple`` representation and the
independence of the thawed copy. No provider, polling loop, or wall clock
takes part: every deadline, settlement moment, and wrapper ``resume_at`` is a
fixed constant.
"""

from __future__ import annotations

import contextlib
import copy
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph.durable_runs import (
    InMemoryDurableRunStore,
    resume_durable_graph,
    run_durable_graph,
)
from maistro.graph.durable_runs.executor import _build_ctx
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes import (
    BaseNode,
    NodeContext,
    get_node,
    pause_until,
    register_node,
)
from maistro.graph.nodes.base import (
    PAUSE_AWAITING_HUMAN_ANSWER,
    PAUSE_WAITING_ON_JIRA_SUBTASKS,
    RESUMED_PAUSE_KEY,
)
from maistro.runs.model import RunStatus
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

from .._canonical_helpers import durable_record, graph_from_dag, hitl_authorization

#: Wrapper ``resume_at`` an answer-gated pause admits. Far future so the
#: deterministic answer (``at=ANSWER_AT``) is never refused as expired, and
#: constant so the carried ISO string is asserted byte for byte.
DEADLINE = datetime(2126, 1, 1, 12, 0, tzinfo=UTC)
#: Wrapper ``resume_at`` for elapsed timer pauses. The re-entry gate
#: (``_requires_continuation_redispatch``) re-dispatches an elapsed pause only
#: when its persisted timestamp has passed, so these are fixed instants in the
#: past — deterministic forever, like the wall clock only more so.
TIMER_AT = datetime(2020, 6, 1, 12, 0, tzinfo=UTC)
TIMER_LATER = datetime(2020, 6, 2, 12, 0, tzinfo=UTC)
LEFT_AT = datetime(2020, 3, 1, 8, 0, tzinfo=UTC)
RIGHT_AT = datetime(2020, 3, 2, 8, 0, tzinfo=UTC)
ANSWER_AT = datetime(2026, 1, 2, 8, 30, tzinfo=UTC)

#: A conflicting value a node wrote *inside* its own pause metadata.
INNER_RESUME_AT = "1999-01-01T00:00:00+00:00"

# --- Scripted probe nodes ---------------------------------------------------
#
# Per-run scripts key the behavior of each reach (1-based). Steps may pause
# (``pause_reason`` + optional ``resume_at``/``pause_metadata``) or finish
# (optionally mutating the carried pause to prove detachment). Every reach
# records what ``resumed_pause`` carried, keyed ``(run_id, node_id)`` so
# concurrent frontier members cannot observe each other and parametrized
# failures cannot leak into the next case.

_SCRIPTS: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
_CARRIED: dict[tuple[str, str], dict[int, dict[str, Any] | None]] = {}
_CARRIED_TYPES: dict[tuple[str, str], dict[int, dict[str, str]]] = {}
_BARE: dict[tuple[str, str], dict[str, Any]] = {}
_MUTATED: set[tuple[str, str]] = set()


def _record_reach(ctx: NodeContext) -> int:
    """Record one reach's carried pause; return the 1-based reach ordinal."""
    key = (ctx.run_id, ctx.node_id)
    reaches = _CARRIED.setdefault(key, {})
    reach = len(reaches) + 1
    carried = ctx.metadata.get(RESUMED_PAUSE_KEY)
    reaches[reach] = copy.deepcopy(carried) if isinstance(carried, dict) else None
    if reach == 1:
        _BARE[key] = {
            "keys": sorted(ctx.metadata),
            "hitl_answers": copy.deepcopy(dict(ctx.metadata.get("hitl_answers") or {})),
            "synth_depth": ctx.metadata.get("synth_depth"),
        }
    return reach


def _note_types(ctx: NodeContext, reach: int) -> None:
    """Pin the container types the node actually received."""
    carried = ctx.metadata.get(RESUMED_PAUSE_KEY)
    if not isinstance(carried, dict):
        return
    types: dict[str, str] = {"carried": type(carried).__name__}
    if "nested" in carried:
        types["nested"] = type(carried["nested"]).__name__
    if "items" in carried:
        types["items"] = type(carried["items"]).__name__
    _CARRIED_TYPES.setdefault((ctx.run_id, ctx.node_id), {})[reach] = types


def _maybe_mutate(ctx: NodeContext, step: dict[str, Any]) -> None:
    """Mutate nested mapping/list values of the carried pause in place."""
    if not step.get("mutate_carried"):
        return
    carried = ctx.metadata.get(RESUMED_PAUSE_KEY)
    assert isinstance(carried, dict), "the executor must hand over mutable JSON containers"
    nested = carried.get("nested")
    assert isinstance(nested, dict), "nested pause metadata must be an ordinary dict"
    nested["mutated_by"] = "node"
    items = carried.get("items")
    assert isinstance(items, list), "nested pause lists must be ordinary lists"
    items.append("appended-by-node")
    _MUTATED.add((ctx.run_id, ctx.node_id))


class _ScriptedProbe(BaseNode):
    """Single-node probe acting out a per-run reach script."""

    kind: ClassVar[str] = "test.resumed_pause_probe"
    kind_category: ClassVar = "sync.transform"

    class In(BaseModel):
        text: str = ""

    class Out(BaseModel):
        text: str = "probed"

    input_schema: ClassVar[type[BaseModel]] = In
    output_schema: ClassVar[type[BaseModel]] = Out

    async def _execute(self, inputs: In, ctx: NodeContext) -> Out:
        key = (ctx.run_id, ctx.node_id)
        reach = _record_reach(ctx)
        _note_types(ctx, reach)
        # A step must exist for every scripted run; a reach past the script's
        # last entry simply finishes. A run with no script at all fails loudly
        # (the malformed-evidence cases rely on that guard).
        step = _SCRIPTS[key].get(reach, {})
        _maybe_mutate(ctx, step)
        if "pause_reason" in step:
            pause_until(
                str(step["pause_reason"]),
                resume_at=step.get("resume_at"),
                metadata=dict(step.get("pause_metadata") or {}),
            )
        return self.Out()


class _ForkPauser(BaseNode):
    """Frontier member that pauses on first reach with its own payload."""

    kind: ClassVar[str] = "test.resumed_pause_fork"
    kind_category: ClassVar = "wait"
    owner: ClassVar[str] = "fork"
    wrapper_at: ClassVar[datetime] = LEFT_AT
    pause_metadata: ClassVar[dict[str, Any]] = {"owner": "fork"}

    class In(BaseModel):
        text: str = ""

    class Out(BaseModel):
        text: str = "forked"

    input_schema: ClassVar[type[BaseModel]] = In
    output_schema: ClassVar[type[BaseModel]] = Out

    async def _execute(self, inputs: In, ctx: NodeContext) -> Out:
        reach = _record_reach(ctx)
        _note_types(ctx, reach)
        if reach == 1:
            pause_until(
                PAUSE_WAITING_ON_JIRA_SUBTASKS,
                resume_at=self.wrapper_at,
                metadata=dict(self.pause_metadata),
            )
        return self.Out()


class _LeftPauser(_ForkPauser):
    kind: ClassVar[str] = "test.resumed_pause_left"
    owner: ClassVar[str] = "left"
    wrapper_at: ClassVar[datetime] = LEFT_AT
    pause_metadata: ClassVar[dict[str, Any]] = {"owner": "left"}


class _RightPauser(_ForkPauser):
    kind: ClassVar[str] = "test.resumed_pause_right"
    owner: ClassVar[str] = "right"
    wrapper_at: ClassVar[datetime] = RIGHT_AT
    pause_metadata: ClassVar[dict[str, Any]] = {"owner": "right"}


for _cls in (_ScriptedProbe, _LeftPauser, _RightPauser):
    # Tests rerun in one process; the collision guard fires on the second run.
    with contextlib.suppress(ValueError):
        register_node(_cls)


def _resolver_for(graph: Any) -> Any:
    kinds = {node.node_id: node.node_type for node in graph.nodes}

    def resolve(node_id: str, _graph: Any) -> BaseNode:
        return get_node(kinds[node_id])()

    return resolve


def _probe_resolver(node_id: str, _graph: Any) -> BaseNode:
    """Resolve any single-probe record's node to the scripted probe."""
    assert node_id == "probe"
    return get_node(_ScriptedProbe.kind)()


def _probe_graph(graph_id: str) -> Any:
    return graph_from_dag(
        {
            "id": graph_id,
            "nodes": [{"id": "probe", "kind": _ScriptedProbe.kind}],
            "edges": [],
            "entry_node": "probe",
        }
    )


def _script(key: tuple[str, str], steps: dict[int, dict[str, Any]]) -> None:
    _SCRIPTS[key] = steps


# --- Positive carry on the real resume path --------------------------------


async def test_elapsed_pause_metadata_and_wrapper_resume_at_reach_the_node_unchanged() -> None:
    """A plain elapsed pause's arbitrary metadata arrives verbatim on re-entry."""
    key = ("rp-carry", "probe")
    _script(
        key,
        {
            1: {
                "pause_reason": PAUSE_WAITING_ON_JIRA_SUBTASKS,
                "resume_at": TIMER_AT,
                "pause_metadata": {
                    "first_seen": INNER_RESUME_AT,
                    "nested": {"k": "v"},
                    "items": [1, 2],
                },
            },
        },
    )
    store = InMemoryDurableRunStore()
    graph = _probe_graph("rp-carry")

    paused = await run_durable_graph(
        graph,
        store=store,
        node_resolver=_resolver_for(graph),
        run_id="rp-carry",
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    assert paused.run.status is RunStatus.WAITING
    entry = paused.graph_state.metadata["pauses"]["probe"]
    assert entry["resume_at"] == TIMER_AT.isoformat()

    resumed = await resume_durable_graph(
        "rp-carry", store=store, node_resolver=_resolver_for(graph)
    )
    assert resumed.run.status is RunStatus.COMPLETED

    carried = _CARRIED[key][2]
    assert carried == {
        "paused_reason": PAUSE_WAITING_ON_JIRA_SUBTASKS,
        "first_seen": INNER_RESUME_AT,
        "nested": {"k": "v"},
        "items": [1, 2],
        "resume_at": TIMER_AT.isoformat(),
    }
    # The public thaw path produced ordinary JSON containers, not the frozen
    # MappingProxyType/tuple shapes the state itself holds.
    assert _CARRIED_TYPES[key][2] == {"carried": "dict", "nested": "dict", "items": "list"}


async def test_wrapper_resume_at_wins_a_conflicting_inner_value() -> None:
    """The wrapper resume_at is stamped last, over any same-name inner value."""
    key = ("rp-wrapper", "probe")
    _script(
        key,
        {
            1: {
                "pause_reason": PAUSE_WAITING_ON_JIRA_SUBTASKS,
                "resume_at": TIMER_AT,
                "pause_metadata": {"resume_at": INNER_RESUME_AT, "note": "inner"},
            },
        },
    )
    store = InMemoryDurableRunStore()
    graph = _probe_graph("rp-wrapper")

    paused = await run_durable_graph(
        graph,
        store=store,
        node_resolver=_resolver_for(graph),
        run_id="rp-wrapper",
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    assert paused.run.status is RunStatus.WAITING
    # Premise: the persisted entry really does carry the conflict.
    assert paused.graph_state.metadata["pauses"]["probe"]["metadata"]["resume_at"] == (
        INNER_RESUME_AT
    )

    resumed = await resume_durable_graph(
        "rp-wrapper", store=store, node_resolver=_resolver_for(graph)
    )
    assert resumed.run.status is RunStatus.COMPLETED

    carried = _CARRIED[key][2]
    assert carried["resume_at"] == TIMER_AT.isoformat()
    assert carried["note"] == "inner"


async def test_current_pause_beats_the_older_answered_pause() -> None:
    """A newer elapsed pause outranks the answered pause the run already settled.

    Deleting the current-pause-first branch in the executor makes this fail:
    the node would read the ordinal-0 answered ``_pause`` instead of its own
    ordinal-1 pause.
    """
    key = ("rp-stale", "probe")
    _script(
        key,
        {
            1: {
                "pause_reason": PAUSE_AWAITING_HUMAN_ANSWER,
                "resume_at": DEADLINE,
                "pause_metadata": {"ordinal": 0, "generation": "answered"},
            },
            2: {
                "pause_reason": PAUSE_WAITING_ON_JIRA_SUBTASKS,
                "resume_at": TIMER_LATER,
                "pause_metadata": {"ordinal": 1, "generation": "current"},
            },
        },
    )
    store = InMemoryDurableRunStore()
    graph = _probe_graph("rp-stale")

    paused = await run_durable_graph(
        graph,
        store=store,
        node_resolver=_resolver_for(graph),
        run_id="rp-stale",
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    assert paused.run.status is RunStatus.PAUSED

    answered = await store.submit_hitl_answer(
        "rp-stale",
        "probe",
        {"answer": "first"},
        authorization=hitl_authorization(),
        at=ANSWER_AT,
    )
    assert answered.run.status is RunStatus.QUEUED
    assert answered.hitl_answers["probe"]["_pause"]["metadata"]["ordinal"] == 0

    # Reach 2: the node re-enters on its answer and pauses again — this time an
    # elapsed timer pause whose entry is the run's *current* pause.
    reparked = await resume_durable_graph(
        "rp-stale", store=store, node_resolver=_resolver_for(graph)
    )
    assert reparked.run.status is RunStatus.WAITING
    assert reparked.graph_state.metadata["pauses"]["probe"]["metadata"]["ordinal"] == 1

    # Reach 3: the current ordinal-1 pause must win the stale ordinal-0 answer.
    completed = await resume_durable_graph(
        "rp-stale", store=store, node_resolver=_resolver_for(graph)
    )
    assert completed.run.status is RunStatus.COMPLETED

    carried = _CARRIED[key][3]
    assert carried["ordinal"] == 1
    assert carried["generation"] == "current"
    assert carried["resume_at"] == TIMER_LATER.isoformat()
    # The answered visit's payload did not displace the current pause, and the
    # answer itself survives untouched beside it.
    assert completed.hitl_answers["probe"]["answer"] == "first"
    assert completed.hitl_answers["probe"]["_pause"]["metadata"]["ordinal"] == 0


async def test_absent_current_pause_keeps_the_answered_pause_fallback() -> None:
    """With no current pause entry, the answered ``_pause`` still supplies it."""
    key = ("rp-fallback", "probe")
    _script(
        key,
        {
            1: {
                "pause_reason": PAUSE_AWAITING_HUMAN_ANSWER,
                "resume_at": DEADLINE,
                "pause_metadata": {"question": "why"},
            },
        },
    )
    store = InMemoryDurableRunStore()
    graph = _probe_graph("rp-fallback")

    paused = await run_durable_graph(
        graph,
        store=store,
        node_resolver=_resolver_for(graph),
        run_id="rp-fallback",
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    assert paused.run.status is RunStatus.PAUSED

    answered = await store.submit_hitl_answer(
        "rp-fallback",
        "probe",
        {"answer": "yes"},
        authorization=hitl_authorization(),
        at=ANSWER_AT,
    )
    # The answer consumed the run's only pause projection, so this re-entry is
    # precisely the no-current-pause shape the answered fallback must serve.
    assert "pauses" not in answered.graph_state.metadata

    resumed = await resume_durable_graph(
        "rp-fallback", store=store, node_resolver=_resolver_for(graph)
    )
    assert resumed.run.status is RunStatus.COMPLETED

    assert _CARRIED[key][2] == {
        "paused_reason": PAUSE_AWAITING_HUMAN_ANSWER,
        "question": "why",
        "resume_at": DEADLINE.isoformat(),
    }


async def test_a_sibling_pause_never_enters_this_nodes_context() -> None:
    """Each frontier member carries its own pause — never the singleton's."""
    run_id = "rp-sibling"
    left_key = (run_id, "left")
    right_key = (run_id, "right")
    graph = graph_from_dag(
        {
            "id": run_id,
            "nodes": [
                {"id": "entry", "kind": "test.resumed_pause_probe"},
                {"id": "right", "kind": "test.resumed_pause_right"},
                {"id": "left", "kind": "test.resumed_pause_left"},
            ],
            "edges": [
                {"id": "e1", "from_node": "entry", "to_node": "right", "parallel": True},
                {"id": "e2", "from_node": "entry", "to_node": "left", "parallel": True},
            ],
            "entry_node": "entry",
        }
    )
    _script((run_id, "entry"), {1: {}})
    store = InMemoryDurableRunStore()

    paused = await run_durable_graph(
        graph,
        store=store,
        node_resolver=_resolver_for(graph),
        run_id=run_id,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    assert paused.run.status is RunStatus.WAITING
    # Premise: the singleton "pause" names right (the frontier's first
    # checkpointed member) — exactly the entry a per-node lookup must skip.
    assert paused.graph_state.metadata["pause"]["metadata"]["owner"] == "right"

    resumed = await resume_durable_graph(run_id, store=store, node_resolver=_resolver_for(graph))
    assert resumed.run.status is RunStatus.COMPLETED

    left_carried = _CARRIED[left_key][2]
    assert left_carried == {
        "paused_reason": PAUSE_WAITING_ON_JIRA_SUBTASKS,
        "owner": "left",
        "resume_at": LEFT_AT.isoformat(),
    }
    right_carried = _CARRIED[right_key][2]
    assert right_carried == {
        "paused_reason": PAUSE_WAITING_ON_JIRA_SUBTASKS,
        "owner": "right",
        "resume_at": RIGHT_AT.isoformat(),
    }


async def test_first_reach_without_pauses_keeps_the_previous_context_shape() -> None:
    """No pause anywhere: no resumed_pause key, unrelated fields intact."""
    key = ("rp-bare", "probe")
    _script(key, {1: {}})
    store = InMemoryDurableRunStore()
    graph = _probe_graph("rp-bare")

    completed = await run_durable_graph(
        graph,
        store=store,
        node_resolver=_resolver_for(graph),
        run_id="rp-bare",
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    assert completed.run.status is RunStatus.COMPLETED

    bare = _BARE[key]
    assert RESUMED_PAUSE_KEY not in bare["keys"]
    assert bare["hitl_answers"] == {}
    assert bare["synth_depth"] == 0


# --- Corrupt evidence fails visibly -----------------------------------------


def _waiting_record(
    run_id: str,
    *,
    pauses: object,
    hitl_answers: dict[str, Any],
) -> Any:
    """A WAITING single-probe record whose pauses projection is authored by hand.

    No NodeRun is authored: the walk creates the frontier's own fresh NodeRun
    before ``_build_ctx`` reads the corrupt pause, which is exactly the order
    the failure visibility is pinned against.
    """
    return durable_record(
        {
            "id": run_id,
            "nodes": [{"id": "probe", "kind": _ScriptedProbe.kind}],
            "edges": [],
            "entry_node": "probe",
        },
        run_id=run_id,
        status=RunStatus.WAITING,
        active_node_id="probe",
        metadata={
            "initial_inputs": {},
            "hitl_answers": hitl_answers,
            "pauses": pauses,
        },
    )


def _stale_answer() -> dict[str, Any]:
    """A plausible answered pause the executor must never fall back to."""
    return {
        "answer": "stale",
        "_pause": {
            "kind": "hitl",
            "metadata": {"ordinal": 0, "generation": "answered"},
            "resume_at": DEADLINE.isoformat(),
        },
    }


@pytest.mark.parametrize(
    ("run_id", "pauses", "expected_fragment"),
    [
        pytest.param(
            "rp-bad-entry",
            {"probe": None},
            "corrupt persisted",
            id="entry-none-is-present-corrupt",
        ),
        pytest.param(
            "rp-bad-metadata",
            {"probe": {"kind": "wait", "metadata": "not-a-mapping", "resume_at": None}},
            "persisted pause metadata must be a JSON object",
            id="metadata-not-a-mapping",
        ),
        pytest.param(
            "rp-bad-container",
            None,
            "graph state pauses must be a JSON object",
            id="pauses-container-none",
        ),
    ],
)
async def test_malformed_current_pause_fails_visibly_before_node_execution(
    run_id: str,
    pauses: object,
    expected_fragment: str,
) -> None:
    """Corrupt pause evidence terminalizes the resume; the node never runs."""
    key = (run_id, "probe")
    store = InMemoryDurableRunStore()
    await store.create(
        _waiting_record(run_id, pauses=pauses, hitl_answers={"probe": _stale_answer()})
    )

    failed = await resume_durable_graph(run_id, store=store, node_resolver=_probe_resolver)

    assert failed.run.status is RunStatus.FAILED
    assert "PhysicalExecutionError" in (failed.run.error or "")
    assert expected_fragment in (failed.run.error or "")
    # Visible before node execution: no reach was ever recorded, and the stale
    # answered pause was not silently borrowed as metadata.
    assert key not in _CARRIED


# --- Detached copies --------------------------------------------------------


async def test_thawed_carry_is_independent_of_the_frozen_record() -> None:
    """Mutating the carried pause cannot reach GraphExecutionState's frozen shapes."""
    run_id = "rp-thaw"
    record = _waiting_record(
        run_id,
        pauses={
            "probe": {
                "kind": "wait",
                "metadata": {"nested": {"k": "v"}, "items": [1, 2]},
                "resume_at": DEADLINE.isoformat(),
            }
        },
        hitl_answers={},
    )
    # Premise: the state really is the frozen MappingProxyType/tuple
    # representation the public thaw helper exists to escape.
    pauses = record.graph_state.metadata["pauses"]
    assert isinstance(pauses, MappingProxyType)
    entry = pauses["probe"]
    assert isinstance(entry, MappingProxyType)
    assert isinstance(entry["metadata"]["items"], tuple)

    before = record.model_dump(mode="json")
    ctx = _build_ctx(record, "probe")
    carried = ctx.metadata[RESUMED_PAUSE_KEY]
    assert carried == {
        "nested": {"k": "v"},
        "items": [1, 2],
        "resume_at": DEADLINE.isoformat(),
    }

    carried["nested"]["k"] = "mutated"
    carried["items"].append(99)
    carried["resume_at"] = "mutated"
    assert record.model_dump(mode="json") == before


async def test_node_mutation_of_the_carried_answer_leaves_the_record_unchanged() -> None:
    """A node may mutate its carried pause; the persisted answer stays as stamped."""
    key = ("rp-mutate", "probe")
    _script(
        key,
        {
            1: {
                "pause_reason": PAUSE_AWAITING_HUMAN_ANSWER,
                "resume_at": DEADLINE,
                "pause_metadata": {"question": "why", "nested": {"k": "v"}, "items": [1]},
            },
            2: {"mutate_carried": True},
        },
    )
    store = InMemoryDurableRunStore()
    graph = _probe_graph("rp-mutate")

    paused = await run_durable_graph(
        graph,
        store=store,
        node_resolver=_resolver_for(graph),
        run_id="rp-mutate",
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    assert paused.run.status is RunStatus.PAUSED

    await store.submit_hitl_answer(
        "rp-mutate",
        "probe",
        {"answer": "yes"},
        authorization=hitl_authorization(),
        at=ANSWER_AT,
    )

    resumed = await resume_durable_graph(
        "rp-mutate", store=store, node_resolver=_resolver_for(graph)
    )
    assert resumed.run.status is RunStatus.COMPLETED
    assert key in _MUTATED, "the probe must have exercised the mutation path"

    stamped = resumed.hitl_answers["probe"]["_pause"]
    # The persisted answer is the state's frozen representation (lists freeze
    # to tuples) — the mutation provably never reached it.
    assert stamped["metadata"] == {
        "paused_reason": PAUSE_AWAITING_HUMAN_ANSWER,
        "question": "why",
        "nested": {"k": "v"},
        "items": (1,),
    }
    assert stamped["resume_at"] == DEADLINE.isoformat()


async def test_state_freeze_validators_keeps_the_authoring_record_whole() -> None:
    """A pause entry authored through GraphExecutionState freezes losslessly.

    Guards the fixture premise the other unit test relies on: the metadata the
    executor must copy is stored under the model's frozen representation, not
    as the plain dicts the node wrote.
    """
    state = GraphExecutionState.model_validate(
        {
            "run_id": "rp-freeze",
            "metadata": {
                "pauses": {
                    "probe": {
                        "kind": "wait",
                        "metadata": {"nested": {"k": "v"}, "items": [1, 2]},
                        "resume_at": DEADLINE.isoformat(),
                    }
                }
            },
        }
    )
    pauses = state.metadata["pauses"]
    assert isinstance(pauses, MappingProxyType)
    entry = pauses["probe"]
    assert isinstance(entry, MappingProxyType)
    assert entry["resume_at"] == DEADLINE.isoformat()
    with pytest.raises(TypeError):
        entry["metadata"]["nested"]["k"] = "mutated"  # type: ignore[index]

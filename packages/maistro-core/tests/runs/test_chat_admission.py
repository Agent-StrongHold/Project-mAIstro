"""A chat turn is a Run, and it does not accumulate (#131, ADR-082326-c126).

#41's task half shipped without the chat half because chat raised two questions
tasks had already answered: what a turn's Run *is*, and how long it lives. These
tests hold both answers — one Run per turn correlated to its session, and a
bound that is enforced by the admitter rather than hoped for from the store.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.admission import ADMISSION_SOURCE
from maistro.runs.chat_admission import (
    AGENT_SELECTION_KEY,
    CHAT_SOURCE,
    DEFAULT_TURN_NAME,
    DEFERRED_AGENT_SELECTION,
    INTERNAL_FAILURE,
    REQUEST_ID_KEY,
    SESSION_ID_KEY,
    TIMEOUT_FAILURE,
    UPSTREAM_FAILURE,
    ChatRunAdmitter,
    failure_category,
    last_user_message,
)
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore, RunIntegrityError
from maistro.runs.task_kinds import DELEGATE_NODE_KIND


@pytest.fixture
async def spine():
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    runs = InMemoryRunStore(project_store=projects)
    return projects, runs, root


def _turn(text: str = "What broke the parser?") -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": text},
        {"role": "assistant", "content": "earlier answer"},
        {"role": "user", "content": text},
    ]


# --- one Run per turn -----------------------------------------------------


async def test_a_turn_is_admitted_as_a_run_in_the_workspaces_project(spine) -> None:
    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id)

    run = await admitter.admit(_turn())

    stored = await runs.get_run(run.run_id)
    assert stored is not None
    assert stored.workspace_id == "w1"
    assert stored.project_id == root.project_id
    assert stored.status is RunStatus.CREATED


async def test_the_run_names_chat_as_what_admitted_it(spine) -> None:
    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id)

    run = await admitter.admit(_turn(), session_id="sess-1", request_id="req-1")

    assert run.provenance[ADMISSION_SOURCE] == CHAT_SOURCE
    assert run.provenance[SESSION_ID_KEY] == "sess-1"
    assert run.provenance[REQUEST_ID_KEY] == "req-1"


async def test_two_turns_in_one_session_are_two_runs(spine) -> None:
    """The decision, held directly: a Run is a turn, not a conversation."""
    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id)

    first = await admitter.admit(_turn("one"), session_id="sess-1")
    second = await admitter.admit(_turn("two"), session_id="sess-1")

    assert first.run_id != second.run_id
    assert first.provenance[SESSION_ID_KEY] == second.provenance[SESSION_ID_KEY] == "sess-1"


async def test_the_runs_graph_is_the_one_node_a_turn_can_execute(spine) -> None:
    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id)

    run = await admitter.admit(_turn("What broke the parser?"))

    nodes = run.graph.materialize().nodes
    assert len(nodes) == 1
    assert nodes[0].node_type == DELEGATE_NODE_KIND
    assert nodes[0].parameters["task"] == "What broke the parser?"


async def test_a_turn_with_no_user_message_still_admits(spine) -> None:
    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id)

    run = await admitter.admit([{"role": "system", "content": "hello"}])

    assert run.graph.materialize().nodes[0].name == DEFAULT_TURN_NAME


def test_the_last_user_message_is_the_last_one() -> None:
    assert last_user_message(_turn("second")) == "second"
    assert last_user_message([{"role": "assistant", "content": "x"}]) == ""
    assert last_user_message([{"role": "user", "content": {"not": "text"}}]) == ""


# --- the bound ------------------------------------------------------------


async def test_terminal_chat_runs_are_swept_behind_the_window(spine) -> None:
    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id, max_retained=3)
    admitted = []

    for index in range(10):
        run = await admitter.admit(_turn(f"turn {index}"))
        await runs.transition_run(run.run_id, RunStatus.QUEUED)
        await runs.transition_run(run.run_id, RunStatus.RUNNING)
        await runs.transition_run(run.run_id, RunStatus.COMPLETED)
        admitted.append(run.run_id)

    assert admitter.retained <= 3
    surviving = [rid for rid in admitted if await runs.get_run(rid) is not None]
    # The bound holds, and it is the *oldest* that went.
    assert len(surviving) <= 3
    assert surviving == admitted[-len(surviving) :]


async def test_an_executing_turn_is_never_swept(spine) -> None:
    """A turn still inside its Attempt's lease keeps its identity.

    The lease, not the Run's status, is what says a turn is alive: the chat
    executor leases every Attempt it creates and renews it while the turn
    runs (#1170), so an unexpired lease under a non-terminal Run is work in
    flight, however many admissions arrive behind it.
    """
    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id, max_retained=2)

    live = await admitter.admit(_turn("still going"))
    await runs.transition_run(live.run_id, RunStatus.QUEUED)
    await runs.transition_run(live.run_id, RunStatus.RUNNING)
    node_run = await runs.create_node_run(
        live.run_id, node_id=live.graph.materialize().nodes[0].node_id
    )
    await runs.create_attempt(
        node_run.node_run_id, lease_holder="chat", lease_ttl=timedelta(seconds=30)
    )
    for index in range(8):
        done = await admitter.admit(_turn(f"turn {index}"))
        await runs.transition_run(done.run_id, RunStatus.QUEUED)
        await runs.transition_run(done.run_id, RunStatus.CANCELLED)

    assert await runs.get_run(live.run_id) is not None


async def test_stalled_turns_cannot_grow_the_store_past_the_window(spine) -> None:
    """The bound holds when turns stall — the shape a lost executor leaves.

    Three turns admitted and left RUNNING with nothing executing under them,
    over a window of two. A window that shields every non-terminal Run grows
    without limit exactly when the process is misbehaving, which is when it
    must not: the oldest stalled Run goes, the newest survive.
    """
    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id, max_retained=2)

    admitted = []
    for index in range(3):
        run = await admitter.admit(_turn(f"turn {index}"))
        await runs.transition_run(run.run_id, RunStatus.QUEUED)
        await runs.transition_run(run.run_id, RunStatus.RUNNING)
        admitted.append(run.run_id)

    assert admitter.retained <= 2
    stored = [run_id for run_id in admitted if await runs.get_run(run_id) is not None]
    assert stored == admitted[1:]


async def test_an_attempt_whose_lease_lapsed_no_longer_shields_its_run(spine) -> None:
    """A lapsed lease is a stall, by the rule recovery itself reclaims on."""
    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id, max_retained=1)

    stalled = await admitter.admit(_turn("holder died"))
    await runs.transition_run(stalled.run_id, RunStatus.QUEUED)
    await runs.transition_run(stalled.run_id, RunStatus.RUNNING)
    node_run = await runs.create_node_run(
        stalled.run_id, node_id=stalled.graph.materialize().nodes[0].node_id
    )
    await runs.create_attempt(
        node_run.node_run_id, lease_holder="chat", lease_ttl=timedelta(microseconds=1)
    )

    later = await admitter.admit(_turn("next turn"))

    assert await runs.get_run(stalled.run_id) is None
    assert await runs.get_run(later.run_id) is not None


async def test_a_finished_attempt_under_an_open_run_does_not_shield_it(spine) -> None:
    """A finished Attempt under a Run nobody closed is a stall, not a turn."""
    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id, max_retained=1)

    stalled = await admitter.admit(_turn("executor died at the close"))
    await runs.transition_run(stalled.run_id, RunStatus.QUEUED)
    await runs.transition_run(stalled.run_id, RunStatus.RUNNING)
    node_run = await runs.create_node_run(
        stalled.run_id, node_id=stalled.graph.materialize().nodes[0].node_id
    )
    attempt = await runs.create_attempt(node_run.node_run_id)
    await runs.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    await runs.transition_attempt(attempt.attempt_id, AttemptStatus.COMPLETED)

    later = await admitter.admit(_turn("next turn"))

    assert await runs.get_run(stalled.run_id) is None
    assert await runs.get_run(later.run_id) is not None


async def test_the_sweep_does_not_touch_a_task_run(spine) -> None:
    """Chat volume must not evict work that entered another way."""
    from maistro.runs.admission import admit_direct_work

    _projects, runs, root = spine
    task_run = await admit_direct_work(
        runs,
        workspace_id="w1",
        project_id=root.project_id,
        node_type=DELEGATE_NODE_KIND,
        name="a task",
        source="task_queue",
        parameters={"from_agent": "", "task": "a task", "to_agent": "coder"},
    )
    await runs.transition_run(task_run.run_id, RunStatus.QUEUED)
    await runs.transition_run(task_run.run_id, RunStatus.CANCELLED)
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id, max_retained=1)

    for index in range(20):
        run = await admitter.admit(_turn(f"turn {index}"))
        await runs.transition_run(run.run_id, RunStatus.QUEUED)
        await runs.transition_run(run.run_id, RunStatus.CANCELLED)

    assert await runs.get_run(task_run.run_id) is not None


async def test_a_run_already_gone_leaves_the_window(spine) -> None:
    """The store's own bound may have taken it first; that is not an error."""
    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id, max_retained=1)
    first = await admitter.admit(_turn("one"))
    await runs.transition_run(first.run_id, RunStatus.QUEUED)
    await runs.transition_run(first.run_id, RunStatus.CANCELLED)
    await runs.delete_run(first.run_id)

    second = await admitter.admit(_turn("two"))

    assert admitter.retained == 1
    assert await runs.get_run(second.run_id) is not None


async def test_the_window_must_be_at_least_one(spine) -> None:
    _projects, runs, root = spine

    with pytest.raises(ValueError):
        ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id, max_retained=0)


async def test_the_admitter_needs_a_project_or_a_way_to_find_one(spine) -> None:
    _projects, runs, _root = spine

    with pytest.raises(ValueError):
        ChatRunAdmitter(runs, workspace_id="w1")
    with pytest.raises(ValueError):
        ChatRunAdmitter(runs, workspace_id="   ", project_id="p1")


async def test_the_root_project_resolves_lazily(spine) -> None:
    projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_store=projects)

    run = await admitter.admit(_turn())

    assert run.project_id == root.project_id


# --- deleting a Run at all ------------------------------------------------


async def test_deleting_a_live_run_is_refused(spine) -> None:
    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id)
    run = await admitter.admit(_turn())
    await runs.transition_run(run.run_id, RunStatus.QUEUED)

    with pytest.raises(RunIntegrityError):
        await runs.delete_run(run.run_id)


async def test_deleting_an_unknown_run_says_so_rather_than_raising(spine) -> None:
    _projects, runs, _root = spine

    assert await runs.delete_run("no-such-run") is False


async def test_deleting_a_run_takes_its_node_runs_and_attempts(spine) -> None:
    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id)
    run = await admitter.admit(_turn())
    await runs.transition_run(run.run_id, RunStatus.QUEUED)
    await runs.transition_run(run.run_id, RunStatus.RUNNING)
    node_id = run.graph.materialize().nodes[0].node_id
    node_run = await runs.create_node_run(run.run_id, node_id=node_id)
    attempt = await runs.create_attempt(node_run.node_run_id)
    await runs.transition_run(run.run_id, RunStatus.COMPLETED)

    assert await runs.delete_run(run.run_id) is True

    assert await runs.get_run(run.run_id) is None
    assert await runs.get_node_run(node_run.node_run_id) is None
    assert await runs.get_attempt(attempt.attempt_id) is None


# --- review findings ------------------------------------------------------


async def test_chat_admission_does_not_evict_task_runs(spine) -> None:
    """The claim the whole retention policy rests on.

    The store's own bound runs inside `create_run`, before any admitter sees
    the new Run, and it used to be source-agnostic — so a burst of chat turns
    evicted the oldest *task* Runs to make room for itself, leaving task
    receipts holding a `run_id` that no longer resolved.
    """
    from maistro.runs.admission import admit_direct_work

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    runs = InMemoryRunStore(project_store=projects, max_runs=20, prune_target=10)
    task_runs = []
    for index in range(10):
        run = await admit_direct_work(
            runs,
            workspace_id="w1",
            project_id=root.project_id,
            node_type=DELEGATE_NODE_KIND,
            name=f"task {index}",
            source="task_queue",
            parameters={"from_agent": "", "task": "t", "to_agent": "coder"},
        )
        await runs.transition_run(run.run_id, RunStatus.QUEUED)
        await runs.transition_run(run.run_id, RunStatus.CANCELLED)
        task_runs.append(run.run_id)

    admitter = ChatRunAdmitter(
        runs, workspace_id="w1", project_id=root.project_id, max_retained=100
    )
    for index in range(40):
        run = await admitter.admit(_turn(f"turn {index}"))
        await runs.transition_run(run.run_id, RunStatus.QUEUED)
        await runs.transition_run(run.run_id, RunStatus.CANCELLED)

    survivors = [rid for rid in task_runs if await runs.get_run(rid) is not None]
    assert survivors == task_runs


async def test_the_store_still_evicts_when_only_task_runs_remain(spine) -> None:
    """Preferring chat Runs is an ordering, not an exemption."""
    from maistro.runs.admission import admit_direct_work

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    runs = InMemoryRunStore(project_store=projects, max_runs=5, prune_target=3)
    admitted = []
    for index in range(12):
        run = await admit_direct_work(
            runs,
            workspace_id="w1",
            project_id=root.project_id,
            node_type=DELEGATE_NODE_KIND,
            name=f"task {index}",
            source="task_queue",
            parameters={"from_agent": "", "task": "t", "to_agent": "coder"},
        )
        await runs.transition_run(run.run_id, RunStatus.QUEUED)
        await runs.transition_run(run.run_id, RunStatus.CANCELLED)
        admitted.append(run.run_id)

    surviving = [rid for rid in admitted if await runs.get_run(rid) is not None]
    assert len(surviving) <= 5


async def test_concurrent_admissions_sweep_without_colliding(spine) -> None:
    import asyncio

    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id, max_retained=2)
    for index in range(6):
        run = await admitter.admit(_turn(f"seed {index}"))
        await runs.transition_run(run.run_id, RunStatus.QUEUED)
        await runs.transition_run(run.run_id, RunStatus.CANCELLED)

    admitted = await asyncio.gather(*(admitter.admit(_turn(f"race {i}")) for i in range(8)))

    assert len({run.run_id for run in admitted}) == 8
    for run in admitted:
        await runs.transition_run(run.run_id, RunStatus.QUEUED)
        await runs.transition_run(run.run_id, RunStatus.CANCELLED)
    # A concurrent burst can finish after its last admission. The execution
    # seam calls this same hook; keep the direct admitter contract explicit too.
    await admitter.sweep()

    surviving = [run for run in admitted if await runs.get_run(run.run_id) is not None]
    assert len(surviving) <= 2


async def test_a_turn_with_no_intent_hint_names_no_agent(spine) -> None:
    """Admission must not claim an agent the Conduit has not chosen."""
    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id)

    run = await admitter.admit(_turn("what broke?"))

    node = run.graph.materialize().nodes[0]
    assert node.parameters["to_agent"] == ""
    assert run.provenance[AGENT_SELECTION_KEY] == DEFERRED_AGENT_SELECTION


async def test_a_known_intent_hint_does_name_its_agent(spine) -> None:
    """With a valid hint, `_apply_intent_hint` makes the two resolutions agree."""
    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id)

    run = await admitter.admit(
        _turn("write the parser"), intent_hint="code", known_task_types={"code"}
    )

    node = run.graph.materialize().nodes[0]
    assert node.parameters["to_agent"]
    assert AGENT_SELECTION_KEY not in run.provenance


async def test_an_unknown_intent_hint_names_no_agent_either(spine) -> None:
    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id)

    run = await admitter.admit(
        _turn("do a thing"), intent_hint="not-a-task-type", known_task_types={"code"}
    )

    assert run.graph.materialize().nodes[0].parameters["to_agent"] == ""
    assert run.provenance[AGENT_SELECTION_KEY] == DEFERRED_AGENT_SELECTION


async def test_deleting_a_run_with_a_child_is_refused(spine) -> None:
    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id)
    parent = await admitter.admit(_turn("parent"))
    await runs.transition_run(parent.run_id, RunStatus.QUEUED)
    await runs.transition_run(parent.run_id, RunStatus.RUNNING)
    child_graph = parent.graph.materialize().model_copy(
        update={"graph_id": "child-graph"}, deep=True
    )
    await runs.create_run(child_graph, parent_run_id=parent.run_id)
    await runs.transition_run(parent.run_id, RunStatus.COMPLETED)

    with pytest.raises(RunIntegrityError, match="child Run"):
        await runs.delete_run(parent.run_id)

    assert await runs.get_run(parent.run_id) is not None


async def test_retention_walks_past_a_terminal_parent_with_a_child(spine) -> None:
    """One undeletable parent must not strand younger eligible chat Runs."""
    _projects, runs, root = spine
    admitter = ChatRunAdmitter(runs, workspace_id="w1", project_id=root.project_id, max_retained=2)
    parent = await admitter.admit(_turn("parent"))
    await runs.transition_run(parent.run_id, RunStatus.QUEUED)
    await runs.transition_run(parent.run_id, RunStatus.RUNNING)
    child_graph = parent.graph.materialize().model_copy(
        update={"graph_id": "child-graph"}, deep=True
    )
    child = await runs.create_run(child_graph, parent_run_id=parent.run_id)
    await runs.transition_run(child.run_id, RunStatus.QUEUED)
    await runs.transition_run(child.run_id, RunStatus.RUNNING)
    await runs.transition_run(child.run_id, RunStatus.COMPLETED)
    await runs.transition_run(parent.run_id, RunStatus.COMPLETED)

    second = await admitter.admit(_turn("second"))
    await runs.transition_run(second.run_id, RunStatus.QUEUED)
    await runs.transition_run(second.run_id, RunStatus.RUNNING)
    await runs.transition_run(second.run_id, RunStatus.COMPLETED)
    third = await admitter.admit(_turn("third"))

    assert admitter.retained == 2
    assert await runs.get_run(parent.run_id) is not None
    assert await runs.get_run(second.run_id) is None
    assert await runs.get_run(third.run_id) is not None


def test_a_turns_outcome_records_its_answer() -> None:
    from maistro.runs.chat_admission import MAX_RECORDED_ANSWER_CHARS, chat_turn_outcome

    outcome = chat_turn_outcome(
        {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Request blocked: injection"},
                    "finish_reason": "stop",
                }
            ]
        }
    )

    assert outcome["answer"] == "Request blocked: injection"
    assert outcome["finish_reason"] == "stop"
    assert outcome["answer_truncated"] is False

    long = chat_turn_outcome(
        {"choices": [{"message": {"content": "x" * (MAX_RECORDED_ANSWER_CHARS + 5)}}]}
    )
    assert len(long["answer"]) == MAX_RECORDED_ANSWER_CHARS
    assert long["answer_truncated"] is True


def test_a_malformed_response_still_yields_an_outcome() -> None:
    from maistro.runs.chat_admission import chat_turn_outcome

    assert chat_turn_outcome({})["answer"] == ""
    assert chat_turn_outcome({"choices": []})["answer"] == ""
    assert chat_turn_outcome({"choices": [{"message": {"content": None}}]})["answer"] == ""


class TestFailureCategory:
    """What a failed chat turn records on its Run (#142).

    A category, never the exception text. `/runs/{run_id}` returns `Run.error`
    verbatim to anyone holding the run_id — which the streaming chat path puts
    in a response header — and a provider error's message carries the endpoint
    it called and can carry the key it sent. The detail belongs in the log,
    which a run_id does not open.
    """

    def test_a_timeout_is_a_timeout(self) -> None:
        assert failure_category(TimeoutError("waited 30s for https://provider.internal")) == (
            TIMEOUT_FAILURE
        )

    def test_a_provider_error_is_an_upstream_failure(self) -> None:
        from maistro.agents.types import LLMProviderError

        assert failure_category(LLMProviderError("https://provider.internal key=sk-secret")) == (
            UPSTREAM_FAILURE
        )

    def test_anything_else_is_internal(self) -> None:
        assert failure_category(ValueError("boom")) == INTERNAL_FAILURE

    def test_the_category_never_carries_the_message(self) -> None:
        """The property, stated directly rather than left to the three cases
        above to imply. A future category added without this in mind would be
        the leak coming back."""
        from maistro.agents.types import LLMProviderError

        secret = "https://provider.internal/v1 key=sk-secret"
        for exc in (TimeoutError(secret), LLMProviderError(secret), ValueError(secret)):
            assert "sk-secret" not in failure_category(exc)

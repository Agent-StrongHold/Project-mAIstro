"""A chat turn admits as a canonical Run (#131, ADR-082226-c126).

The claim under test is the one #41 makes for every entry point: the Run is the
execution identity, and the thing that admitted it is a receipt. For chat that
means three properties the task path already had — a resolvable run_id, a Graph
whose node names the agent that will run it, and provenance that ties the turn
back to its conversation — plus one it did not: a retention deadline.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.agents.intents import IntentRegistry
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.admission import (
    ADMISSION_SOURCE,
    REQUEST_ID_KEY,
    SESSION_ID_KEY,
    USER_ID_KEY,
)
from maistro.runs.chat import CHAT_TURN_SOURCE, TASK_TYPE_KEY, ChatRunAdmitter
from maistro.runs.model import RunStatus
from maistro.runs.retention import UNBOUNDED_RETENTION, RetentionPolicy
from maistro.runs.store import InMemoryRunStore
from maistro.runs.task_kinds import DELEGATE_NODE_KIND

WORKSPACE = "chat-workspace"


@pytest.fixture
async def admitter():
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    store = InMemoryRunStore(project_store=projects)
    return (
        ChatRunAdmitter(store, workspace_id=WORKSPACE, project_id=root.project_id),
        store,
    )


# ── the Run itself ────────────────────────────────────────────────


async def test_a_chat_turn_yields_a_resolvable_run(admitter) -> None:
    chat, store = admitter

    run = await chat.admit_chat_turn(prompt="what is the weather")

    assert await store.get_run(run.run_id) is not None


async def test_the_run_is_running_by_the_time_it_is_returned(admitter) -> None:
    """`route_request()` is synchronous — there is no queue and no receipt, so a
    Run still in CREATED would mean the spine disagreed with reality from the
    first instant."""
    chat, store = admitter

    run = await chat.admit_chat_turn(prompt="hello")

    assert run.status is RunStatus.RUNNING
    reloaded = await store.get_run(run.run_id)
    assert reloaded is not None
    assert reloaded.status is RunStatus.RUNNING


async def test_the_run_is_filed_in_the_bound_workspace(admitter) -> None:
    chat, _store = admitter

    run = await chat.admit_chat_turn(prompt="hello")

    assert run.workspace_id == WORKSPACE


async def test_the_graph_is_one_executable_node(admitter) -> None:
    """A Run whose node names a kind no executor knows would be a
    canonical-looking record of work that can never start."""
    chat, _store = admitter

    run = await chat.admit_chat_turn(prompt="write me a function", task_type="code")

    nodes = run.graph.materialize().nodes
    assert len(nodes) == 1
    assert nodes[0].node_type == DELEGATE_NODE_KIND
    assert nodes[0].parameters["task"] == "write me a function"


async def test_the_node_names_the_agent_the_caller_resolved(admitter) -> None:
    """The agent is passed in rather than re-resolved, because the conduit has
    already fallen back to an arbitrary agent by the time it admits — a Run
    naming a different one would disagree with what actually ran."""
    chat, _store = admitter

    run = await chat.admit_chat_turn(prompt="hi", task_type="chat", agent_name="scribe")

    assert run.graph.materialize().nodes[0].parameters["to_agent"] == "scribe"


async def test_without_an_agent_the_intent_table_decides(admitter) -> None:
    chat, _store = admitter
    expected = IntentRegistry().resolve("code")

    run = await chat.admit_chat_turn(prompt="hi", task_type="code")

    assert run.graph.materialize().nodes[0].parameters["to_agent"] == expected


async def test_a_custom_intent_registry_is_honoured() -> None:
    """The container's registry, not a fresh default: a POC-mode deployment
    routes task types the engineering table has never heard of."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    store = InMemoryRunStore(project_store=projects)
    registry = IntentRegistry({"chat": "bespoke-agent"})
    chat = ChatRunAdmitter(
        store, workspace_id=WORKSPACE, project_id=root.project_id, intents=registry
    )

    run = await chat.admit_chat_turn(prompt="hi", task_type="chat")

    assert run.graph.materialize().nodes[0].parameters["to_agent"] == "bespoke-agent"


# ── provenance: the conversation, not a parent row ────────────────


async def test_provenance_records_how_the_run_entered(admitter) -> None:
    chat, _store = admitter

    run = await chat.admit_chat_turn(prompt="hi")

    assert run.provenance[ADMISSION_SOURCE] == CHAT_TURN_SOURCE


async def test_a_conversations_runs_are_recoverable_by_session(admitter) -> None:
    """The correlation the ADR trades a parent row for: one Run per turn, and
    the conversation is a query over provenance."""
    chat, store = admitter

    first = await chat.admit_chat_turn(prompt="turn one", session_id="sess-7")
    second = await chat.admit_chat_turn(prompt="turn two", session_id="sess-7")
    other = await chat.admit_chat_turn(prompt="elsewhere", session_id="sess-8")

    assert first.run_id != second.run_id
    for run_id in (first.run_id, second.run_id):
        run = await store.get_run(run_id)
        assert run is not None
        assert run.provenance[SESSION_ID_KEY] == "sess-7"
    other_run = await store.get_run(other.run_id)
    assert other_run is not None
    assert other_run.provenance[SESSION_ID_KEY] == "sess-8"


async def test_the_request_and_principal_are_recorded(admitter) -> None:
    chat, _store = admitter

    run = await chat.admit_chat_turn(
        prompt="hi", session_id="s", request_id="req-1", user_id="alice", task_type="chat"
    )

    assert run.provenance[REQUEST_ID_KEY] == "req-1"
    assert run.provenance[USER_ID_KEY] == "alice"
    assert run.provenance[TASK_TYPE_KEY] == "chat"
    assert run.actor_principal_id == "alice"


async def test_absent_correlation_is_absent_not_empty(admitter) -> None:
    """An empty-string session_id in provenance would look like a conversation
    that exists and has no turns."""
    chat, _store = admitter

    run = await chat.admit_chat_turn(prompt="hi")

    assert SESSION_ID_KEY not in run.provenance
    assert REQUEST_ID_KEY not in run.provenance
    assert USER_ID_KEY not in run.provenance


# ── retention ─────────────────────────────────────────────────────


async def test_a_chat_run_carries_a_deadline(admitter) -> None:
    chat, _store = admitter
    before = datetime.now(UTC)

    run = await chat.admit_chat_turn(prompt="hi")

    assert run.retention_expires_at is not None
    assert run.retention_expires_at > before


async def test_an_unbounded_policy_leaves_the_run_immortal() -> None:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    store = InMemoryRunStore(project_store=projects)
    chat = ChatRunAdmitter(
        store,
        workspace_id=WORKSPACE,
        project_id=root.project_id,
        retention=UNBOUNDED_RETENTION,
    )

    run = await chat.admit_chat_turn(prompt="hi")

    assert run.retention_expires_at is None


async def test_admission_sweeps_and_the_bound_holds() -> None:
    """The acceptance criterion in the issue, end to end: chat turns admitted
    forever do not grow the store forever."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    store = InMemoryRunStore(project_store=projects)
    chat = ChatRunAdmitter(
        store,
        workspace_id=WORKSPACE,
        project_id=root.project_id,
        # Every turn expires the instant it closes, and every turn sweeps.
        retention=RetentionPolicy(ttl_seconds=1, sweep_interval_seconds=0),
    )

    live = []
    for index in range(25):
        run = await chat.admit_chat_turn(prompt=f"turn {index}")
        await chat.record_outcome(run.run_id, RunStatus.COMPLETED)
        live.append(run.run_id)
        # Sweep against a clock a minute ahead, so everything closed is expired.
        await chat.sweeper.sweep_now(now=datetime.now(UTC) + timedelta(minutes=1))

    resolvable = [run_id for run_id in live if await store.get_run(run_id) is not None]
    assert resolvable == []


async def test_a_live_turn_is_not_swept_out_from_under_itself() -> None:
    """The same bound, with the rule that makes it safe: the turn still running
    when the sweep fires keeps its Run."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    store = InMemoryRunStore(project_store=projects)
    chat = ChatRunAdmitter(
        store,
        workspace_id=WORKSPACE,
        project_id=root.project_id,
        retention=RetentionPolicy(ttl_seconds=1, sweep_interval_seconds=0),
    )

    run = await chat.admit_chat_turn(prompt="still going")
    await chat.sweeper.sweep_now(now=datetime.now(UTC) + timedelta(minutes=1))

    assert await store.get_run(run.run_id) is not None


# ── closing the turn ──────────────────────────────────────────────


@pytest.mark.parametrize("status", [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED])
async def test_record_outcome_closes_the_run(admitter, status: RunStatus) -> None:
    chat, store = admitter
    run = await chat.admit_chat_turn(prompt="hi")

    assert await chat.record_outcome(run.run_id, status, error="why") is True

    closed = await store.get_run(run.run_id)
    assert closed is not None
    assert closed.status is status
    assert closed.finished_at is not None


async def test_closing_a_run_that_does_not_resolve_is_refused(admitter) -> None:
    """A run_id nothing can find is an orphaned identity; reporting success
    there would make "no Run" indistinguishable from "already closed"."""
    chat, _store = admitter

    assert await chat.record_outcome("no-such-run", RunStatus.COMPLETED) is False


async def test_closing_an_already_closed_run_is_refused(admitter) -> None:
    chat, _store = admitter
    run = await chat.admit_chat_turn(prompt="hi")
    await chat.record_outcome(run.run_id, RunStatus.COMPLETED)

    assert await chat.record_outcome(run.run_id, RunStatus.FAILED) is False


async def test_closing_to_the_state_it_is_already_in_is_not_a_refusal(admitter) -> None:
    chat, _store = admitter
    run = await chat.admit_chat_turn(prompt="hi")
    await chat.record_outcome(run.run_id, RunStatus.COMPLETED)

    assert await chat.record_outcome(run.run_id, RunStatus.COMPLETED) is True


# ── the binding is wiring, never inferred from the request ────────


async def test_a_binding_needs_a_project_or_a_way_to_find_one() -> None:
    projects = InMemoryProjectScopeStore()
    store = InMemoryRunStore(project_store=projects)

    with pytest.raises(ValueError):
        ChatRunAdmitter(store, workspace_id=WORKSPACE)


async def test_an_empty_workspace_is_refused() -> None:
    projects = InMemoryProjectScopeStore()
    store = InMemoryRunStore(project_store=projects)

    with pytest.raises(ValueError):
        ChatRunAdmitter(store, workspace_id="   ", project_id="p")


async def test_the_root_project_is_resolved_once_and_cached() -> None:
    projects = InMemoryProjectScopeStore()
    await projects.create_root(WORKSPACE)
    store = InMemoryRunStore(project_store=projects)
    chat = ChatRunAdmitter(store, workspace_id=WORKSPACE, project_store=projects)

    first = await chat.admit_chat_turn(prompt="one")
    second = await chat.admit_chat_turn(prompt="two")

    assert first.project_id == second.project_id

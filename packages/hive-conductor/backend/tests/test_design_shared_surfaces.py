"""Design Studio's work opening consumes the shared persistent surfaces (row 18).

Row 18 of the issue #7 acceptance matrix (#777/#773): "Design Studio consumes
the same persistent Workspace Agent/user-memory/Attention surfaces rather
than defining product-private variants". Proven under the interview spec's
AC-15 (SPEC-091726-7c2a), the contract the work opening already carries. The repair composes the canonical
seams into the one flow where Design Studio opens work — the brief interview
— and these tests drive that flow through the app's real chat surface:

- the opening turn recalls the owner's relevant durable facts through the
  ONE ``UserModelService`` (a foreign owner's fact and an irrelevant fact
  never appear);
- recall stays capped at PERSONAL sensitivity at this surface even when a
  SENSITIVE fact is topically relevant — opt-in stays with the Agent and
  API surfaces that own it;
- an unavailable user model degrades to an omitted payload key, never to a
  process-local lookalike or fabricated context, and the deterministic
  interview phrasing is unchanged either way;
- the opening turn carries the shared Attention projection (#1049), so the
  surface shows what is waiting the moment new work starts, and an outage
  of that projection degrades to omission rather than failure;
- the hive resolver refuses to compose the shared service without the
  deployment PostgreSQL — the durable user model has no other backend by
  design, so there is no in-memory twin pretending to survive a restart.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest
import stores

from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier
from maistro.memory.user_model import InMemoryUserModelStore, promote_evidence
from maistro.memory.user_model.retrieval import RecallQuery, ScoredFact
from maistro.memory.user_model.service import UserModelService
from maistro.memory.user_model.types import FactSensitivity, new_fact_id
from maistro.security.sentinel.audit import InMemoryAuditLog

pytestmark = [pytest.mark.contract("behavioral"), pytest.mark.usefixtures("chat_run_spine")]

#: A turn that asks for work, matched by the interview's own work-request
#: pattern; it names the task the recall query scores against.
_OPEN = "Let's make a new video, let's start drafting a storyboard"

_RELEVANT = "the user edits videos in Final Cut and likes 16:9 reels"
_FOREIGN = "another user edits videos in Premiere and likes vertical cuts"
_IRRELEVANT = "the user's recording booth is in the basement closet"


@pytest.fixture(autouse=True)
def _clear_state():
    from services import brief_commit

    for store in (stores.workspaces, stores.brief_interviews):
        for key in list(store.keys()):
            store.pop(key, None)
    for key in list(brief_commit._commits.keys()):
        brief_commit._commits.pop(key, None)
    yield
    for store in (stores.workspaces, stores.brief_interviews):
        for key in list(store.keys()):
            store.pop(key, None)
    for key in list(brief_commit._commits.keys()):
        brief_commit._commits.pop(key, None)


class _CountingLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, req):
        self.calls += 1
        return {"choices": [{"message": {"role": "assistant", "content": "model answer"}}]}


@pytest.fixture
def llm(monkeypatch) -> _CountingLLM:
    fake = _CountingLLM()
    monkeypatch.setattr("routes.chat.build_llm_port", lambda: fake)
    return fake


@pytest.fixture
def shared_user_model(monkeypatch) -> UserModelService:
    """The one canonical service over the in-memory twin of its durable store.

    Production resolves ``PostgresUserModelStore`` over the deployment's
    PostgreSQL (the resolver test below proves it refuses anything else);
    this fixture swaps only that resolution, exactly the way the brief
    commit facade's tests swap the brief store, so the interview exercises
    the real service and the real recall rule.
    """
    store = InMemoryUserModelStore()
    service = UserModelService(store=store, audit_log=InMemoryAuditLog())
    monkeypatch.setattr("services.user_model.resolve_user_model_service", lambda: service)
    return service


async def _observe(service: UserModelService, owner: str, content: str, workspace_id: str) -> None:
    """One consolidated observation, promoted through consolidation's door."""
    memory = EpisodicMemory(
        tier=MemoryTier.OBSERVATION,
        content=content,
        user_id=owner,
        agent_id="agent-1",
        scope=MemoryScope.AGENT,
        project_id=f"proj-{workspace_id}",
        run_id=f"run-{workspace_id}",
    )
    await promote_evidence(
        memory,
        acting_user_id=owner,
        store=service.store,
        audit_log=service.audit_log,
        workspace_id=workspace_id,
        kind="possession",
    )


def _workspace(admin_client, *, share_with_user: bool = True) -> str:
    r = admin_client.post(
        "/v1/workspaces",
        json={"persona_template_id": "content_creator", "name": "Shared Surfaces Co"},
    )
    assert r.status_code == 201
    ws = r.json()["id"]
    if share_with_user:
        r = admin_client.post(
            f"/v1/workspaces/{ws}/members", json={"user_id": "user", "role": "editor"}
        )
        assert r.status_code == 200
    return ws


def _stream(client, text: str, workspace_id: str | None = None) -> list[dict[str, Any]]:
    body: dict[str, Any] = {"messages": [{"role": "user", "content": text}], "model": "m"}
    if workspace_id:
        body["workspace_id"] = workspace_id
    with client.stream("POST", "/v1/chat/stream", json=body) as r:
        assert r.status_code == 200
        raw = "".join(r.iter_text())
    return [
        json.loads(frame.split("data:", 1)[1])
        for frame in raw.split("\n\n")
        if frame.strip().startswith("data:")
    ]


@pytest.mark.ac("SPEC-091726-7c2a/AC-15")
async def test_work_opening_recalls_owner_relevant_facts_through_the_shared_user_model(
    admin_client, authed_client, llm, shared_user_model
) -> None:
    ws = _workspace(admin_client)
    await _observe(shared_user_model, "user", _RELEVANT, ws)
    await _observe(shared_user_model, "user", _IRRELEVANT, ws)
    await _observe(shared_user_model, "someone-else", _FOREIGN, ws)

    events = _stream(authed_client, _OPEN, ws)
    assert [e["type"] for e in events] == ["brief", "done"]
    brief = events[0]
    assert brief["event"] == "started"

    recalled = brief["user_context"]
    assert isinstance(recalled, list) and recalled, "the relevant fact must reach the surface"
    statements = [fact["statement"] for fact in recalled]
    assert any("Final Cut" in statement for statement in statements)
    assert all("Premiere" not in statement for statement in statements), (
        "another user's fact never reaches this surface: ownership is the store's gate"
    )
    assert all("basement" not in statement for statement in statements), (
        "an irrelevant fact is not injected: recall is relevance-gated, not a profile dump"
    )
    fact = recalled[0]
    assert fact["lineage_id"], "recalled facts carry provenance, not bare text"
    assert isinstance(fact["confidence"], float)
    assert llm.calls == 0
    assert any("user-model" in citation for citation in brief.get("citations", []))


@pytest.mark.ac("SPEC-091726-7c2a/AC-15")
async def test_recall_at_the_design_surface_caps_sensitivity(shared_user_model) -> None:
    """SENSITIVE facts stay behind their opt-in even when topically relevant.

    The surface composes ``RecallQuery`` with the protocol default
    (``PERSONAL``): a fact marked SENSITIVE scores 0 here, and widening the
    cap would be the surface growing its own disclosure policy.
    """
    from services.user_model import recall_for_design_task

    ws = "ws-sensitivity"
    await _observe(shared_user_model, "user", _RELEVANT, ws)
    store: InMemoryUserModelStore = shared_user_model.store
    head = await store.list_for_user("user")
    assert head and head[0].statement == _RELEVANT
    await store.append_revision(
        dataclasses.replace(
            head[0],
            fact_id=new_fact_id(),
            revision=2,
            supersedes=head[0].fact_id,
            sensitivity=FactSensitivity.SENSITIVE,
        )
    )

    recalled = await recall_for_design_task("user", "edit a new video", workspace_id=ws)
    assert recalled == [], "a SENSITIVE fact never surfaces at the design surface"

    await _observe(shared_user_model, "user", "the user prefers warm color grades", ws)
    recalled = await recall_for_design_task("user", "grade the new video", workspace_id=ws)
    assert recalled and recalled[0]["statement"] == "the user prefers warm color grades"

    assert (
        await recall_for_design_task("user", "refactor the payment parser", workspace_id=ws) == []
    ), "a task with no topical link recalls nothing"
    assert await recall_for_design_task("user", "edit a video", service=shared_user_model) == []


@pytest.mark.ac("SPEC-091726-7c2a/AC-15")
async def test_unavailable_user_model_omits_the_context_and_keeps_the_interview_deterministic(
    admin_client, authed_client, llm, monkeypatch
) -> None:
    """No shared service, no context — and no lookalike, no changed phrasing."""

    monkeypatch.setattr("services.user_model.resolve_user_model_service", lambda: None)

    ws = _workspace(admin_client)
    events = _stream(authed_client, _OPEN, ws)
    assert [e["type"] for e in events] == ["brief", "done"]
    brief, done = events
    assert brief["event"] == "started"
    assert "user_context" not in brief, "unavailable degrades to omission, never an empty list"
    assert "becomes a Goal" in done["content"], "the deterministic phrasing is unchanged"
    assert done["content"].endswith(brief["question"]["question"])
    assert llm.calls == 0

    from services.user_model import recall_for_design_task

    assert await recall_for_design_task("user", "edit a video") is None, (
        "an unavailable shared service recalls nothing rather than asserting an empty model"
    )


@pytest.mark.ac("SPEC-091726-7c2a/AC-15")
async def test_work_opening_carries_the_shared_attention_projection(
    admin_client, authed_client, llm, monkeypatch
) -> None:
    """The opening turn shows what is waiting, through the one #1049 projection."""
    from services import dag_agents

    from maistro.graph.definitions import Graph, Node
    from maistro.graph.durable_runs import InMemoryDurableRunStore
    from maistro.graph.durable_runs.types import DurableRunRecord
    from maistro.graph.execution_state import GraphExecutionState
    from maistro.graph.nodes.base import PAUSE_AWAITING_HUMAN_ANSWER
    from maistro.runs.lifecycle import transition_node_run, transition_run
    from maistro.runs.model import GraphSnapshot, NodeRun, Run, RunStatus
    from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

    ws = _workspace(admin_client)

    graph = Graph(
        workspace_id=ws,
        project_id="project-shared-surfaces",
        name="attention",
        nodes=[Node(node_id="ask", node_type="human.ask_question")],
    )
    run = Run(
        run_id="ss-paused-run",
        workspace_id=ws,
        project_id=graph.project_id,
        graph=GraphSnapshot.from_graph(graph),
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    for status in (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.PAUSED):
        run = transition_run(run, status)
    node_run = NodeRun(run_id=run.run_id, node_id="ask", ordinal=1)
    for status in (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.PAUSED):
        node_run = transition_node_run(node_run, status)
    record = DurableRunRecord(
        run=run,
        graph_state=GraphExecutionState(
            run_id=run.run_id,
            active_node_ids=("ask",),
            blackboard_snapshot={},
            metadata={
                "initial_inputs": {},
                "hitl_answers": {},
                "pauses": {
                    "ask": {
                        "kind": "hitl",
                        "metadata": {
                            "paused_reason": PAUSE_AWAITING_HUMAN_ANSWER,
                            "question": "ss-paused-run?",
                        },
                        "resume_at": None,
                    }
                },
            },
        ),
        node_runs=(node_run,),
        version=1,
    )
    store = InMemoryDurableRunStore()
    await store.create(record)
    monkeypatch.setattr(dag_agents, "get_run_store", lambda: store)

    events = _stream(authed_client, _OPEN, ws)
    brief = events[0]
    attention = brief["attention"]
    assert attention["workspace_id"] == ws
    ids = [item["source_id"] for item in attention["items"]]
    assert any(i.startswith("ss-paused-run") for i in ids), (
        "the shared projection's item reaches the opening turn"
    )
    item = next(i for i in attention["items"] if i["source_id"].startswith("ss-paused-run"))
    assert item["attention_class"] == "queued", (
        "the shared projection classifies; the surface does not re-rank"
    )
    assert any("attention" in citation for citation in brief.get("citations", []))
    assert llm.calls == 0


@pytest.mark.ac("SPEC-091726-7c2a/AC-15")
async def test_attention_outage_degrades_to_an_omitted_key(
    admin_client, authed_client, llm, monkeypatch
) -> None:
    async def _outage(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("attention projection is down")

    monkeypatch.setattr("services.attention.list_attention", _outage)
    ws = _workspace(admin_client)
    events = _stream(authed_client, _OPEN, ws)
    assert [e["type"] for e in events] == ["brief", "done"]
    brief = events[0]
    assert brief["event"] == "started"
    assert "attention" not in brief, "a projection outage omits the key, never fails the turn"
    assert llm.calls == 0


def test_resolver_refuses_to_compose_without_postgres(monkeypatch) -> None:
    """The durable user model is PostgreSQL-only by design; no memory lookalike."""
    import services.user_model as user_model_service

    monkeypatch.setattr(user_model_service, "resolve_database_url", lambda: "sqlite:///./dev.db")
    assert user_model_service.resolve_user_model_service() is None, (
        "a deployment without PostgreSQL gets None — never an in-memory store "
        "that could not survive a restart"
    )


@pytest.mark.ac("SPEC-091726-7c2a/AC-15")
def test_resolver_refuses_to_compose_without_the_core_audit_log(monkeypatch) -> None:
    """PostgreSQL configured but no core runtime: no half-composed service.

    The user model's canonical audit log is resolved from the embedded core
    runtime — the same wiring ``maistro_server.main`` makes. Without it the
    resolver answers ``None`` rather than composing a service that could not
    record what it recalled.
    """
    import services.audit_bridge
    import services.user_model as user_model_service

    monkeypatch.setattr(
        user_model_service,
        "resolve_database_url",
        lambda: "postgresql://maistro:maistro@127.0.0.1:5432/maistro_test",
    )
    monkeypatch.setattr(services.audit_bridge, "core_audit_log", lambda: None)
    assert user_model_service.resolve_user_model_service() is None, (
        "a missing canonical audit log is a half-composed service; recall nothing"
    )


@pytest.mark.ac("SPEC-091726-7c2a/AC-15")
def test_resolver_refuses_to_compose_without_the_design_session_factory(monkeypatch) -> None:
    """PostgreSQL and audit present but the design engine never started: None.

    ``_get_async_session_factory`` answers ``None`` when the design services'
    async engine did not start; the resolver degrades the same way it does for
    every other unavailability instead of building the store over an
    invented factory.
    """
    import services.audit_bridge
    import services.design_service
    import services.user_model as user_model_service

    audit = InMemoryAuditLog()
    monkeypatch.setattr(
        user_model_service,
        "resolve_database_url",
        lambda: "postgresql://maistro:maistro@127.0.0.1:5432/maistro_test",
    )
    monkeypatch.setattr(services.audit_bridge, "core_audit_log", lambda: audit)
    monkeypatch.setattr(services.design_service, "_get_async_session_factory", lambda: None)
    assert user_model_service.resolve_user_model_service() is None, (
        "no session factory means no store; degrade to None, never to a lookalike"
    )


@pytest.mark.ac("SPEC-091726-7c2a/AC-15")
def test_resolver_composes_the_shared_service_over_postgres(monkeypatch) -> None:
    """The one composition: shared service over the deployment's own seams.

    With PostgreSQL configured, the core audit log running and the design
    session factory started, the resolver returns the canonical
    ``UserModelService`` whose store is the durable ``PostgresUserModelStore"
    bound to that same factory — no second service class, no second store.
    """
    import services.audit_bridge
    import services.design_service
    import services.user_model as user_model_service

    from maistro.memory.user_model.pg_store import PostgresUserModelStore
    from maistro.memory.user_model.service import UserModelService

    audit = InMemoryAuditLog()
    factory = object()  # sentinel: the store keeps it; no session is opened here
    monkeypatch.setattr(
        user_model_service,
        "resolve_database_url",
        lambda: "postgresql://maistro:maistro@127.0.0.1:5432/maistro_test",
    )
    monkeypatch.setattr(services.audit_bridge, "core_audit_log", lambda: audit)
    monkeypatch.setattr(services.design_service, "_get_async_session_factory", lambda: factory)

    service = user_model_service.resolve_user_model_service()

    assert isinstance(service, UserModelService), "the one shared service class"
    assert isinstance(service.store, PostgresUserModelStore), "the durable store, not a twin"
    assert service.store._factory is factory, "bound to the design deployment's own factory"
    assert service.audit_log is audit, "the canonical audit log travels with the service"


@pytest.mark.ac("SPEC-091726-7c2a/AC-15")
async def test_recall_failure_degrades_to_none(caplog) -> None:
    """A user-model outage must not fail the work opening — and must be visible.

    Recall is enrichment over an already-working interview: the outage path
    answers ``None`` (omitted context) and logs, never raises through the
    chat surface.
    """
    import logging

    from services.user_model import recall_for_design_task

    class _OutageService:
        """Duck-typed stand-in for the one shared service, mid-outage."""

        async def recall_for_task(self, query: RecallQuery) -> list[ScoredFact]:
            raise RuntimeError("user model store is down")

    with caplog.at_level(logging.ERROR, logger="services.user_model"):
        recalled = await recall_for_design_task("user", "edit a video", service=_OutageService())
    assert recalled is None, "an outage recalls nothing instead of failing the opening"
    assert caplog.records, "the outage is logged, not swallowed"

"""The brief interview runs as chat turns (SPEC-091726-7c2a, #53).

The admin account is blocked from chat (break-glass only), so the workspace
is created by the admin, shared with the regular user, and every chat turn is
the regular user's.

A turn in a workspace that asks for work is answered by the interview, not
the model; while an interview is open every turn there is an answer to it;
"never mind" hands the next turn back to the model; "commit it" produces the
draft and says nothing else was written. A turn with no workspace, or one
that asks a question, still reaches the model exactly as before.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
import stores

pytestmark = [pytest.mark.contract("behavioral"), pytest.mark.usefixtures("chat_run_spine")]


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


def _workspace(admin_client, *, share_with_user: bool = True) -> str:
    r = admin_client.post(
        "/v1/workspaces",
        json={"persona_template_id": "content_creator", "name": "Rooted Craft Co"},
    )
    assert r.status_code == 201
    ws = r.json()["id"]
    if share_with_user:
        r = admin_client.post(
            f"/v1/workspaces/{ws}/members", json={"user_id": "user", "role": "editor"}
        )
        assert r.status_code == 200
    return ws


def _user_owned_workspace(authed_client) -> str:
    """A Workspace the regular user OWNS.

    Committing canonical state is an administration act (#1823): only an
    owner may confirm the commit, and the admin account is blocked from chat,
    so the committing conversation happens in a workspace this user created."""
    r = authed_client.post(
        "/v1/workspaces",
        json={"persona_template_id": "content_creator", "name": "My Craft Co"},
    )
    assert r.status_code == 201
    return r.json()["id"]


@pytest.fixture
def brief_commit_facade(monkeypatch, chat_run_spine):
    """Give the boundary its real stores for a chat-level commit.

    The Goal seam resolves through production composition — the fixture hangs
    a `ScopedGoalStore` (over the spine Container's own Goal store and the
    canonical Workspace authority) on the chat spine's container, exactly the
    pair production builds in `create_container`. The brief store is the real
    `PgCreativeBriefStore` over a real SQLite schema (the same facade
    `maistro-design`'s store tests drive), injected at the boundary's
    resolution seam because a PostgreSQL server is not part of a unit run."""
    from contextlib import asynccontextmanager

    from services import brief_commit as brief_commit_mod
    from services import chat_runs
    from services.engine import get_engine
    from services.workspace_authority import canonical_store_for_tests
    from sqlalchemy import create_engine, text

    from maistro.goals.authorization import ScopedGoalStore
    from maistro.projects.scope_store import InMemoryProjectScopeStore

    workspaces = canonical_store_for_tests()
    goal_store = chat_run_spine.goal_store
    goal_reader = ScopedGoalStore(goal_store, workspaces)
    container = get_engine()._agent_port.container
    container.goal_reader = goal_reader
    container.workspace_store = workspaces

    class _Briefs:
        def __init__(self) -> None:
            # check_same_thread: the test drives SQLite from the TestClient's
            # portal thread; the facade's single connection is used only from
            # that loop once handed to the app.
            self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
            self.connection = self.engine.connect()
            for statement in (
                "CREATE TABLE canonical_projects (project_id TEXT PRIMARY KEY, "
                "workspace_id TEXT NOT NULL)",
                "CREATE TABLE design_creative_briefs (brief_id TEXT PRIMARY KEY, "
                "lineage_id TEXT NOT NULL, version INTEGER NOT NULL, "
                "supersedes_brief_id TEXT, workspace_id TEXT NOT NULL, "
                "project_id TEXT NOT NULL, goal_id TEXT NOT NULL, "
                "goal_revision INTEGER NOT NULL, payload TEXT NOT NULL, "
                "created_by TEXT NOT NULL DEFAULT '', created_at TEXT, "
                "CONSTRAINT uq_design_creative_briefs_lineage_version "
                "UNIQUE (lineage_id, version))",
            ):
                self.connection.execute(text(statement))
            self.connection.commit()

        @asynccontextmanager
        async def _session(self):
            connection = self.connection

            class Session:
                async def execute(
                    self, statement: Any, params: dict[str, Any] | None = None
                ) -> Any:
                    return connection.execute(statement, params or {})

                async def commit(self) -> None:
                    connection.commit()

            yield Session()

        def seed_project(self, project_id: str, workspace_id: str) -> None:
            self.connection.execute(
                text("INSERT INTO canonical_projects (project_id, workspace_id) VALUES (:p, :w)"),
                {"p": project_id, "w": workspace_id},
            )
            self.connection.commit()

        def brief_rows(self) -> list[tuple[str, int]]:
            rows = self.connection.execute(
                text("SELECT brief_id, version FROM design_creative_briefs")
            ).fetchall()
            return [(str(r[0]), int(r[1])) for r in rows]

    briefs = _Briefs()
    from maistro_design.brief_store import PgCreativeBriefStore

    store = PgCreativeBriefStore(session_factory=briefs._session)
    project_store = InMemoryProjectScopeStore()

    def _resolve_brief_store(override: Any = None) -> Any:
        return override if override is not None else store

    def _resolve_project_store(override: Any = None) -> Any:
        return override if override is not None else project_store

    monkeypatch.setattr(brief_commit_mod, "_resolve_brief_store", _resolve_brief_store)
    monkeypatch.setattr(brief_commit_mod, "_resolve_project_store", _resolve_project_store)
    chat_runs.reset_for_tests()
    yield SimpleNamespace(
        briefs=briefs,
        brief_store=store,
        project_store=project_store,
        goal_reader=goal_reader,
    )
    chat_runs.reset_for_tests()


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


def test_a_turn_without_a_workspace_reaches_the_model_as_before(authed_client, llm) -> None:
    events = _stream(authed_client, "Let's make a new video")
    assert [e["type"] for e in events] == ["done"]
    assert events[0]["content"] == "model answer"
    assert llm.calls == 1


def test_a_question_in_a_workspace_reaches_the_model(admin_client, authed_client, llm) -> None:
    ws = _workspace(admin_client)
    events = _stream(authed_client, "What did you do overnight?", ws)
    assert [e["type"] for e in events] == ["done"]
    assert llm.calls == 1


@pytest.mark.ac("SPEC-091726-7c2a/AC-1")
def test_a_work_request_in_a_workspace_opens_the_interview_instead_of_the_model(
    admin_client, authed_client, llm
) -> None:
    ws = _workspace(admin_client)
    events = _stream(authed_client, "Let's make a new video, let's start drafting a storyboard", ws)

    assert [e["type"] for e in events] == ["brief", "done"]
    brief, done = events
    assert brief["event"] == "started"
    assert brief["summary"]["known"] == 0
    assert brief["question"]["key"] == "subject"
    assert "becomes a Goal" in done["content"]
    assert done["content"].endswith(brief["question"]["question"])
    assert llm.calls == 0, "the model is not asked while the interview owns the turn"


@pytest.mark.ac("SPEC-091726-7c2a/AC-2")
@pytest.mark.ac("SPEC-091726-7c2a/AC-8")
def test_answers_advance_the_interview_and_preconfirmation_writes_nothing(
    admin_client, authed_client, llm
) -> None:
    ws = _workspace(admin_client)
    _stream(authed_client, "New reel about the grouting haze", ws)

    seen: list[tuple[str, str | None]] = []
    for text in ("the grouting haze fix", "teach it", "the assembled cut", "you decide"):
        brief, done = _stream(authed_client, text, ws)
        seen.append((brief["event"], brief["question"] and brief["question"]["key"]))
        assert done["content"]
    assert seen == [
        ("answered", "outcome"),
        ("answered", "source"),
        ("answered", "deadline"),
        ("assumed", None),
    ]
    brief, done = _stream(authed_client, "keep the intro under three seconds", ws)
    assert brief["event"] == "noted", "once ready, a non-answer is a note, not a Goal change"
    assert "Here's what I'd commit" in done["content"]
    assert brief["written"] == [], "nothing is written before the explicit confirmation"
    assert llm.calls == 0


@pytest.mark.ac("SPEC-091726-7c2a/AC-7")
def test_cancel_drops_and_hands_the_next_turn_to_the_model(
    admin_client, authed_client, llm
) -> None:
    """The Warden input boundary runs before the interview, as before every
    chat turn; "never mind" trips its injection patterns and is refused
    before the interview sees it, so the chat's drop word is "cancel"."""
    ws = _workspace(admin_client)
    _stream(authed_client, "start a storyboard for a new reel", ws)
    brief, done = _stream(authed_client, "cancel", ws)
    assert brief["event"] == "dropped"
    assert brief["interview"] is None
    assert "Nothing was committed" in done["content"]
    assert llm.calls == 0

    events = _stream(authed_client, "so what's on for saturday?", ws)
    assert [e["type"] for e in events] == ["done"]
    assert llm.calls == 1


@pytest.mark.ac("SPEC-091726-7c2a/AC-5")
def test_an_answer_for_another_field_is_routed_and_the_question_is_repeated(
    admin_client, authed_client, llm
) -> None:
    ws = _workspace(admin_client)
    _stream(authed_client, "make a video", ws)
    _stream(authed_client, "the grouting haze", ws)
    _stream(authed_client, "teach it", ws)
    brief, done = _stream(authed_client, "after the market", ws)
    assert brief["event"] == "routed"
    assert brief["question"]["key"] == "channel"
    assert "put it there" in done["content"]
    assert done["content"].endswith(brief["question"]["question"])


def test_the_non_streaming_route_carries_the_same_brief(admin_client, authed_client, llm) -> None:
    ws = _workspace(admin_client)
    r = authed_client.post(
        "/v1/chat/complete",
        json={
            "messages": [{"role": "user", "content": "let's draft a new reel"}],
            "model": "m",
            "workspace_id": ws,
        },
    )
    assert r.status_code == 200
    assert r.json()["brief"]["event"] == "started"
    assert "becomes a Goal" in r.json()["choices"][0]["message"]["content"]
    assert llm.calls == 0


def test_a_workspace_the_caller_is_not_a_member_of_is_the_models_turn(
    admin_client, authed_client, llm
) -> None:
    ws = _workspace(admin_client, share_with_user=False)
    events = _stream(authed_client, "let's make a new video", ws)
    assert [e["type"] for e in events] == ["done"]
    assert llm.calls == 1


@pytest.mark.ac("SPEC-091726-7c2a/AC-6")
def test_you_decide_is_refused_where_nothing_is_defensible(
    admin_client, authed_client, llm
) -> None:
    ws = _workspace(admin_client)
    _stream(authed_client, "make a video", ws)
    brief, done = _stream(authed_client, "you decide", ws)
    assert brief["event"] == "cannot_assume"
    assert brief["question"]["key"] == "subject", "the subject stays open"
    assert "can't assume" in done["content"]
    assert not done["content"].endswith(brief["question"]["question"]), (
        "the refusal stands alone; the question is not repeated after it"
    )
    assert llm.calls == 0


def test_once_ready_a_vague_change_asks_which_field(admin_client, authed_client, llm) -> None:
    ws = _workspace(admin_client)
    _stream(authed_client, "New reel about the grouting haze", ws)
    for text in ("the grouting haze fix", "teach it", "the assembled cut", "you decide"):
        _stream(authed_client, text, ws)
    brief, done = _stream(authed_client, "something's wrong", ws)
    assert brief["event"] == "noted"
    assert done["content"].startswith("Which one?")

    brief, done = _stream(authed_client, "change channel to youtube", ws)
    assert brief["event"] == "changed"
    assert "Channel:" in done["content"]
    assert llm.calls == 0


def test_an_interview_dropped_through_the_program_api_hands_chat_to_the_model(
    admin_client, authed_client, llm
) -> None:
    """The program routes leave a dropped interview in the store; the chat
    forgets it on the next turn and lets the model answer."""
    ws = _workspace(admin_client)
    r = authed_client.post(
        f"/v1/program/brief/start?workspace_id={ws}", json={"opening": "a video"}
    )
    assert r.status_code == 201
    r = authed_client.post(
        f"/v1/program/brief/answer?workspace_id={ws}", json={"answer": "never mind"}
    )
    assert r.json()["event"] == "dropped"

    events = _stream(authed_client, "what's on for saturday?", ws)
    assert [e["type"] for e in events] == ["done"]
    assert llm.calls == 1
    assert authed_client.get(f"/v1/program/brief?workspace_id={ws}").json()["interview"] is None


def test_a_blank_turn_in_a_workspace_is_the_models(admin_client, authed_client, llm) -> None:
    ws = _workspace(admin_client)
    _stream(authed_client, "make a video", ws)
    events = _stream(authed_client, "   ", ws)
    assert [e["type"] for e in events] == ["done"]
    assert llm.calls == 1


# ---------------------------------------------------------------------------
# The commit (#1823): the explicit confirmation is the one write path.
# ---------------------------------------------------------------------------


def _interview_to_ready(client, ws: str):
    """Drive the shipped interview to the ready state; return the last turn."""
    _stream(client, "New reel about the grouting haze", ws)
    last = None
    for text in ("the grouting haze fix", "teach it", "the assembled cut", "you decide"):
        last = _stream(client, text, ws)
    brief, _done = _stream(client, "keep the intro under three seconds", ws)
    assert brief["event"] == "noted"
    return last


def _root_project(facade, ws: str) -> str:
    """Create the Workspace's Root Project and register it where the brief
    store's scope check reads it (production composes this off the same
    canonical spine: the Project store writes `canonical_projects`)."""
    import asyncio

    root = asyncio.run(facade.project_store.create_root(ws))
    facade.briefs.seed_project(str(root.project_id), ws)
    return str(root.project_id)


def _goal_route(client, ws: str) -> list[dict[str, Any]]:
    """Canonical Goal enumeration through the product's own inspection
    route (#65) — the same surface AC-6 names, on the same event loop the
    commit ran on."""
    r = client.get(f"/v1/workspaces/{ws}/goals")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.ac("SPEC-091726-7c2a/AC-10")
def test_a_confirmed_interview_commits_one_goal_and_one_brief(
    authed_client, llm, brief_commit_facade
) -> None:
    import asyncio

    from services.brief_commit import list_commitments
    from services.engine import get_engine

    ws = _user_owned_workspace(authed_client)
    _root_project(brief_commit_facade, ws)
    _interview_to_ready(authed_client, ws)
    brief, done = _stream(authed_client, "commit it", ws)

    assert brief["event"] == "committed"
    commit = brief["commit"]
    assert commit["status"] == "committed"
    assert commit["goal_revision"] == 1
    assert commit["brief_version"] == 1
    assert brief["written"] == [
        {"kind": "goal", "goal_id": commit["goal_id"], "revision": 1},
        {
            "kind": "creative_brief",
            "brief_id": commit["brief_id"],
            "lineage_id": commit["lineage_id"],
            "version": 1,
        },
    ]
    assert "Committed. Goal" in done["content"]
    assert "#458 and #774" not in done["content"], "the draft-only copy is gone"
    assert brief["interview"] is None, "a committed interview is over"
    assert llm.calls == 0, "the model is not asked while the interview owns the turn"
    # A commit is not work admission (AC-3): the canonical Run spine gained
    # nothing — fulfillment stays with Goal -> Graph -> Run, driven by
    # reconciliation (#805/#806), never by an interview-owned loop.
    run_store = get_engine()._agent_port.container.run_store
    runs_before = len(run_store._runs)

    # The committed pair is really there: the Goal enumerates through the
    # product's Goal inspection route (the scoped canonical reader), the
    # brief reads back bound to it, and the queryable commit record names
    # the same ids.
    views = _goal_route(authed_client, ws)
    assert [v["goal_id"] for v in views] == [commit["goal_id"]]
    assert "grouting haze fix — Teach it" in views[0]["desired_state"]
    # The brief row is bound to the exact Goal identity/revision (scalar
    # columns — the payload round-trip is held by the PostgreSQL boundary
    # suite, since SQLite cannot store the jsonb cast the real store writes).
    from sqlalchemy import text

    rows = brief_commit_facade.briefs.connection.execute(
        text(
            "SELECT brief_id, version, goal_id, goal_revision, workspace_id "
            "FROM design_creative_briefs"
        )
    ).fetchall()
    assert [(str(r[0]), int(r[1])) for r in rows] == [(commit["brief_id"], 1)]
    binding = rows[0]._mapping
    assert str(binding["goal_id"]) == commit["goal_id"]
    assert int(binding["goal_revision"]) == 1
    assert str(binding["workspace_id"]) == ws
    commitments = asyncio.run(list_commitments("user", ws))
    assert [c["status"] for c in commitments] == ["committed"]
    assert commitments[0]["goal_id"] == commit["goal_id"]
    assert len(run_store._runs) == runs_before, "the commit admitted no Run"


@pytest.mark.ac("SPEC-091726-7c2a/AC-11")
def test_cancel_creates_no_goal_and_the_next_model_turn_still_admits_a_run(
    authed_client, llm, brief_commit_facade
) -> None:
    from services.engine import get_engine

    ws = _user_owned_workspace(authed_client)
    _stream(authed_client, "start a storyboard for a new reel", ws)
    brief, done = _stream(authed_client, "cancel", ws)
    assert brief["event"] == "dropped"
    assert "Nothing was committed" in done["content"]

    assert _goal_route(authed_client, ws) == [], "a dropped interview created no Goal"
    assert brief_commit_facade.briefs.brief_rows() == []
    assert list(stores.brief_interviews.keys()) == []

    # #1037 evidence is untouched: the next ordinary turn is still admitted
    # as a Run on the canonical spine, exactly as it was before #1823.
    run_store = get_engine()._agent_port.container.run_store
    runs_before = len(run_store._runs)
    events = _stream(authed_client, "what's on for saturday?", ws)
    assert [e["type"] for e in events] == ["done"]
    assert llm.calls == 1
    assert len(run_store._runs) == runs_before + 1, "the model turn admitted a Run"


@pytest.mark.ac("SPEC-091726-7c2a/AC-12")
def test_a_replayed_confirmation_after_a_lost_response_returns_the_same_commit(
    authed_client, llm, brief_commit_facade
) -> None:
    """Crash after the durable commit but before the interview cleared: the
    replayed 'commit it' returns the same ids and duplicates nothing."""
    from services import brief_store as interview_store

    ws = _user_owned_workspace(authed_client)
    _root_project(brief_commit_facade, ws)
    _interview_to_ready(authed_client, ws)
    state = interview_store.get_interview("user", ws)
    assert state is not None

    brief, _ = _stream(authed_client, "commit it", ws)
    assert brief["event"] == "committed"

    # Simulate the crash window: the interview survives a committed result.
    interview_store.save_interview("user", ws, state)
    replay, done = _stream(authed_client, "commit it", ws)
    assert replay["event"] == "committed"
    assert replay["commit"]["status"] == "already_committed"
    assert replay["commit"]["goal_id"] == brief["commit"]["goal_id"]
    assert replay["commit"]["brief_id"] == brief["commit"]["brief_id"]
    assert "Nothing was duplicated" in done["content"]
    assert len(_goal_route(authed_client, ws)) == 1
    assert brief_commit_facade.briefs.brief_rows() == [(brief["commit"]["brief_id"], 1)]


@pytest.mark.ac("SPEC-091726-7c2a/AC-13")
def test_a_non_owner_confirmation_is_refused_without_writing(
    admin_client, authed_client, llm, brief_commit_facade
) -> None:
    ws = _workspace(admin_client)  # user is an editor here, not the owner
    _root_project(brief_commit_facade, ws)
    _interview_to_ready(authed_client, ws)

    brief, _done = _stream(authed_client, "commit it", ws)
    assert brief["event"] == "refused"
    assert brief["commit"]["status"] == "refused"
    assert brief["written"] == []
    assert brief["interview"] is not None, "the draft is still open"
    assert _goal_route(authed_client, ws) == []
    assert brief_commit_facade.briefs.brief_rows() == []


@pytest.mark.ac("SPEC-091726-7c2a/AC-14")
def test_an_unavailable_brief_store_is_an_explicit_recoverable_limitation(
    authed_client, llm
) -> None:
    """No brief store wired (the no-database dev path): the boundary refuses
    loudly, the interview stays open, and the copy says how to retry."""
    ws = _user_owned_workspace(authed_client)
    _interview_to_ready(authed_client, ws)

    brief, done = _stream(authed_client, "commit it", ws)
    assert brief["event"] == "unavailable"
    assert brief["commit"]["status"] == "unavailable"
    assert "unavailable" in brief["commit"]["reason"]
    assert brief["written"] == []
    assert brief["interview"] is not None, "the recoverable draft is kept"
    assert "commit it" in done["content"], "the reply says the same confirmation can retry"
    assert _goal_route(authed_client, ws) == []

    brief2, _ = _stream(authed_client, "commit it", ws)
    assert brief2["event"] == "unavailable", "the retry reaches the same honest answer"

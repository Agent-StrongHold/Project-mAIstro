"""The brief-interview commit boundary (#1823, SPEC-091726-7c2a).

The interview used to stop at a draft: the confirmation turn cleared the
interview and said nothing was written. These tests hold the replacement —
`services.brief_commit`, the one authorized application-service commit
boundary — against the issue's acceptance criteria:

- AC-1  one confirmed interview -> one canonical Goal revision + one
        CreativeBrief version bound to its exact Goal revision and owner;
        the same ids read back after a restart;
- AC-2  unconfirmed/incomplete intake writes nothing (cancellation lives in
        `test_chat_brief_interview.py`, on the shipped chat path);
- AC-3  replayed and concurrent identical confirmations return the existing
        result and mint no duplicate Goal, brief version, Subgoal or Run;
- AC-4  forced crashes before/between/after the writes recover
        deterministically from the durable commit record, and recovery
        completes the pair instead of stranding a half intake;
- AC-5  a non-owner principal is refused before any identity is minted, and
        cannot read another's commitments; server-resolved Project/agent
        identities cannot be supplied by the caller;
- AC-6  canonical Goal enumeration exposes the committed Goal through a
        fresh scoped reader (chat closed, stores re-opened);
- AC-7  revising the desired outcome appends a Goal revision and a brief
        version on the same lineage; a creative-only change mints a brief
        version without touching the Goal;
- AC-8  missing prerequisites answer the explicit recoverable limitation and
        the same confirmation stays retryable.

Driven against the real supported durable stores: `PgGoalStore` and
`PgCreativeBriefStore` over one real PostgreSQL server migrated by the real
alembic chain (the same skip contract `maistro-design`'s brief-store tests
use: no `MAISTRO_TEST_DATABASE_URL` skips, `MAISTRO_REQUIRE_PG_LEGS` makes an
absent server a failure), the `ScopedGoalStore` authorization seam, and the
canonical Workspace authority the product itself answers membership from. A
restart re-opens fresh pools and engines on the same server before anything
is asserted.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) in sys.path:
    sys.path.remove(str(_BACKEND))
sys.path.insert(0, str(_BACKEND))

pytestmark = [pytest.mark.contract("boundary")]

DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")


def _require_postgres() -> str:
    """The asyncpg URL, or a skip — unless a server is declared guaranteed."""
    if DATABASE_URL:
        return DATABASE_URL
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_DATABASE_URL is empty: "
            "the brief-commit PostgreSQL leg cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_DATABASE_URL is unset; these need a real PostgreSQL server")


def _asyncpg_url() -> str:
    url = _require_postgres()
    if url.startswith("postgresql+asyncpg://"):
        return url
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


def _dsn() -> str:
    """The plain asyncpg DSN (for the Goal store's pool)."""
    return _asyncpg_url().replace("postgresql+asyncpg://", "postgresql://", 1)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _final_draft(**overrides: Any) -> dict[str, Any]:
    """A finalized draft exactly as `brief_interview.commit_brief` emits it."""
    draft: dict[str, Any] = {
        "script": "video_brief",
        "opening": "let's make a new reel about the grouting haze",
        "fields": {
            "subject": "the grouting haze fix",
            "outcome": "Teach it",
            "channel": "a 30-second vertical reel",
            "source": "A fresh shoot; the specialist writes a shot list first",
            "deadline": "Before the market",
            "voice": "The persona's voice",
            "claims": "Only what the published guides say; no growth-rate or price claims",
            "mode": "Collaborative: the specialist drafts, you mark up, nothing publishes",
        },
        "sources": {
            "subject": "user",
            "outcome": "user",
            "channel": "user",
            "source": "record",
            "deadline": "assumed",
            "voice": "assumed",
            "claims": "assumed",
            "mode": "assumed",
        },
        "options": {"outcome": "teach", "channel": "reel", "deadline": "before"},
        "assumed": ["deadline", "voice", "claims", "mode"],
        "notes": ["keep the intro under three seconds"],
        "turns": 7,
    }
    draft.update(overrides)
    return draft


_USER = "brief-commit-owner"
_OTHER = "brief-commit-stranger"


@pytest.fixture(autouse=True)
def _clean_commit_records():
    from services import brief_commit

    for key in list(brief_commit._commits.keys()):
        brief_commit._commits.pop(key, None)
    yield
    for key in list(brief_commit._commits.keys()):
        brief_commit._commits.pop(key, None)


@pytest.fixture
async def _pg_server():
    """One real PostgreSQL server, migrated by the real alembic chain.

    Function-scoped objects: an asyncpg pool's connections and a SQLAlchemy
    async engine's pool bind to the event loop that first uses them, so every
    test gets its own pool/engine on its own loop and disposes them after."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    _require_postgres()
    engine = create_async_engine(_asyncpg_url(), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    import asyncpg

    pool = await asyncpg.create_pool(_dsn())
    try:
        yield SimpleNamespace(engine=engine, factory=factory, pool=pool)
    finally:
        await pool.close()
        await engine.dispose()


@pytest.fixture
async def owned_workspace():
    """A canonical Workspace this principal owns (per-test unique id)."""
    from services import workspace_authority

    workspace = await workspace_authority.create_workspace(
        creator_user_id=_USER,
        name=f"Brief Commit {uuid.uuid4().hex[:8]}",
        persona_template_id="content_creator",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    return workspace


@pytest.fixture
async def stack(_pg_server, owned_workspace):
    """Goal seam + brief store + project store over the real durable stores,
    scoped to a fresh Workspace; every row the tests create is removed."""
    from services import workspace_authority

    from maistro.goals.authorization import ScopedGoalStore
    from maistro.goals.pg_store import PgGoalStore, ensure_goal_schema
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro_design.brief_store import PgCreativeBriefStore

    await ensure_goal_schema(_pg_server.pool)
    goal_store = PgGoalStore(_pg_server.pool)
    workspaces = workspace_authority.canonical_store_for_tests()
    brief_store = PgCreativeBriefStore(session_factory=_pg_server.factory)
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(owned_workspace.id)

    async def register_project() -> None:
        # What the canonical Project store's PostgreSQL twin writes; the
        # brief store's scope check reads exactly this table.
        from sqlalchemy import text

        async with _pg_server.factory() as session:
            await session.execute(
                text(
                    "INSERT INTO canonical_projects (project_id, workspace_id, is_root, "
                    "payload) VALUES (:p, :w, TRUE, CAST(:payload AS jsonb)) "
                    "ON CONFLICT (project_id) DO NOTHING"
                ),
                {
                    "p": str(root.project_id),
                    "w": owned_workspace.id,
                    "payload": '{"name": "brief-commit-test"}',
                },
            )
            await session.commit()

    await register_project()

    async def restart_durable() -> Any:
        """A restarted process: fresh pool + fresh engine, same server."""
        import asyncpg
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        pool = await asyncpg.create_pool(_dsn())
        await ensure_goal_schema(pool)
        engine = create_async_engine(_asyncpg_url(), pool_pre_ping=True)
        fresh = SimpleNamespace(
            goal_reader=ScopedGoalStore(PgGoalStore(pool), workspaces),
            brief_store=PgCreativeBriefStore(
                session_factory=async_sessionmaker(engine, expire_on_commit=False)
            ),
        )
        return SimpleNamespace(fresh=fresh, pool=pool, engine=engine)

    handle = SimpleNamespace(
        workspace=owned_workspace,
        root=root,
        projects=projects,
        workspaces=workspaces,
        brief_store=brief_store,
        goal_reader=ScopedGoalStore(goal_store, workspaces),
        goal_store=goal_store,
        register_project=register_project,
        restart_durable=restart_durable,
        server=_pg_server,
    )
    try:
        yield handle
    finally:
        from sqlalchemy import text

        ws = owned_workspace.id
        async with _pg_server.factory() as session:
            await session.execute(
                text("DELETE FROM design_creative_briefs WHERE workspace_id = :w"), {"w": ws}
            )
            await session.execute(
                text(
                    "DELETE FROM canonical_goal_transitions WHERE goal_id IN "
                    "(SELECT goal_id FROM canonical_goals WHERE workspace_id = :w)"
                ),
                {"w": ws},
            )
            await session.execute(
                text(
                    "DELETE FROM canonical_goal_revisions WHERE goal_id IN "
                    "(SELECT goal_id FROM canonical_goals WHERE workspace_id = :w)"
                ),
                {"w": ws},
            )
            await session.execute(
                text("DELETE FROM canonical_goals WHERE workspace_id = :w"), {"w": ws}
            )
            await session.execute(
                text("DELETE FROM canonical_projects WHERE workspace_id = :w"), {"w": ws}
            )
            await session.commit()
        # The per-test Workspace lives in the in-process canonical store; the
        # shared test database keeps no Workspace rows of its own.


async def _commit(stack: Any, draft: dict[str, Any], **kwargs: Any) -> Any:
    from services.brief_commit import commit_draft

    return await commit_draft(
        _USER,
        stack.workspace.id,
        draft,
        confirmed=kwargs.pop("confirmed", True),
        goal_reader=kwargs.pop("goal_reader", stack.goal_reader),
        project_store=kwargs.pop("project_store", stack.projects),
        brief_store=kwargs.pop("brief_store", stack.brief_store),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# AC-1: one confirmed interview -> one Goal + one brief, readable back
# ---------------------------------------------------------------------------


@pytest.mark.contract("behavioral")
async def test_confirmed_interview_commits_one_goal_and_one_brief(stack) -> None:
    from services.agent_materialization import workspace_agent_id
    from services.brief_commit import _get_record, commit_key

    from maistro.goals import GoalStatus

    outcome = await _commit(stack, _final_draft())
    assert outcome.status == "committed", outcome
    assert outcome.goal_revision == 1
    assert outcome.brief_version == 1

    # Exactly one Goal, active, parented on the Root Project, accountable to
    # the stable Workspace Agent.
    goals = await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER)
    assert [g.goal_id for g in goals] == [outcome.goal_id]
    goal = goals[0]
    assert goal.status == GoalStatus.ACTIVE
    assert goal.project_id == str(stack.root.project_id)
    assert goal.agent_id == workspace_agent_id(stack.workspace.id)
    assert goal.parent_goal_id is None, "an intake commit creates no Subgoal"

    revisions = await stack.goal_reader.list_goal_revisions(goal.goal_id, principal_id=_USER)
    assert len(revisions) == 1
    revision = revisions[0]
    assert revision.revision == 1
    assert revision.desired_state == "the grouting haze fix — Teach it"
    assert revision.success_conditions == ("Teach it",)
    assert revision.stop_conditions == ("deadline: Before the market",)
    assert revision.author == workspace_agent_id(stack.workspace.id)

    # Exactly one brief version, bound to the exact Goal identity/revision —
    # read back through the real PostgreSQL store.
    brief = await stack.brief_store.get(outcome.brief_id, workspace_id=stack.workspace.id)
    assert brief is not None
    assert (brief.lineage_id, brief.version) == (outcome.lineage_id, 1)
    assert brief.goal_id == outcome.goal_id
    assert brief.goal_revision == 1
    assert brief.goal_owner_agent_id == goal.agent_id
    assert brief.workspace_id == stack.workspace.id
    assert brief.project_id == str(stack.root.project_id)
    assert brief.created_by == _USER
    assert brief.success_interpretation == "Teach it"
    assert brief.change_note.startswith("interview video_brief (7 turns)")
    assert "deadline, voice, claims, mode" in brief.change_note
    assert brief.artifact_requests[0].requirements[0] == "keep the intro under three seconds"

    # Provenance: the commit record keeps the whole draft, sources included.
    record = _get_record(commit_key(_USER, stack.workspace.id, _final_draft()))
    assert record is not None and record["status"] == "committed"
    kept = record["draft"]
    assert kept["sources"]["subject"] == "user"
    assert kept["sources"]["source"] == "record"
    assert kept["sources"]["deadline"] == "assumed"
    assert kept["assumed"] == ["deadline", "voice", "claims", "mode"]
    assert kept["notes"] == ["keep the intro under three seconds"]
    assert record["project_id"] == str(stack.root.project_id)
    assert record["agent_id"] == goal.agent_id


async def test_restart_reads_back_the_same_ids_and_provenance(stack) -> None:
    """AC-1 read-back: every store re-opened, same ids, same content."""
    outcome = await _commit(stack, _final_draft())
    first_brief = await stack.brief_store.get(outcome.brief_id, workspace_id=stack.workspace.id)

    restarted = await stack.restart_durable()
    try:
        goal = await restarted.fresh.goal_reader.get_goal(outcome.goal_id, principal_id=_USER)
        assert goal.current_revision == 1
        revisions = await restarted.fresh.goal_reader.list_goal_revisions(
            goal.goal_id, principal_id=_USER
        )
        assert len(revisions) == 1
        assert revisions[0].desired_state == "the grouting haze fix — Teach it"

        brief = await restarted.fresh.brief_store.get(
            outcome.brief_id, workspace_id=stack.workspace.id
        )
        assert brief is not None
        assert brief.model_dump(mode="json") == first_brief.model_dump(mode="json")
        assert brief.goal_id == outcome.goal_id
        assert brief.goal_revision == 1
    finally:
        await restarted.pool.close()
        await restarted.engine.dispose()


# ---------------------------------------------------------------------------
# AC-2: unconfirmed / incomplete intake writes nothing
# ---------------------------------------------------------------------------


async def test_unconfirmed_draft_is_refused_with_nothing_written(stack) -> None:
    from services.brief_commit import CommitRejected

    with pytest.raises(CommitRejected):
        await _commit(stack, _final_draft(), confirmed=False)
    assert await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER) == []
    rows = await _brief_rows(stack)
    assert rows == []


async def test_incomplete_draft_is_refused_at_the_boundary(stack) -> None:
    """The boundary re-runs the gate; it does not trust the chat layer's."""
    from services.brief_commit import CommitRejected

    draft = _final_draft()
    del draft["fields"]["subject"]
    with pytest.raises(CommitRejected, match="subject"):
        await _commit(stack, draft)
    draft = _final_draft(script="mystery_script")
    with pytest.raises(CommitRejected, match="unknown brief script"):
        await _commit(stack, draft)
    assert await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER) == []
    assert await _brief_rows(stack) == []


async def _brief_rows(stack: Any) -> list[tuple[str, int]]:
    from sqlalchemy import text

    async with stack.server.factory() as session:
        rows = await session.execute(
            text(
                "SELECT brief_id, version FROM design_creative_briefs "
                "WHERE workspace_id = :w ORDER BY version"
            ),
            {"w": stack.workspace.id},
        )
        return [(str(r[0]), int(r[1])) for r in rows.fetchall()]


# ---------------------------------------------------------------------------
# AC-3: replay and concurrency return the one result
# ---------------------------------------------------------------------------


async def test_replayed_confirmation_returns_the_existing_result(stack) -> None:
    first = await _commit(stack, _final_draft())
    assert first.status == "committed"

    replay = await _commit(stack, _final_draft())
    assert replay.status == "already_committed"
    assert (
        replay.goal_id,
        replay.goal_revision,
        replay.brief_id,
        replay.lineage_id,
        replay.brief_version,
    ) == (
        first.goal_id,
        first.goal_revision,
        first.brief_id,
        first.lineage_id,
        first.brief_version,
    )

    goals = await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER)
    assert [g.goal_id for g in goals] == [first.goal_id]
    assert await _brief_rows(stack) == [(first.brief_id, 1)]


async def test_concurrent_identical_commits_produce_one_pair(stack) -> None:
    draft = _final_draft()
    first, second = await asyncio.gather(
        _commit(stack, draft, takeover_after=5.0),
        _commit(stack, draft, takeover_after=5.0),
    )
    statuses = {first.status, second.status}
    assert statuses <= {"committed", "already_committed"}, (first, second)
    assert "committed" in statuses
    assert {first.goal_id, second.goal_id} == {first.goal_id}
    assert {first.brief_id, second.brief_id} == {first.brief_id}

    goals = await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER)
    assert len(goals) == 1
    assert await _brief_rows(stack) == [(first.brief_id, 1)]


# ---------------------------------------------------------------------------
# AC-4: crash recovery at every boundary
# ---------------------------------------------------------------------------


class _FailOnceGoalReader:
    """A goal seam whose `create_goal` fails the first call, then delegates —
    the crash between the brief write and the Goal write."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.failed = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def create_goal(self, *args: Any, **kwargs: Any) -> Any:
        if not self.failed:
            self.failed = True
            raise ConnectionError("forced crash between the writes")
        return await self._inner.create_goal(*args, **kwargs)


class _FailFirstBriefCreate:
    """A brief store whose `create` fails once — the crash before either
    durable write lands."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.failed = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def create(self, brief: Any) -> Any:
        if not self.failed:
            self.failed = True
            raise ConnectionError("forced crash before the first write")
        return await self._inner.create(brief)


async def test_crash_before_either_write_recovers_deterministically(stack) -> None:
    from services.brief_commit import _get_record, commit_key, recover_pending_commits

    flaky = _FailFirstBriefCreate(stack.brief_store)
    await _commit(stack, _final_draft(), brief_store=flaky)
    assert flaky.failed
    assert await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER) == []
    assert await _brief_rows(stack) == [], "nothing durable before the failure"

    recovered = await recover_pending_commits(
        goal_reader=stack.goal_reader,
        project_store=stack.projects,
        brief_store=stack.brief_store,
    )
    assert [o.status for o in recovered] == ["committed"]
    resumed = recovered[0]
    # The resumed pair is exactly the identity the durable record carried.
    record = _get_record(commit_key(_USER, stack.workspace.id, _final_draft()))
    assert resumed.goal_id == record["goal_id"]
    assert resumed.brief_id == record["brief_id"]
    goals = await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER)
    assert [g.goal_id for g in goals] == [resumed.goal_id]
    assert await _brief_rows(stack) == [(resumed.brief_id, 1)]


async def test_crash_between_writes_completes_the_pair_with_the_same_ids(stack) -> None:
    from services.brief_commit import (
        _get_record,
        commit_key,
        list_commitments,
        recover_pending_commits,
    )

    flaky = _FailOnceGoalReader(stack.goal_reader)
    draft = _final_draft()
    outcome = await _commit(stack, draft, goal_reader=flaky)
    assert outcome.status == "failed"

    # The brief exists (brief-first), the Goal does not, and the record
    # carries the pre-minted identities recovery will resume.
    assert len(await _brief_rows(stack)) == 1
    assert await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER) == []
    record = _get_record(commit_key(_USER, stack.workspace.id, draft))
    assert record["stage"] == "brief_created", "the durable record kept the progress"
    assert record["status"] == "failed"
    stranded_brief_id = record["brief_id"]
    stranded_goal_id = record["goal_id"]

    recovered = await recover_pending_commits(
        goal_reader=stack.goal_reader,
        project_store=stack.projects,
        brief_store=stack.brief_store,
    )
    assert [o.status for o in recovered] == ["committed"]
    assert recovered[0].goal_id == stranded_goal_id
    assert recovered[0].brief_id == stranded_brief_id
    assert len(await _brief_rows(stack)) == 1, "no duplicate brief version"
    goal = await stack.goal_reader.get_goal(stranded_goal_id, principal_id=_USER)
    assert goal.current_revision == 1

    # Reconciliation-facing truth: only complete pairs are named committed.
    commitments = await list_commitments(_USER, stack.workspace.id)
    assert [c["status"] for c in commitments] == ["committed"]
    assert commitments[0]["goal_id"] == stranded_goal_id


async def test_recovery_sweep_leaves_committed_records_alone(stack) -> None:
    from services.brief_commit import recover_pending_commits

    first = await _commit(stack, _final_draft())
    recovered = await recover_pending_commits(
        goal_reader=stack.goal_reader,
        project_store=stack.projects,
        brief_store=stack.brief_store,
    )
    assert recovered == []
    goals = await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER)
    assert [g.goal_id for g in goals] == [first.goal_id]


async def test_a_recovered_commit_returns_its_result_on_replay(stack) -> None:
    """The confirmed turn that arrives after recovery gets the same ids back
    (the response was lost once; it is not minted twice)."""
    from services.brief_commit import _get_record, commit_key, recover_pending_commits

    flaky = _FailOnceGoalReader(stack.goal_reader)
    draft = _final_draft()
    await _commit(stack, draft, goal_reader=flaky)
    recovered = await recover_pending_commits(
        goal_reader=stack.goal_reader,
        project_store=stack.projects,
        brief_store=stack.brief_store,
    )
    assert recovered and recovered[0].status == "committed"

    replay = await _commit(stack, draft)
    assert replay.status == "already_committed"
    assert replay.goal_id == recovered[0].goal_id
    assert replay.brief_id == recovered[0].brief_id
    record = _get_record(commit_key(_USER, stack.workspace.id, draft))
    assert record["attempts"] == 2, "the replay did not re-drive the protocol"


# ---------------------------------------------------------------------------
# AC-5: authorization and foreign references
# ---------------------------------------------------------------------------


async def test_a_non_owner_member_cannot_commit_and_cannot_read(stack) -> None:
    from services import workspace_authority
    from services.brief_commit import (
        CommitNotAuthorized,
        commit_draft,
        list_commitments,
    )

    await workspace_authority.set_member(
        stack.workspace.id, user_id=_OTHER, role="editor", principal_id=_USER
    )
    draft = _final_draft()
    with pytest.raises(CommitNotAuthorized):
        await commit_draft(
            _OTHER,
            stack.workspace.id,
            draft,
            confirmed=True,
            goal_reader=stack.goal_reader,
            project_store=stack.projects,
            brief_store=stack.brief_store,
        )
    assert await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER) == []
    assert await _brief_rows(stack) == []

    # A member may list only their own commitments — which are empty, since
    # their commits are refused — and a non-member's read is refused too.
    assert await list_commitments(_OTHER, stack.workspace.id) == []
    with pytest.raises(CommitNotAuthorized):
        await list_commitments(_OTHER, "workspace-that-does-not-exist")


async def test_a_stranger_cannot_read_the_committed_goal(stack) -> None:
    from services.brief_commit import list_commitments

    from maistro.goals import GoalNotVisible

    outcome = await _commit(stack, _final_draft())
    with pytest.raises(GoalNotVisible):
        await stack.goal_reader.get_goal(outcome.goal_id, principal_id=_OTHER)
    commitments = await list_commitments(_USER, stack.workspace.id)
    assert len(commitments) == 1
    assert commitments[0]["goal_id"] == outcome.goal_id


async def test_intake_identities_are_server_resolved(stack) -> None:
    """The caller supplies no Project, agent, Goal or persona identity: they
    are resolved on the server from the canonical Workspace (#1823 scope 1)."""
    from services.brief_commit import _get_record, commit_key

    outcome = await _commit(stack, _final_draft())
    record = _get_record(commit_key(_USER, stack.workspace.id, _final_draft()))
    assert record["project_id"] == str(stack.root.project_id)
    assert record["agent_id"].startswith("workspace-agent:")
    assert record["goal_id"] == outcome.goal_id  # minted server-side

    brief = await stack.brief_store.get(outcome.brief_id, workspace_id=stack.workspace.id)
    assert brief.persona.ref_id == stack.workspace.persona_template_id
    assert brief.persona.workspace_id == stack.workspace.id
    assert brief.design_system.ref_id == stack.workspace.theme_id


async def test_a_revision_cannot_target_a_foreign_goal(stack) -> None:
    from services import workspace_authority
    from services.brief_commit import commit_draft

    first = await _commit(stack, _final_draft())

    other_workspace = await workspace_authority.create_workspace(
        creator_user_id=_OTHER,
        name=f"Brief Commit foreign {uuid.uuid4().hex[:8]}",
        persona_template_id="content_creator",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    foreign_projects = stack.projects.__class__()
    foreign_root = await foreign_projects.create_root(other_workspace.id)
    foreign_session_factory = stack.server.factory
    foreign_brief_store = stack.brief_store.__class__(session_factory=foreign_session_factory)
    from sqlalchemy import text

    async with foreign_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO canonical_projects (project_id, workspace_id, is_root, "
                "payload) VALUES (:p, :w, TRUE, CAST(:payload AS jsonb)) "
                "ON CONFLICT (project_id) DO NOTHING"
            ),
            {
                "p": str(foreign_root.project_id),
                "w": other_workspace.id,
                "payload": '{"name": "brief-commit-foreign"}',
            },
        )
        await session.commit()

    try:
        outcome = await commit_draft(
            _OTHER,
            other_workspace.id,
            _final_draft(),
            confirmed=True,
            revises={
                "goal_id": first.goal_id,
                "expected_revision": 1,
                "lineage_id": first.lineage_id,
                "revise_goal": True,
            },
            goal_reader=stack.goal_reader,
            project_store=foreign_projects,
            brief_store=foreign_brief_store,
        )
        assert outcome.status == "failed"
        assert "GoalNotVisible" in (outcome.reason or "")
        # The foreign attempt wrote nothing to the target Goal.
        revisions = await stack.goal_reader.list_goal_revisions(first.goal_id, principal_id=_USER)
        assert [r.revision for r in revisions] == [1]
        foreign_rows = await _brief_rows_for(foreign_session_factory, other_workspace.id)
        assert foreign_rows == []
    finally:
        async with foreign_session_factory() as session:
            await session.execute(
                text("DELETE FROM canonical_projects WHERE workspace_id = :w"),
                {"w": other_workspace.id},
            )
            await session.commit()


async def _brief_rows_for(factory: Any, workspace_id: str) -> list[tuple[str, int]]:
    from sqlalchemy import text

    async with factory() as session:
        rows = await session.execute(
            text(
                "SELECT brief_id, version FROM design_creative_briefs "
                "WHERE workspace_id = :w ORDER BY version"
            ),
            {"w": workspace_id},
        )
        return [(str(r[0]), int(r[1])) for r in rows.fetchall()]


# ---------------------------------------------------------------------------
# AC-6: canonical enumeration after the chat closed and the service restarted
# ---------------------------------------------------------------------------


async def test_goal_enumeration_exposes_the_committed_goal_after_restart(stack) -> None:
    from services.brief_commit import list_commitments

    outcome = await _commit(stack, _final_draft())
    restarted = await stack.restart_durable()
    try:
        goals = await restarted.fresh.goal_reader.list_goals(stack.workspace.id, principal_id=_USER)
        assert [g.goal_id for g in goals] == [outcome.goal_id]
    finally:
        await restarted.pool.close()
        await restarted.engine.dispose()

    commitments = await list_commitments(_USER, stack.workspace.id)
    assert commitments[0]["status"] == "committed"
    assert commitments[0]["goal_id"] == outcome.goal_id
    assert commitments[0]["brief_id"] == outcome.brief_id
    assert commitments[0]["brief_version"] == 1


# ---------------------------------------------------------------------------
# AC-7: revisions and creative-only changes
# ---------------------------------------------------------------------------


async def test_revising_the_desired_outcome_appends_revision_and_brief_version(
    stack,
) -> None:
    from services.brief_commit import commit_draft

    first = await _commit(stack, _final_draft())
    revised = _final_draft(fields={**_final_draft()["fields"], "subject": "the wipe tutorial"})
    outcome = await commit_draft(
        _USER,
        stack.workspace.id,
        revised,
        confirmed=True,
        revises={
            "goal_id": first.goal_id,
            "expected_revision": 1,
            "lineage_id": first.lineage_id,
            "revise_goal": True,
        },
        goal_reader=stack.goal_reader,
        project_store=stack.projects,
        brief_store=stack.brief_store,
    )
    assert outcome.status == "committed", outcome
    assert outcome.goal_revision == 2
    assert outcome.brief_version == 2
    assert outcome.goal_id == first.goal_id

    goal = await stack.goal_reader.get_goal(first.goal_id, principal_id=_USER)
    assert goal.current_revision == 2
    revisions = await stack.goal_reader.list_goal_revisions(first.goal_id, principal_id=_USER)
    assert [r.revision for r in revisions] == [1, 2]
    assert revisions[0].desired_state == "the grouting haze fix — Teach it"
    assert revisions[1].desired_state == "the wipe tutorial — Teach it"

    versions = await stack.brief_store.list_versions(
        first.lineage_id, workspace_id=stack.workspace.id
    )
    assert [b.version for b in versions] == [1, 2]
    assert versions[0].goal_revision == 1
    assert versions[1].goal_revision == 2
    assert versions[1].supersedes_brief_id == versions[0].brief_id
    assert await _brief_rows(stack) == [
        (versions[0].brief_id, 1),
        (versions[1].brief_id, 2),
    ]


async def test_a_stale_revision_hand_loses_cleanly_and_stays_retryable(stack) -> None:
    from services.brief_commit import commit_draft

    first = await _commit(stack, _final_draft())
    revised = _final_draft(fields={**_final_draft()["fields"], "subject": "the wipe tutorial"})
    outcome = await commit_draft(
        _USER,
        stack.workspace.id,
        revised,
        confirmed=True,
        revises={
            "goal_id": first.goal_id,
            "expected_revision": 1,
            "lineage_id": first.lineage_id,
            "revise_goal": True,
        },
        goal_reader=stack.goal_reader,
        project_store=stack.projects,
        brief_store=stack.brief_store,
    )
    assert outcome.status == "committed"
    stale = await commit_draft(
        _USER,
        stack.workspace.id,
        _final_draft(fields={**_final_draft()["fields"], "subject": "third shape"}),
        confirmed=True,
        revises={
            "goal_id": first.goal_id,
            "expected_revision": 1,  # stale: the Goal is at 2 now
            "lineage_id": first.lineage_id,
            "revise_goal": True,
        },
        goal_reader=stack.goal_reader,
        project_store=stack.projects,
        brief_store=stack.brief_store,
    )
    assert stale.status == "failed", "a stale compare-and-set must not silently win"
    goal = await stack.goal_reader.get_goal(first.goal_id, principal_id=_USER)
    assert goal.current_revision == 2
    versions = await stack.brief_store.list_versions(
        first.lineage_id, workspace_id=stack.workspace.id
    )
    assert [b.version for b in versions] == [1, 2]


async def test_a_revised_outcome_read_back_after_a_restart(stack) -> None:
    """AC-7 + AC-1 together: the revision chain and the version chain survive
    a restart with their exact bindings intact."""
    from services.brief_commit import commit_draft

    first = await _commit(stack, _final_draft())
    revised = _final_draft(fields={**_final_draft()["fields"], "subject": "the wipe tutorial"})
    second = await commit_draft(
        _USER,
        stack.workspace.id,
        revised,
        confirmed=True,
        revises={
            "goal_id": first.goal_id,
            "expected_revision": 1,
            "lineage_id": first.lineage_id,
            "revise_goal": True,
        },
        goal_reader=stack.goal_reader,
        project_store=stack.projects,
        brief_store=stack.brief_store,
    )
    assert second.status == "committed"

    restarted = await stack.restart_durable()
    try:
        revisions = await restarted.fresh.goal_reader.list_goal_revisions(
            first.goal_id, principal_id=_USER
        )
        assert [r.revision for r in revisions] == [1, 2]
        versions = await restarted.fresh.brief_store.list_versions(
            first.lineage_id, workspace_id=stack.workspace.id
        )
        assert [(b.version, b.goal_revision) for b in versions] == [(1, 1), (2, 2)]
        assert versions[1].supersedes_brief_id == versions[0].brief_id
    finally:
        await restarted.pool.close()
        await restarted.engine.dispose()


async def test_creative_only_change_mints_a_brief_version_without_a_goal_write(
    stack,
) -> None:
    from services.brief_commit import commit_draft

    first = await _commit(stack, _final_draft())
    creative = _final_draft(notes=["keep the intro under three seconds", "no music"])
    outcome = await commit_draft(
        _USER,
        stack.workspace.id,
        creative,
        confirmed=True,
        revises={
            "goal_id": first.goal_id,
            "expected_revision": 1,
            "lineage_id": first.lineage_id,
            "revise_goal": False,
        },
        goal_reader=stack.goal_reader,
        project_store=stack.projects,
        brief_store=stack.brief_store,
    )
    assert outcome.status == "committed", outcome
    assert outcome.goal_revision == 1, "the Goal revision did not move"
    assert outcome.brief_version == 2

    goal = await stack.goal_reader.get_goal(first.goal_id, principal_id=_USER)
    assert goal.current_revision == 1
    revisions = await stack.goal_reader.list_goal_revisions(first.goal_id, principal_id=_USER)
    assert len(revisions) == 1, "creative-only changes append no Goal revision"
    brief = await stack.brief_store.get(outcome.brief_id, workspace_id=stack.workspace.id)
    assert brief.goal_revision == 1
    assert brief.version == 2
    # Historical provenance untouched: v1 still names what v1 named.
    old = await stack.brief_store.get(first.brief_id, workspace_id=stack.workspace.id)
    assert old.version == 1
    assert old.artifact_requests[0].requirements == (
        "keep the intro under three seconds",
        "A fresh shoot; the specialist writes a shot list first",
    )


# ---------------------------------------------------------------------------
# AC-8: explicit recoverable limitation
# ---------------------------------------------------------------------------


async def test_unavailable_prerequisites_are_the_explicit_limitation(
    owned_workspace,
) -> None:
    """With the Goal seam unreachable, the boundary refuses loudly, writes
    nothing, and the same confirmation stays retryable once it is back."""
    from services.brief_commit import _get_record, commit_draft, commit_key

    class _NoRuntime:
        goal_reader = None
        project_scope_store = None

    import services.engine as engine_mod

    saved = engine_mod._singleton
    engine_mod._singleton = _NoRuntime()
    try:
        outcome = await commit_draft(
            _USER,
            owned_workspace.id,
            _final_draft(),
            confirmed=True,
            project_store=object(),  # a project store is not enough on its own
            brief_store=object(),
        )
    finally:
        engine_mod._singleton = saved
    assert outcome.status == "unavailable"
    assert outcome.reason and "unavailable" in outcome.reason
    record = _get_record(commit_key(_USER, owned_workspace.id, _final_draft()))
    assert record is None, "no commit identity was recorded for a refused commit"


async def test_the_same_confirmation_is_retryable_after_the_limitation_clears(
    stack,
) -> None:
    """A commit that failed for lack of a usable seam succeeds, unchanged,
    once the seam is back — same draft, same key, one pair."""
    from services.brief_commit import recover_pending_commits

    class _BrokenSeam:
        def __getattr__(self, name: str) -> Any:
            raise AttributeError("forced prerequisite outage")

    outcome = await _commit(stack, _final_draft(), goal_reader=_BrokenSeam())
    assert outcome.status in ("failed", "unavailable")

    recovered = await recover_pending_commits(
        goal_reader=stack.goal_reader,
        project_store=stack.projects,
        brief_store=stack.brief_store,
    )
    assert recovered and recovered[0].status == "committed"
    goals = await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER)
    assert len(goals) == 1


# ---------------------------------------------------------------------------
# Truthful copy and payload shape (AC-8) — the chat layer's contract
# ---------------------------------------------------------------------------


def test_written_payload_is_empty_until_the_commit_is_durable() -> None:
    from services.brief_chat import BriefTurn

    pending = BriefTurn(
        text="...",
        event="failed",
        brief={"interview": None, "summary": None, "question": None},
        draft={"fields": {}, "assumed": [], "notes": []},
        commit={"status": "failed", "reason": "boom"},
    )
    assert pending.payload()["written"] == []
    assert "commit" in pending.payload()

    durable = BriefTurn(
        text="...",
        event="committed",
        brief={"interview": None, "summary": None, "question": None},
        draft={"fields": {}, "assumed": [], "notes": []},
        commit={
            "status": "committed",
            "goal_id": "g1",
            "goal_revision": 1,
            "brief_id": "b1",
            "lineage_id": "l1",
            "brief_version": 1,
        },
    )
    payload = durable.payload()
    assert payload["written"] == [
        {"kind": "goal", "goal_id": "g1", "revision": 1},
        {
            "kind": "creative_brief",
            "brief_id": "b1",
            "lineage_id": "l1",
            "version": 1,
        },
    ]
    already = BriefTurn(
        text="...",
        event="committed",
        brief={"interview": None, "summary": None, "question": None},
        draft={"fields": {}, "assumed": [], "notes": []},
        commit={
            "status": "already_committed",
            "goal_id": "g1",
            "goal_revision": 1,
            "brief_id": "b1",
            "lineage_id": "l1",
            "brief_version": 1,
        },
    )
    assert already.payload()["written"] == payload["written"]


def test_commit_key_is_content_addressed_and_principal_scoped() -> None:
    from services.brief_commit import commit_key

    draft = _final_draft()
    base = commit_key(_USER, "ws-1", draft)
    assert base == commit_key(_USER, "ws-1", dict(draft))
    assert base != commit_key(
        _USER, "ws-1", _final_draft(fields={**draft["fields"], "subject": "x"})
    )
    assert base != commit_key("someone-else", "ws-1", draft)
    assert base != commit_key(_USER, "ws-2", draft)

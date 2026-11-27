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
        completes the pair instead of stranding a half intake. A caught,
        reported failure is the principal's to retry: the startup sweep
        never auto-drives a ``failed`` record, so a draft cancelled or
        replaced after a failure cannot be committed by a restart;
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


async def _mirror_workspace_identity(factory: Any, workspace_id: str, name: str) -> None:
    """Mirror one canonical Workspace identity into the shared database.

    Migration 071 (#37) enforces `canonical_projects` -> `canonical_workspaces`
    (RESTRICT) on new writes, so a Project mirror is refused until the
    Workspace identity the in-process canonical authority owns is durable in
    the same database. Idempotent: `ON CONFLICT DO NOTHING`.
    """
    from sqlalchemy import text

    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO canonical_workspaces "
                "(workspace_id, name, created_at, updated_at, payload) "
                "VALUES (:w, :name, NOW(), NOW(), '{}'::jsonb) "
                "ON CONFLICT (workspace_id) DO NOTHING"
            ),
            {"w": workspace_id, "name": name},
        )
        await session.commit()


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

    # The Project mirror below is refused until the Workspace identity the
    # in-process canonical authority owns is durable in the same database
    # (#37 fence). No second Root row is created:
    # `ix_canonical_projects_one_root` allows one root per Workspace, and the
    # mirror below already provides it.
    await _mirror_workspace_identity(_pg_server.factory, owned_workspace.id, owned_workspace.name)

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
            # The mirrored identity goes last: the Projects RESTRICT above is
            # only satisfied once their rows are gone (memberships and
            # personas cascade; canonical_projects does not).
            await session.execute(
                text("DELETE FROM canonical_workspaces WHERE workspace_id = :w"), {"w": ws}
            )
            await session.commit()
        # The per-test Workspace's canonical identity is mirrored into the
        # shared database for the #37 fence and removed with everything else.


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
    assert brief.supervision_constraints == (
        "source: A fresh shoot; the specialist writes a shot list first",
        "control mode: Collaborative: the specialist drafts, you mark up, nothing publishes",
    )
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


class _SlowGoalCreate:
    """A goal seam whose ``create_goal`` yields long enough that a follower's
    takeover window expires while the driver's insert is still in flight —
    the mid-protocol takeover the staleness heuristic cannot tell apart from
    process death."""

    def __init__(self, inner: Any, delay: float) -> None:
        self._inner = inner
        self._delay = delay

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def create_goal(self, *args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(self._delay)
        return await self._inner.create_goal(*args, **kwargs)


class _SlowBriefCreate:
    """A brief store whose ``create`` yields past a follower's takeover
    window before it writes."""

    def __init__(self, inner: Any, delay: float) -> None:
        self._inner = inner
        self._delay = delay

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def create(self, brief: Any) -> Any:
        await asyncio.sleep(self._delay)
        return await self._inner.create(brief)


class _SlowAppendRevision:
    """A goal seam whose ``append_revision`` yields past a follower's takeover
    window before it compares-and-sets."""

    def __init__(self, inner: Any, delay: float) -> None:
        self._inner = inner
        self._delay = delay

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def append_revision(self, *args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(self._delay)
        return await self._inner.append_revision(*args, **kwargs)


async def test_a_mid_protocol_takeover_at_the_goal_insert_still_produces_one_pair(
    stack,
) -> None:
    """The takeover heuristic resolves 'slow driver' and 'dead driver' the
    same way, so a follower can resume a record whose driver is still
    mid-write. Both then race the same pre-minted goal insert; the loser of
    the unique constraint must adopt the winner's row and converge on the
    one pair, not fail the logical commit (the takeover costs a
    duplicate-skip check, not a failed commit)."""
    draft = _final_draft(subject="takeover at the goal insert")
    driver = _commit(
        stack,
        draft,
        goal_reader=_SlowGoalCreate(stack.goal_reader, 1.0),
        takeover_after=0.2,
    )
    follower = _commit(stack, draft, takeover_after=0.2)
    first, second = await asyncio.gather(driver, follower)
    statuses = {first.status, second.status}
    assert statuses <= {"committed", "already_committed"}, (first, second)
    assert "committed" in statuses
    assert {first.goal_id, second.goal_id} == {first.goal_id}
    assert {first.brief_id, second.brief_id} == {first.brief_id}
    goals = await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER)
    assert len(goals) == 1
    assert await _brief_rows(stack) == [(first.brief_id, 1)]


async def test_a_mid_protocol_takeover_at_the_brief_insert_still_produces_one_pair(
    stack,
) -> None:
    """The brief-first write has the same window: a follower that takes the
    record over while the driver's brief insert is in flight writes the twin
    row first, and the driver's insert loses the unique constraint. The
    loser adopts the winner's brief; one pair, one logical commit."""
    draft = _final_draft(subject="takeover at the brief insert")
    driver = _commit(
        stack,
        draft,
        brief_store=_SlowBriefCreate(stack.brief_store, 1.0),
        takeover_after=0.2,
    )
    follower = _commit(stack, draft, takeover_after=0.2)
    first, second = await asyncio.gather(driver, follower)
    statuses = {first.status, second.status}
    assert statuses <= {"committed", "already_committed"}, (first, second)
    assert "committed" in statuses
    assert {first.goal_id, second.goal_id} == {first.goal_id}
    assert {first.brief_id, second.brief_id} == {first.brief_id}
    goals = await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER)
    assert len(goals) == 1
    assert await _brief_rows(stack) == [(first.brief_id, 1)]


async def test_a_mid_protocol_takeover_at_the_revision_append_converges_on_one_tail(
    stack,
) -> None:
    """The same takeover race at AC-7's compare-and-set: the twin append
    wins the tail this commit was about to mint. The loser re-reads and
    adopts that tail only when it is exactly the successor its own CAS would
    have produced — a stale writer still loses cleanly, a twin converges."""
    from services.brief_commit import commit_draft

    first = await _commit(stack, _final_draft(subject="takeover at the append"))
    revised = _final_draft(fields={**_final_draft()["fields"], "subject": "the wipe tutorial"})
    revises = {
        "goal_id": first.goal_id,
        "expected_revision": 1,
        "lineage_id": first.lineage_id,
        "revise_goal": True,
    }
    driver = commit_draft(
        _USER,
        stack.workspace.id,
        revised,
        confirmed=True,
        revises=revises,
        goal_reader=_SlowAppendRevision(stack.goal_reader, 1.0),
        project_store=stack.projects,
        brief_store=stack.brief_store,
        takeover_after=0.2,
    )
    follower = commit_draft(
        _USER,
        stack.workspace.id,
        revised,
        confirmed=True,
        revises=dict(revises),
        goal_reader=stack.goal_reader,
        project_store=stack.projects,
        brief_store=stack.brief_store,
        takeover_after=0.2,
    )
    outcomes = await asyncio.gather(driver, follower)
    assert {o.status for o in outcomes} <= {"committed", "already_committed"}, outcomes
    assert {o.goal_revision for o in outcomes} == {2}, outcomes
    assert {o.brief_version for o in outcomes} == {2}, outcomes

    goal = await stack.goal_reader.get_goal(first.goal_id, principal_id=_USER)
    assert goal.current_revision == 2
    revisions = await stack.goal_reader.list_goal_revisions(first.goal_id, principal_id=_USER)
    assert [r.revision for r in revisions] == [1, 2]
    versions = await stack.brief_store.list_versions(
        first.lineage_id, workspace_id=stack.workspace.id
    )
    assert [v.version for v in versions] == [1, 2]


class _ForeignVersionWinner:
    """A brief store whose ``create`` always loses the version race to a
    foreign writer: the unique conflict fires, but no row exists under THIS
    record's pre-minted brief id — a genuine conflict, not a twin to adopt."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def create(self, brief: Any) -> Any:
        from maistro_design.brief import BriefVersionConflictError

        raise BriefVersionConflictError(
            f"creative brief lineage {brief.lineage_id!r} already has version {brief.version}"
        )


async def test_a_foreign_version_conflict_fails_the_commit_and_stays_retryable(
    stack,
) -> None:
    """A version conflict that is not our twin (the conflicting row carries
    a different brief id, so the identity re-read misses) is a genuine
    failure: the record reports it, nothing was written, and the same
    confirmation safely retries the same pre-minted pair."""
    from services.brief_commit import _get_record, commit_key

    draft = _final_draft(subject="foreign version winner")
    outcome = await _commit(stack, draft, brief_store=_ForeignVersionWinner(stack.brief_store))
    assert outcome.status == "failed"
    assert await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER) == []
    assert await _brief_rows(stack) == [], "the conflict wrote nothing"

    retry = await _commit(stack, draft)
    assert retry.status == "committed", retry
    record = _get_record(commit_key(_USER, stack.workspace.id, draft))
    assert (retry.goal_id, retry.brief_id) == (record["goal_id"], record["brief_id"])
    assert await _brief_rows(stack) == [(retry.brief_id, 1)]


async def test_a_foreign_version_conflict_at_a_revision_keeps_the_lineage_retryable(
    stack,
) -> None:
    """The same distinction at AC-7: the append is canonical the moment it
    lands, so a foreign version conflict on the brief half leaves the Goal
    revised, the brief stranded — and the record retryable into exactly the
    recorded pair."""
    from services.brief_commit import commit_draft

    first = await _commit(stack, _final_draft(subject="foreign conflict revise"))
    revised = _final_draft(fields={**_final_draft()["fields"], "subject": "the wipe tutorial"})
    revises = {
        "goal_id": first.goal_id,
        "expected_revision": 1,
        "lineage_id": first.lineage_id,
        "revise_goal": True,
    }

    async def _revise(brief_store: Any) -> Any:
        return await commit_draft(
            _USER,
            stack.workspace.id,
            revised,
            confirmed=True,
            revises=dict(revises),
            goal_reader=stack.goal_reader,
            project_store=stack.projects,
            brief_store=brief_store,
        )

    outcome = await _revise(_ForeignVersionWinner(stack.brief_store))
    assert outcome.status == "failed"
    goal = await stack.goal_reader.get_goal(first.goal_id, principal_id=_USER)
    assert goal.current_revision == 2, "the append is canonical the moment it lands"
    versions = await stack.brief_store.list_versions(
        first.lineage_id, workspace_id=stack.workspace.id
    )
    assert [v.version for v in versions] == [1], "the conflicting brief wrote nothing"

    resumed = await _revise(stack.brief_store)
    assert resumed.status == "committed", resumed
    assert (resumed.goal_revision, resumed.brief_version) == (2, 2)
    versions = await stack.brief_store.list_versions(
        first.lineage_id, workspace_id=stack.workspace.id
    )
    assert [v.version for v in versions] == [1, 2]


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


class _DieBeforeFirstWrite:
    """A brief store that 'kills the process' before any durable write —
    the record is left on its live-driver ``pending`` status."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def create(self, brief: Any) -> Any:
        raise _ProcessDeath("forced termination before the first write")


async def test_crash_before_either_write_recovers_deterministically(stack) -> None:
    from services.brief_commit import _get_record, commit_key, recover_pending_commits

    dying = _DieBeforeFirstWrite(stack.brief_store)
    draft = _final_draft()
    with pytest.raises(_ProcessDeath):
        await _commit(stack, draft, brief_store=dying)
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
    record = _get_record(commit_key(_USER, stack.workspace.id, draft))
    assert resumed.goal_id == record["goal_id"]
    assert resumed.brief_id == record["brief_id"]
    goals = await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER)
    assert [g.goal_id for g in goals] == [resumed.goal_id]
    assert await _brief_rows(stack) == [(resumed.brief_id, 1)]


async def test_a_failed_attempt_is_never_committed_by_the_startup_sweep(stack) -> None:
    """A caught, reported failure belongs to its principal: after it, the
    user may say 'never mind' or edit the draft into a replacement — neither
    abandoned shape may be completed by startup recovery (a restart must not
    turn a cancelled draft into a Goal). Only re-confirming the exact failed
    draft resumes the recorded identities, adopting the stranded brief."""
    from services.brief_commit import _get_record, commit_key, recover_pending_commits

    flaky = _FailOnceGoalReader(stack.goal_reader)
    draft = _final_draft()
    outcome = await _commit(stack, draft, goal_reader=flaky)
    assert outcome.status == "failed"
    key = commit_key(_USER, stack.workspace.id, draft)
    assert _get_record(key)["status"] == "failed"
    assert len(await _brief_rows(stack)) == 1, "the brief-first write stranded"
    assert await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER) == []

    # Startup recovery, run twice, resurrects nothing.
    for _ in range(2):
        assert (
            await recover_pending_commits(
                goal_reader=stack.goal_reader,
                project_store=stack.projects,
                brief_store=stack.brief_store,
            )
            == []
        )
    assert await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER) == []
    assert len(await _brief_rows(stack)) == 1

    # A replacement confirmation (edited draft) commits its own pair, and the
    # sweep still does not resurrect the abandoned draft behind it.
    replacement = _final_draft(fields={**draft["fields"], "channel": "a 60-second vertical reel"})
    second = await _commit(stack, replacement)
    assert second.status == "committed"
    assert (
        await recover_pending_commits(
            goal_reader=stack.goal_reader,
            project_store=stack.projects,
            brief_store=stack.brief_store,
        )
        == []
    )
    goals = await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER)
    assert [g.goal_id for g in goals] == [second.goal_id]

    # Only the explicit re-confirmation of the failed draft completes it —
    # with exactly the identities the record carried (no second Goal, and
    # the stranded brief adopted, not duplicated).
    retry = await _commit(stack, draft)
    assert retry.status == "committed", retry
    record = _get_record(key)
    assert (retry.goal_id, retry.brief_id) == (record["goal_id"], record["brief_id"])
    assert record["attempts"] == 2
    goals = await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER)
    assert {g.goal_id for g in goals} == {second.goal_id, retry.goal_id}
    assert len(await _brief_rows(stack)) == 2, "the stranded brief was adopted"


async def test_a_reported_failure_completes_only_through_its_own_confirmation(
    stack,
) -> None:
    """A caught failure between the writes leaves the record ``failed`` with
    the brief stranded — invisible, since the Goal row does not exist yet.
    The startup sweep must not complete that record (its principal may have
    walked away or said 'never mind'); the *same confirmation* is what safely
    retries it, adopting the stranded brief under the pre-minted goal id."""
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
    # carries the pre-minted identities a retry will resume.
    assert len(await _brief_rows(stack)) == 1
    assert await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER) == []
    record = _get_record(commit_key(_USER, stack.workspace.id, draft))
    assert record["stage"] == "brief_created", "the durable record kept the progress"
    assert record["status"] == "failed"
    stranded_brief_id = record["brief_id"]
    stranded_goal_id = record["goal_id"]

    # Recovery never auto-drives a reported failure: no restart turns this
    # abandoned attempt into a Goal.
    assert (
        await recover_pending_commits(
            goal_reader=stack.goal_reader,
            project_store=stack.projects,
            brief_store=stack.brief_store,
        )
        == []
    )
    assert await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER) == []

    # The principal's own retry — the chat's 'commit it' again — completes
    # the exact recorded pair: the stranded brief is adopted, no duplicate.
    resumed = await _commit(stack, draft)
    assert resumed.status == "committed", resumed
    assert resumed.goal_id == stranded_goal_id
    assert resumed.brief_id == stranded_brief_id
    assert len(await _brief_rows(stack)) == 1, "no duplicate brief version"
    goal = await stack.goal_reader.get_goal(stranded_goal_id, principal_id=_USER)
    assert goal.current_revision == 1

    # Reconciliation-facing truth: only complete pairs are named committed.
    commitments = await list_commitments(_USER, stack.workspace.id)
    assert [c["status"] for c in commitments] == ["committed"]
    assert commitments[0]["goal_id"] == stranded_goal_id


class _ProcessDeath(BaseException):
    """Termination the protocol's ``except Exception`` handler never sees —
    the durable stand-in for a SIGKILL between writes."""


class _DieOnGoalCreate:
    """A goal reader that 'kills the process' minting the Goal."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def create_goal(self, *args: Any, **kwargs: Any) -> Any:
        raise _ProcessDeath("forced termination after brief_created")


class _DieOnBriefCreate:
    """A brief store that 'kills the process' after the Goal write lands."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def create(self, brief: Any) -> Any:
        raise _ProcessDeath("forced termination after the goal write")


async def test_process_death_after_brief_created_is_swept_at_startup(stack) -> None:
    """A kill between the intake writes persists ``brief_created``, a status
    no exception path ever sets; startup recovery must resume it too."""
    from services.brief_commit import _get_record, commit_key, recover_pending_commits

    dying = _DieOnGoalCreate(stack.goal_reader)
    draft = _final_draft()
    with pytest.raises(_ProcessDeath):
        await _commit(stack, draft, goal_reader=dying)

    record = _get_record(commit_key(_USER, stack.workspace.id, draft))
    assert record["status"] == "brief_created"
    assert len(await _brief_rows(stack)) == 1
    assert await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER) == []

    recovered = await recover_pending_commits(
        goal_reader=stack.goal_reader,
        project_store=stack.projects,
        brief_store=stack.brief_store,
    )
    assert [o.status for o in recovered] == ["committed"]
    assert recovered[0].goal_id == record["goal_id"]
    assert recovered[0].brief_id == record["brief_id"]
    goals = await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER)
    assert [g.goal_id for g in goals] == [record["goal_id"]]
    assert await _brief_rows(stack) == [(record["brief_id"], 1)]

    # Reconciliation-facing truth: the recovered pair is named committed, the
    # completed Goal exposed under its pre-minted id.
    from services.brief_commit import list_commitments

    commitments = await list_commitments(_USER, stack.workspace.id)
    assert [c["status"] for c in commitments] == ["committed"]
    assert commitments[0]["goal_id"] == record["goal_id"]


async def test_process_death_after_goal_revised_is_swept_at_startup(stack) -> None:
    """A kill between the revise writes persists ``goal_revised``; recovery
    adopts the appended revision and completes the brief counterpart."""
    from services.brief_commit import commit_draft, recover_pending_commits

    first = await _commit(stack, _final_draft())
    revised = _final_draft(fields={**_final_draft()["fields"], "subject": "the wipe tutorial"})
    with pytest.raises(_ProcessDeath):
        await commit_draft(
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
            brief_store=_DieOnBriefCreate(stack.brief_store),
        )

    recovered = await recover_pending_commits(
        goal_reader=stack.goal_reader,
        project_store=stack.projects,
        brief_store=stack.brief_store,
    )
    assert [o.status for o in recovered] == ["committed"]
    assert recovered[0].goal_id == first.goal_id
    assert recovered[0].goal_revision == 2
    assert recovered[0].brief_version == 2
    revisions = await stack.goal_reader.list_goal_revisions(first.goal_id, principal_id=_USER)
    assert [r.revision for r in revisions] == [1, 2]
    versions = await stack.brief_store.list_versions(
        first.lineage_id, workspace_id=stack.workspace.id
    )
    assert [b.version for b in versions] == [1, 2]


async def test_crashed_append_is_not_adopted_when_only_deadline_differs(stack) -> None:
    """desired_state alone does not identify a revision: two confirmations with
    the same subject/outcome but different deadlines share it. A resume whose
    draft carries a different deadline than the tail's must refuse to adopt
    that tail (another writer's revision) instead of reporting it committed."""
    from services.brief_commit import (
        _get_record,
        commit_draft,
        commit_key,
        recover_pending_commits,
    )

    revises = {
        "goal_id": None,  # set per commit below
        "expected_revision": 1,
        "lineage_id": None,  # set per commit below
        "revise_goal": True,
    }

    first = await _commit(stack, _final_draft())
    revised = _final_draft(fields={**_final_draft()["fields"], "subject": "the wipe tutorial"})
    crashed_revises = {
        **revises,
        "goal_id": first.goal_id,
        "lineage_id": first.lineage_id,
    }
    with pytest.raises(_ProcessDeath):
        await commit_draft(
            _USER,
            stack.workspace.id,
            revised,
            confirmed=True,
            revises=crashed_revises,
            goal_reader=stack.goal_reader,
            project_store=stack.projects,
            brief_store=_DieOnBriefCreate(stack.brief_store),
        )

    # Same subject/outcome, different deadline: identical desired_state, a
    # different stop condition — the stale confirmation must not adopt the
    # crashed append as its own result.
    stale = _final_draft(
        fields={
            **_final_draft()["fields"],
            "subject": "the wipe tutorial",
            "deadline": "End of the quarter",
        }
    )
    outcome = await commit_draft(
        _USER,
        stack.workspace.id,
        stale,
        confirmed=True,
        revises=crashed_revises,
        goal_reader=stack.goal_reader,
        project_store=stack.projects,
        brief_store=stack.brief_store,
    )
    assert outcome.status == "failed"

    # The matching crashed confirmation resumes cleanly and adopts revision 2.
    # The stale one — a caught, reported failure — is NOT auto-retried by the
    # sweep: recovery cannot know whether its draft was cancelled or replaced
    # after the failure was reported, so it stays failed until its principal
    # explicitly re-confirms it (safely retryable, never silently completed).
    recovered = await recover_pending_commits(
        goal_reader=stack.goal_reader,
        project_store=stack.projects,
        brief_store=stack.brief_store,
    )
    assert [o.status for o in recovered] == ["committed"]
    assert recovered[0].goal_id == first.goal_id
    assert recovered[0].goal_revision == 2
    assert "moved to revision" not in (recovered[0].reason or "")
    stale_record = _get_record(commit_key(_USER, stack.workspace.id, stale, crashed_revises))
    assert stale_record is not None and stale_record["status"] == "failed"
    assert "moved to revision" in str(stale_record.get("failure"))
    revisions = await stack.goal_reader.list_goal_revisions(first.goal_id, principal_id=_USER)
    assert [r.stop_conditions for r in revisions] == [
        ("deadline: Before the market",),
        ("deadline: Before the market",),
    ]


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

    dying = _DieOnGoalCreate(stack.goal_reader)
    draft = _final_draft()
    with pytest.raises(_ProcessDeath):
        await _commit(stack, draft, goal_reader=dying)
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
    # The #37 fence refuses the Project mirror until the second Workspace's
    # identity is durable in the shared database too.
    await _mirror_workspace_identity(
        foreign_session_factory, other_workspace.id, other_workspace.name
    )
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


async def test_a_dual_admin_cannot_cross_workspaces_via_revises(stack) -> None:
    """The principal administering *both* Workspaces cannot reach across
    them: `revises` scoped to Workspace B naming a Goal from Workspace A is
    rejected before any write — `get_goal`/`append_revision` authorize
    against the Goal's own Workspace, so without this pin the protocol
    would mutate A's Goal under B's Root Project and agent."""
    from services import workspace_authority
    from services.brief_commit import commit_draft

    first = await _commit(stack, _final_draft())

    # Same principal, second Workspace they administer.
    other_workspace = await workspace_authority.create_workspace(
        creator_user_id=_USER,
        name=f"Brief Commit dual {uuid.uuid4().hex[:8]}",
        persona_template_id="content_creator",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    other_projects = stack.projects.__class__()
    other_root = await other_projects.create_root(other_workspace.id)
    other_brief_store = stack.brief_store.__class__(session_factory=stack.server.factory)
    # The #37 fence refuses the Project mirror until the second Workspace's
    # identity is durable in the shared database too.
    await _mirror_workspace_identity(stack.server.factory, other_workspace.id, other_workspace.name)
    from sqlalchemy import text

    async with stack.server.factory() as session:
        await session.execute(
            text(
                "INSERT INTO canonical_projects (project_id, workspace_id, is_root, "
                "payload) VALUES (:p, :w, TRUE, CAST(:payload AS jsonb)) "
                "ON CONFLICT (project_id) DO NOTHING"
            ),
            {
                "p": str(other_root.project_id),
                "w": other_workspace.id,
                "payload": '{"name": "brief-commit-dual"}',
            },
        )
        await session.commit()

    try:
        outcome = await commit_draft(
            _USER,
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
            project_store=other_projects,
            brief_store=other_brief_store,
        )
        assert outcome.status == "failed"
        assert "belongs to workspace" in (outcome.reason or "")

        # Nothing was written to either Workspace: the Goal stays at its
        # original revision and no brief row appears in either scope.
        revisions = await stack.goal_reader.list_goal_revisions(first.goal_id, principal_id=_USER)
        assert [r.revision for r in revisions] == [1]
        assert await _brief_rows_for(stack.server.factory, other_workspace.id) == []
        assert await _brief_rows_for(stack.server.factory, stack.workspace.id) == [
            (first.brief_id, 1)
        ]
    finally:
        async with stack.server.factory() as session:
            await session.execute(
                text("DELETE FROM design_creative_briefs WHERE workspace_id = :w"),
                {"w": other_workspace.id},
            )
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
    once the seam is back — same draft, same key, one pair, the stranded
    brief adopted. The retry is the principal's own confirmation, not the
    startup sweep: recovery never auto-drives a reported failure."""
    from services.brief_commit import _get_record, commit_key

    class _BrokenSeam:
        def __getattr__(self, name: str) -> Any:
            raise AttributeError("forced prerequisite outage")

    draft = _final_draft()
    outcome = await _commit(stack, draft, goal_reader=_BrokenSeam())
    assert outcome.status in ("failed", "unavailable")
    assert len(await _brief_rows(stack)) == 1, "the brief-first write stranded"
    assert await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER) == []

    retry = await _commit(stack, draft)
    assert retry.status == "committed", retry
    record = _get_record(commit_key(_USER, stack.workspace.id, draft))
    assert (retry.goal_id, retry.brief_id) == (record["goal_id"], record["brief_id"])
    goals = await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER)
    assert [g.goal_id for g in goals] == [retry.goal_id]
    assert await _brief_rows(stack) == [(retry.brief_id, 1)]


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


def test_the_brief_store_accepts_every_shared_postgresql_spelling(monkeypatch) -> None:
    """The scheme gate defers to the shared configuration, not a local list.

    A ``postgresql+psycopg://`` DATABASE_URL is one the shared database
    configuration accepts (and ``design_service._get_async_engine`` loads
    through ``to_async_url``), so it must not read here as "no PostgreSQL
    database configured". Non-PostgreSQL URLs still get the explicit
    limitation.
    """
    import services.design_service as design_service_mod
    from services.brief_commit import (
        CommitPrerequisiteUnavailable,
        _resolve_brief_store,
    )

    import maistro.config.database as database_mod

    sentinel = object()
    monkeypatch.setattr(design_service_mod, "_get_async_session_factory", lambda: sentinel)
    import maistro_design.brief_store as brief_store_mod

    monkeypatch.setattr(brief_store_mod, "PgCreativeBriefStore", lambda factory: ("store", factory))

    for spelling in (
        "postgresql://u:p@h:5432/db",
        "postgres://u:p@h:5432/db",
        "postgresql+asyncpg://u:p@h:5432/db",
        "postgresql+psycopg://u:p@h:5432/db?sslmode=require",
    ):
        monkeypatch.setattr(database_mod, "resolve_database_url", lambda url=spelling: url)
        assert _resolve_brief_store() == ("store", sentinel), spelling

    monkeypatch.setattr(
        database_mod,
        "resolve_database_url",
        lambda: "sqlite:////tmp/no-postgres-here.db",
    )
    with pytest.raises(CommitPrerequisiteUnavailable, match="PostgreSQL"):
        _resolve_brief_store()


# ---------------------------------------------------------------------------
# Seams the commit protocol leans on: refusals, degenerate records and the
# recovery sweep's own filters. Each line here is a boundary behaviour, not
# plumbing: the refuses-before-write and truthfulness contracts the issue's
# acceptance criteria hang on.
# ---------------------------------------------------------------------------


def test_revalidate_rejects_an_empty_draft_and_a_fieldless_draft() -> None:
    """The boundary's own gate (scope item 1): a draft that is not a draft,
    or carries no fields, is rejected before any identity is minted."""
    from services.brief_commit import CommitRejected, revalidate_draft

    with pytest.raises(CommitRejected, match="no interview draft"):
        revalidate_draft({})
    with pytest.raises(CommitRejected, match="no fields"):
        revalidate_draft({"script": "video_brief", "fields": "not-a-dict"})


def test_an_engine_that_cannot_start_leaves_the_prerequisites_unavailable(
    monkeypatch,
) -> None:
    """`get_engine` raising (no embedded runtime) is the AC-8 limitation, not
    a crash: both Goal and Project seams answer the same typed refusal."""
    import services.engine as engine_mod
    from services.brief_commit import (
        CommitPrerequisiteUnavailable,
        _resolve_goal_reader,
        _resolve_project_store,
    )

    def _raising_engine() -> Any:
        raise RuntimeError("the embedded runtime is not running")

    monkeypatch.setattr(engine_mod, "get_engine", _raising_engine)
    with pytest.raises(CommitPrerequisiteUnavailable, match="Goal store"):
        _resolve_goal_reader()
    with pytest.raises(CommitPrerequisiteUnavailable, match="Project store"):
        _resolve_project_store()


def test_the_engines_project_store_is_used_when_the_runtime_is_up(monkeypatch) -> None:
    """Production resolves the Project store off the engine's Container —
    the override parameter exists for tests; the engine path is what ships."""
    import services.engine as engine_mod
    from services.brief_commit import _resolve_project_store

    marker = object()
    monkeypatch.setattr(
        engine_mod, "get_engine", lambda: SimpleNamespace(project_scope_store=marker)
    )
    assert _resolve_project_store() is marker


def test_a_postgres_url_with_no_session_factory_is_still_the_limitation(
    monkeypatch,
) -> None:
    """A configured PostgreSQL URL whose design session factory never started
    (design service down) cannot write briefs: the same typed refusal."""
    import services.design_service as design_service_mod
    from services.brief_commit import (
        CommitPrerequisiteUnavailable,
        _resolve_brief_store,
    )

    import maistro.config.database as database_mod

    monkeypatch.setattr(
        database_mod,
        "resolve_database_url",
        lambda: "postgresql://u:p@h:5432/db",
    )
    monkeypatch.setattr(design_service_mod, "_get_async_session_factory", lambda: None)
    with pytest.raises(CommitPrerequisiteUnavailable, match="session factory did not start"):
        _resolve_brief_store()


async def test_a_view_by_a_principal_outside_the_workspace_is_refused(stack) -> None:
    """AC-5's read half, at the seam: `list_commitments` authorizes through
    the same workspace authority before it answers, so a non-member cannot
    even enumerate another's intake."""
    from services.brief_commit import CommitNotAuthorized, _require_view

    with pytest.raises(CommitNotAuthorized):
        await _require_view(_OTHER, stack.workspace.id)


def test_a_record_with_no_parseable_timestamp_is_not_fresh() -> None:
    """A degenerate record (no `updated_at`, or garbage in it) must not read
    as a live driver: takeover proceeds instead of waiting out a phantom."""
    from services.brief_commit import _fresh

    assert _fresh({}, takeover_after=60.0) is False
    assert _fresh({"updated_at": "not-a-timestamp"}, takeover_after=60.0) is False


def test_an_outcome_from_an_unsettled_record_is_failed_and_truthful() -> None:
    """Records parked on a live stage (or poisoned) are not successes: the
    follower's answer names the recorded failure, or says the attempt did
    not complete — never the ids of a pair that does not exist."""
    from services.brief_commit import _outcome_from_record

    outcome = _outcome_from_record({"status": "failed", "failure": "boom"}, recovered=True)
    assert outcome.status == "failed"
    assert outcome.reason == "boom"
    assert outcome.durable is False

    unnamed = _outcome_from_record({"status": "brief_created"}, recovered=True)
    assert unnamed.status == "failed"
    assert unnamed.reason == "commit did not complete"


async def test_the_sweep_skips_records_that_do_not_belong_to_the_request() -> None:
    """The operations-facing filters (user/workspace) select exactly the
    records asked for; a non-matching record is left untouched."""
    from services import brief_commit as brief_commit_mod
    from services.brief_commit import _candidate, _get_record, recover_pending_commits

    draft = _final_draft()
    key = brief_commit_mod.commit_key(_USER, "ws-under-sweep", draft)
    record = _candidate(
        key,
        user_id=_USER,
        workspace_id="ws-under-sweep",
        project_id="p",
        agent_id="a",
        draft=draft,
        revises=None,
    )
    brief_commit_mod._put_record(record)
    try:
        assert await recover_pending_commits(user_id=_OTHER) == []
        assert await recover_pending_commits(workspace_id="another-ws") == []
        after = _get_record(key)
        assert after is not None and after["status"] == "pending", "the sweep left it alone"
    finally:
        brief_commit_mod._commits.pop(key, None)


def test_forget_commit_refuses_everything_but_a_settled_record_of_the_owners() -> None:
    """`forget_commit` is the principal's way to drop a settled attempt's
    queryable record: it declines a missing record, a foreign principal, and
    an attempt still in flight — and only then removes the record."""
    from services import brief_commit as brief_commit_mod
    from services.brief_commit import _candidate, commit_key

    draft = _final_draft()
    key = commit_key(_USER, "ws-forget", draft)
    settled = _candidate(
        key,
        user_id=_USER,
        workspace_id="ws-forget",
        project_id="p",
        agent_id="a",
        draft=draft,
        revises=None,
    )
    settled["status"] = "failed"
    settled["failure"] = "boom"
    brief_commit_mod._commits[key] = settled
    try:
        assert brief_commit_mod.forget_commit("missing-key", user_id=_USER) is False
        assert brief_commit_mod.forget_commit(key, user_id=_OTHER) is False
        assert key in brief_commit_mod._commits, "a foreign principal removed nothing"

        settled["status"] = "pending"
        assert brief_commit_mod.forget_commit(key, user_id=_USER) is False
        assert key in brief_commit_mod._commits, "an in-flight attempt is not forgettable"

        settled["status"] = "failed"
        assert brief_commit_mod.forget_commit(key, user_id=_USER) is True
        assert key not in brief_commit_mod._commits
    finally:
        brief_commit_mod._commits.pop(key, None)


async def test_the_sweep_resolves_the_agent_for_a_record_that_never_pinned_one(
    stack,
) -> None:
    """A record written before the accountable-agent pin (or by a path that
    could not resolve it) resumes with the Workspace's stable agent resolved
    from the canonical authority — the sweep, not the record, owns that
    identity when it is absent."""
    from services import brief_commit as brief_commit_mod
    from services.agent_materialization import workspace_agent_id
    from services.brief_commit import (
        _candidate,
        _get_record,
        _put_record,
        commit_key,
        recover_pending_commits,
    )

    draft = _final_draft()
    key = commit_key(_USER, stack.workspace.id, draft)
    record = _candidate(
        key,
        user_id=_USER,
        workspace_id=stack.workspace.id,
        project_id=str(stack.root.project_id),
        agent_id="",
        draft=draft,
        revises=None,
    )
    _put_record(record)
    try:
        outcomes = await recover_pending_commits(
            goal_reader=stack.goal_reader,
            project_store=stack.projects,
            brief_store=stack.brief_store,
        )
        assert [o.status for o in outcomes] == ["committed"], outcomes
        goals = await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER)
        assert [g.goal_id for g in goals] == [outcomes[0].goal_id]
        assert goals[0].agent_id == workspace_agent_id(stack.workspace.id)
        assert await _brief_rows(stack) == [(outcomes[0].brief_id, 1)]
        assert _get_record(key)["status"] == "committed"
    finally:
        brief_commit_mod._commits.pop(key, None)


async def test_the_sweep_reports_each_interrupted_records_own_failure(stack) -> None:
    """Recovery is per-record: one record whose resume hits an unavailable
    prerequisite reports `unavailable`, one that hits a write error reports
    `failed`, and neither stops the sweep from finishing the others."""
    from services import brief_commit as brief_commit_mod
    from services.brief_commit import (
        CommitPrerequisiteUnavailable,
        _candidate,
        _get_record,
        _put_record,
        commit_key,
        recover_pending_commits,
    )

    class _FlakyStore:
        """Loses the first write loudly-unavailable, the second as a crash."""

        def __init__(self, inner: Any) -> None:
            self._inner = inner
            self.calls = 0

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        async def create(self, brief: Any) -> None:
            self.calls += 1
            if self.calls == 1:
                raise CommitPrerequisiteUnavailable("brief store lost mid-sweep")
            raise RuntimeError("brief store crashed mid-sweep")

    keys = []
    for subject in ("first interrupted", "second interrupted"):
        draft = _final_draft(subject=subject)
        key = commit_key(_USER, stack.workspace.id, draft)
        _put_record(
            _candidate(
                key,
                user_id=_USER,
                workspace_id=stack.workspace.id,
                project_id=str(stack.root.project_id),
                agent_id="a",
                draft=draft,
                revises=None,
            )
        )
        keys.append(key)
    try:
        outcomes = await recover_pending_commits(
            goal_reader=stack.goal_reader,
            project_store=stack.projects,
            brief_store=_FlakyStore(stack.brief_store),
        )
        assert [o.status for o in outcomes] == ["unavailable", "failed"], outcomes
        assert "brief store lost mid-sweep" in (outcomes[0].reason or "")
        assert "RuntimeError" in (outcomes[1].reason or "")
        # Both records settled as failures the sweep reported — neither is
        # left in flight, and neither wrote a Goal.
        for key in keys:
            assert _get_record(key)["status"] == "failed"
        assert await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER) == []
    finally:
        for key in keys:
            brief_commit_mod._commits.pop(key, None)


async def test_concurrent_identical_commits_converge_on_one_failed_result(stack) -> None:
    """The follower half of AC-3's concurrency promise: when the driver's
    attempt fails, the concurrent identical confirmation reports the same
    failed record — it does not start a second protocol on a second record."""

    class _SlowLosingStore:
        """Resolves and reads, then loses the write after a real window, so
        the concurrent confirmation observes a live driver."""

        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        async def create(self, brief: Any) -> None:
            await asyncio.sleep(0.2)
            raise RuntimeError("forced concurrent lost write")

    draft = _final_draft(subject="concurrent failure")
    first, second = await asyncio.gather(
        _commit(stack, draft, brief_store=_SlowLosingStore(stack.brief_store)),
        _commit(stack, draft, brief_store=_SlowLosingStore(stack.brief_store)),
    )
    statuses = {first.status, second.status}
    assert statuses == {"failed"}, (first, second)
    assert await _brief_rows(stack) == [], "neither attempt wrote a brief"
    assert await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER) == []


async def test_a_revision_cannot_bind_a_lineage_from_another_workspace(stack) -> None:
    """The lineage pin: the Goal may legitimately belong to the requested
    Workspace, but `revises` naming a lineage that lives in another is
    refused before any brief version is minted against it."""
    from services import workspace_authority
    from services.brief_commit import commit_draft

    first = await _commit(stack, _final_draft())

    other_workspace = await workspace_authority.create_workspace(
        creator_user_id=_USER,
        name=f"Brief Commit lineage pin {uuid.uuid4().hex[:8]}",
        persona_template_id="content_creator",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    other_projects = stack.projects.__class__()
    other_root = await other_projects.create_root(other_workspace.id)
    # The #37 fence refuses the Project mirror until the second Workspace's
    # identity is durable in the shared database too.
    await _mirror_workspace_identity(stack.server.factory, other_workspace.id, other_workspace.name)
    from services.agent_materialization import workspace_agent_id

    from maistro.goals import GoalRevisionDraft

    goal = await stack.goal_reader.create_goal(
        principal_id=_USER,
        workspace_id=other_workspace.id,
        project_id=str(other_root.project_id),
        agent_id=workspace_agent_id(other_workspace.id),
        draft=GoalRevisionDraft(
            desired_state="own workspace goal — Teach it",
            success_conditions=("Teach it",),
            stop_conditions=(),
            author=workspace_agent_id(other_workspace.id),
        ),
    )
    from sqlalchemy import text

    async with stack.server.factory() as session:
        await session.execute(
            text(
                "INSERT INTO canonical_projects (project_id, workspace_id, is_root, "
                "payload) VALUES (:p, :w, TRUE, CAST(:payload AS jsonb)) "
                "ON CONFLICT (project_id) DO NOTHING"
            ),
            {
                "p": str(other_root.project_id),
                "w": other_workspace.id,
                "payload": '{"name": "brief-commit-lineage-pin"}',
            },
        )
        await session.commit()
    try:
        outcome = await commit_draft(
            _USER,
            other_workspace.id,
            _final_draft(subject="lineage pin probe"),
            confirmed=True,
            revises={
                "goal_id": goal.goal_id,
                "expected_revision": goal.current_revision,
                "lineage_id": first.lineage_id,
                "revise_goal": False,
            },
            goal_reader=stack.goal_reader,
            project_store=other_projects,
            brief_store=stack.brief_store.__class__(session_factory=stack.server.factory),
        )
        assert outcome.status == "failed"
        assert "no CreativeBrief in workspace" in (outcome.reason or "")
        # The foreign lineage gained no version, and the own-Workspace Goal
        # gained no revision either.
        assert await _brief_rows_for(stack.server.factory, other_workspace.id) == []
        revisions = await stack.goal_reader.list_goal_revisions(goal.goal_id, principal_id=_USER)
        assert [r.revision for r in revisions] == [1]
    finally:
        async with stack.server.factory() as session:
            await session.execute(
                text("DELETE FROM design_creative_briefs WHERE workspace_id = :w"),
                {"w": other_workspace.id},
            )
            await session.execute(
                text(
                    "DELETE FROM canonical_goal_transitions WHERE goal_id IN "
                    "(SELECT goal_id FROM canonical_goals WHERE workspace_id = :w)"
                ),
                {"w": other_workspace.id},
            )
            await session.execute(
                text(
                    "DELETE FROM canonical_goal_revisions WHERE goal_id IN "
                    "(SELECT goal_id FROM canonical_goals WHERE workspace_id = :w)"
                ),
                {"w": other_workspace.id},
            )
            await session.execute(
                text("DELETE FROM canonical_goals WHERE workspace_id = :w"),
                {"w": other_workspace.id},
            )
            await session.execute(
                text("DELETE FROM canonical_projects WHERE workspace_id = :w"),
                {"w": other_workspace.id},
            )
            await session.commit()


async def test_a_creative_only_revision_with_a_stale_revision_refuses(stack) -> None:
    """A creative-only change re-reads the Goal it annotates: naming a
    revision the Goal is no longer at refuses cleanly — nothing is written,
    and the caller re-reads before retrying."""
    from services.brief_commit import commit_draft

    first = await _commit(stack, _final_draft())
    outcome = await commit_draft(
        _USER,
        stack.workspace.id,
        _final_draft(subject="stale creative-only probe"),
        confirmed=True,
        revises={
            "goal_id": first.goal_id,
            "expected_revision": first.goal_revision + 7,
            "lineage_id": first.lineage_id,
            "revise_goal": False,
        },
        goal_reader=stack.goal_reader,
        project_store=stack.projects,
        brief_store=stack.brief_store,
    )
    assert outcome.status == "failed"
    assert "re-read it before changing the brief" in (outcome.reason or "")
    assert await _brief_rows(stack) == [(first.brief_id, 1)], "no version was minted"


async def test_an_unresolvable_workspace_agent_is_the_explicit_limitation(
    stack, monkeypatch
) -> None:
    """Without a stable accountable Workspace Agent there is nothing to be
    accountable for: the boundary refuses loudly, writes nothing, and the
    confirmation stays retryable once the agent resolves."""
    from services import brief_commit as brief_commit_mod
    from services.brief_commit import WorkspaceNotFound

    async def _no_agent(workspace_id: str) -> Any:
        raise WorkspaceNotFound(f"no agent for {workspace_id}")

    monkeypatch.setattr(brief_commit_mod, "resolve_workspace_agent", _no_agent)
    outcome = await _commit(stack, _final_draft())
    assert outcome.status == "unavailable"
    assert "accountable agent" in (outcome.reason or "")
    assert await _brief_rows(stack) == []
    assert await stack.goal_reader.list_goals(stack.workspace.id, principal_id=_USER) == []

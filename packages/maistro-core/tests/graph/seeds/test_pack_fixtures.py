"""M7-A13 pack fixtures load through the canonical spine — and only there.

The book fixture (accepted) and the game fixture (parked) must be inspectable
as canonical Goal -> Graph -> Run -> NodeRun -> Attempt lineage: eval records,
the accept fence, the refine Attempt, the failing dimension, and a restart-safe
resume of the parked Run. A fixture that lived only in frontend JSON, zustand,
or localStorage would satisfy none of these queries, and the last test makes
that failure explicit by scanning the frontend trees for fixture content.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from pathlib import Path

import aiosqlite
import pytest

from maistro.graph.seeds.pack_fixtures import (
    BOOK_GRAPH_ID,
    BOOK_WAVE1_THESIS_CONVENTIONAL,
    BOOK_WAVE1_THESIS_WORDLESS,
    BOOK_WAVE2_WINNER,
    FENCE_REVIEW_NODE,
    GAME_EXPLORE_THESIS,
    GAME_GRAPH_ID,
    GAME_PACK,
    PACK_FIXTURE_PROVENANCE_KEY,
    PACK_FIXTURE_WORKSPACE_ID,
    PackFixtureSeed,
    seed_book_fixture,
    seed_game_fixture,
)
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import AttemptStatus, RunStatus
from maistro.runs.concurrency import RunConcurrencyLimits
from maistro.runs.store import InMemoryRunStore

_GENEROUS_LIMITS = RunConcurrencyLimits(per_principal=16, per_workspace=16)


def _memory_stores() -> tuple[InMemoryProjectScopeStore, InMemoryRunStore]:
    project_store = InMemoryProjectScopeStore()
    return project_store, InMemoryRunStore(
        project_store=project_store, concurrency_limits=_GENEROUS_LIMITS
    )


def _spreads(artifact: dict[str, object]) -> list[dict[str, object]]:
    return list(artifact["spreads"])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Book fixture: accepted, complete lineage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_book_fixture_lineage_is_complete() -> None:
    project_store, run_store = _memory_stores()
    seed: PackFixtureSeed = await seed_book_fixture(run_store, project_store)

    run = await run_store.get_run(seed.run_id)
    assert run is not None
    assert run.status is RunStatus.COMPLETED
    assert (run.workspace_id, run.project_id) == (
        PACK_FIXTURE_WORKSPACE_ID,
        seed.project_id,
    )
    assert run.graph.graph_id == BOOK_GRAPH_ID
    assert run.provenance[PACK_FIXTURE_PROVENANCE_KEY] == "book"
    # Goal revision and rubric revision are inspectable on the Run, and the
    # redirect between waves names both revisions it moved.
    assert run.provenance["goal_revision"] == 2
    assert run.provenance["rubric_revision"] == 2
    assert run.provenance["redirect"]["from_revision"] == 1
    assert run.provenance["redirect"]["to_revision"] == 2

    node_runs = {
        node_run.node_id: node_run for node_run in await run_store.list_node_runs(seed.run_id)
    }
    assert set(node_runs) == {
        BOOK_WAVE1_THESIS_CONVENTIONAL,
        BOOK_WAVE1_THESIS_WORDLESS,
        BOOK_WAVE2_WINNER,
        FENCE_REVIEW_NODE,
    }

    # Wave 1: at least two rejected theses, each with an eval record on the Run.
    rejects = [
        node_runs[BOOK_WAVE1_THESIS_CONVENTIONAL],
        node_runs[BOOK_WAVE1_THESIS_WORDLESS],
    ]
    for reject in rejects:
        assert reject.status is RunStatus.COMPLETED, (
            "a rejected thesis is a completed explore whose output was judged "
            "down, not a failed node"
        )
        record = reject.result["eval_record"]
        assert record["verdict"] == "rejected"
        assert record["rubric_revision"] == 1
    assert len(rejects) >= 2

    # Wave 2 winner: BookPages artifact, accepted after a refine Attempt.
    winner = node_runs[BOOK_WAVE2_WINNER]
    assert winner.status is RunStatus.COMPLETED
    assert winner.accepted_outcome is not None
    assert winner.accepted_outcome.attempt_result.status is AttemptStatus.COMPLETED
    assert winner.result["artifact_kind"] == "BookPages"
    spreads = _spreads(winner.result["artifact"])
    assert len(spreads) == 16
    assert all(spread["turn"] for spread in spreads)

    attempts = await run_store.list_attempts(winner.node_run_id)
    assert [attempt.ordinal for attempt in attempts] == [1, 2]
    # The planted earlier failure is still queryable, and the refine Attempt
    # that accepted is the one the accepted outcome names.
    assert attempts[0].status is AttemptStatus.FAILED
    assert "contained_fear" in attempts[0].error
    assert attempts[1].status is AttemptStatus.COMPLETED
    assert attempts[1].result["eval_record"]["verdict"] == "accepted"
    assert winner.accepted_outcome.attempt_result.attempt_id == attempts[1].attempt_id

    # Fence: accept after refine.
    fence = node_runs[FENCE_REVIEW_NODE]
    assert fence.status is RunStatus.COMPLETED
    assert fence.result["fence_decision"]["decision"] == "accept"
    assert fence.result["fence_decision"]["rubric_revision"] == 2
    assert run.result["fence_decision"] == "accept"
    assert run.result["artifact_kind"] == "BookPages"


# ---------------------------------------------------------------------------
# Game fixture: parked, failing dimension, restart-safe resume
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_game_fixture_parks_with_failing_dimension() -> None:
    project_store, run_store = _memory_stores()
    seed = await seed_game_fixture(run_store, project_store)

    run = await run_store.get_run(seed.run_id)
    assert run is not None
    assert run.status is RunStatus.WAITING
    assert run.graph.graph_id == GAME_GRAPH_ID
    assert run.provenance[PACK_FIXTURE_PROVENANCE_KEY] == GAME_PACK

    node_runs = {
        node_run.node_id: node_run for node_run in await run_store.list_node_runs(seed.run_id)
    }
    thesis = node_runs[GAME_EXPLORE_THESIS]
    assert thesis.status is RunStatus.COMPLETED
    record = thesis.result["eval_record"]
    assert record["verdict"] == "rejected"
    # The scored dimensions live on the Attempt that produced the thesis;
    # the NodeRun projects the verdict summary.
    attempts = await run_store.list_attempts(thesis.node_run_id)
    scored = attempts[-1].result["eval_record"]["dimensions"]
    failing = [dimension for dimension in scored if dimension["verdict"] == "fail"]
    assert failing, "the scored thesis must carry at least one failing dimension"
    assert any(dimension["dimension"] == "taught_by_play" for dimension in failing)
    assert any(dimension["dimension"] in record["note"] for dimension in failing)

    fence = node_runs[FENCE_REVIEW_NODE]
    assert fence.status is RunStatus.WAITING
    assert fence.result["fence_decision"]["decision"] == "park"

    # Artifact kinds stay thesis-shaped; GameLoop is the catalog's artifact
    # kind, and no playable runtime or engine artifact is claimed.
    assert thesis.result["artifact_kind"] == "ThesisDraft"


@pytest.mark.asyncio
async def test_game_fixture_resume_restores_the_same_identities() -> None:
    project_store, run_store = _memory_stores()
    seed = await seed_game_fixture(run_store, project_store)
    before_runs = await run_store.list_node_runs(seed.run_id)

    # Resume: the canonical WAITING -> RUNNING move, on the same identities.
    run = await run_store.transition_run(seed.run_id, RunStatus.RUNNING)
    fence_id = seed.node_run_id("fence")
    fence = await run_store.transition_node_run(fence_id, RunStatus.RUNNING)
    assert run.run_id == seed.run_id
    assert run.status is RunStatus.RUNNING
    assert fence.node_run_id == fence_id
    assert fence.status is RunStatus.RUNNING
    assert [node_run.node_run_id for node_run in await run_store.list_node_runs(seed.run_id)] == [
        node_run.node_run_id for node_run in before_runs
    ]


# ---------------------------------------------------------------------------
# Durable stores: refresh/reconnect shows the same identities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixtures_survive_a_store_reconnect(tmp_path: Path) -> None:
    from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
    from maistro.runs import SqliteRunStore

    db_path = tmp_path / "pack-fixtures.db"
    first_conn = await aiosqlite.connect(db_path)
    try:
        first_projects = SqliteProjectScopeStore(first_conn)
        await first_projects.ensure_schema()
        first_runs = SqliteRunStore(
            first_conn,
            project_store=first_projects,
            concurrency_limits=_GENEROUS_LIMITS,
        )
        await first_runs.ensure_schema()
        book = await seed_book_fixture(first_runs, first_projects)
        game = await seed_game_fixture(first_runs, first_projects)
    finally:
        await first_conn.close()

    # A reconnect (process restart, Design Studio refresh) reads the same
    # identities with the same lineage — nothing is re-seeded or merged.
    second_conn = await aiosqlite.connect(db_path)
    try:
        second_projects = SqliteProjectScopeStore(second_conn)
        await second_projects.ensure_schema()
        second_runs = SqliteRunStore(
            second_conn,
            project_store=second_projects,
            concurrency_limits=_GENEROUS_LIMITS,
        )
        await second_runs.ensure_schema()

        book_run = await second_runs.get_run(book.run_id)
        assert book_run is not None and book_run.status is RunStatus.COMPLETED
        winner_id = book.node_run_id("wave2_winner")
        winner = await second_runs.get_node_run(winner_id)
        assert winner is not None
        assert winner.accepted_outcome is not None
        assert winner.result["artifact_kind"] == "BookPages"
        assert len(await second_runs.list_attempts(winner_id)) == 2
        fence_id = book.node_run_id("fence")
        book_fence = await second_runs.get_node_run(fence_id)
        assert book_fence is not None
        assert book_fence.result["fence_decision"]["decision"] == "accept"

        game_run = await second_runs.get_run(game.run_id)
        assert game_run is not None and game_run.status is RunStatus.WAITING
        game_fence_id = game.node_run_id("fence")
        game_fence = await second_runs.get_node_run(game_fence_id)
        assert game_fence is not None and game_fence.status is RunStatus.WAITING

        # Resume after restart: same Run, same waiting NodeRun.
        resumed = await second_runs.transition_run(game.run_id, RunStatus.RUNNING)
        resumed_fence = await second_runs.transition_node_run(game_fence_id, RunStatus.RUNNING)
        assert resumed.run_id == game.run_id
        assert resumed_fence.node_run_id == game_fence_id
    finally:
        await second_conn.close()


# ---------------------------------------------------------------------------
# Ontology: fixtures share the Workspace/Project identity scheme
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixtures_share_one_workspace_project_ontology() -> None:
    project_store, run_store = _memory_stores()
    book = await seed_book_fixture(run_store, project_store)
    game = await seed_game_fixture(run_store, project_store)

    for seed in (book, game):
        lineage = await project_store.lineage(seed.project_id)
        assert lineage, "fixture Project must resolve in canonical Project scope"
        assert lineage[0].workspace_id == PACK_FIXTURE_WORKSPACE_ID
        run = await run_store.get_run(seed.run_id)
        assert run is not None
        assert (run.workspace_id, run.project_id) == (
            lineage[-1].workspace_id,
            lineage[-1].project_id,
        )
    # Same Project row, same Workspace: one ontology, not a second scheme.
    assert book.project_id == game.project_id
    assert book.workspace_id == game.workspace_id == PACK_FIXTURE_WORKSPACE_ID


async def test_open_pack_fixture_is_a_read_only_inspection_path() -> None:
    """A host opens either fixture by canonical id without executing anything."""
    from maistro.graph.seeds.pack_fixtures import open_pack_fixture

    project_store, run_store = _memory_stores()
    book = await seed_book_fixture(run_store, project_store)
    game = await seed_game_fixture(run_store, project_store)

    opened_book = await open_pack_fixture(run_store, book.run_id)
    assert opened_book["pack"] == "book"
    assert opened_book["goal_id"] and opened_book["goal_revision"] == 2
    assert opened_book["rubric_revision"] == 2
    assert opened_book["fence_decision"] == "accept"
    assert opened_book["artifact_kind"] == "BookPages"
    rejects = [wave for wave in opened_book["waves"] if wave["eval_verdict"] == "rejected"]
    assert len(rejects) >= 2
    winner = next(wave for wave in opened_book["waves"] if wave["node_id"] == BOOK_WAVE2_WINNER)
    assert winner["artifact_kind"] == "BookPages"
    assert winner["attempt_statuses"] == ["failed", "completed"]

    opened_game = await open_pack_fixture(run_store, game.run_id)
    assert opened_game["pack"] == "game"
    assert opened_game["status"] == "waiting"
    assert opened_game["fence_decision"] is None, "the Run-level fence fires on settle only"
    game_fence = next(wave for wave in opened_game["waves"] if wave["node_id"] == FENCE_REVIEW_NODE)
    assert game_fence["fence_decision"] == "park"
    assert game_fence["status"] == "waiting"

    # Read-only: opening changed nothing on the spine.
    assert (await run_store.get_run(book.run_id)).status is RunStatus.COMPLETED
    assert (await run_store.get_run(game.run_id)).status is RunStatus.WAITING


# ---------------------------------------------------------------------------
# Fixtures are not frontend seeds
# ---------------------------------------------------------------------------


def _frontend_files() -> Iterator[Path]:
    repo_root = Path(__file__).resolve().parents[5]
    for frontend in ("packages/hive-conductor/frontend", "packages/maistro-canvas/frontend"):
        base = repo_root / frontend
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in {
                ".ts",
                ".tsx",
                ".js",
                ".jsx",
                ".json",
                ".html",
            }:
                yield path


def test_fixture_content_never_lives_in_a_frontend_store() -> None:
    """A frontend-only fixture (JSON / zustand / localStorage) fails here.

    The scan refuses any frontend file that carries fixture identity or copy:
    fixture content belongs to the canonical seed module, and a reviewer who
    finds it in a client store is looking at the parallel app this issue
    forbids. Seeding itself already requires a RunStore, so no client-side
    copy can satisfy the lineage queries above either.
    """
    # The seed is a store-writer, not a serializer: both entry points take the
    # canonical stores and return identity handles, never JSON documents.
    for seeder in (seed_book_fixture, seed_game_fixture):
        parameters = set(inspect.signature(seeder).parameters)
        assert {"run_store", "project_store"} <= parameters

    markers = (
        PACK_FIXTURE_WORKSPACE_ID,
        BOOK_GRAPH_ID,
        GAME_GRAPH_ID,
        "The Small Brass Ship",
        "Lantern Corner",
    )
    offenders: list[str] = []
    for path in _frontend_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover - unreadable file is not evidence
            continue
        if any(marker in text for marker in markers):
            offenders.append(str(path))
    assert offenders == []

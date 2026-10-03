"""The documented seed command provisions inspectable fixture Runs (#989).

`maistro fixtures seed` is the production entry point for the pack fixtures:
the command that makes `maistro.graph.seeds.pack_fixtures` reachable and a
deployment's fixtures real. These tests invoke the CLI exactly as an operator
does — through the unified `maistro` app — and then verify the store it leaves
behind through canonical reads only: fresh store objects, reopened from disk,
must show the same identities (the refresh/reconnect criterion) without any
fixture JSON, frontend store, or direct insert ever existing.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite
from typer.testing import CliRunner

from maistro.cli import app as cli_app
from maistro.graph.seeds.pack_fixtures import (
    BOOK_GOAL_ID,
    BOOK_WAVE1_THESIS_CONVENTIONAL,
    BOOK_WAVE1_THESIS_WORDLESS,
    BOOK_WAVE2_WINNER,
    GAME_EXPLORE_THESIS,
    GAME_GOAL_ID,
    PACK_FIXTURE_WORKSPACE_ID,
)
from maistro.runs import RunStatus, SqliteRunStore
from maistro.runs.concurrency import RunConcurrencyLimits

runner = CliRunner()

_LIMITS = RunConcurrencyLimits(per_principal=16, per_workspace=16)


@asynccontextmanager
async def _reopened(db_path: Path) -> AsyncIterator[SqliteRunStore]:
    """A fresh store over the seeded file — what a restart or refresh reads."""
    from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore

    conn = await aiosqlite.connect(db_path)
    try:
        projects = SqliteProjectScopeStore(conn)
        await projects.ensure_schema()
        runs = SqliteRunStore(conn, project_store=projects, concurrency_limits=_LIMITS)
        await runs.ensure_schema()
        yield runs
    finally:
        await conn.close()


def _seed_json(db_path: Path) -> dict[str, dict[str, Any]]:
    """Run the documented seed command and capture its open payloads."""
    result = runner.invoke(cli_app, ["fixtures", "seed", "--db", str(db_path), "--json"])
    assert result.exit_code == 0, result.output
    payloads = json.loads(result.output)
    return {payload["pack"]: payload for payload in payloads}


def test_seed_command_provisions_an_inspectable_durable_store(tmp_path: Path) -> None:
    """The command's own output is the open path, and the store it leaves is real."""
    db_path = tmp_path / "pack-fixtures.db"
    payloads = _seed_json(db_path)

    book = payloads["book"]
    assert book["status"] == RunStatus.COMPLETED.value
    assert book["goal_id"] == BOOK_GOAL_ID
    assert book["goal_revision"] == 2 and book["rubric_revision"] == 2
    assert book["redirect"]["kind"] == "redirect-rubric"
    assert book["fence_decision"] == "accept"
    by_node = {wave["node_id"]: wave for wave in book["waves"]}
    for rejected in (BOOK_WAVE1_THESIS_CONVENTIONAL, BOOK_WAVE1_THESIS_WORDLESS):
        assert by_node[rejected]["eval_verdict"] == "rejected"
    winner = by_node[BOOK_WAVE2_WINNER]
    assert winner["artifact_kind"] == "BookPages"
    assert winner["attempt_statuses"] == ["failed", "completed"]

    game = payloads["game"]
    assert game["status"] == RunStatus.WAITING.value
    assert game["goal_id"] == GAME_GOAL_ID
    game_by_node = {wave["node_id"]: wave for wave in game["waves"]}
    assert game_by_node[GAME_EXPLORE_THESIS]["eval_verdict"] == "rejected"
    game_fence_id = game_by_node["fence-review"]["node_run_id"]

    # Refresh/reconnect: fresh store objects over the same file show the same
    # identities and statuses — the command's output is not the authority.
    async def check_reopen() -> tuple[bool, bool, bool]:
        async with _reopened(db_path) as reopened:
            book_run = await reopened.get_run(book["run_id"])
            game_run = await reopened.get_run(game["run_id"])
            assert book_run is not None and game_run is not None
            fence = await reopened.get_node_run(game_fence_id)
            assert fence is not None
            decision = fence.result["fence_decision"]
            # The parked game declares GameLoop and nothing else: the catalog
            # carries the kind, and the only artifact a parked Run ever
            # composed is the scored ThesisDraft.
            return (
                book_run.status is RunStatus.COMPLETED
                and book_run.workspace_id == PACK_FIXTURE_WORKSPACE_ID,
                game_run.status is RunStatus.WAITING,
                decision["decision"] == "park"
                and "taught_by_play" in decision["reason"]
                and game_run.provenance["catalog"]["artifact_kind"] == "GameLoop",
            )

    book_holds, game_holds, park_holds = asyncio.run(check_reopen())
    assert book_holds and game_holds and park_holds


def test_seed_command_table_output_names_the_canonical_workspace(tmp_path: Path) -> None:
    """The operator-facing output points at the shared Workspace and the file."""
    db_path = tmp_path / "pack-fixtures.db"
    result = runner.invoke(cli_app, ["fixtures", "seed", "--db", str(db_path)])
    assert result.exit_code == 0, result.output

    # Compare with whitespace collapsed. Rich hard-breaks a token too long for
    # the console width, so an absolute path can arrive split across lines --
    # and `_fixtures` builds its Console at import time, which bakes `COLUMNS`
    # in before the runner can override it. Paths carry no whitespace of their
    # own, so this still pins the whole path, just not the line it landed on.
    def _flat(text: str) -> str:
        return "".join(text.split())

    flat = _flat(result.output)
    assert _flat(PACK_FIXTURE_WORKSPACE_ID) in flat
    assert _flat(str(db_path)) in flat
    assert "completed" in flat and "waiting" in flat


def test_unified_cli_routes_the_fixtures_command() -> None:
    """The seed command is a real entry point on the unified `maistro` app."""
    result = runner.invoke(cli_app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "fixtures" in result.output

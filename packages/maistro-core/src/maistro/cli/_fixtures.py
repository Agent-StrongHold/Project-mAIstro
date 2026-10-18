"""`maistro fixtures` subcommand — provision the M7-A13 pack fixtures (#989).

The documented seed command the fixture contract names: it writes the book and
game fixture Runs through the canonical lifecycle APIs only —
`ProjectScopeStore` and `RunStore` create/transition calls, the exact calls
`maistro.graph.seeds.pack_fixtures` makes — into a durable store an operator
names. Nothing here seeds by direct insert, ships fixture JSON, or touches a
frontend store.

This module exists because reachability is a floor, not a nicety: a fixture
library only tests import is built-but-never-wired, and the reachability gate
(rightly) refuses it as new unreachable debt. A deployment that wants the
fixtures inspectable in Design Studio runs this once against its store; the
printed Run identities are then canonical and durable — a refresh, a
reconnect, or a process restart shows the same ids.

Seeding is a provisioning step, not an upsert: each invocation appends fresh
fixture Runs under the same canonical Workspace/Project ids. Re-run it only
when you want another copy.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import aiosqlite
from rich.console import Console
from rich.table import Table
from typer import Option, Typer

from maistro.graph.seeds.pack_fixtures import (
    PACK_FIXTURE_WORKSPACE_ID,
    open_pack_fixture,
    seed_book_fixture,
    seed_game_fixture,
)
from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
from maistro.runs import SqliteRunStore

console = Console()
app = Typer(help="Seed the #989 book/game pack fixtures into a durable canonical store.")

# The command function is this module's public surface: it is registered on
# `app` by decorator, invoked through Typer dispatch, and exercised by name in
# tests. Declaring the exports here says so to static analysis (the same
# declaration `graph/seeds/pack_fixtures.py` carries) instead of banking a
# known-live command as vulture debt.
__all__ = ["app", "fixtures_seed"]


async def _seed(db_path: Path) -> list[dict[str, Any]]:
    """Open one SQLite store, seed both fixtures, return their open payloads."""
    conn = await aiosqlite.connect(db_path)
    try:
        projects = SqliteProjectScopeStore(conn)
        await projects.ensure_schema()
        runs = SqliteRunStore(conn, project_store=projects)
        await runs.ensure_schema()
        book = await seed_book_fixture(runs, projects)
        game = await seed_game_fixture(runs, projects)
        return [
            await open_pack_fixture(runs, book.run_id),
            await open_pack_fixture(runs, game.run_id),
        ]
    finally:
        await conn.close()


@app.command("seed")
def fixtures_seed(
    db_path: Annotated[
        Path,
        Option(
            "--db",
            help="SQLite database file to provision (created if absent).",
            show_default=False,
        ),
    ],
    json_output: Annotated[
        bool,
        Option("--json", help="Print the full open payloads instead of a table."),
    ] = False,
) -> None:
    """Seed the book and game fixture Runs through the canonical spine.

    Both fixtures land in the shared `m7-pack-fixtures` Workspace/Project and
    stay exactly what Design Studio reads through `GET /v1/dag-runs`: the book
    Run completes (accepted), the game Run parks (WAITING, resumable). Opening
    a fixture never executes explore/judge — these Runs carry no registered
    executors, only recorded evidence.
    """
    payloads = asyncio.run(_seed(db_path))
    if json_output:
        console.print_json(json.dumps(payloads))
        return

    table = Table("pack", "run_id", "status", "fence", "goal rev", "rubric rev")
    for payload in payloads:
        fence = payload.get("fence_decision")
        decision = fence.get("decision") if isinstance(fence, dict) else fence
        table.add_row(
            str(payload["pack"]),
            str(payload["run_id"]),
            str(payload["status"]),
            str(decision or "—"),
            str(payload.get("goal_revision", "—")),
            str(payload.get("rubric_revision", "—")),
        )
    console.print(table)
    console.print(
        f"workspace [bold]{PACK_FIXTURE_WORKSPACE_ID}[/bold] in [bold]{db_path}[/bold]: "
        "give the reviewer's principal canonical membership on this workspace and the "
        "Runs appear in the Design Studio run list — open by run_id, no explore/judge run."
    )

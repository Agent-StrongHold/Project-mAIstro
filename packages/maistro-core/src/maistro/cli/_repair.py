"""`maistro repair` — operator commands for durable records that need correcting.

One subcommand today: `attempt-outputs`, for Attempts emptied by the pre-#566
serialization (ADR-083026-14c3).

The store is resolved the way the running system resolves it — through
`resolve_database_url` and `wire_execution_spine` — rather than from a path the
operator types. That is the correction this command exists to be: its withdrawn
predecessor took a filesystem `Path`, which meant it could not address a
PostgreSQL deployment at all and, against a SQLite one, opened a table nothing
writes and reported it clean.

Survey by default. `--apply` is the only thing that writes.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from rich.console import Console
from rich.table import Table
from typer import Option, Typer

from maistro.config.database import resolve_database_url
from maistro.runs.repair import DEFAULT_SWEEP_LIMIT, Survey, repair, survey

console = Console()
app = Typer(help="Correct durable records that a shipped defect wrote wrongly.")


@app.command("attempt-outputs")
def attempt_outputs(
    apply: Annotated[
        bool, Option("--apply", help="Write the repairs. Without this, nothing is written.")
    ] = False,
    workspace_id: Annotated[str, Option(help="Workspace whose spine to open.")] = "default",
    limit: Annotated[
        int, Option(help="Runs to examine per status in one sweep.")
    ] = DEFAULT_SWEEP_LIMIT,
) -> None:
    """Report — and with --apply, correct — Attempts whose output was emptied."""
    asyncio.run(_run(apply=apply, workspace_id=workspace_id, limit=limit))


async def _run(*, apply: bool, workspace_id: str, limit: int) -> None:
    database_url = resolve_database_url()
    store, closer = await _open_store(database_url, workspace_id)
    try:
        found = await survey(store, limit=limit)
        _report(found)
        if not apply:
            if found.repairable:
                console.print(
                    f"\n{len(found.repairable)} repairable. "
                    "Re-run with --apply to write the corrections."
                )
            return
        applied = await repair(store, found.findings)
        console.print(f"\nRepaired {len(applied)} Attempt(s).")
    finally:
        await closer()


async def _open_store(database_url: str, workspace_id: str) -> tuple[Any, Any]:
    """The configured canonical Run store, and how to close what it opened.

    `wire_execution_spine` picks the backend the deployment actually uses, so
    this command reaches PostgreSQL and SQLite by the same route the runtime
    does rather than by a second opinion about which store is live.
    """
    from maistro.runs.wiring import wire_execution_spine

    if database_url.startswith("sqlite:"):
        import aiosqlite

        conn = await aiosqlite.connect(database_url.removeprefix("sqlite:///"))
        _projects, store, *_rest = await wire_execution_spine(conn, workspace_id=workspace_id)
        return store, conn.close

    from maistro.config.database import to_asyncpg_dsn
    from maistro.persistence import get_pool

    pool = await get_pool(to_asyncpg_dsn(database_url))
    _projects, store, *_rest = await wire_execution_spine(
        None, workspace_id=workspace_id, pg_pool=pool
    )
    return store, pool.close


def _report(found: Survey) -> None:
    """Print what the sweep saw, including what it could not see."""
    console.print(f"Examined {found.runs_examined} run(s).")
    if not found.findings:
        console.print("No Attempt holds an emptied output.")
    else:
        table = Table("run_id", "attempt_id", "disposition")
        for finding in found.findings:
            table.add_row(finding.run_id, finding.attempt_id, finding.disposition.value)
        console.print(table)
    if not found.complete:
        # Stated, never omitted. A partial sweep read as a complete one is the
        # same defect as the survey that opened the wrong table.
        statuses = ", ".join(status.value for status in found.truncated_statuses)
        console.print(
            f"[yellow]This sweep stopped at its limit for: {statuses}. "
            "There may be more; re-run with a higher --limit.[/yellow]"
        )


__all__ = ["app"]

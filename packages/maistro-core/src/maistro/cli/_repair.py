"""`maistro repair` subcommand — restore node outputs an old contract emptied.

The door for SPEC-082926-2844's recovery. `NodeResult.output` was declared with
a bare `BaseModel` union member, whose schema has no fields, so a node returning
a typed model persisted its Attempt as `output: {}` (#566). The contract is
fixed; rows already written are not, and a repair nobody can invoke does not
repair anything.

Two commands, deliberately separate. `survey` reads and reports and writes
nothing, so an operator can see the damage before deciding. `apply` writes the
restorable ones back. Nothing here runs on its own: rewriting stored execution
history is the operator's call, not a startup side effect.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from rich.console import Console
from rich.table import Table
from typer import Argument, Option, Typer

from maistro.graph.durable_runs.repair import (
    OutputRecoveryReport,
    recover_typed_attempt_outputs,
)
from maistro.graph.durable_runs.stores import SqliteDurableRunStore

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.graph.durable_runs.types import DurableRunRecord

console = Console()
app = Typer(help="Restore Attempt outputs emptied by the superseded serialization contract.")

DbPath = Annotated[Path, Argument(help="Path to a durable-run database.")]
ProjectId = Annotated[str, Argument(help="Project whose runs to examine.")]
Limit = Annotated[int, Option("--limit", help="Most recent runs to examine.")]


async def _load(db_path: Path, project_id: str, limit: int) -> list[DurableRunRecord]:
    store = SqliteDurableRunStore(db_path)
    return await store.list_for_project(project_id, limit=limit)


def _report_table(reports: list[tuple[str, OutputRecoveryReport]]) -> Table:
    table = Table("run_id", "recoverable", "unrecoverable", "why not")
    for run_id, report in reports:
        reasons = sorted({entry.reason for entry in report.unrecoverable if entry.reason})
        table.add_row(
            run_id,
            str(len(report.recovered)),
            str(len(report.unrecoverable)),
            "; ".join(reasons) or "—",
        )
    return table


def _examine(
    db_path: Path, project_id: str, limit: int
) -> list[tuple[DurableRunRecord, OutputRecoveryReport]]:
    records = asyncio.run(_load(db_path, project_id, limit))
    examined = [recover_typed_attempt_outputs(record) for record in records]
    return [
        (repaired, report)
        for repaired, report in examined
        if report.recovered or report.unrecoverable
    ]


@app.command("survey")
def repair_survey(db_path: DbPath, project_id: ProjectId, limit: Limit = 25) -> None:
    """Report which Attempt outputs can be restored. Writes nothing."""
    affected = _examine(db_path, project_id, limit)
    if not affected:
        console.print("No emptied Attempt outputs.")
        return
    console.print(_report_table([(record.run_id, report) for record, report in affected]))
    console.print("[dim]Read-only. Run `maistro repair apply` to write these back.[/dim]")


@app.command("apply")
def repair_apply(db_path: DbPath, project_id: ProjectId, limit: Limit = 25) -> None:
    """Write back every Attempt output that can be restored exactly."""
    affected = _examine(db_path, project_id, limit)
    writable = [(record, report) for record, report in affected if report.changed]
    if not writable:
        console.print("Nothing to restore.")
    else:
        store = SqliteDurableRunStore(db_path)
        for record, report in writable:
            asyncio.run(store.update(record))
            console.print(f"{record.run_id}: restored {len(report.recovered)} Attempt output(s)")

    stranded = sum(len(report.unrecoverable) for _record, report in affected)
    if stranded:
        console.print(
            f"[yellow]{stranded} Attempt output(s) stay empty: nothing in the record "
            "holds what they produced.[/yellow]"
        )

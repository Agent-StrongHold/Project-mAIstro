"""`maistro archive` subcommand — read durable graph runs from before the convergence.

The entry point that makes #44's fifth criterion true in practice rather than in
principle. `LegacyGraphRunArchive` can reproduce a pre-convergence run, but a
library nobody can invoke does not make history reachable: the operator holding
a database written before #565 needs a way to open it.

Read-only throughout. These runs cannot be resumed — their Run, NodeRun and
Attempt identities were never admitted to the canonical spine — so the commands
here inspect and never write.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from rich.console import Console
from rich.table import Table
from typer import Argument, Typer

from maistro.graph.durable_runs.legacy_archive import LegacyGraphRunArchive

console = Console()
app = Typer(help="Inspect durable graph runs persisted before the store convergence.")


@app.command("list")
def archive_list(
    db_path: Annotated[Path, Argument(help="Path to a pre-convergence durable-run database.")],
) -> None:
    """List every archived run, oldest first."""
    archive = LegacyGraphRunArchive(db_path)
    run_ids = archive.list_run_ids()
    if not run_ids:
        console.print("No archived runs.")
        return

    table = Table("run_id", "status", "nodes", "attempts")
    for run_id in run_ids:
        run = archive.get(run_id)
        if run is None:  # pragma: no cover - listed ids always resolve
            continue
        table.add_row(
            run.run_id,
            run.run.status.value,
            str(len(run.node_runs)),
            str(len(run.attempts)),
        )
    console.print(table)


@app.command("show")
def archive_show(
    db_path: Annotated[Path, Argument(help="Path to a pre-convergence durable-run database.")],
    run_id: Annotated[str, Argument(help="The archived run to reproduce.")],
) -> None:
    """Reproduce one archived run: its Run, NodeRuns and Attempts."""
    archived = LegacyGraphRunArchive(db_path).get(run_id)
    if archived is None:
        console.print(f"No archived run {run_id!r}.")
        return

    console.print(
        f"[bold]{archived.run_id}[/bold]  {archived.run.status.value}  "
        f"workspace={archived.run.workspace_id}  project={archived.run.project_id}"
    )
    table = Table("node_id", "ordinal", "status", "attempts")
    for node_run in archived.node_runs:
        attempts = archived.attempts_for(node_run.node_run_id)
        table.add_row(
            node_run.node_id,
            str(node_run.ordinal),
            node_run.status.value,
            ", ".join(item.status.value for item in attempts) or "—",
        )
    console.print(table)
    console.print(
        f"traversal: {len(archived.traversal_checkpoints)} checkpoint(s), "
        f"{len(archived.traversal_commits)} commit(s)"
    )
    console.print(
        "[dim]Read-only: this run predates the canonical store convergence and "
        "cannot be resumed.[/dim]"
    )

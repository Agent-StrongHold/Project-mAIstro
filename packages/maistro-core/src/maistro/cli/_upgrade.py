"""`maistro upgrade` subcommand — pull latest updates, preserve config."""

from __future__ import annotations

import subprocess

from rich.console import Console
from typer import Typer

from maistro.security.warden.sanitizer import strip_terminal_escapes

app = Typer(help="Upgrade maistro to the latest version.")
console = Console()


@app.callback(invoke_without_command=True)
def upgrade_main() -> None:
    """Pull the latest updates from the repo, preserving compatible configuration."""
    console.print("[bold]maistro upgrade[/bold]")

    try:
        result = subprocess.run(
            ["git", "pull", "--rebase", "--autostash"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            console.print(f"[green]{strip_terminal_escapes(result.stdout.strip())}[/green]")
        else:
            console.print(f"[yellow]{strip_terminal_escapes(result.stderr.strip())}[/yellow]")
    except FileNotFoundError:
        console.print("[red]git not found[/red]")
        return
    except subprocess.TimeoutExpired:
        console.print("[red]git pull timed out[/red]")
        return

    console.print("\n[bold]Syncing dependencies...[/bold]")
    try:
        subprocess.run(["uv", "sync", "--all-extras"], check=True, timeout=120)
        console.print("[green]Dependencies synced.[/green]")
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        console.print(f"[red]Dependency sync failed: {exc}[/red]")

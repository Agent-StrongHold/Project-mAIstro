"""`maistro launch` subcommand — start server or TUI."""

from __future__ import annotations

import os
import sys

from rich.console import Console
from typer import Typer

app = Typer(help="Launch maistro services.")
console = Console()


@app.command("server")
def launch_server(
    host: str = "0.0.0.0",  # nosec B104 — intentional default for the self-hosted server CLI; user-overridable flag
    port: int = 8000,
    reload: bool = False,
) -> None:
    """Start the maistro API server (uvicorn)."""
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "maistro_server.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if reload:
        cmd.append("--reload")

    console.print(f"[bold]Starting maistro server on {host}:{port}[/bold]")
    os.execvp(cmd[0], cmd)


@app.command("tui")
def launch_tui() -> None:
    """Launch the maistro dashboard TUI (placeholder)."""
    console.print("[yellow]maistro dashboard TUI — coming soon[/yellow]")
    console.print("Use [bold]maistro builders[/bold] for the interactive coding TUI.")

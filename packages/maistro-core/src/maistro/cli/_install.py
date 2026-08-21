"""`maistro install` subcommand — delegates to maistro_bootstrap.

Thin wrapper: if maistro-bootstrap is installed, delegate the entire
argv to its Typer app. If not, print a helpful error.
"""

from __future__ import annotations

import sys

from typer import Typer

app = Typer(help="Add, remove, and configure maistro components.")


@app.callback(invoke_without_command=True)
def install_main() -> None:
    """Run the interactive installer / component manager."""
    try:
        from maistro_bootstrap.cli import run

        run()
    except ImportError:
        from rich.console import Console

        Console().print(
            "[red]maistro-bootstrap is not installed.[/red]\n"
            "Install it with: [bold]uv sync --extra bootstrap[/bold]"
        )
        sys.exit(1)

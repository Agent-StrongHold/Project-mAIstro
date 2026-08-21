"""`maistro builders` — interactive coding app.

Just run `maistro builders` and it opens the app. From there you can:
  - Open a repo (paste a git URL or browse)
  - Resume a previous session
  - Start coding with the AI agent

That's it. No flags needed.
"""

from __future__ import annotations

import typer
from rich.console import Console

app = typer.Typer(
    help="Interactive AI coding environment.",
    invoke_without_command=True,
    no_args_is_help=False,
)
console = Console()


@app.callback()
def builders_main() -> None:
    """Launch the builders interactive app."""
    _launch_app()


def _launch_app() -> None:
    try:
        from maistro.cli._builders_tui import BuildersApp

        app_instance = BuildersApp()
        app_instance.run()
    except ImportError:
        console.print(
            "[red]Textual is not installed.[/red]\n"
            "Install it with: [bold]uv sync --extra bootstrap[/bold]"
        )
        raise typer.Exit(1) from None

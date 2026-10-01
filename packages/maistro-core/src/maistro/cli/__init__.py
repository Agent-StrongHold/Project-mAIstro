"""`maistro` unified command-line interface.

Subcommands:
    maistro install          Add/remove/configure components
    maistro upgrade          Pull latest updates, preserve config
    maistro launch server    Start the API server
    maistro launch tui       Start the dashboard TUI
    maistro builders         Interactive coding sessions in isolated containers
    maistro approvals        Manage the HITL approval inbox
    maistro security         Rotate the credential master key, revoke sessions
    maistro archive          Read durable graph runs from before the convergence
    maistro sandbox          Report the isolation this host can provide

Config via env: MAISTRO_API_URL (default http://127.0.0.1:8101),
MAISTRO_API_TOKEN (bearer session token).
"""

from __future__ import annotations

from typer import Typer

app = Typer(
    name="maistro",
    help="mAIstro — AI agent platform CLI",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

from maistro.cli._approvals import app as _approvals_app  # noqa: E402
from maistro.cli._archive import app as _archive_app  # noqa: E402
from maistro.cli._builders import app as _builders_app  # noqa: E402
from maistro.cli._install import app as _install_app  # noqa: E402
from maistro.cli._launch import app as _launch_app  # noqa: E402
from maistro.cli._repair import app as _repair_app  # noqa: E402
from maistro.cli._sandbox import app as _sandbox_app  # noqa: E402
from maistro.cli._security import app as _security_app  # noqa: E402
from maistro.cli._upgrade import app as _upgrade_app  # noqa: E402

app.add_typer(_install_app, name="install")
app.add_typer(_upgrade_app, name="upgrade")
app.add_typer(_launch_app, name="launch")
app.add_typer(_builders_app, name="builders")
app.add_typer(_approvals_app, name="approvals")
app.add_typer(_security_app, name="security")
app.add_typer(_archive_app, name="archive")
app.add_typer(_sandbox_app, name="sandbox")
app.add_typer(_repair_app, name="repair")


def main() -> None:
    app()

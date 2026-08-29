"""`maistro sandbox` subcommand — what isolation this host can actually provide.

The operational half of `docs/security/SANDBOX-SUPPORT-MATRIX.md`. That page
says what each tier requires and what happens when a host cannot reach it; this
command answers the question an operator actually has, which is *which tier does
my machine give me, and if not the one I expected, why not*.

That question is not rhetorical here. A host with only bubblewrap refuses
`UNTRUSTED_CODE` outright, and a host where `bwrap` is installed but
unprivileged user namespaces are restricted refuses it too while looking
identical from the outside. The difference is a line of `notes`, and before
this command there was no way to read it short of importing the library.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from typer import Typer

from maistro.sandbox.detect import detect_host_capabilities
from maistro.sandbox.policy import _TIER_ORDER
from maistro.sandbox.wiring import build_selector

console = Console()
app = Typer(help="Inspect the isolation this host can provide.")


@app.command("status")
def sandbox_status() -> None:
    """Report the isolation tiers this host provides, and why any are missing."""
    capabilities = detect_host_capabilities()
    selector = build_selector(capabilities=capabilities)

    table = Table("tier", "available", "backend", "why not")
    registered = set(selector.available_tiers)
    for tier in _TIER_ORDER:
        if tier == "fake":
            continue
        available = capabilities.supports(tier)
        backend = "registered" if tier in registered else "—"
        table.add_row(
            tier,
            "yes" if available else "no",
            backend if available else "—",
            "" if available else capabilities.notes.get(tier, ""),
        )
    console.print(table)

    strongest = capabilities.strongest
    console.print(f"strongest available tier: [bold]{strongest or 'none'}[/bold]")
    if not selector.available_tiers:
        console.print(
            "[bold red]No sandbox backend is available.[/bold red] "
            "Every workload will be refused — there is no bare-subprocess tier."
        )

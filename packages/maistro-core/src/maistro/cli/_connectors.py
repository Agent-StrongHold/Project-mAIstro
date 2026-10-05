"""`maistro connectors` subcommand — run shared conformance for a connector.

The operator/developer surface for M9-E2 (issue #963): before a connector —
built-in or third-party — is installed anywhere, this command loads it by
module path, runs the same conformance suite the host runs, and reports the
violations. It never ingests into a durable store: conformance builds its own
in-memory stores, so a verification run leaves no records behind.
"""

from __future__ import annotations

import asyncio
import importlib
from typing import Annotated

from rich.console import Console
from typer import Argument, Exit, Option, Typer

from maistro.connectors import ConnectorSource, run_connector_conformance

console = Console()
app = Typer(help="Verify a connector against the shared conformance suite.")


def _load_source(ref: str) -> ConnectorSource:
    """Resolve a ``module:ClassName`` (or ``module.ClassName``) reference."""
    module_ref, _, class_ref = ref.partition(":")
    if not class_ref:
        module_ref, _, class_ref = ref.rpartition(".")
    try:
        module = importlib.import_module(module_ref)
        source = getattr(module, class_ref)()
    except (ImportError, AttributeError, TypeError) as exc:
        console.print(f"[red]Cannot load connector {ref!r}: {exc}[/red]")
        raise Exit(code=1) from exc
    if not isinstance(source, ConnectorSource):
        console.print(f"[red]{ref!r} does not implement the ConnectorSource protocol.[/red]")
        raise Exit(code=1)
    return source


def _print_report(ref: str, violations: tuple[str, ...]) -> None:
    """Print the conformance verdict as plain lines (CI-width friendly)."""
    if not violations:
        console.print(f"[green]conformant[/green] {ref}: all shared checks passed")
        return
    console.print(f"{ref}: {len(violations)} violation(s)")
    for violation in violations:
        console.print(f"  [red]FAIL[/red] {violation}")


@app.command("verify")
def connectors_verify(
    source_ref: Annotated[str, Argument(help="Connector as 'module:ClassName'.")],
    workspace: Annotated[
        list[str] | None,
        Option(help="Workspace id(s) the connector instance may ingest into."),
    ] = None,
) -> None:
    """Run the shared connector conformance suite; exit 1 on any violation."""
    source = _load_source(source_ref)
    violations = asyncio.run(
        run_connector_conformance(source, workspace_ids=workspace or ["default"])
    )
    _print_report(source_ref, violations)
    if violations:
        raise Exit(code=1)


@app.command("describe")
def connectors_describe(
    source_ref: Annotated[str, Argument(help="Connector as 'module:ClassName'.")],
) -> None:
    """Print what a connector declares: id, version, capabilities, secrets."""
    source = _load_source(source_ref)
    descriptor = source.descriptor
    console.print(f"[bold]{descriptor.connector_id}[/bold] @ {descriptor.version}")
    console.print(
        f"  capabilities: {', '.join(sorted(c.value for c in descriptor.capabilities)) or 'none'}"
    )
    if descriptor.secret_refs:
        console.print("  declared secrets:")
        for ref in descriptor.secret_refs:
            console.print(f"    {ref.name}: {ref.description}")
    else:
        console.print("  declared secrets: none")

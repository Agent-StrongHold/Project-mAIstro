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

from maistro.connectors import (
    ConnectorSource,
    StaticSecretAuthority,
    run_connector_conformance,
)

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
    """Print the conformance verdict as plain lines (CI-width friendly).

    Violations print unwrapped: they name identities and error messages a
    human or a CI log greps for, and rich's soft wrap would split a message
    like ``no secret provisioned for 'api_token' in workspace 'ws-primary'``
    mid-phrase at whatever the ambient width is.
    """
    if not violations:
        console.print(f"[green]conformant[/green] {ref}: all shared checks passed")
        return
    console.print(f"{ref}: {len(violations)} violation(s)")
    for violation in violations:
        console.print(f"  [red]FAIL[/red] {violation}", soft_wrap=True)


def _parse_secret_provisions(provisions: list[str], declared_names: set[str]) -> dict[str, str]:
    """Parse ``NAME=VALUE`` options into {name: value}; refuse undeclared names.

    An undeclared provision is refused rather than ignored: verify checks the
    declaration installers approve, and silently provisioning a name the
    descriptor does not declare would verify a different contract than the
    one being shipped.
    """
    values: dict[str, str] = {}
    for provision in provisions:
        name, sep, value = provision.partition("=")
        if not sep or not name:
            console.print(f"[red]--secret expects NAME=VALUE, got {provision!r}[/red]")
            raise Exit(code=1)
        if name not in declared_names:
            declared = ", ".join(sorted(declared_names)) or "none"
            console.print(
                f"[red]secret {name!r} is not declared on this connector's descriptor "
                f"(declared: {declared})[/red]"
            )
            raise Exit(code=1)
        values[name] = value
    return values


@app.command("verify")
def connectors_verify(
    source_ref: Annotated[str, Argument(help="Connector as 'module:ClassName'.")],
    workspace: Annotated[
        list[str] | None,
        Option(help="Workspace id(s) the connector instance may ingest into."),
    ] = None,
    secret: Annotated[
        list[str] | None,
        Option(
            "--secret",
            help="Provision a declared secret for this run, as NAME=VALUE. Repeatable.",
        ),
    ] = None,
) -> None:
    """Run the shared connector conformance suite; exit 1 on any violation.

    Declared secrets resolve through an authority bound for the run: names
    provisioned with ``--secret NAME=VALUE`` resolve to the given value in
    every declared Workspace, and declared-but-unprovisioned names raise the
    canonical LookupError naming the missing (Workspace, secret) pair — an
    operator gap, not a connector violation of a different kind.
    """
    source = _load_source(source_ref)
    workspaces = workspace or ["default"]
    values = _parse_secret_provisions(
        secret or [], {ref.name for ref in source.descriptor.secret_refs}
    )
    authority = StaticSecretAuthority(
        {
            (workspace_id, name): value
            for workspace_id in workspaces
            for name, value in values.items()
        }
    )
    violations = asyncio.run(
        run_connector_conformance(source, workspace_ids=workspaces, secrets=authority)
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

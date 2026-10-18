"""`maistro conformance` subcommand — run the extension-family conformance suite.

The operational half of the shared extension conformance framework (M9-E4,
issue #965). Extension implementers register a
:class:`~maistro.conformance.ConformanceSubject` under the
``maistro.conformance`` entry-point group; this command discovers every
registered subject, runs the shared cross-cutting checks (secret references,
egress, scope, error/cancellation normalization, usage provenance, bypass
refusal) against each, and exits non-zero unless every subject supports a
valid conformance claim.

Set ``MAISTRO_REQUIRE_REAL_BACKEND_LEGS`` to make a skipped required
real-backend leg fatal instead of a documented skip.
"""

from __future__ import annotations

import asyncio

from rich.console import Console
from typer import Typer

from maistro.conformance.contract import (
    ALL_FAMILIES,
    ENTRY_POINT_GROUP,
    ConformanceFailure,
    SubjectFamily,
)
from maistro.conformance.runner import render_report, run_registered_subjects

console = Console()
app = Typer(help="Run the shared extension conformance suite (issue #965).")


@app.command("run")
def conformance_run() -> None:
    """Run every registered conformance subject and print the reports."""
    try:
        reports = asyncio.run(run_registered_subjects(ENTRY_POINT_GROUP))
    except ConformanceFailure as exc:
        console.print(f"[bold red]conformance failed:[/bold red] {exc}")
        raise SystemExit(1) from exc
    for report in reports:
        console.print(render_report(report))
        console.print()
    console.print(
        f"[bold green]{len(reports)} subject(s) conform[/bold green] "
        "(reports name the exact tested contract/version and backend)."
    )


@app.command("subjects")
def conformance_subjects() -> None:
    """List the conformance subjects registered on this installation."""
    from maistro.conformance.runner import discover_subjects

    subjects = discover_subjects(ENTRY_POINT_GROUP)
    if not subjects:
        console.print(
            "no conformance subjects registered — implement "
            "ConformanceSubject and register it under the 'maistro.conformance' "
            "entry-point group"
        )
        return
    for subject in subjects:
        descriptor = subject.descriptor
        console.print(
            f"{descriptor.name}: family={descriptor.family.value} "
            f"declared-contract={descriptor.declared_contract_version}"
        )
    covered = {subject.descriptor.family for subject in subjects}
    missing = [family.value for family in ALL_FAMILIES if family not in covered]
    if missing:
        console.print(f"families with no registered subject: {', '.join(missing)}")
    else:
        console.print(f"all {len(SubjectFamily)} supported families have a registered subject")


#: The command callbacks this module registers on ``app``, named so the
#: command surface stays inspectable.
REGISTERED_COMMANDS = (conformance_run, conformance_subjects)


def _require_commands_registered() -> None:
    """Fail at import if a decorator name drifts off the declared surface."""
    registered = {command.callback for command in app.registered_commands}
    missing = [callback.__name__ for callback in REGISTERED_COMMANDS if callback not in registered]
    if missing:
        raise RuntimeError(f"conformance commands missing from the CLI app: {missing}")


_require_commands_registered()

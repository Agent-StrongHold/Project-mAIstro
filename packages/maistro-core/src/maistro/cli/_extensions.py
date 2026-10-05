"""`maistro extensions` subcommand — inspect install records, preflight compat.

Read-only throughout, like `maistro archive`: the history/show commands open
the SQLite install-record store in read-only mode and report what was
installed, by whom, from which catalog, with which digest, and with what
trust evidence. They never verify, never import, and never write — the
install flow that produces records lands with #953, and these records
outlive it either way.

`compat` (#955) is the contract-compatibility preflight: it negotiates an
extension's declared contract metadata against this host's — metadata only,
so it runs before any extension code import by construction.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from rich.console import Console
from rich.table import Table
from typer import Argument, Exit, Option, Typer

from maistro.extensions.compat import (
    CompatibilityReport,
    CompatMetadataError,
    ExtensionCompatMetadata,
    HostContractMetadata,
    Verdict,
    negotiate,
    parse_compat_metadata,
)
from maistro.extensions.sqlite_store import SqliteExtensionInstallStore

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Awaitable, Callable

    from maistro.extensions.types import InstallRecord

console = Console()
app = Typer(help="Inspect install records (publisher, digest, trust); preflight contract compat.")


def _short_digest(digest: str) -> str:
    """Short display form of a hex digest; ``—`` when absent."""
    return f"{digest[:12]}…" if digest else "—"


def _short_timestamp(iso: str) -> str:
    """Compact display form of an ISO-8601 timestamp."""
    return iso.replace("T", " ")[:19]


async def _read_only(
    db_path: Path, operation: Callable[[SqliteExtensionInstallStore], Awaitable[object]]
) -> object:
    """Run one read operation against the store, opening the database read-only."""
    try:
        import aiosqlite
    except ImportError as exc:  # pragma: no cover - depends on install extras
        console.print(
            "[red]maistro extensions reads a SQLite install-record database, "
            "which needs maistro-core's [sqlite] extra (uv sync --extra sqlite)[/red]"
        )
        raise Exit(code=1) from exc
    conn = await aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return await operation(SqliteExtensionInstallStore(conn))
    finally:
        await conn.close()


def _print_history(records: list[InstallRecord]) -> None:
    """Print one row per install record, oldest first.

    Kept to five narrow columns so the table renders un-elided at CI's pinned
    80-column width; `show` is the full-detail view.
    """
    if not records:
        console.print("No install records.")
        return
    table = Table("installed_at", "version", "package", "publisher", "trust")
    for record in records:
        table.add_row(
            _short_timestamp(record.installed_at.isoformat()),
            record.identity.semantic_version,
            _short_digest(record.identity.package_sha256),
            record.publisher.publisher_id,
            "verified" if record.evidence.verified else "unverified",
        )
    console.print(table)


@app.command("history")
def extensions_history(
    db_path: Annotated[Path, Argument(help="Path to the extension install SQLite database.")],
    extension_name: Annotated[str, Argument(help="Extension to report history for.")],
) -> None:
    """List every install record for one extension, oldest first."""
    try:
        records = asyncio.run(_read_only(db_path, lambda s: s.install_history(extension_name)))
    except sqlite3.OperationalError as exc:
        console.print(f"[red]Cannot open {db_path}: {exc}[/red]")
        raise Exit(code=1) from exc
    assert isinstance(records, list)
    _print_history(records)


@app.command("show")
def extensions_show(
    db_path: Annotated[Path, Argument(help="Path to the extension install SQLite database.")],
    extension_name: Annotated[str, Argument(help="Extension to inspect.")],
    semantic_version: Annotated[str, Argument(help="Semantic version to inspect.")],
) -> None:
    """Show the full record — provenance, manifest digest, trust evidence."""
    try:
        records = asyncio.run(_read_only(db_path, lambda s: s.install_history(extension_name)))
    except sqlite3.OperationalError as exc:
        console.print(f"[red]Cannot open {db_path}: {exc}[/red]")
        raise Exit(code=1) from exc
    assert isinstance(records, list)
    matching = [r for r in records if r.identity.semantic_version == semantic_version]
    if not matching:
        console.print(
            f"[red]No install record for {extension_name}@{semantic_version} in {db_path}.[/red]"
        )
        raise Exit(code=1)
    for record in matching:
        console.print(
            f"[bold]{record.identity.extension_name}@{record.identity.semantic_version}[/bold]"
        )
        console.print(f"  install_id:    {record.install_id}")
        console.print(f"  installed_at:  {_short_timestamp(record.installed_at.isoformat())}")
        console.print(
            f"  publisher:     {record.publisher.publisher_id} ({record.publisher.display_name})"
        )
        console.print(f"  signing key:   {_short_digest(record.publisher.signing_key_fingerprint)}")
        console.print(f"  package:       sha256:{record.identity.package_sha256}")
        console.print(f"  manifest:      sha256:{record.identity.manifest_sha256}")
        console.print(f"  signature:     {_short_digest(record.signature)}")
        console.print(f"  catalog:       {record.provenance.catalog_url}")
        console.print(
            f"  catalog snap:  sha256:{record.provenance.catalog_snapshot_sha256} "
            f"({_short_timestamp(record.provenance.retrieved_at.isoformat())})"
        )
        console.print(
            f"  evidence:      verified={record.evidence.verified} "
            f"policy={record.evidence.policy} subject=sha256:{record.evidence.subject_sha256} "
            f"by key {_short_digest(record.evidence.verifier_key_fingerprint)} "
            f"at {_short_timestamp(record.evidence.verified_at.isoformat())}"
        )


def _load_compat_metadata(metadata_path: Path) -> ExtensionCompatMetadata:
    """Read and parse one extension's compatibility-metadata JSON file."""
    try:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    except OSError as exc:
        console.print(f"[red]Cannot read {metadata_path}: {exc}[/red]")
        raise Exit(code=1) from exc
    except json.JSONDecodeError as exc:
        console.print(f"[red]{metadata_path} is not valid JSON: {exc}[/red]")
        raise Exit(code=1) from exc
    try:
        return parse_compat_metadata(raw)
    except CompatMetadataError as exc:
        console.print(f"[red]{metadata_path}: {exc}[/red]")
        raise Exit(code=1) from exc


def _print_compat_report(report: CompatibilityReport, host: HostContractMetadata) -> None:
    """Render the negotiation report; the machine-readable form is --json."""
    style = {
        Verdict.COMPATIBLE: "green",
        Verdict.DEGRADED: "yellow",
        Verdict.INCOMPATIBLE: "red",
    }[report.verdict]
    console.print(f"[bold {style}]Verdict: {report.verdict.value}[/bold {style}]")
    for reason in report.reasons:
        console.print(f"[red]incompatible: {reason}[/red]")
    if report.degradations:
        table = Table("degraded feature", "why it is withheld")
        for degradation in report.degradations:
            table.add_row(degradation.feature, degradation.reason)
        console.print(table)
    if report.deprecations:
        table = Table("deprecated feature", "status", "removal target", "migration")
        for notice in report.deprecations:
            table.add_row(
                notice.feature,
                notice.status.value,
                "—" if notice.removal_target is None else str(notice.removal_target),
                notice.migration,
            )
        console.print(table)
    console.print(f"host contract: {host.contract_version} (majors {list(host.supported_majors)})")
    granted = ", ".join(report.supported_features) if report.supported_features else "none"
    console.print(f"features granted: {granted}")


@app.command("compat")
def extensions_compat(
    metadata_path: Annotated[
        Path, Argument(help="JSON file with the extension's compatibility metadata.")
    ],
    json_output: Annotated[
        bool,
        Option("--json", help="Emit the machine-readable report instead of the table."),
    ] = False,
) -> None:
    """Negotiate an extension's contract metadata against this host.

    Decides compatibility from metadata alone — the extension's code is never
    imported, so a manifest can be rejected before anything executes. Exits
    non-zero when the verdict is incompatible (the preflight signal), with the
    actionable reasons on stderr-free stdout either way.
    """
    metadata = _load_compat_metadata(metadata_path)
    host = HostContractMetadata.current()
    report = negotiate(host, metadata)
    if json_output:
        console.print_json(json.dumps(report.to_dict()))
    else:
        _print_compat_report(report, host)
    if report.verdict is Verdict.INCOMPATIBLE:
        raise Exit(code=1)

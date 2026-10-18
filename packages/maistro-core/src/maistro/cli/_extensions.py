"""`maistro extensions` subcommand — inspect durable extension install records.

Read-only throughout, like `maistro archive`: these commands open the SQLite
install-record store in read-only mode and report what was installed, by whom,
from which catalog, with which digest, and with what trust evidence. They never
verify, never import, and never write — the install flow that produces records
lands with #953, and these records outlive it either way.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from rich.console import Console
from rich.table import Table
from typer import Argument, Exit, Typer

from maistro.extensions.sqlite_store import SqliteExtensionInstallStore

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Awaitable, Callable

    from maistro.extensions.types import InstallRecord

console = Console()
app = Typer(help="Inspect durable extension install records (publisher, digest, trust).")


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

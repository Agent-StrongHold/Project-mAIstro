"""`maistro extensions` subcommand — inspect install records and contracts.

Read-only throughout, like `maistro archive`: `history`/`show` open the SQLite
install-record store in read-only mode and report what was installed, by whom,
from which catalog, with which digest, and with what trust evidence. They never
verify, never import, and never write — the install flow that produces records
lands with #953, and these records outlive it either way.

`contract` (M9-E3, #964) validates a package's tool/Skill manifest against the
published closed vocabularies and reports the host classification — without
importing the manifest's entrypoint module.

The `lock` and `explain` commands (M9-C2, #956) read a resolved lock file —
the reproducible output of dependency resolution: which extension versions are
pinned, from which source, and why each one and its version were selected.
They are likewise read-only: a lock file is evidence about a decision already
made, and these commands never rewrite it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from rich.console import Console
from rich.table import Table
from typer import Argument, Exit, Typer

from maistro.extensions.resolution import LockFormatError, LockState
from maistro.extensions.sqlite_store import SqliteExtensionInstallStore

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Awaitable, Callable

    from maistro.extensions.tool_skill import ExtensionContract
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


def _load_lock(lock_path: Path) -> LockState:
    """Read and validate a lock file; exit non-zero on any refusal."""
    try:
        raw = lock_path.read_text()
    except OSError as exc:
        console.print(f"[red]Cannot read {lock_path}: {exc}[/red]")
        raise Exit(code=1) from exc
    try:
        return LockState.from_json(raw)
    except LockFormatError as exc:
        console.print(f"[red]{lock_path} is not a valid extension lock: {exc}[/red]")
        raise Exit(code=1) from exc


@app.command("lock")
def extensions_lock(
    lock_path: Annotated[Path, Argument(help="Path to the resolved extension lock file (JSON).")],
) -> None:
    """Summarize a resolved lock: one row per pinned extension version."""
    lock = _load_lock(lock_path)
    if not lock.entries:
        console.print("Nothing locked.")
        return
    table = Table("extension", "version", "kind", "package", "source")
    for entry in lock.entries:
        table.add_row(
            entry.extension_name,
            entry.semantic_version,
            str(entry.kind),
            _short_digest(entry.package_sha256),
            entry.source,
        )
    console.print(table)
    console.print(f"lock digest: sha256:{lock.lock_digest()} ({len(lock.entries)} entries)")


@app.command("explain")
def extensions_explain(
    lock_path: Annotated[Path, Argument(help="Path to the resolved extension lock file (JSON).")],
    extension_name: Annotated[str, Argument(help="Extension to explain.")],
) -> None:
    """Explain why an extension and its exact version are in the lock."""
    lock = _load_lock(lock_path)
    explanation = lock.explain(extension_name)
    if explanation is None:
        console.print(f"[red]{extension_name} is not in the lock ({lock_path}).[/red]")
        raise Exit(code=1)
    entry = explanation.entry
    console.print(f"[bold]{entry.extension_name}@{entry.semantic_version}[/bold] ({entry.kind})")
    console.print(f"  present because: {explanation.present_because}")
    console.print(f"  package:         sha256:{entry.package_sha256}")
    console.print(f"  manifest:        sha256:{entry.manifest_sha256}")
    console.print(f"  source:          {entry.source}")
    console.print(f"  publisher:       {entry.publisher_id}")
    if entry.required_by:
        console.print(f"  required by:     {', '.join(entry.required_by)}")
    if entry.optional_for:
        console.print(f"  optional for:    {', '.join(entry.optional_for)}")
    console.print("  constraints:")
    for constraint in explanation.constraints:
        polarity = "" if constraint.required else " (optional)"
        console.print(f"    - '{constraint.range_text}' — {constraint.origin}{polarity}")
    console.print(f"  policy:          {explanation.policy}")
    if explanation.rejected:
        console.print("  rejected candidates:")
        for candidate in explanation.rejected:
            console.print(
                f"    - {candidate.semantic_version} "
                f"(sha256:{candidate.package_sha256[:12]}…): {candidate.reason}"
            )
    for skip in explanation.skipped_optional:
        if skip.requirer == extension_name:
            console.print(f"  skipped optional: {skip.target} '{skip.range_text}' — {skip.reason}")
        else:
            console.print(
                f"  skipped optional on this: {skip.requirer} wanted "
                f"'{skip.range_text}' — {skip.reason}"
            )


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


@app.command("contract")
def extensions_contract(
    manifest_path: Annotated[Path, Argument(help="Path to an extension.json manifest.")],
) -> None:
    """Validate a tool/Skill manifest and show the host classification (M9-E3).

    Reads the manifest file, validates it against the published closed
    vocabularies, and reports the canonical capability/effect classification
    the host will hold the package to — the ADR-050 reversibility tier and
    the effect floor derived from the manifest's declared effects AND
    requested capabilities. Data-only: the manifest's entrypoint module is
    never imported here.
    """
    loaded = _load_manifest_contract(manifest_path)
    if loaded is None:
        raise Exit(code=1)
    _print_manifest_contract(*loaded)


def _load_manifest_contract(
    manifest_path: Path,
) -> tuple[ExtensionContract, str] | None:
    """Read and validate one manifest; report and return ``None`` on failure."""
    from maistro.extensions.tool_skill import ExtensionContract

    try:
        body = manifest_path.read_bytes()
        manifest = json.loads(body)
    except OSError as exc:
        console.print(f"[red]Cannot read {manifest_path}: {exc}[/red]")
        return None
    except json.JSONDecodeError as exc:
        console.print(f"[red]{manifest_path} is not valid JSON: {exc}[/red]")
        return None
    if not isinstance(manifest, dict):
        console.print(f"[red]{manifest_path} does not contain a JSON object.[/red]")
        return None
    digest = hashlib.sha256(body).hexdigest()
    try:
        return ExtensionContract.from_manifest(manifest, digest=digest), digest
    except Exception as exc:
        console.print(f"[red]{manifest_path}: {exc}[/red]")
        return None


def _print_manifest_contract(contract: ExtensionContract, digest: str) -> None:
    """Render one validated contract and its host classification."""
    console.print(f"[bold]{contract.extension_id}@{contract.version}[/bold]")
    console.print(f"  family:        {contract.family}")
    console.print(f"  contract:      {contract.contract_range}")
    console.print(f"  manifest:      sha256:{digest}")
    console.print(f"  entrypoint:    {contract.entrypoint.module}:{contract.entrypoint.object}")
    console.print(f"  capabilities:  {', '.join(contract.capabilities) or '—'}")
    console.print(f"  effects:       {', '.join(e.value for e in contract.effects) or '—'}")
    console.print(f"  data scopes:   {', '.join(contract.data_scopes) or '—'}")
    console.print(
        f"  network:       {', '.join(contract.network_allow) or '—'}"
        f" ports {contract.network_ports or '—'}"
    )
    console.print(f"  secret refs:   {', '.join(contract.secret_refs) or '—'}")
    console.print(
        f"  [bold]host classification[/bold]: effect floor "
        f"[bold]{contract.effect_floor.value}[/bold] -> reversibility "
        f"[bold]{contract.reversibility.value}[/bold] (ADR-050)"
    )

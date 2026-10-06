"""`maistro extensions` subcommand — inspect durable extension install records.

Read-only throughout, like `maistro archive`: these commands open the SQLite
install-record store in read-only mode and report what was installed, by whom,
from which catalog, with which digest, and with what trust evidence. They never
verify, never import, and never write — the install flow that produces records
lands with #953, and these records outlive it either way.

`preflight` evaluates those same records against a *target* host release
(#957): which installed extensions are compatible, deprecated,
migration-required, or blocking — before the upgrade is applied, without
activating the new host version, from public contract metadata only.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from rich.console import Console
from rich.table import Table
from typer import Argument, Exit, Option, Typer

from maistro.extensions.preflight import (
    ManifestContractError,
    PreflightPolicy,
    PreflightReport,
    TargetHostContract,
    run_preflight,
)
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


def _split_meta(entry: str, option: str) -> tuple[str, str]:
    """Split a ``NAME=note`` CLI value; both halves must be present."""
    name, separator, note = entry.partition("=")
    if not separator or not name.strip():
        console.print(f"[red]--{option} expects NAME=note, got {entry!r}[/red]")
        raise Exit(code=1)
    return name.strip(), note.strip()


def _print_findings(report: PreflightReport) -> None:
    """The two distinct sections: hard blockers first, then warnings."""
    if report.blockers:
        console.print("[red]Blocking extensions (must be resolved or disabled):[/red]")
        for row in report.blockers:
            console.print(f"  [red]{row.extension_name}@{row.semantic_version}[/red]")
            for conflict in row.conflicts:
                console.print(f"    - {conflict}")
    if report.warning_rows:
        console.print("[yellow]Warnings (upgrade proceeds):[/yellow]")
        for row in report.warning_rows:
            console.print(f"  [yellow]{row.extension_name}@{row.semantic_version}[/yellow]")
            for warning in row.warnings:
                console.print(f"    - {warning}")
            for note in row.migration_notes:
                console.print(f"    - {note}")


def _print_preflight(report: PreflightReport) -> None:
    """Render the compatibility matrix, then blockers, then warnings.

    Blockers and warnings are separate sections on purpose (#957): a hard
    blocker must never render as one warning among others.
    """
    console.print(
        f"Upgrade preflight: target host {report.target_host_version}, "
        f"contract {report.target_contract_version}, policy {report.policy.value}"
    )
    if not report.rows:
        console.print("No installed extensions; nothing can block the upgrade.")
        return
    table = Table("extension", "version", "status", "enabled")
    for row in report.rows:
        table.add_row(
            row.extension_name,
            row.semantic_version,
            row.status.value,
            "yes" if row.enabled else "no",
        )
    console.print(table)
    _print_findings(report)
    if report.can_proceed:
        console.print("[green]Verdict: the upgrade can proceed.[/green]")
    else:
        console.print(
            "[red]Verdict: strict policy refuses the upgrade while blocking "
            "extensions remain enabled.[/red]"
        )


def _meta_options(entries: Sequence[str], option: str) -> dict[str, str]:
    """Turn repeated ``NAME=note`` option values into a mapping."""
    return dict(_split_meta(entry, option) for entry in entries)


def _preflight_enabled_set(all_disabled: bool, enabled: Sequence[str]) -> frozenset[str] | None:
    """The operator's enabled lever as :func:`run_preflight` reads it.

    An explicit ``--enabled`` set wins; ``--all-disabled`` is the empty set;
    passing neither is the conservative default (every installed extension
    treated as enabled).
    """
    if all_disabled:
        return frozenset()
    return frozenset(enabled) if enabled else None


def _parse_preflight_inputs(
    policy_name: str,
    all_disabled: bool,
    enabled: Sequence[str],
    deprecated_capability: Sequence[str],
    removed_capability: Sequence[str],
) -> tuple[PreflightPolicy, dict[str, str], dict[str, str]]:
    """Validate the CLI-only preflight inputs; exit non-zero on a bad one.

    Typer hands the command raw repeatable options; the preflight takes
    structured values. Parsing and contradiction checks live here so the
    command body reads as the pipeline it is: validate → read → evaluate →
    render → gate the exit.
    """
    if all_disabled and enabled:
        console.print("[red]--all-disabled contradicts --enabled; pass one or the other.[/red]")
        raise Exit(code=1)
    try:
        policy = PreflightPolicy.from_name(policy_name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise Exit(code=1) from exc
    return (
        policy,
        _meta_options(deprecated_capability, "deprecated-capability"),
        _meta_options(removed_capability, "removed-capability"),
    )


def _render_preflight(report: PreflightReport, as_json: bool) -> None:
    """Emit the canonical JSON or the operator report."""
    if as_json:
        # soft_wrap: the canonical JSON is one long token; rich would break it
        # across lines and destroy byte-reproducibility for consumers.
        # markup/highlight disabled: metadata is user-controlled, so sequences
        # like "[red]...[/red]" in notes must pass through byte-for-byte.
        console.print(report.canonical_json(), soft_wrap=True, markup=False, highlight=False)
    else:
        _print_preflight(report)


@app.command("preflight")
def extensions_preflight(
    db_path: Annotated[Path, Argument(help="Path to the extension install SQLite database.")],
    target_host: Annotated[
        str, Argument(help="Target host release version to evaluate, e.g. 2.0.0.")
    ],
    contract_version: Annotated[
        str,
        Option(
            "--contract-version",
            help="Manifest-contract version the target host enforces (its public metadata).",
        ),
    ],
    capability: Annotated[
        list[str],
        Option(
            "--capability",
            help="Capability name the target contract supports; repeatable. Omit to have "
            "the preflight take no position on unknown capability names.",
        ),
    ] = [],  # noqa: B006 - typer collects repeats into a fresh list per invocation
    deprecated_capability: Annotated[
        list[str],
        Option(
            "--deprecated-capability",
            metavar="NAME=REPLACEMENT",
            help="Capability deprecated in the target, with its replacement; repeatable.",
        ),
    ] = [],  # noqa: B006
    removed_capability: Annotated[
        list[str],
        Option(
            "--removed-capability",
            metavar="NAME=NOTE",
            help="Capability removed in the target, with a note; repeatable.",
        ),
    ] = [],  # noqa: B006
    policy_name: Annotated[
        str,
        Option(
            "--policy",
            help="permissive (report only) or strict (blockers refuse the upgrade).",
        ),
    ] = "permissive",
    enabled: Annotated[
        list[str],
        Option(
            "--enabled",
            help="Extension the host currently has enabled; repeatable. Omit to treat "
            "every installed extension as enabled (the conservative default).",
        ),
    ] = [],  # noqa: B006
    all_disabled: Annotated[
        bool,
        Option(
            "--all-disabled",
            help="The host has every installed extension disabled. Without either "
            "this flag or --enabled, every installed extension is treated as "
            "enabled (the conservative default).",
        ),
    ] = False,
    as_json: Annotated[
        bool, Option("--json", help="Print the canonical machine-readable report.")
    ] = False,
) -> None:
    """Evaluate installed extensions against a target host release.

    Runs entirely on data: the install records in DB_PATH plus the target
    release's public contract metadata given here. Nothing from the target
    release is imported or activated, and nothing is written. Under
    --policy strict the command exits non-zero while blocking extensions
    remain enabled — that exit is the gate an upgrade flow must honor.
    """
    policy, deprecated_map, removed_map = _parse_preflight_inputs(
        policy_name, all_disabled, enabled, deprecated_capability, removed_capability
    )
    try:
        target = TargetHostContract(
            host_version=target_host,
            contract_version=contract_version,
            capabilities=frozenset(capability),
            deprecated=deprecated_map,
            removed=removed_map,
        )
    except ManifestContractError as exc:
        console.print(f"[red]Invalid target contract metadata: {exc}[/red]")
        raise Exit(code=1) from exc
    try:
        records = asyncio.run(_read_only(db_path, lambda s: s.all_installs()))
    except sqlite3.OperationalError as exc:
        console.print(f"[red]Cannot open {db_path}: {exc}[/red]")
        raise Exit(code=1) from exc
    assert isinstance(records, list)
    report = run_preflight(
        records,
        target,
        policy=policy,
        enabled=_preflight_enabled_set(all_disabled, enabled),
    )
    _render_preflight(report, as_json)
    if not report.can_proceed:
        raise Exit(code=1)

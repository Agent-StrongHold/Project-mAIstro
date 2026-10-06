"""`maistro extensions` subcommand — inspect durable extension install records.

Read-only throughout, like `maistro archive`: these commands open the SQLite
install-record store in read-only mode and report what was installed, by whom,
from which catalog, with which digest, and with what trust evidence. They never
verify, never import, and never write — the install flow that produces records
lands with #953, and these records outlive it either way.

The `lock` and `explain` commands (M9-C2, #956) read a resolved lock file —
the reproducible output of dependency resolution: which extension versions are
pinned, from which source, and why each one and its version were selected.
They are likewise read-only: a lock file is evidence about a decision already
made, and these commands never rewrite it.

The `certify` and `verify-certification` commands (M9-H3, #975) are the
pre-publication half: `certify` validates a package (manifest, artifact
binding, shipped entry points, public-import policy, dynamic-execution
scan), emits the certification report as CI-friendly JSON plus a
human-readable summary, and optionally seals the report digest with an
Ed25519 key. It exits non-zero unless the package certified. Conformance
suites cannot be supplied over a CLI flag — publication-profile
certification (which requires executed suites) belongs to the Python API
(`maistro.extensions.certification.certify`), where hosts wire their own
harnesses; a CLI run under that profile truthfully reports the conformance
gap and refuses. `verify-certification` re-verifies a report+seal against
the presented package bytes and prints the trust claim it can mint —
evidence for the install flow's trust evaluation, never an authorization by
itself.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from rich.console import Console
from rich.table import Table
from typer import Argument, Exit, Option, Typer

from maistro.extensions.certification import (
    MANIFEST_PROFILE,
    PUBLICATION_PROFILE,
    CertificationInvalid,
    CertificationPackageMismatch,
    CertificationProfile,
    CertificationReport,
    CertificationSeal,
    ConformanceCheck,
    EntryPointPresenceCheck,
    ExtensionBundle,
    ImportPolicy,
    PackageStructureCheck,
    PublicImportCheck,
    SecurityScanCheck,
    certification_as_trust_claim,
    certify,
    detect_environment,
    render_summary,
    report_from_json,
    report_to_json,
    seal_from_json,
    seal_to_json,
    verify_certification,
    verify_certified_package,
)
from maistro.extensions.resolution import LockFormatError, LockState
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


#: The profiles `maistro extensions certify` can run by name. Publication-
#: profile runs always record the conformance gap over a CLI: suites are
#: host-supplied Python objects, so over a command line they are absent —
#: and a required check that was skipped refuses certification, truthfully.
_CERTIFICATION_PROFILES: dict[str, CertificationProfile] = {
    MANIFEST_PROFILE.name: MANIFEST_PROFILE,
    PUBLICATION_PROFILE.name: PUBLICATION_PROFILE,
}


def _read_bytes(path: Path, what: str) -> bytes:
    """Read a required input file, exiting with a named error when absent."""
    try:
        return path.read_bytes()
    except OSError as exc:
        console.print(f"[red]Cannot read {what} {path}: {exc}[/red]")
        raise Exit(code=1) from exc


def _read_key_file(path: Path) -> Ed25519PrivateKey:
    """Load a hex-encoded raw Ed25519 private key from ``path``."""
    raw = _read_bytes(path, "signing key").decode().strip()
    try:
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(raw))
    except ValueError as exc:
        console.print(f"[red]{path} is not a hex Ed25519 private key: {exc}[/red]")
        raise Exit(code=1) from exc


def _load_import_policy(policy_path: Path | None) -> ImportPolicy:
    """Load the public/private namespace policy for the import scan.

    Without a policy file, no first-party namespace is public: only the
    repo-relative and explicitly-private rules apply. A policy file carries
    ``public_namespaces``, ``private_namespaces`` and (optionally)
    ``repo_relative_roots`` as JSON lists.
    """
    if policy_path is None:
        return ImportPolicy(public_namespaces=frozenset())
    document: dict[str, Any] = json.loads(_read_bytes(policy_path, "import policy"))
    return ImportPolicy(
        public_namespaces=frozenset(document.get("public_namespaces", ())),
        private_namespaces=frozenset(document.get("private_namespaces", ())),
        repo_relative_roots=frozenset(
            document.get("repo_relative_roots", ("packages", "extensions"))
        ),
    )


def _collect_sources(source_dirs: list[Path]) -> tuple[tuple[str, bytes], ...]:
    """Gather every ``*.py`` under each dir, keyed relative to that dir.

    The relative path is what entry-point containment matches dotted module
    names against, mirroring how the files sit inside a built wheel.
    """
    sources: list[tuple[str, bytes]] = []
    for base in source_dirs:
        for file in sorted(base.rglob("*.py")):
            if "__pycache__" in file.parts:
                continue
            sources.append((file.relative_to(base).as_posix(), file.read_bytes()))
    return tuple(sources)


@app.command("certify")
def extensions_certify(
    manifest_path: Annotated[
        Path, Option("--manifest", help="Path to the extension manifest (JSON bytes).")
    ],
    payload_path: Annotated[
        Path, Option("--payload", help="Path to the artifact bytes the manifest declares.")
    ],
    source_dir: Annotated[
        list[Path] | None,
        Option(
            "--source-dir",
            help="Directory of packaged sources to scan (repeatable; *.py files, "
            "paths relative to the directory).",
        ),
    ] = None,
    profile_name: Annotated[
        str,
        Option(
            "--profile",
            help="Certification profile: 'manifest' (default) or 'publication'. "
            "Publication requires executed conformance suites, which a CLI run "
            "cannot supply, so it truthfully refuses.",
        ),
    ] = MANIFEST_PROFILE.name,
    policy_path: Annotated[
        Path | None,
        Option("--import-policy", help="JSON import policy: public/private namespaces."),
    ] = None,
    key_file: Annotated[
        Path | None,
        Option("--sign-key-file", help="Hex Ed25519 private key to seal the report with."),
    ] = None,
    report_out: Annotated[
        Path | None, Option("--report-json", help="Write the certification report JSON here.")
    ] = None,
    seal_out: Annotated[
        Path | None, Option("--seal-json", help="Write the certification seal JSON here.")
    ] = None,
) -> None:
    """Validate a package and emit its certification report (exit 1 unless certified)."""
    profile = _CERTIFICATION_PROFILES.get(profile_name)
    if profile is None:
        console.print(
            f"[red]Unknown profile {profile_name!r}; "
            f"available: {', '.join(sorted(_CERTIFICATION_PROFILES))}[/red]"
        )
        raise Exit(code=1)
    bundle = ExtensionBundle(
        manifest_bytes=_read_bytes(manifest_path, "manifest"),
        payload=_read_bytes(payload_path, "payload"),
        sources=_collect_sources(source_dir or []),
    )
    signer = _read_key_file(key_file) if key_file is not None else None
    report, seal = certify(
        bundle,
        profile=profile,
        environment=detect_environment(),
        checks=(
            PackageStructureCheck(bundle),
            EntryPointPresenceCheck(bundle),
            PublicImportCheck(bundle, _load_import_policy(policy_path)),
            SecurityScanCheck(bundle),
            ConformanceCheck(suites=[]),
        ),
        signer=signer,
    )
    console.print(render_summary(report, seal))
    if report_out is not None:
        report_out.write_text(report_to_json(report) + "\n")
    if seal_out is not None:
        seal_out.write_text(seal_to_json(seal) + "\n")
    if not report.certified:
        raise Exit(code=1)


def _load_certification(
    report_path: Path, seal_path: Path
) -> tuple[CertificationReport, CertificationSeal]:
    """Load a report+seal pair, exiting non-zero on any refusal."""
    try:
        report = report_from_json(_read_bytes(report_path, "report").decode("utf-8"))
        seal = seal_from_json(_read_bytes(seal_path, "seal").decode("utf-8"))
    except (CertificationInvalid, json.JSONDecodeError) as exc:
        console.print(f"[red]Cannot load certification: {exc}[/red]")
        raise Exit(code=1) from exc
    return report, seal


@app.command("verify-certification")
def extensions_verify_certification(
    report_path: Annotated[Path, Argument(help="Path to the certification report JSON.")],
    seal_path: Annotated[Path, Argument(help="Path to the certification seal JSON.")],
    manifest_path: Annotated[
        Path, Option("--manifest", help="Presented manifest bytes to verify against.")
    ],
    payload_path: Annotated[
        Path, Option("--payload", help="Presented artifact bytes to verify against.")
    ],
    source_dir: Annotated[
        list[Path] | None,
        Option(
            "--source-dir",
            help="Directory of packaged sources (same layout as `certify`), so the "
            "full certified package digest can be recomputed.",
        ),
    ] = None,
    trusted_public_key: Annotated[
        str | None,
        Option(
            "--trusted-public-key",
            help="Hex Ed25519 public key the seal must have been made by; without "
            "it the seal is checked for integrity but not for publisher origin.",
        ),
    ] = None,
) -> None:
    """Verify a sealed certification against the package bytes in hand.

    Prints the trust claim the certification can mint for the install flow.
    Certification is evidence for the trust evaluation — never an
    authorization by itself.
    """
    report, seal = _load_certification(report_path, seal_path)
    bundle = ExtensionBundle(
        manifest_bytes=_read_bytes(manifest_path, "manifest"),
        payload=_read_bytes(payload_path, "payload"),
        sources=_collect_sources(source_dir or []),
    )
    try:
        fingerprint = verify_certification(report, seal, trusted_public_key=trusted_public_key)
        verify_certified_package(report, bundle)
        claim = certification_as_trust_claim(
            report,
            seal,
            presented_manifest=bundle.manifest_bytes,
            presented_payload=bundle.payload,
            trusted_public_key=trusted_public_key,
        )
    except (CertificationInvalid, CertificationPackageMismatch) as exc:
        console.print(f"[red]Certification refused: {exc}[/red]")
        raise Exit(code=1) from exc
    console.print(render_summary(report, seal))
    console.print(
        f"trust claim (evidence only): publisher={claim.publisher_id} "
        f"package=sha256:{claim.package_sha256} key={_short_digest(str(claim.signer_key_id))}"
    )
    console.print(f"verified by key fingerprint {_short_digest(fingerprint)}")

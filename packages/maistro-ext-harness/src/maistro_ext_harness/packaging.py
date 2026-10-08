"""Package-structure validation for certification (M9-H3, #975).

Two views of the same package, both checked before anything is claimed:

**source tree** — what conformance ran against:

- ``extension.json`` parses and validates against the harness's manifest
  contract (the normative schema is the SDK package's; the two statements
  are held together by the harness's own test suite — see the
  reconciliation note in ``maistro_ext_harness.contract``);
- the entrypoint module exists as a file (a ``stat``, never an import) in
  either shipped layout — the SDK's flat layout and the ``src/`` layout
  the repository's reference extension uses — so the same tooling certifies
  built-in reference extensions and external-style samples;
- ``pyproject.toml`` parses and names a distribution;
- the distribution version equals the manifest version — an ambiguous
  identity is exactly what certification must not sign.

**artifact** — the exact bytes a digest will bind:

- the artifact reads as a zip archive with intact members;
- no member escapes the archive (absolute paths, ``..`` traversal, Windows
  separators) — a package that writes outside its install root is refused,
  not certified;
- the manifest ships inside the artifact and is *the same manifest* the
  conformance suite tested: certify binds "what was tested" to "what is
  signed" by equality, not by convention;
- the entrypoint modules ship inside the artifact;
- for a ``.whl``, the ``dist-info/METADATA`` identity (Name, Version) says
  what the manifest says;
- the SHA-256 digest and size of the exact bytes are recorded — the number
  the signature covers and the number any later consumer re-derives to
  detect mutation.
"""

from __future__ import annotations

import hashlib
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path

from maistro_ext_harness.checks import CheckRecord, CheckStatus
from maistro_ext_harness.manifest import (
    ExtensionManifest,
    ManifestRejected,
    load_manifest_bytes,
    load_manifest_file,
)
from maistro_ext_harness.security import declared_distributions

__all__ = [
    "ArtifactInfo",
    "SourceInspection",
    "inspect_artifact",
    "inspect_source_tree",
]


def sha256_file(path: Path) -> str:
    """The hex SHA-256 of a file's exact bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ArtifactInfo:
    """The identity of the artifact's exact bytes, as certified."""

    filename: str
    sha256: str
    size_bytes: int
    manifest_sha256: str
    top_package: str


@dataclass(frozen=True)
class SourceInspection:
    """What the source-tree pass found (checks plus what callers need)."""

    checks: tuple[CheckRecord, ...]
    manifest: ExtensionManifest | None
    #: ``[project] name`` from pyproject.toml, when it parsed.
    project_name: str | None
    #: Distribution names declared in pyproject.toml, for the security pass.
    declared: tuple[str, ...] = ()


def _entrypoint_candidates(module: str) -> list[list[str]]:
    """File-path shapes a dotted module can take, relative to a layout root."""
    parts = module.split(".")
    return [
        [*parts[:-1], f"{parts[-1]}.py"],
        [*parts, "__init__.py"],
    ]


def resolve_entrypoint_file(root: Path, module: str) -> Path | None:
    """Locate the entrypoint file in a source tree, in either layout.

    Mirrors the SDK's own resolution order (flat layout first), then falls
    back to the ``src/`` layout the repository's reference extension ships.
    A ``stat``-only walk: no module is imported here, ever.
    """
    for layout in (root, root / "src"):
        for candidate in _entrypoint_candidates(module):
            path = layout.joinpath(*candidate)
            if path.is_file():
                return path
        # A layout whose first segment resolves to a plain module cannot
        # carry the dotted path at all; only keep walking when the segment
        # directory (or its __init__.py) actually exists.
    return None


def _manifest_check(root: Path) -> tuple[CheckRecord, ExtensionManifest | None]:
    """extension.json exists and validates; the parsed manifest or None."""
    description = "extension.json exists and validates against the manifest contract"
    manifest_path = root / "extension.json"
    if not manifest_path.is_file():
        return (
            CheckRecord(
                check_id="package/manifest-parses",
                description=description,
                status=CheckStatus.FAILED,
                detail=f"no extension.json at {str(root)!r}",
            ),
            None,
        )
    try:
        manifest = load_manifest_file(manifest_path)
    except ManifestRejected as exc:
        return (
            CheckRecord(
                check_id="package/manifest-parses",
                description=description,
                status=CheckStatus.FAILED,
                detail=str(exc),
            ),
            None,
        )
    return (
        CheckRecord(
            check_id="package/manifest-parses",
            description=description,
            status=CheckStatus.PASSED,
            detail=(
                f"{manifest.id} {manifest.version} (family {manifest.family}, "
                f"contract {manifest.contract})"
            ),
        ),
        manifest,
    )


def _entrypoint_check(root: Path, manifest: ExtensionManifest | None) -> CheckRecord:
    description = "the declared entrypoint module exists as a file"
    if manifest is None:
        return CheckRecord(
            check_id="package/entrypoint-file-exists",
            description=description,
            status=CheckStatus.FAILED,
            detail="no parsed manifest, so no entrypoint to resolve",
        )
    module = manifest.entrypoint.module
    entrypoint = resolve_entrypoint_file(root, module)
    if entrypoint is None:
        return CheckRecord(
            check_id="package/entrypoint-file-exists",
            description=description,
            status=CheckStatus.FAILED,
            detail=f"{module!r} not found under {str(root)!r} (flat or src/ layout)",
        )
    return CheckRecord(
        check_id="package/entrypoint-file-exists",
        description=description,
        status=CheckStatus.PASSED,
        detail=f"{module!r} at {entrypoint}",
    )


def _pyproject_check(pyproject: Path) -> tuple[CheckRecord, str | None, str | None]:
    """pyproject.toml parses and names a distribution; (record, name, version)."""
    description = "pyproject.toml parses and names a distribution"
    if not pyproject.is_file():
        return (
            CheckRecord(
                check_id="package/pyproject-parses",
                description=description,
                status=CheckStatus.FAILED,
                detail=f"no pyproject.toml at {str(pyproject)!r}",
            ),
            None,
            None,
        )
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = data.get("project")
        if not isinstance(project, dict) or "name" not in project:
            raise ValueError("[project] table with a name is required")
        name = str(project["name"])
        version = str(project.get("version", ""))
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        return (
            CheckRecord(
                check_id="package/pyproject-parses",
                description=description,
                status=CheckStatus.FAILED,
                detail=str(exc),
            ),
            None,
            None,
        )
    return (
        CheckRecord(
            check_id="package/pyproject-parses",
            description=description,
            status=CheckStatus.PASSED,
            detail=f"distribution {name!r} version {version!r}",
        ),
        name,
        version,
    )


def _version_parity_check(
    manifest: ExtensionManifest | None, project_version: str | None
) -> CheckRecord:
    description = "the distribution version equals the manifest version"
    if manifest is None or project_version is None:
        return CheckRecord(
            check_id="package/version-parity",
            description=description,
            status=CheckStatus.FAILED,
            detail="one side of the comparison is missing (manifest or pyproject)",
        )
    if project_version == manifest.version:
        return CheckRecord(
            check_id="package/version-parity",
            description=description,
            status=CheckStatus.PASSED,
            detail=f"{project_version!r}",
        )
    return CheckRecord(
        check_id="package/version-parity",
        description=description,
        status=CheckStatus.FAILED,
        detail=(
            f"pyproject says {project_version!r} but extension.json says "
            f"{manifest.version!r} — the certified identity must be unambiguous"
        ),
    )


def inspect_source_tree(root: Path) -> SourceInspection:
    """Validate the extension source tree; return checks plus what callers need.

    The manifest is returned (even alongside failed checks) only when it
    parsed and validated — callers need it for conformance and for the
    artifact equality check, and a ``None`` here is itself the decline.
    """
    manifest_check, manifest = _manifest_check(root)
    checks = [manifest_check, _entrypoint_check(root, manifest)]
    pyproject_check, project_name, project_version = _pyproject_check(root / "pyproject.toml")
    checks.append(pyproject_check)
    checks.append(_version_parity_check(manifest, project_version))

    return SourceInspection(
        checks=tuple(checks),
        manifest=manifest,
        project_name=project_name,
        declared=declared_distributions(root / "pyproject.toml"),
    )


def _safe_member(name: str) -> str | None:
    """Why this zip member name escapes its archive, or ``None`` if it does not."""
    if name.startswith("/") or name.startswith("\\"):
        return "absolute path"
    if "\\" in name:
        return "Windows path separator"
    parts = name.split("/")
    if ".." in parts:
        return "parent-directory traversal"
    if any(part == "" for part in parts[:-1]):
        return "empty path segment"
    if ":" in name:
        return "drive-like path"
    return None


def _module_member(names: list[str], module: str, top: str) -> str | None:
    """The archive member carrying the entrypoint module, if any."""
    for layout in (top, ""):
        prefix = f"{layout}/" if layout else ""
        for candidate in _entrypoint_candidates(module):
            name = prefix + "/".join(candidate)
            if name in names:
                return name
    return None


@dataclass(frozen=True)
class _Archive:
    """What one successful archive read yields (or the error that didn't)."""

    names: tuple[str, ...]
    manifest_text: str | None
    manifest_member: str | None
    metadata: dict[str, str]
    error: str | None = None


def _read_archive(artifact: Path, top: str) -> _Archive:
    """Read the artifact once; a bad zip or unreadable file is the error."""
    try:
        with zipfile.ZipFile(artifact) as archive:
            names = tuple(archive.namelist())
            bad_member = archive.testzip()
            manifest_member: str | None = None
            manifest_text: str | None = None
            for candidate in (f"{top}/extension.json", "extension.json"):
                if candidate in names:
                    manifest_member = candidate
                    manifest_text = archive.read(candidate).decode("utf-8")
                    break
            metadata: dict[str, str] = {}
            for name in names:
                if name.endswith(".dist-info/METADATA"):
                    for line in archive.read(name).decode("utf-8", errors="replace").splitlines():
                        if ": " in line and not line.startswith(" "):
                            key, _, value = line.partition(": ")
                            metadata.setdefault(key, value)
                    break
    except (zipfile.BadZipFile, OSError, UnicodeDecodeError) as exc:
        return _Archive(
            names=(), manifest_text=None, manifest_member=None, metadata={}, error=str(exc)
        )
    if bad_member is not None:
        return _Archive(
            names=names,
            manifest_text=manifest_text,
            manifest_member=manifest_member,
            metadata=metadata,
            error=f"corrupt member {bad_member!r}",
        )
    return _Archive(
        names=names,
        manifest_text=manifest_text,
        manifest_member=manifest_member,
        metadata=metadata,
    )


def _artifact_manifest_checks(
    source_manifest: ExtensionManifest | None,
    archive: _Archive,
    top: str,
) -> list[CheckRecord]:
    """The artifact must ship the manifest conformance tested — by equality."""
    ships_description = "the artifact ships a valid discovery manifest"
    equals_description = "the shipped manifest equals the manifest conformance tested"
    if source_manifest is None:
        return [
            CheckRecord(
                check_id="artifact/manifest-ships",
                description=ships_description,
                status=CheckStatus.FAILED,
                detail=(
                    "the source manifest did not parse; the artifact's manifest "
                    "cannot be located or compared"
                ),
            ),
            CheckRecord(
                check_id="artifact/manifest-matches-tested",
                description=equals_description,
                status=CheckStatus.FAILED,
                detail="no tested manifest to compare against",
            ),
        ]
    if archive.manifest_member is None:
        return [
            CheckRecord(
                check_id="artifact/manifest-ships",
                description=ships_description,
                status=CheckStatus.FAILED,
                detail=f"no {top}/extension.json (or extension.json) member in the archive",
            ),
            CheckRecord(
                check_id="artifact/manifest-matches-tested",
                description=equals_description,
                status=CheckStatus.FAILED,
                detail="nothing shipped to compare",
            ),
        ]
    try:
        artifact_manifest = load_manifest_bytes(archive.manifest_text or "")
    except ManifestRejected as exc:
        return [
            CheckRecord(
                check_id="artifact/manifest-ships",
                description=ships_description,
                status=CheckStatus.FAILED,
                detail=f"{archive.manifest_member}: {exc}",
            ),
            CheckRecord(
                check_id="artifact/manifest-matches-tested",
                description=equals_description,
                status=CheckStatus.FAILED,
                detail="the shipped manifest does not validate",
            ),
        ]
    same = artifact_manifest == source_manifest
    return [
        CheckRecord(
            check_id="artifact/manifest-ships",
            description=ships_description,
            status=CheckStatus.PASSED,
            detail=(
                f"{archive.manifest_member}: {artifact_manifest.id} {artifact_manifest.version}"
            ),
        ),
        CheckRecord(
            check_id="artifact/manifest-matches-tested",
            description=equals_description,
            status=CheckStatus.PASSED if same else CheckStatus.FAILED,
            detail=(
                f"{archive.manifest_member} equals the tested manifest"
                if same
                else (
                    f"{archive.manifest_member} ({artifact_manifest.id} "
                    f"{artifact_manifest.version}) differs from the tested "
                    f"manifest ({source_manifest.id} {source_manifest.version}) — "
                    "certification would sign bytes that were never tested"
                )
            ),
        ),
    ]


def _metadata_check(
    artifact: Path,
    archive: _Archive,
    project_name: str | None,
    source_manifest: ExtensionManifest | None,
) -> CheckRecord:
    description = "the wheel's dist-info METADATA names the same distribution and version"
    if artifact.suffix != ".whl":
        return CheckRecord(
            check_id="artifact/metadata-identity",
            description=description,
            status=CheckStatus.NOT_APPLICABLE,
            detail=f"artifact is {artifact.name!r}, not a .whl; no dist-info to check",
        )
    name = archive.metadata.get("Name")
    version = archive.metadata.get("Version")
    ok = (
        project_name is not None
        and name is not None
        and name.replace("_", "-") == project_name.replace("_", "-")
        and source_manifest is not None
        and version == source_manifest.version
    )
    return CheckRecord(
        check_id="artifact/metadata-identity",
        description=description,
        status=CheckStatus.PASSED if ok else CheckStatus.FAILED,
        detail=(
            f"Name={name!r} Version={version!r}"
            if name or version
            else "no *.dist-info/METADATA member found"
        ),
    )


def inspect_artifact(
    artifact: Path,
    source_manifest: ExtensionManifest | None,
    *,
    project_name: str | None,
) -> tuple[list[CheckRecord], ArtifactInfo | None]:
    """Validate the artifact's structure and bind its exact bytes.

    ``source_manifest`` is the manifest conformance ran against; the
    artifact must ship the same one, or the certification would sign bytes
    that were never tested.
    """
    checks: list[CheckRecord] = []

    if not artifact.is_file():
        checks.append(
            CheckRecord(
                check_id="artifact/readable",
                description="the artifact exists and reads as a zip archive",
                status=CheckStatus.FAILED,
                detail=f"no such file: {str(artifact)!r}",
            )
        )
        return checks, None

    top = source_manifest.entrypoint.module.split(".")[0] if source_manifest else ""
    archive = _read_archive(artifact, top)
    if archive.error is not None and not archive.names:
        checks.append(
            CheckRecord(
                check_id="artifact/readable",
                description="the artifact exists and reads as a zip archive",
                status=CheckStatus.FAILED,
                detail=archive.error,
            )
        )
        return checks, None

    checks.append(
        CheckRecord(
            check_id="artifact/readable",
            description="the artifact exists and reads as a zip archive",
            status=CheckStatus.FAILED if archive.error else CheckStatus.PASSED,
            detail=(
                f"{len(archive.names)} members" + (f"; {archive.error}" if archive.error else "")
            ),
        )
    )

    unsafe = [(name, why) for name in archive.names if (why := _safe_member(name))]
    checks.append(
        CheckRecord(
            check_id="artifact/members-contained",
            description="every archive member stays inside the archive (no traversal)",
            status=CheckStatus.PASSED if not unsafe else CheckStatus.FAILED,
            detail=(
                "; ".join(f"{name}: {why}" for name, why in unsafe)
                or f"{len(archive.names)} members checked"
            ),
        )
    )

    checks.extend(_artifact_manifest_checks(source_manifest, archive, top))

    if source_manifest is not None:
        module = source_manifest.entrypoint.module
        member = _module_member(list(archive.names), module, top)
        checks.append(
            CheckRecord(
                check_id="artifact/entrypoint-ships",
                description="the entrypoint module ships inside the artifact",
                status=CheckStatus.PASSED if member else CheckStatus.FAILED,
                detail=(
                    f"{module!r} at {member!r}"
                    if member
                    else f"{module!r} not found in the archive"
                ),
            )
        )

    checks.append(_metadata_check(artifact, archive, project_name, source_manifest))

    manifest_text = archive.manifest_text
    info = ArtifactInfo(
        filename=artifact.name,
        sha256=sha256_file(artifact),
        size_bytes=artifact.stat().st_size,
        manifest_sha256=(
            hashlib.sha256((manifest_text or "").encode("utf-8")).hexdigest()
            if manifest_text is not None
            else ""
        ),
        top_package=top,
    )
    checks.append(
        CheckRecord(
            check_id="artifact/digest-recorded",
            description="the SHA-256 of the exact certified bytes is recorded",
            status=CheckStatus.PASSED,
            detail=f"sha256:{info.sha256} ({info.size_bytes} bytes)",
        )
    )
    return checks, info

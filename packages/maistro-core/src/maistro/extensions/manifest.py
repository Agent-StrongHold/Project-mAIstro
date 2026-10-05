"""Manifest inspection without code execution (#953, M9-B2).

Parsing works on raw bytes only. There is no import machinery here, no module
resolution, and no evaluation of manifest content: a manifest is data, and
everything this module returns is derived from the bytes themselves. The
returned snapshot is anchored by the SHA-256 of the exact bytes so the
permissions an operator is shown are provably the permissions that were
inspected.
"""

from __future__ import annotations

import hashlib
import json
import re

from maistro.extensions.types import (
    ExtensionDependency,
    ExtensionEntryPoint,
    ExtensionManifest,
    ManifestRejected,
)

#: The only manifest envelope this platform accepts. Unknown versions fail
#: closed: a forward-compat guess would authorize a document nobody read.
SUPPORTED_MANIFEST_VERSION = 1

#: Extra keys are refused, not ignored — an ignored key is a permission or a
#: constraint the operator never saw.
_REQUIRED_KEYS = (
    "manifest_version",
    "id",
    "name",
    "version",
    "publisher",
    "api_version",
    "permissions",
    "entry_points",
    "artifact",
)
_OPTIONAL_KEYS = ("dependencies",)
_ALLOWED_KEYS = frozenset({*_REQUIRED_KEYS, *_OPTIONAL_KEYS})

#: Strict semver: no leading zeros, exactly three components.
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_PERMISSION_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
#: Publisher ids are org-style slugs: hyphens and digits allowed, punctuation
#: that would survive copy/paste from a registry disallowed.
_PUBLISHER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def sha256_hex(data: bytes) -> str:
    """Return the lowercase hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def assert_snapshot_intact(manifest: ExtensionManifest) -> None:
    """Raise if the manifest snapshot's bytes no longer match its anchor.

    Every permission display and grant freeze goes through this check, so a
    corrupted or swapped snapshot fails loudly instead of authorizing
    something the operator never saw.
    """
    if sha256_hex(manifest.raw) != manifest.source_sha256:
        raise ManifestRejected(
            f"manifest snapshot integrity failure for {manifest.extension_id!r}: "
            "bytes no longer match the inspected digest"
        )


def _reject(detail: str) -> ManifestRejected:
    return ManifestRejected(f"invalid extension manifest: {detail}")


def _validate_semver(value: object, what: str) -> str:
    if not isinstance(value, str) or SEMVER_RE.match(value) is None:
        raise _reject(f"{what} must be semver X.Y.Z, got {value!r}")
    return value


def _parse_permissions(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
        raise _reject("permissions must be a list of strings")
    seen: set[str] = set()
    for permission in raw:
        if _PERMISSION_RE.match(permission) is None:
            raise _reject(f"malformed permission token: {permission!r}")
        if permission in seen:
            raise _reject(f"duplicate permission: {permission!r}")
        seen.add(permission)
    return tuple(raw)


def _parse_entry_points(raw: object) -> tuple[ExtensionEntryPoint, ...]:
    if not isinstance(raw, list) or not raw:
        raise _reject("entry_points must be a non-empty list")
    points: list[ExtensionEntryPoint] = []
    names: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise _reject("each entry point must be an object")
        if set(item) != {"name", "module", "attribute"}:
            raise _reject("entry point object must have exactly name, module, attribute")
        for key in ("name", "module", "attribute"):
            value = item[key]
            if not isinstance(value, str) or not value.strip():
                raise _reject(f"entry point {key} must be a non-empty string")
        if item["name"] in names:
            raise _reject(f"duplicate entry point name: {item['name']!r}")
        names.add(item["name"])
        points.append(
            ExtensionEntryPoint(
                name=item["name"], module=item["module"], attribute=item["attribute"]
            )
        )
    return tuple(points)


def _parse_dependencies(raw: object) -> tuple[ExtensionDependency, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise _reject("dependencies must be a list")
    deps: list[ExtensionDependency] = []
    ids: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"id", "range"}:
            raise _reject("each dependency must be an object with exactly id and range")
        dep_id, range_spec = item["id"], item["range"]
        if not isinstance(dep_id, str) or _ID_RE.match(dep_id) is None:
            raise _reject(f"malformed dependency id: {dep_id!r}")
        if not isinstance(range_spec, str) or not range_spec.strip():
            raise _reject(f"malformed dependency range for {dep_id!r}")
        if dep_id in ids:
            raise _reject(f"duplicate dependency: {dep_id!r}")
        ids.add(dep_id)
        deps.append(ExtensionDependency(extension_id=dep_id, range_spec=range_spec))
    return tuple(deps)


def _parse_document(raw: bytes) -> dict[str, object]:
    """Decode bytes to a JSON object, refusing anything else."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _reject(f"not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise _reject("top-level document must be an object")
    unknown = sorted(set(document) - _ALLOWED_KEYS)
    if unknown:
        raise _reject(f"unknown manifest keys: {unknown}")
    missing = [key for key in _REQUIRED_KEYS if key not in document]
    if missing:
        raise _reject(f"missing manifest keys: {missing}")
    if document["manifest_version"] != SUPPORTED_MANIFEST_VERSION:
        raise _reject(f"unsupported manifest_version: {document['manifest_version']!r}")
    return document


def _validate_identity(document: dict[str, object]) -> tuple[str, str, str]:
    """Validate and return (extension_id, name, publisher) as typed strings."""
    identity: list[str] = []
    for key in ("id", "name", "publisher"):
        value = document[key]
        if not isinstance(value, str) or not value.strip():
            raise _reject(f"{key} must be a non-empty string")
        identity.append(value)
    extension_id, name, publisher = identity
    if _ID_RE.match(extension_id) is None:
        raise _reject(f"malformed extension id: {extension_id!r}")
    if _PUBLISHER_RE.match(publisher) is None:
        raise _reject(f"malformed publisher id: {publisher!r}")
    return extension_id, name, publisher


def _parse_artifact(artifact: object) -> tuple[str, int]:
    """Validate and return the declared artifact digest and size."""
    if not isinstance(artifact, dict) or set(artifact) != {"sha256", "size"}:
        raise _reject("artifact must be an object with exactly sha256 and size")
    artifact_sha256 = artifact["sha256"]
    if (
        not isinstance(artifact_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", artifact_sha256) is None
    ):
        raise _reject("artifact.sha256 must be a lowercase 64-hex digest")
    artifact_size = artifact["size"]
    if not isinstance(artifact_size, int) or isinstance(artifact_size, bool) or artifact_size <= 0:
        raise _reject("artifact.size must be a positive integer")
    return artifact_sha256, artifact_size


def inspect_manifest(raw: bytes) -> ExtensionManifest:
    """Parse and validate manifest bytes into an immutable snapshot.

    Fails closed on malformed JSON, unknown envelope versions, unexpected
    keys, malformed identifiers/permissions/semver, duplicate permissions or
    dependencies, and artifact declarations without a well-formed digest and
    positive size. Never touches the payload and never imports anything.
    """
    document = _parse_document(raw)
    extension_id, name, publisher = _validate_identity(document)
    version = _validate_semver(document["version"], "version")
    api_version = _validate_semver(document["api_version"], "api_version")
    artifact_sha256, artifact_size = _parse_artifact(document["artifact"])

    manifest = ExtensionManifest(
        manifest_version=SUPPORTED_MANIFEST_VERSION,
        extension_id=extension_id,
        name=name,
        version=version,
        publisher=publisher,
        api_version=api_version,
        permissions=_parse_permissions(document["permissions"]),
        entry_points=_parse_entry_points(document["entry_points"]),
        dependencies=_parse_dependencies(document.get("dependencies")),
        artifact_sha256=artifact_sha256,
        artifact_size=artifact_size,
        source_sha256=sha256_hex(raw),
        raw=raw,
    )
    # The snapshot must survive its own integrity check the moment it exists.
    assert_snapshot_intact(manifest)
    return manifest


def verify_package_payload(manifest: ExtensionManifest, payload: bytes) -> str:
    """Check candidate payload bytes against the manifest's artifact claim.

    Returns the verified digest. A payload that does not match the declared
    digest/size is a tampered bundle: callers reject the inspection instead of
    binding a digest the manifest never claimed.
    """
    digest = sha256_hex(payload)
    if digest != manifest.artifact_sha256:
        raise ManifestRejected(
            f"artifact digest mismatch for {manifest.extension_id} "
            f"{manifest.version}: manifest declares {manifest.artifact_sha256}, "
            f"package carries {digest}"
        )
    if len(payload) != manifest.artifact_size:
        raise ManifestRejected(
            f"artifact size mismatch for {manifest.extension_id} "
            f"{manifest.version}: manifest declares {manifest.artifact_size}, "
            f"package carries {len(payload)}"
        )
    return digest

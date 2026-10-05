"""Parse, validate, and reject manifests — without importing extension code.

This module is the SDK's front door. Every entry point takes *text* or a
*directory* and returns data or raises ``ExtensionManifestError``; none of
them executes a line of the extension under validation. The directory
validator checks the entrypoint's file exists on disk — a ``stat``, not an
import — so a manifest whose module is missing fails with the manifest error
rather than an ``ImportError`` from inside untrusted code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from maistro_ext_sdk.contract import EXTENSION_CONTRACT_VERSION, parse_contract_version
from maistro_ext_sdk.manifest import (
    ExtensionManifest,
    ExtensionManifestError,
    reject_unknown_fields,
    validate_manifest,
)

__all__ = [
    "MANIFEST_FILENAME",
    "ValidatedExtension",
    "manifest_from_dict",
    "manifest_from_json",
    "manifest_from_yaml",
    "public_json_schema",
    "validate_extension_dir",
]

#: The manifest filename an out-of-tree extension package carries.
MANIFEST_FILENAME = "extension.json"


def manifest_from_dict(data: dict[str, Any]) -> ExtensionManifest:
    """Validate an already-parsed manifest mapping.

    Raises ``ExtensionManifestError`` on any malformed or unknown content —
    including unknown top-level fields and unknown authority names — with a
    message naming the offending token. Shape (strict, unknown-key-rejecting)
    and semantics (the full manifest contract) both run here; neither imports
    the extension.
    """
    try:
        reject_unknown_fields(ExtensionManifest, data)
        shaped = ExtensionManifest.model_validate(data)
        return validate_manifest(shaped)
    except ValidationError as exc:
        raise ExtensionManifestError(_render(exc, data)) from exc
    except ExtensionManifestError:
        raise
    except ValueError as exc:
        raise ExtensionManifestError(str(exc)) from exc


def manifest_from_json(text: str | bytes) -> ExtensionManifest:
    """Parse and validate a JSON manifest.

    Malformed JSON and schema violations are both ``ExtensionManifestError``;
    the distinction is in the message, so an author sees one error type no
    matter which half failed.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExtensionManifestError(f"manifest is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ExtensionManifestError(f"manifest must be a JSON object, got {type(data).__name__}")
    return manifest_from_dict(data)


def manifest_from_yaml(text: str) -> ExtensionManifest:
    """Parse and validate a YAML manifest (requires the ``[yaml]`` extra)."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - exercised via subprocess-free import guard
        raise ExtensionManifestError(
            "YAML manifest support requires the 'yaml' extra: install maistro-ext-sdk[yaml]"
        ) from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ExtensionManifestError(f"manifest is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ExtensionManifestError(f"manifest must be a mapping, got {type(data).__name__}")
    return manifest_from_dict(data)


@dataclass(frozen=True)
class ValidatedExtension:
    """A manifest that validated, plus what the host needs to load it later."""

    manifest: ExtensionManifest
    root: Path
    #: Filesystem path of the declared entrypoint module. Its existence was
    #: checked with a ``stat``; its code has not been read, let alone run.
    entrypoint_file: Path

    def entrypoint_target(self) -> str:
        """The ``module:object`` target a host would import *after* validation."""
        return f"{self.manifest.entrypoint.module}:{self.manifest.entrypoint.object}"


def validate_extension_dir(root: str | Path) -> ValidatedExtension:
    """Validate an out-of-tree extension package directory against this SDK.

    Reads ``extension.json``, validates the manifest, confirms the declared
    entrypoint module exists as a file under ``root`` — and imports nothing.
    Steps 1-3 are all data checks; if any fails, the extension's code has
    not executed.

    Raises ``ExtensionManifestError`` when the manifest is missing, unreadable,
    invalid, written against an unsupported contract version, or its
    entrypoint file is absent.
    """
    root = Path(root)
    if not root.is_dir():
        raise ExtensionManifestError(f"extension directory {str(root)!r} does not exist")
    manifest_path = root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ExtensionManifestError(
            f"no {MANIFEST_FILENAME} in {str(root)!r} — an extension package must "
            f"carry its manifest at its root"
        )
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExtensionManifestError(
            f"cannot read {MANIFEST_FILENAME} in {str(root)!r}: {exc}"
        ) from exc

    manifest = manifest_from_json(text)

    if not manifest.targets_contract(EXTENSION_CONTRACT_VERSION):
        raise ExtensionManifestError(
            f"extension {manifest.id!r} targets contract range '{manifest.contract}', "
            f"which does not include the contract version this SDK publishes "
            f"({EXTENSION_CONTRACT_VERSION})"
        )

    entrypoint_file = _resolve_entrypoint_file(root, manifest.entrypoint.module)
    if entrypoint_file is None:
        raise ExtensionManifestError(
            f"entrypoint module '{manifest.entrypoint.module}' of extension "
            f"{manifest.id!r} not found under {str(root)!r}: expected "
            f"{' or '.join(_entrypoint_candidates(manifest.entrypoint.module))}"
        )
    return ValidatedExtension(manifest=manifest, root=root, entrypoint_file=entrypoint_file)


def _entrypoint_candidates(module: str) -> list[str]:
    """File shapes a dotted module path can legally take under the root."""
    parts = module.split(".")
    return [
        "/".join([*parts[:-1], f"{parts[-1]}.py"]),
        "/".join([*parts, "__init__.py"]),
    ]


def _resolve_entrypoint_file(root: Path, module: str) -> Path | None:
    for rel in _entrypoint_candidates(module):
        candidate = root / rel
        if candidate.is_file():
            return candidate
    return None


def public_json_schema() -> dict[str, Any]:
    """The manifest schema as a JSON Schema document.

    The machine-validatable public schema: a host or an author can validate
    a manifest against it with any JSON Schema implementation, without this
    SDK installed. ``model_json_schema()`` already emits ``additionalProperties:
    false`` for the forbidding models, so the strictness above is visible to
    non-Python validators too.
    """
    schema = ExtensionManifest.model_json_schema()
    schema["$id"] = (
        f"https://maistro.dev/schemas/ext-sdk/extension-manifest-v"
        f"{parse_contract_version(EXTENSION_CONTRACT_VERSION).major}.json"
    )
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "MAIstro Extension Manifest"
    return schema


def _render(exc: ValidationError, data: dict[str, Any]) -> str:
    """One line per pydantic error, prefixed by the offending input value.

    pydantic's default multi-line trace hides *which declared value* was
    rejected; authors debugging a rejected manifest need that first. (The
    contract's semantic rules raise plain values already; only shape errors
    arrive as pydantic errors.)
    """
    lines = []
    for err in exc.errors():
        loc = err.get("loc") or ()
        loc_str = ".".join(str(p) for p in loc) or "<manifest>"
        msg = str(err.get("msg", "")).removeprefix("Value error, ")
        first = str(loc[0]) if loc else ""
        value = data.get(first) if isinstance(data, dict) and first else None
        shown = f" (got {value!r})" if value is not None else ""
        lines.append(f"{loc_str}: {msg}{shown}")
    return "manifest rejected: " + "; ".join(lines)

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
    semantic_json_schema_constraints,
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


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """``object_pairs_hook`` that rejects duplicate object keys.

    ``json.loads`` silently keeps the final value of a duplicated key, so a
    manifest carrying both ``"capabilities": []`` and
    ``"capabilities": ["filesystem.write"]`` would validate against
    whichever copy came last — letting security review, schema validation,
    signing, and this SDK each see a different authority set. A duplicated
    key is ambiguity, not configuration: reject it, at every nesting depth.
    """
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object key {key!r}")
        result[key] = value
    return result


def manifest_from_json(text: str | bytes) -> ExtensionManifest:
    """Parse and validate a JSON manifest.

    Malformed JSON and schema violations are both ``ExtensionManifestError``;
    the distinction is in the message, so an author sees one error type no
    matter which half failed. Decoding failures count as malformed input:
    since ``bytes`` are accepted, invalid UTF-8 must not leak a
    ``UnicodeDecodeError`` past the single-error-type promise. Duplicate
    object keys are rejected rather than resolved last-wins (see
    ``_no_duplicate_keys``).
    """
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except UnicodeDecodeError as exc:
        raise ExtensionManifestError(f"manifest is not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ExtensionManifestError(f"manifest is not valid JSON: {exc}") from exc
    except ValueError as exc:  # duplicate key from _no_duplicate_keys
        raise ExtensionManifestError(f"manifest is ambiguous: {exc}") from exc
    if not isinstance(data, dict):
        raise ExtensionManifestError(f"manifest must be a JSON object, got {type(data).__name__}")
    return manifest_from_dict(data)


def _reject_duplicate_mapping_keys(yaml: Any, text: str) -> None:
    """Reject duplicate explicit mapping keys before ``yaml.safe_load`` runs.

    PyYAML's ``safe_load`` silently keeps the last occurrence of a duplicated
    key, so the YAML front door walks the composed node tree first: the same
    last-wins ambiguity ``json.loads`` has (see ``_no_duplicate_keys``) would
    let a manifest present one authority set to review and another to
    ``validate_manifest``. The walk is inspection, not execution — ``compose``
    builds the node graph without running a constructor, so no tag can build
    a Python object here; construction happens afterwards, exclusively through
    ``yaml.safe_load``.

    Detection runs on the explicit pairs before merge keys (``<<``) are
    expanded by ``safe_load``: spec-defined merge precedence (explicit key
    wins, first anchor wins) is resolution, not ambiguity, so merges stay
    legal. Non-scalar keys are skipped, mirroring the constructor, which
    cannot hash them either. Defined as a function taking the module because
    ``yaml`` is an optional import.
    """

    def walk(node: Any) -> None:
        if isinstance(node, yaml.MappingNode):
            seen: set[tuple[str, str]] = set()
            for key_node, value_node in node.value:
                if key_node.tag == "tag:yaml.org,2002:merge":  # '<<' merge key
                    continue  # expanded by flatten_mapping inside safe_load
                if isinstance(key_node, yaml.ScalarNode):
                    identity = (key_node.tag, key_node.value)
                    if identity in seen:
                        raise yaml.constructor.ConstructorError(
                            None,
                            None,
                            f"found duplicate key {key_node.value!r}",
                            key_node.start_mark,
                        )
                    seen.add(identity)
                walk(value_node)
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                walk(item)

    walk(yaml.compose(text))


def manifest_from_yaml(text: str) -> ExtensionManifest:
    """Parse and validate a YAML manifest (requires the ``[yaml]`` extra).

    Duplicate mapping keys are rejected rather than resolved last-wins (see
    ``_reject_duplicate_mapping_keys``), mirroring the JSON front door.
    Construction goes through ``yaml.safe_load`` — the loader cannot build
    ``!!python/...`` objects from a manifest.
    """
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - exercised via subprocess-free import guard
        raise ExtensionManifestError(
            "YAML manifest support requires the 'yaml' extra: install maistro-ext-sdk[yaml]"
        ) from exc
    try:
        _reject_duplicate_mapping_keys(yaml, text)
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
    except UnicodeDecodeError as exc:
        raise ExtensionManifestError(
            f"{MANIFEST_FILENAME} in {str(root)!r} is not valid UTF-8: {exc}"
        ) from exc
    except OSError as exc:
        raise ExtensionManifestError(
            f"cannot read {MANIFEST_FILENAME} in {str(root)!r}: {exc}"
        ) from exc

    manifest = manifest_from_json(text)

    # Contract compatibility is enforced inside the shared pipeline
    # (``validate_manifest``), so every parse entry point rejects unsupported
    # ranges; no dir-specific check is needed here.

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
    """Locate the file ``import module`` would actually execute under ``root``.

    Mirrors importlib's FileFinder order: at every dotted segment a package
    directory (``name/__init__.py``) shadows a same-named module file
    (``name.py``). If a parent segment resolves to a plain module, the
    dotted path is unimportable, so resolution fails rather than returning
    a file the host could never load. (A parent directory without an
    ``__init__.py`` is a namespace package — its children still import.)
    """
    parts = module.split(".")
    current = root
    for part in parts[:-1]:
        if (current / part / "__init__.py").is_file():
            current = current / part
        elif (current / f"{part}.py").is_file():
            return None  # parent is a plain module: deeper path cannot import
        elif (current / part).is_dir():
            current = current / part
        else:
            return None
    head = parts[-1]
    package_init = current / head / "__init__.py"
    if package_init.is_file():
        return package_init
    module_file = current / f"{head}.py"
    return module_file if module_file.is_file() else None


def _merge_fragment(target: dict[str, Any], fragment: dict[str, Any]) -> None:
    """Deep-merge ``fragment`` into ``target`` without discarding sibling keys."""
    for key, value in fragment.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_fragment(target[key], value)
        else:
            target[key] = value


def _apply_semantic_constraints(schema: dict[str, Any]) -> None:
    """Splice the manifest module's semantic fragments into the emitted schema.

    ``model_json_schema()`` can only describe shape — the closed authority
    vocabularies are ``str`` fields by design, their membership checked in
    :func:`~maistro_ext_sdk.manifest.validate_manifest`. Splicing the enum
    and pattern fragments in afterwards closes the gap the other direction:
    a manifest an external validator passes cannot be one this SDK rejects
    on vocabulary or lexical shape. A pointer that does not resolve means
    pydantic's emission shape changed; failing loudly here (KeyError) is the
    test-visible signal, not a silently unconstrained schema.
    """
    for pointer, fragment in semantic_json_schema_constraints().items():
        node: dict[str, Any] = schema
        for key in pointer.split("/"):
            node = node[key]
        _merge_fragment(node, fragment)


def public_json_schema() -> dict[str, Any]:
    """The manifest schema as a JSON Schema document.

    The machine-validatable public schema: a host or an author can validate
    a manifest against it with any JSON Schema implementation, without this
    SDK installed. ``model_json_schema()`` already emits ``additionalProperties:
    false`` for the forbidding models, so the strictness above is visible to
    non-Python validators too, and :func:`~maistro_ext_sdk.manifest.semantic_json_schema_constraints`
    folds the closed authority vocabularies and identity patterns in, so the
    schema encodes what the pipeline enforces rather than only what it shapes.
    """
    schema = ExtensionManifest.model_json_schema()
    _apply_semantic_constraints(schema)
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

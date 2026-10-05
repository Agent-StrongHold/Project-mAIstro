"""The extension manifest schema (M9-A1, #949).

One Pydantic model tree that IS the public contract:

- **Machine-validatable before any extension code runs.** Every field is
  data — strings, enums, tuples — and the entrypoint is declarative
  metadata (a module path plus an object name as *strings*). Parsing a
  manifest performs no ``import`` of the extension, so a host can reject a
  manifest before the extension's code executes at all.
- **Strict.** ``extra="forbid"`` on every model: an unknown top-level key,
  an unknown authority field, a misspelled capability — each is a
  validation error naming the offending token, never a silently ignored
  line. This is the "malformed/unknown authority declarations fail
  explicitly" acceptance criterion, enforced structurally rather than by
  convention.
- **Closed authority vocabulary.** Capabilities, effects, data scopes,
  filesystem modes and optional features are closed enums anchored in
  accepted ADRs (see each constant's comment). An unknown authority name
  cannot be declared, so an extension cannot invent authority by
  misspelling its way past a host.
- **One explicit validation pipeline.** Shape strictness is Pydantic's
  (``extra="forbid"``); every semantic rule is a plain module-level
  function called from :func:`validate_manifest`, which the parse surface
  in ``validation.py`` invokes. Nothing relies on framework-dispatched
  hooks: every rule is statically findable, and a host that wants to reuse
  one rule can import it directly.

The model is the authority *declaration*, not the authority *grant*: what a
manifest says here is what a host may consider granting (M9-A2 binds the
runtime context to these declarations). Declaring nothing yields nothing —
least authority by default.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from maistro_ext_sdk.contract import EXTENSION_CONTRACT_VERSION
from maistro_ext_sdk.ranges import VersionRange

__all__ = [
    "CAPABILITIES",
    "DATA_SCOPES",
    "EFFECTS",
    "EXTENSION_FAMILIES",
    "OPTIONAL_FEATURES",
    "AuthorityError",
    "DataAuthority",
    "DependencyRef",
    "EntrypointMetadata",
    "ExtensionIdentity",
    "ExtensionManifest",
    "ExtensionManifestError",
    "FilesystemAuthority",
    "NetworkAuthority",
    "SecretRequirement",
    "validate_manifest",
]


# ---------------------------------------------------------------------------
# authority vocabulary — closed, each name anchored in an accepted ADR
# ---------------------------------------------------------------------------

#: Authority a manifest may ask the host for. Closed on purpose: a name not
#: in this list is an unknown authority and fails validation (the issue's
#: explicit-failure bar). Anchors:
#:
#: - ``workspace.*`` — Workspace data (ADR-081426-b1d3 project scope tree)
#: - ``agent.read`` — agent identity/spec metadata
#: - ``run.read`` — canonical Run/NodeRun projection (read-only; extension
#:   code never writes the execution model)
#: - ``memory.*`` — memory layers (ADR-091)
#: - ``tool.invoke`` — governed tool surface (ADR-082226-4478)
#: - ``network.outbound`` — outbound HTTP (ADR-082326-5386 central seam)
#: - ``filesystem.*`` — sandboxed filesystem (ADR-093)
#: - ``secrets.read`` — named secret references (ADR-064 redaction posture)
CapabilityName = Literal[
    "workspace.read",
    "workspace.write",
    "agent.read",
    "run.read",
    "memory.read",
    "memory.write",
    "tool.invoke",
    "network.outbound",
    "filesystem.read",
    "filesystem.write",
    "secrets.read",
]
CAPABILITIES: frozenset[str] = frozenset(CapabilityName.__args__)  # type: ignore[attr-defined]

#: Reversibility classes for what the extension does (ADR-050 taxonomy).
EffectName = Literal["read-only", "mutating", "external-side-effect", "irreversible"]
EFFECTS: frozenset[str] = frozenset(EffectName.__args__)  # type: ignore[attr-defined]

#: Categories of product data the extension touches. Coarse by design: the
#: manifest declares *what kind* of data, never row-level scope — that is the
#: host's job at grant time (M9-A2).
DataScope = Literal["workspace", "agent", "run", "memory", "messages", "artifacts"]
DATA_SCOPES: frozenset[str] = frozenset(DataScope.__args__)  # type: ignore[attr-defined]

#: The extension families M9 supports, each bound to a lifecycle contract in
#: M9-A2 (#950). Closed enum per the issue ("declared extension family");
#: unknown families fail validation.
#:
#: - ``tool`` — governed tool surface (ADR-082226-4478)
#: - ``skill`` — skills marketplace (ADR-083 Part A)
#: - ``mcp-gateway`` — external MCP servers (ADR-083 Part B)
#: - ``capability-provider`` — capability slots/providers (SPEC-184,
#:   ADR-081226-6b46, ADR-070426-f2a0)
#: - ``renderer-plugin`` — external renderers (ADR-070426-f2a0)
ExtensionFamily = Literal[
    "tool",
    "skill",
    "mcp-gateway",
    "capability-provider",
    "renderer-plugin",
]
EXTENSION_FAMILIES: frozenset[str] = frozenset(ExtensionFamily.__args__)  # type: ignore[attr-defined]

#: Optional features a host may enable but a manifest need not declare.
#: Closed enum: an unknown feature name is a typo-shaped authority claim and
#: fails like one.
OptionalFeature = Literal["streaming", "background", "scheduled", "interactive"]
OPTIONAL_FEATURES: frozenset[str] = frozenset(OptionalFeature.__args__)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# identity patterns
# ---------------------------------------------------------------------------

#: ``publisher.name`` — both segments slug-cased, so an extension id is
#: namespaced under its publisher by construction (validated by
#: :func:`_validate_extension_id`).
_EXTENSION_ID_RE = re.compile(
    r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?\.[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$"
)
_PUBLISHER_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")
#: Strict SemVer 2.0.0 grammar (https://semver.org/#backus-naur-form): no
#: leading zeros in numeric identifiers, prerelease dot-separated identifiers
#: must be alphanumeric-or-hyphen (never empty), optional build metadata.
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)
#: Dotted import path for the entrypoint module — lexical only, never
#: resolved at validation time.
_MODULE_PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
#: Secret references are environment-style names; lowercase or punctuation
#: would blur into arbitrary shell and is refused.
_SECRET_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
#: Hosts: a DNS name (labels slug-ish) with an optional ``*.`` first label
#: for suffix authorization. Ports are validated as integers 1..65535.
_HOST_RE = re.compile(r"^(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_ABSOLUTE_PATH_RE = re.compile(r"^/")

_VERSION_EXAMPLE = "MAJOR.MINOR.PATCH (e.g. 1.0.0)"


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------


class ExtensionManifestError(ValueError):
    """A manifest failed validation.

    The single public error for manifest parsing — hosts catch this one type
    and can render ``str(exc)`` to the author. Wrapping pydantic's
    ``ValidationError`` keeps pydantic an implementation detail of the SDK.
    """


class AuthorityError(ExtensionManifestError):
    """A declared authority is unknown, malformed, or internally inconsistent."""


# ---------------------------------------------------------------------------
# models — every one strict (extra="forbid"); semantics live in validate_manifest
# ---------------------------------------------------------------------------


class _Strict(BaseModel):
    """Base for every manifest model: unknown keys are errors, not defaults."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ExtensionIdentity(_Strict):
    """Who publishes this extension and which artifact version it is.

    Shape only — the identity rules (namespacing, semver) are enforced by
    :func:`validate_manifest`, so a host reusing the nested model gets the
    same rules by calling that one function.
    """

    id: str = Field(description="Extension id, '<publisher>.<name>'")
    publisher: str = Field(description="Publisher slug; must equal the id's first segment")
    version: str = Field(description=f"This extension's version, {_VERSION_EXAMPLE}")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class EntrypointMetadata(_Strict):
    """Where the host finds the extension — as data, not as an import.

    ``module`` and ``object`` are plain strings validated *lexically* by
    :func:`validate_manifest`. Parsing or validating a manifest never imports
    this module; that is what makes "manifest can be parsed and rejected
    before importing extension code" a structural fact rather than a promise.
    """

    module: str = Field(description="Dotted import path of the extension module")
    object: str = Field(description="Module-level attribute naming the extension object")


class DependencyRef(_Strict):
    """One dependency on another extension, by id and version range."""

    id: str
    range: str = Field(description="Version range over the dependency, e.g. '>=1.0.0,<2.0.0'")


class DataAuthority(_Strict):
    """Which categories of product data the extension touches."""

    scopes: tuple[str, ...] = ()


class NetworkAuthority(_Strict):
    """Outbound network the extension needs — declared hosts, nothing else."""

    allow: tuple[str, ...] = ()
    allowed_ports: tuple[int, ...] = ()


class FilesystemAuthority(_Strict):
    """Filesystem the extension needs: absolute paths plus a read/write mode."""

    paths: tuple[str, ...] = ()
    mode: Literal["read", "write", "read-write"] = "read"


class SecretRequirement(_Strict):
    """One named secret the extension needs the host to inject at runtime."""

    name: str


class ExtensionManifest(_Strict):
    """The whole manifest: identity, contract, family, authority, entrypoint.

    Field order mirrors the issue's scope list. **Constructing this model
    checks shape only** (unknown keys, types, lengths); the full contract —
    identity rules, closed authority vocabulary, least-authority cross-checks,
    dependency rules — runs in :func:`validate_manifest`, which every parse
    entry point in ``validation.py`` applies. A host that constructs the model
    by hand must call :func:`validate_manifest` itself before trusting it.
    """

    # -- identity (issue: "extension ID, publisher, version")
    id: str
    publisher: str
    version: str
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)

    # -- SDK/contract compatibility (issue: "SDK/contract compatibility fields")
    contract: str = Field(
        description=(
            "Range of extension-contract versions this manifest is written against, "
            f"e.g. '>={EXTENSION_CONTRACT_VERSION},<2.0.0'"
        )
    )

    # -- declared family (issue: "declared extension family")
    family: ExtensionFamily

    # -- authority declarations (issue: "capabilities/effects/data/network/
    #    filesystem/secret requirements")
    capabilities: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    data: DataAuthority = Field(default_factory=DataAuthority)
    network: NetworkAuthority = Field(default_factory=NetworkAuthority)
    filesystem: FilesystemAuthority = Field(default_factory=FilesystemAuthority)
    secrets: tuple[SecretRequirement, ...] = ()

    # -- composition (issue: "dependencies and optional features")
    dependencies: tuple[DependencyRef, ...] = ()
    optional_features: tuple[str, ...] = ()

    # -- entrypoint (issue: "entrypoint metadata that is inspectable without
    #    importing extension code")
    entrypoint: EntrypointMetadata

    def contract_range(self) -> VersionRange:
        """The parsed contract-version range this manifest is written against."""
        return VersionRange.parse(self.contract)

    def targets_contract(self, version: str) -> bool:
        """Whether this manifest is written against the named contract version."""
        from maistro_ext_sdk.contract import parse_contract_version

        return self.contract_range().satisfied_by(parse_contract_version(version))


# ---------------------------------------------------------------------------
# the validation pipeline — every rule is a plain, statically-called function
# ---------------------------------------------------------------------------


def _check_vocabulary(field: str, values: tuple[str, ...], known: frozenset[str]) -> None:
    """Explicit closed-vocabulary check with a uniform message shape."""
    unknown = [v for v in values if v not in known]
    if unknown:
        raise AuthorityError(f"unknown {field}(s) {unknown}: known values are {sorted(known)}")


def _validate_extension_id(id_: str, publisher: str) -> None:
    if not _EXTENSION_ID_RE.match(id_):
        raise ValueError(
            f"extension id {id_!r} must be '<publisher>.<name>' with slug-cased "
            f"segments (letters, digits, hyphens)"
        )
    id_publisher = id_.split(".", 1)[0]
    if id_publisher != publisher:
        raise ValueError(
            f"extension id {id_!r} is not namespaced under its publisher "
            f"{publisher!r}: id must start with '{publisher}.'"
        )
    if not _PUBLISHER_RE.match(publisher):
        raise ValueError(f"publisher slug {publisher!r} is not a valid slug")


def _validate_semver(version: str) -> None:
    if not _SEMVER_RE.match(version):
        raise ValueError(f"extension version {version!r} is not {_VERSION_EXAMPLE}")


def _validate_entrypoint(module: str, object_name: str) -> None:
    if not _MODULE_PATH_RE.match(module):
        raise ValueError(f"entrypoint module {module!r} is not a dotted import path")
    if not _IDENTIFIER_RE.match(object_name):
        raise ValueError(f"entrypoint object {object_name!r} is not a Python identifier")


def _validate_dependency(dep: DependencyRef) -> None:
    if not _EXTENSION_ID_RE.match(dep.id):
        raise ValueError(f"dependency id {dep.id!r} must be '<publisher>.<name>'")
    try:
        VersionRange.parse(dep.range)
    except ValueError as exc:
        raise ValueError(f"dependency {dep.id!r}: {exc}") from exc


def _validate_authority_vocabulary(manifest: ExtensionManifest) -> None:
    _check_vocabulary("capability", manifest.capabilities, CAPABILITIES)
    _check_vocabulary("effect", manifest.effects, EFFECTS)
    _check_vocabulary("data scope", manifest.data.scopes, DATA_SCOPES)
    _check_vocabulary("optional feature", manifest.optional_features, OPTIONAL_FEATURES)


def _validate_requirement_shapes(manifest: ExtensionManifest) -> None:
    """Each named requirement must be well-formed for its authority kind."""
    for host in manifest.network.allow:
        if not _HOST_RE.match(host):
            raise AuthorityError(
                f"unknown/malformed network host {host!r}: expected a DNS name "
                f"(optionally '*.'-prefixed), e.g. 'api.example.com'"
            )
    for port in manifest.network.allowed_ports:
        if not 1 <= port <= 65535:
            raise AuthorityError(f"network port {port} is outside 1..65535")
    for path in manifest.filesystem.paths:
        if not _ABSOLUTE_PATH_RE.match(path):
            raise AuthorityError(
                f"filesystem path {path!r} must be absolute — relative paths cannot be authorized"
            )
    for secret in manifest.secrets:
        if not _SECRET_NAME_RE.match(secret.name):
            raise AuthorityError(
                f"unknown/malformed secret name {secret.name!r}: expected an "
                f"UPPER_SNAKE_CASE environment-style name, e.g. 'ACME_API_KEY'"
            )


def _validate_least_authority(manifest: ExtensionManifest) -> None:
    """Capability and requirement block must exist together — both ways.

    Asking for an authority without saying what exactly you need it for
    (hosts, paths, secrets) is an error, and naming hosts/paths/secrets
    without the matching capability is an error too.
    """
    caps = set(manifest.capabilities)

    # capability -> its concrete requirement block must be present.
    if "network.outbound" in caps and not manifest.network.allow:
        raise AuthorityError(
            "capability 'network.outbound' declared but no network hosts allowed: "
            "declare 'network.allow' — authority without a scope is not grantable"
        )
    if {"filesystem.read", "filesystem.write"} & caps and not manifest.filesystem.paths:
        raise AuthorityError(
            "filesystem capability declared but 'filesystem.paths' is empty: "
            "declare the absolute paths the extension needs"
        )
    if "secrets.read" in caps and not manifest.secrets:
        raise AuthorityError(
            "capability 'secrets.read' declared but no secrets named: declare "
            "'secrets' entries — authority without a scope is not grantable"
        )

    # ...and a requirement block without its capability is undeclared
    # authority in the other direction (scope creep by omission).
    if manifest.network.allow and "network.outbound" not in caps:
        raise AuthorityError(
            f"network hosts {list(manifest.network.allow)} declared without the "
            f"'network.outbound' capability"
        )
    if manifest.filesystem.paths and not {"filesystem.read", "filesystem.write"} & caps:
        raise AuthorityError(
            f"filesystem paths {list(manifest.filesystem.paths)} declared without a "
            f"'filesystem.read'/'filesystem.write' capability"
        )
    if manifest.secrets and "secrets.read" not in caps:
        raise AuthorityError(
            f"secrets {[s.name for s in manifest.secrets]} declared without the "
            f"'secrets.read' capability"
        )


def _validate_contract_field(manifest: ExtensionManifest) -> None:
    """The contract range must be well-formed *and* cover this SDK's version.

    Well-formedness alone used to be the whole check, so a manifest declaring
    ``contract: ">=2.0.0"`` parsed cleanly through ``manifest_from_dict`` and
    only the directory front door rejected it — one entry point said v1,
    another said unsupported. Compatibility belongs to the shared pipeline so
    every parse path answers the same question (see ``validate_manifest``).
    Raises ``ValueError``; the pipeline translates to the public error type.
    """
    try:
        manifest.contract_range()
    except ValueError as exc:
        raise ValueError(f"contract field: {exc}") from exc
    if not manifest.targets_contract(EXTENSION_CONTRACT_VERSION):
        raise ValueError(
            f"contract field: range '{manifest.contract}' does not include "
            f"the contract version this SDK publishes ({EXTENSION_CONTRACT_VERSION})"
        )


def validate_manifest(manifest: ExtensionManifest) -> ExtensionManifest:
    """Apply the full manifest contract to an already-shaped model.

    Identity rules, the closed authority vocabulary, least-authority
    cross-checks (both directions), contract-range well-formedness, and the
    dependency rules. Returns the same manifest; raises
    ``ExtensionManifestError`` (usually ``AuthorityError``) naming the
    offending declaration. This is the function every parse entry point
    applies; it is public so a host that hand-builds a model can enforce the
    identical contract.
    """
    try:
        _validate_extension_id(manifest.id, manifest.publisher)
        _validate_semver(manifest.version)
        _validate_entrypoint(manifest.entrypoint.module, manifest.entrypoint.object)
        for dep in manifest.dependencies:
            _validate_dependency(dep)

        dep_ids = [d.id for d in manifest.dependencies]
        if manifest.id in dep_ids:
            raise ValueError(f"extension {manifest.id!r} cannot depend on itself")
        duplicates = sorted({i for i in dep_ids if dep_ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate dependency declaration(s): {duplicates}")

        _validate_contract_field(manifest)

        _validate_authority_vocabulary(manifest)
        _validate_requirement_shapes(manifest)
        _validate_least_authority(manifest)
    except ExtensionManifestError:
        raise
    except ValueError as exc:
        raise ExtensionManifestError(str(exc)) from exc
    return manifest


def reject_unknown_fields(model_cls: type[BaseModel], data: object) -> None:
    """Name unknown keys against ``model_cls``'s own fields, explicitly.

    ``extra="forbid"`` already rejects unknown keys; this names them the way
    the manifest contract speaks (all known fields, in one message) before
    pydantic's per-field errors are raised. Public so the parse surface in
    ``validation.py`` and the CLI share one message shape.
    """
    if isinstance(data, dict):
        unknown = sorted(set(data) - set(model_cls.model_fields))
        if unknown:
            known = ", ".join(sorted(model_cls.model_fields))
            raise AuthorityError(f"unknown manifest field(s) {unknown}; known fields are: {known}")

"""Public manifest-contract validation for the host harness (#974).

The harness's statement of the `extension.json` contract documented in the
repository's extension guides. Parsing and validating a manifest is a pure
data operation: **the entrypoint module named here is never imported by this
module** — that is the structural fact that lets a host reject a manifest
before any extension code can influence its own acceptance.

Strictness rules (each rejection names the offending token):

- unknown top-level keys and unknown keys inside optional blocks fail —
  an unknown key or a misspelled authority name is a validation error,
  never an ignored line;
- the authority vocabularies (families, capabilities, effects, data scopes)
  are closed; an unknown name cannot be declared, so an extension cannot
  invent authority by misspelling its way past a host;
- the id is `publisher.name`, both slug-cased, and the `publisher` field
  must equal the id's first segment;
- the contract range must pin exactly one supported major (the guides'
  "pin exactly the major you code against" rule) — an unbounded range or a
  range spanning two majors claims compatibility with schemas that do not
  exist yet and is rejected;
- the entrypoint's module is validated lexically only: a dotted path of
  identifiers with no underscore-private segment, never resolved at
  validation time.

Reconciliation with the pending SDK package (M9-A1, #949): the normative
schema is code in `maistro-ext-sdk`. Until that package merges, this module
implements contract 1.0.0 over the standard library so the harness ships
with zero third-party dependencies; the harness's test suite validates the
merged reference extension's real manifest to hold the two statements of the
contract together. When the SDK lands, this module becomes its delegation
point, not a second schema authority.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from maistro_ext_harness.contract import (
    CAPABILITIES,
    CONTRACT_VERSION,
    DATA_SCOPES,
    EFFECTS,
    FAMILIES,
    SUPPORTED_CONTRACT_MAJORS,
    ContractError,
)

__all__ = [
    "EntrypointSpec",
    "ExtensionManifest",
    "ManifestRejected",
    "load_manifest_bytes",
    "load_manifest_file",
]

_EXTENSION_ID_RE = re.compile(
    r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?\.[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$"
)
_PUBLISHER_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_MODULE_PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_HOST_RE = re.compile(r"^(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_ABSOLUTE_PATH_RE = re.compile(r"^/")
_RANGE_SPEC_RE = re.compile(r"^(>=|<=|==|>|<)(\d+\.\d+\.\d+)$")

_FILESYSTEM_MODES: tuple[str, ...] = ("read", "write", "read-write")
_OPTIONAL_FEATURES: tuple[str, ...] = ("streaming", "background", "scheduled", "interactive")


class ManifestRejected(ContractError):
    """A manifest failed validation; no extension code has run at this point."""


@dataclass(frozen=True)
class EntrypointSpec:
    """The declarative entrypoint: where a host finds the extension.

    Both fields are strings validated lexically. Loading them is the host's
    job — and it happens only after this manifest validated (see
    `maistro_ext_harness.lifecycle`).
    """

    module: str
    object: str


@dataclass(frozen=True)
class DependencyRef:
    """One dependency on another extension, by id and version range."""

    id: str
    range: str


@dataclass(frozen=True)
class ExtensionManifest:
    """A validated `extension.json`: the authority *declaration*, not the grant.

    Everything here is data. `capabilities`/`effects`/`data_scopes` are the
    declared authority; `maistro_ext_harness.grants.resolve_grants` turns a
    declaration into the (possibly smaller) grant a host actually hands the
    extension.
    """

    id: str
    publisher: str
    version: str
    title: str
    description: str
    contract: str
    family: str
    contract_major: int
    capabilities: tuple[str, ...]
    effects: tuple[str, ...]
    data_scopes: tuple[str, ...]
    network_allow: tuple[str, ...]
    network_ports: tuple[int, ...]
    filesystem_paths: tuple[str, ...]
    filesystem_mode: str
    secrets: tuple[str, ...]
    dependencies: tuple[DependencyRef, ...]
    optional_features: tuple[str, ...]
    entrypoint: EntrypointSpec


# ---------------------------------------------------------------------------
# scalar / list helpers — every failure names the offending token
# ---------------------------------------------------------------------------


def _require_str(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ManifestRejected(f"manifest field {key!r} must be a non-empty string")
    return value


def _str_list(value: object, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ManifestRejected(f"manifest field {key!r} must be a list of strings")
    if len(set(value)) != len(value):
        raise ManifestRejected(f"manifest field {key!r} repeats a value")
    return tuple(value)


def _check_vocabulary(field_name: str, values: tuple[str, ...], known: tuple[str, ...]) -> None:
    unknown = [v for v in values if v not in known]
    if unknown:
        raise ManifestRejected(
            f"unknown {field_name}(s) {unknown}: known values are {sorted(known)}"
        )


def _forbid_unknown_keys(data: dict[str, object], known: tuple[str, ...], where: str) -> None:
    extra = sorted(set(data) - set(known))
    if extra:
        raise ManifestRejected(
            f"unknown key(s) in {where}: {extra} (the contract is strict; "
            "a misspelled key is an error, not an ignored line)"
        )


# ---------------------------------------------------------------------------
# contract-range majors rule
# ---------------------------------------------------------------------------


def _contract_major(contract: str) -> int:
    """The single contract major a range pins; rejects everything else.

    Grammar: `>=`, `>`, `==`, `<`, `<=` over `MAJOR.MINOR.PATCH`,
    comma-joined — the specifier set the monorepo's capping convention
    needs, nothing more. A loose parser would let a manifest that means
    "contract 2 only" validate against a v1 host, which is exactly the
    authority creep the manifest exists to prevent.
    """
    specs: list[tuple[str, tuple[int, ...]]] = []
    for raw in contract.split(","):
        token = raw.strip()
        m = _RANGE_SPEC_RE.match(token)
        if m is None:
            raise ManifestRejected(
                f"unsupported contract specifier {token!r} in range {contract!r}: "
                "expected >=, >, ==, <, or <= over MAJOR.MINOR.PATCH"
            )
        specs.append((m.group(1), tuple(int(part) for part in m.group(2).split("."))))
    major = _pinned_or_floor_major(specs, contract)
    if major not in SUPPORTED_CONTRACT_MAJORS:
        raise ManifestRejected(
            f"contract range {contract!r} pins major {major}; this host enforces "
            f"{CONTRACT_VERSION} (supported majors: {list(SUPPORTED_CONTRACT_MAJORS)})"
        )
    return major


def _pinned_or_floor_major(specs: list[tuple[str, tuple[int, ...]]], contract: str) -> int:
    """The major a parsed specifier set pins, under the one-major rule."""
    pinned = {version[0] for op, version in specs if op == "=="}
    if pinned:
        if len(pinned) != 1 or len(pinned) != len(specs):
            raise ManifestRejected(
                f"contract range {contract!r} must pin exactly one major one way; "
                "pin with == alone or comparisons alone"
            )
        return pinned.pop()
    floor: tuple[int, ...] | None = None
    ceiling: tuple[int, ...] | None = None
    for op, version in specs:
        if op in (">", ">="):
            floor = version if floor is None else max(floor, version)
        else:
            ceiling = version if ceiling is None else min(ceiling, version)
    if floor is None or ceiling is None:
        raise ManifestRejected(
            f"contract range {contract!r} must pin one major with a floor and a "
            f"next-major ceiling, e.g. '>={CONTRACT_VERSION},<2.0.0'"
        )
    floor_major, ceiling_major = floor[0], ceiling[0]
    in_major_cap = ceiling_major == floor_major
    next_major_cap = ceiling_major == floor_major + 1 and ceiling[1] == 0 and ceiling[2] == 0
    if not in_major_cap and not next_major_cap:
        raise ManifestRejected(
            f"contract range {contract!r} spans majors ambiguously; pin exactly the "
            f"major you code against, e.g. '>={CONTRACT_VERSION},<2.0.0'"
        )
    return floor_major


# ---------------------------------------------------------------------------
# optional authority blocks — validated and returned, so the manifest is
# assembled from typed values rather than re-parsed
# ---------------------------------------------------------------------------


def _parse_scopes(data: dict[str, object]) -> tuple[str, ...]:
    block = data.get("data")
    if block is None:
        return ()
    if not isinstance(block, dict):
        raise ManifestRejected("manifest field 'data' must be an object")
    _forbid_unknown_keys(block, ("scopes",), "data")
    scopes = _str_list(block.get("scopes"), "data.scopes")
    _check_vocabulary("data scope", scopes, DATA_SCOPES)
    return scopes


def _parse_network(data: dict[str, object]) -> tuple[tuple[str, ...], tuple[int, ...]]:
    block = data.get("network")
    if block is None:
        return (), ()
    if not isinstance(block, dict):
        raise ManifestRejected("manifest field 'network' must be an object")
    _forbid_unknown_keys(block, ("allow", "allowed_ports"), "network")
    hosts = _str_list(block.get("allow"), "network.allow")
    bad_hosts = [h for h in hosts if not _HOST_RE.match(h)]
    if bad_hosts:
        raise ManifestRejected(f"network allow entries {bad_hosts} are not host patterns")
    ports_raw = block.get("allowed_ports")
    if ports_raw is None:
        return hosts, ()
    if not isinstance(ports_raw, list) or any(
        not isinstance(p, int) or isinstance(p, bool) or not 1 <= p <= 65535 for p in ports_raw
    ):
        raise ManifestRejected("network.allowed_ports must be a list of ports 1..65535")
    return hosts, tuple(int(p) for p in ports_raw)


def _parse_filesystem(data: dict[str, object]) -> tuple[tuple[str, ...], str]:
    block = data.get("filesystem")
    if block is None:
        return (), "read"
    if not isinstance(block, dict):
        raise ManifestRejected("manifest field 'filesystem' must be an object")
    _forbid_unknown_keys(block, ("paths", "mode"), "filesystem")
    paths = _str_list(block.get("paths"), "filesystem.paths")
    bad_paths = [p for p in paths if not _ABSOLUTE_PATH_RE.match(p)]
    if bad_paths:
        raise ManifestRejected(f"filesystem paths {bad_paths} must be absolute sandbox paths")
    mode = block.get("mode", "read")
    if mode not in _FILESYSTEM_MODES:
        raise ManifestRejected(f"filesystem mode {mode!r} must be one of {list(_FILESYSTEM_MODES)}")
    return paths, str(mode)


def _parse_secrets(data: dict[str, object]) -> tuple[str, ...]:
    raw = data.get("secrets")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ManifestRejected("manifest field 'secrets' must be a list of {name} objects")
    names: list[str] = []
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"name"}:
            raise ManifestRejected("each secrets entry must be an object with exactly 'name'")
        name = item["name"]
        if not isinstance(name, str) or not _SECRET_NAME_RE.match(name):
            raise ManifestRejected(
                f"secret reference {name!r} must be an env-style name "
                "(uppercase letters, digits, underscores)"
            )
        names.append(name)
    if len(set(names)) != len(names):
        raise ManifestRejected("secrets repeat a reference name")
    return tuple(names)


def _parse_dependencies(data: dict[str, object]) -> tuple[DependencyRef, ...]:
    raw = data.get("dependencies")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ManifestRejected("manifest field 'dependencies' must be a list")
    deps: list[DependencyRef] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ManifestRejected("each dependency must be an object")
        _forbid_unknown_keys(item, ("id", "range"), "dependency")
        dep_id = _require_str(item, "id")
        if not _EXTENSION_ID_RE.match(dep_id):
            raise ManifestRejected(f"dependency id {dep_id!r} is not '<publisher>.<name>'")
        dep_range = _require_str(item, "range")
        _contract_major(dep_range)
        deps.append(DependencyRef(id=dep_id, range=dep_range))
    return tuple(deps)


def _parse_optional_features(data: dict[str, object]) -> tuple[str, ...]:
    raw = data.get("optional_features")
    if raw is None:
        return ()
    features = _str_list(raw, "optional_features")
    _check_vocabulary("optional feature", features, _OPTIONAL_FEATURES)
    return features


def _parse_entrypoint(data: dict[str, object]) -> EntrypointSpec:
    entry = data.get("entrypoint")
    if not isinstance(entry, dict):
        raise ManifestRejected("manifest field 'entrypoint' must be an object")
    _forbid_unknown_keys(entry, ("module", "object"), "entrypoint")
    module = _require_str(entry, "module")
    obj = _require_str(entry, "object")
    if not _MODULE_PATH_RE.match(module):
        raise ManifestRejected(f"entrypoint module {module!r} is not a dotted import path")
    if any(segment.startswith("_") for segment in module.split(".")):
        raise ManifestRejected(
            f"entrypoint module {module!r} names an underscore-private segment; "
            "private modules are private even under a public root"
        )
    if not _IDENTIFIER_RE.match(obj):
        raise ManifestRejected(f"entrypoint object {obj!r} is not an identifier")
    return EntrypointSpec(module=module, object=obj)


# ---------------------------------------------------------------------------
# the validation pipeline
# ---------------------------------------------------------------------------


def _validate(data: dict[str, object]) -> ExtensionManifest:
    _forbid_unknown_keys(
        data,
        (
            "id",
            "publisher",
            "version",
            "title",
            "description",
            "contract",
            "family",
            "capabilities",
            "effects",
            "data",
            "network",
            "filesystem",
            "secrets",
            "dependencies",
            "optional_features",
            "entrypoint",
        ),
        "manifest",
    )
    ext_id = _require_str(data, "id")
    publisher = _require_str(data, "publisher")
    if not _EXTENSION_ID_RE.match(ext_id):
        raise ManifestRejected(
            f"extension id {ext_id!r} must be '<publisher>.<name>' with slug-cased segments"
        )
    if not _PUBLISHER_RE.match(publisher) or ext_id.split(".", 1)[0] != publisher:
        raise ManifestRejected(
            f"extension id {ext_id!r} is not namespaced under its publisher {publisher!r}"
        )
    version = _require_str(data, "version")
    if not _SEMVER_RE.match(version):
        raise ManifestRejected(f"version {version!r} must be MAJOR.MINOR.PATCH")

    contract = _require_str(data, "contract")
    contract_major = _contract_major(contract)

    family = _require_str(data, "family")
    _check_vocabulary("family", (family,), FAMILIES)

    capabilities = _str_list(data.get("capabilities"), "capabilities")
    _check_vocabulary("capability", capabilities, CAPABILITIES)
    effects = _str_list(data.get("effects"), "effects")
    _check_vocabulary("effect", effects, EFFECTS)

    network_allow, network_ports = _parse_network(data)
    filesystem_paths, filesystem_mode = _parse_filesystem(data)
    secrets = _parse_secrets(data)

    # Least-authority cross-checks, both directions: network/filesystem/secrets
    # detail is only meaningful alongside its capability, and declaring the
    # capability without any detail is the empty grant — allowed, but named.
    if network_allow and "network.outbound" not in capabilities:
        raise ManifestRejected(
            "network.allow declared without the network.outbound capability; "
            "a capability without its scope is an inconsistent declaration"
        )
    if filesystem_paths and not (
        "filesystem.read" in capabilities or "filesystem.write" in capabilities
    ):
        raise ManifestRejected(
            "filesystem.paths declared without a filesystem.read/write capability"
        )
    if secrets and "secrets.read" not in capabilities:
        raise ManifestRejected(
            "secrets declared without the secrets.read capability; secret "
            "references resolve only through a declared capability"
        )

    return ExtensionManifest(
        id=ext_id,
        publisher=publisher,
        version=version,
        title=_require_str(data, "title"),
        description=_require_str(data, "description"),
        contract=contract,
        family=family,
        contract_major=contract_major,
        capabilities=capabilities,
        effects=effects,
        data_scopes=_parse_scopes(data),
        network_allow=network_allow,
        network_ports=network_ports,
        filesystem_paths=filesystem_paths,
        filesystem_mode=filesystem_mode,
        secrets=secrets,
        dependencies=_parse_dependencies(data),
        optional_features=_parse_optional_features(data),
        entrypoint=_parse_entrypoint(data),
    )


def load_manifest_bytes(raw: bytes | str) -> ExtensionManifest:
    """Parse and validate a manifest from JSON text; no extension code runs."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManifestRejected(f"manifest is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestRejected("manifest must be a JSON object")
    return _validate(data)


def load_manifest_file(path: Path) -> ExtensionManifest:
    """Parse and validate the manifest at `path` (typically `extension.json`)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestRejected(f"manifest {path} is unreadable: {exc}") from exc
    return load_manifest_bytes(raw)

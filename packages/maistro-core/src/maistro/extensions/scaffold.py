"""Extension project scaffolding and manifest validation (M9-H1, #973).

`maistro extension new` gives extension authors a supported starting point: it
writes a complete, buildable, out-of-tree extension package — `pyproject.toml`,
`extension.json`, a family-shaped entrypoint, and self-contract tests — using
the same layout and rules the reference extension
(`extensions/reference-greeter/`) demonstrates by hand.

Two halves live here:

**Schema validation.** :func:`validate_manifest` checks an ``extension.json``
document against the manifest contract documented in
``docs/extensions/manifest-reference.md``: required fields, closed authority
vocabularies (families, capabilities, effects, data scopes), identity and
semver shapes, a contract range that pins exactly one major, and
``extra="forbid"`` strictness — an unknown key or a misspelled authority name
is a validation error, never an ignored line. The normative schema remains the
versioned extension SDK package (``maistro-ext-sdk``, M9-A1, #949); until that
package ships, this module is the in-repo validator for the documented
contract-1.0 shape, and the scaffold refuses to write a manifest it has not
validated. Validation is lexical throughout: like the platform's manifest
inspection (M9-B2), it never imports or executes anything the manifest names.

**Template rendering.** :func:`render_project` produces every file of a
scaffolded project as plain strings; :func:`scaffold_project` writes them. The
rendered package deliberately imports nothing first-party and nothing
third-party — not even the future SDK — so it builds and tests in a clean
directory outside this repository with zero dependencies, exactly like the
reference extension. Family templates are structurally distinct where the
families are: each family's entrypoint module declares the objects a host of
that family discovers (a tool's handler registry, a skill's instruction set,
a gateway's upstream servers, a provider's capability slots, a renderer's
artifact kinds), while every family ships the same least-authority manifest —
a tool that has not earned ``network.outbound`` must not declare it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The manifest contract major this module validates and the scaffold pins.
#: ``docs/extensions/manifest-reference.md`` is the field guide for this major;
#: breaking changes bump it behind a supported-majors gate (M9-A1).
CONTRACT_MAJOR = 1

#: Closed extension families (manifest-reference.md). Each binds to a lifecycle
#: contract, so a family is structural, not cosmetic — the templates differ.
FAMILIES: tuple[str, ...] = (
    "tool",
    "skill",
    "mcp-gateway",
    "capability-provider",
    "renderer-plugin",
)

#: Closed authority vocabularies (manifest-reference.md, capabilities.md).
CAPABILITIES: tuple[str, ...] = (
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
)

EFFECTS: tuple[str, ...] = (
    "read-only",
    "mutating",
    "external-side-effect",
    "irreversible",
)

DATA_SCOPES: tuple[str, ...] = (
    "workspace",
    "agent",
    "run",
    "memory",
    "messages",
    "artifacts",
)

#: Manifest fields. Extra keys are refused, not ignored — an ignored key is a
#: permission or a constraint the operator never saw (M9-B2's rule, applied to
#: the discovery manifest's documented field set).
_REQUIRED_KEYS = (
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
    "entrypoint",
)
_OPTIONAL_KEYS = ("network", "filesystem", "secrets", "dependencies")
_ALLOWED_KEYS = frozenset({*_REQUIRED_KEYS, *_OPTIONAL_KEYS})

_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*$")
#: Strict semver: no leading zeros, exactly three components.
_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
#: A contract range pins exactly one major: ``>=N.B.C,<(N+1).0.0``. A range
#: spanning two majors claims compatibility with a schema that does not exist
#: yet, and any other spelling does not name the boundary a host enforces.
_CONTRACT_RE = re.compile(r"^>=(0|[1-9]\d*)\.\d+\.\d+,<\d+\.0\.0$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PRIVATE_SEGMENT_RE = re.compile(r"^_")
_HOST_PATTERN_RE = re.compile(r"^[a-z0-9]([a-z0-9*.-]*[a-z0-9])?$")
_RELATIVE_PATH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_SECRET_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_DOTTED_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


class ManifestValidationError(ValueError):
    """A manifest document does not satisfy the documented contract.

    Every violation found in one pass is reported, so an author fixes a
    document once instead of discovering its errors one rejection at a time.
    """


class ScaffoldError(ValueError):
    """A scaffold request names a project the scaffold refuses to create."""


def _type_name(value: object) -> str:
    return type(value).__name__


def _fail(errors: list[str], field: str, problem: str) -> None:
    errors.append(f"{field}: {problem}")


def _check_str(
    errors: list[str], data: dict[str, Any], field: str, *, pattern: re.Pattern[str] | None = None
) -> str | None:
    """Validate one required string field, returning it when well-formed."""
    value = data.get(field)
    if not isinstance(value, str) or not value:
        _fail(errors, field, f"required non-empty string, got {_type_name(value)}")
        return None
    if pattern is not None and not pattern.match(value):
        _fail(errors, field, f"{value!r} does not match {pattern.pattern}")
        return None
    return value


def _check_closed_vocabulary(
    errors: list[str],
    value: object,
    field: str,
    vocabulary: tuple[str, ...],
    *,
    minimum: int = 0,
) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        _fail(errors, field, f"required array of strings, got {_type_name(value)}")
        return
    if len(value) < minimum:
        _fail(errors, field, f"must declare at least {minimum} entry(s), got {len(value)}")
    unknown = sorted(set(value) - set(vocabulary))
    if unknown:
        _fail(
            errors,
            field,
            f"unknown name(s) {unknown}; the vocabulary is closed: {list(vocabulary)}",
        )
    if len(set(value)) != len(value):
        _fail(errors, field, "duplicate entries are not a declaration, they are a typo")


def _check_entrypoint(errors: list[str], data: dict[str, Any]) -> None:
    entrypoint = data.get("entrypoint")
    if not isinstance(entrypoint, dict):
        _fail(
            errors,
            "entrypoint",
            f"required object with module/object, got {_type_name(entrypoint)}",
        )
        return
    extra = sorted(set(entrypoint) - {"module", "object"})
    if extra:
        _fail(errors, "entrypoint", f"unknown key(s) {extra}")
    module = entrypoint.get("module")
    if not isinstance(module, str) or not _DOTTED_MODULE_RE.match(module):
        _fail(errors, "entrypoint.module", f"{module!r} is not a dotted import path")
    else:
        private = [seg for seg in module.split(".") if _PRIVATE_SEGMENT_RE.match(seg)]
        if private:
            _fail(
                errors,
                "entrypoint.module",
                f"underscore segment(s) {private} are private even under a public root",
            )
    obj = entrypoint.get("object")
    if not isinstance(obj, str) or not _IDENTIFIER_RE.match(obj):
        _fail(errors, "entrypoint.object", f"{obj!r} is not an attribute name")


def _check_data_scopes(errors: list[str], data: dict[str, Any]) -> None:
    payload = data.get("data")
    if not isinstance(payload, dict):
        _fail(errors, "data", f"required object with scopes, got {_type_name(payload)}")
        return
    extra = sorted(set(payload) - {"scopes"})
    if extra:
        _fail(errors, "data", f"unknown key(s) {extra}")
    _check_closed_vocabulary(errors, payload.get("scopes"), "data.scopes", DATA_SCOPES)


def _check_ports(errors: list[str], value: object) -> None:
    if not isinstance(value, list) or not all(
        isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535
        for port in value
    ):
        _fail(errors, "network.allowed_ports", "required array of ports in 1..65535")


def _check_network(errors: list[str], data: dict[str, Any]) -> None:
    network = data.get("network")
    if not isinstance(network, dict):
        _fail(
            errors,
            "network",
            f"required object with allow/allowed_ports, got {_type_name(network)}",
        )
        return
    extra = sorted(set(network) - {"allow", "allowed_ports"})
    if extra:
        _fail(errors, "network", f"unknown key(s) {extra}")
    allow = _check_str_array(errors, network.get("allow"), "network.allow")
    if allow is not None and any(not _HOST_PATTERN_RE.match(host) for host in allow):
        _fail(errors, "network.allow", f"host pattern(s) {allow} are not hostnames or *-wildcards")
    _check_ports(errors, network.get("allowed_ports"))


def _check_str_array(
    errors: list[str], value: object, field: str, *, non_empty: bool = False
) -> list[str] | None:
    """Validate an array-of-strings field, returning it when well-formed."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        _fail(errors, field, f"required array of strings, got {_type_name(value)}")
        return None
    if non_empty and not value:
        _fail(errors, field, "required non-empty array")
        return None
    return value


def _check_filesystem(errors: list[str], data: dict[str, Any]) -> None:
    filesystem = data.get("filesystem")
    if not isinstance(filesystem, dict):
        _fail(
            errors,
            "filesystem",
            f"required object with mode/paths, got {_type_name(filesystem)}",
        )
        return
    extra = sorted(set(filesystem) - {"mode", "paths"})
    if extra:
        _fail(errors, "filesystem", f"unknown key(s) {extra}")
    mode = filesystem.get("mode")
    if mode not in ("read", "write", "read-write"):
        _fail(errors, "filesystem.mode", f"{mode!r} is not read/write/read-write")
    paths = _check_str_array(errors, filesystem.get("paths"), "filesystem.paths", non_empty=True)
    if paths is not None and any(
        not _RELATIVE_PATH_RE.match(p) or p.startswith("/") for p in paths
    ):
        _fail(errors, "filesystem.paths", f"{paths} must be sandbox-relative (no absolute paths)")


def _check_secrets(errors: list[str], data: dict[str, Any]) -> None:
    secrets = data.get("secrets")
    if not isinstance(secrets, list) or not all(isinstance(entry, dict) for entry in secrets):
        _fail(
            errors,
            "secrets",
            f"required array of {{name}} objects, got {_type_name(secrets)}",
        )
        return
    for index, secret in enumerate(secrets):
        extra = sorted(set(secret) - {"name"})
        if extra:
            _fail(errors, f"secrets[{index}]", f"unknown key(s) {extra}")
        name = secret.get("name")
        if not isinstance(name, str) or not _SECRET_NAME_RE.match(name):
            _fail(
                errors,
                f"secrets[{index}].name",
                f"{name!r} is not an env-style reference ([A-Z][A-Z0-9_]*); "
                "a manifest names references, never values",
            )


def _is_extension_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.count(".") == 1
        and all(_SLUG_RE.match(part) for part in value.split("."))
    )


def _check_dependency_entry(errors: list[str], dependency: dict[str, Any], index: int) -> None:
    extra = sorted(set(dependency) - {"id", "version"})
    if extra:
        _fail(errors, f"dependencies[{index}]", f"unknown key(s) {extra}")
    dep_id = dependency.get("id")
    if not _is_extension_id(dep_id):
        _fail(errors, f"dependencies[{index}].id", f"{dep_id!r} is not a publisher.name id")
    version = dependency.get("version")
    if not isinstance(version, str) or not _SEMVER_RE.match(version.lstrip("^~<>=")):
        _fail(errors, f"dependencies[{index}].version", f"{version!r} is not a version range")


def _check_dependencies(errors: list[str], data: dict[str, Any]) -> None:
    dependencies = data.get("dependencies")
    if not isinstance(dependencies, list) or not all(
        isinstance(entry, dict) for entry in dependencies
    ):
        _fail(
            errors,
            "dependencies",
            f"required array of {{id, version}} objects, got {_type_name(dependencies)}",
        )
        return
    for index, dependency in enumerate(dependencies):
        _check_dependency_entry(errors, dependency, index)


def _check_identity_fields(errors: list[str], data: dict[str, Any]) -> None:
    """Identity and contract shapes: who, what version, which schema major."""
    publisher = _check_str(errors, data, "publisher", pattern=_SLUG_RE)
    manifest_id = _check_str(errors, data, "id")
    _check_str(errors, data, "version", pattern=_SEMVER_RE)
    _check_str(errors, data, "title")
    _check_str(errors, data, "description")
    contract = _check_str(errors, data, "contract", pattern=_CONTRACT_RE)
    _check_str(errors, data, "family")
    if (
        manifest_id is not None
        and publisher is not None
        and not manifest_id.startswith(f"{publisher}.")
    ):
        _fail(errors, "id", f"{manifest_id!r} must be {publisher!r}.<name>")
    if contract is not None and not _contract_pins_one_major(contract):
        _fail(
            errors,
            "contract",
            f"{contract!r} must pin exactly one major (>=N..., <N+1.0.0)",
        )
    family = data.get("family")
    if isinstance(family, str) and family:
        _check_closed_vocabulary(errors, [family], "family", FAMILIES, minimum=1)


def _contract_pins_one_major(contract: str) -> bool:
    floor = int(contract.removeprefix(">=").split(".")[0])
    ceiling = int(contract.split(",<")[1].split(".")[0])
    return ceiling == floor + 1


def validate_manifest(data: object) -> dict[str, Any]:
    """Validate one ``extension.json`` document against contract major 1.

    Returns the document unchanged when it satisfies the documented schema;
    raises :class:`ManifestValidationError` naming every violation otherwise.
    Purely lexical: nothing the manifest names is imported or executed.
    """
    if not isinstance(data, dict):
        raise ManifestValidationError(f"manifest must be a JSON object, got {_type_name(data)}")
    errors: list[str] = []
    unknown = sorted(set(data) - _ALLOWED_KEYS)
    if unknown:
        _fail(errors, "manifest", f"unknown key(s) {unknown} (extra keys are forbidden)")
    for key in _REQUIRED_KEYS:
        if key not in data:
            _fail(errors, key, "required key is missing")
    _check_identity_fields(errors, data)
    _check_closed_vocabulary(errors, data.get("capabilities"), "capabilities", CAPABILITIES)
    _check_closed_vocabulary(errors, data.get("effects"), "effects", EFFECTS)
    _check_data_scopes(errors, data)
    _check_entrypoint(errors, data)
    for field, checker in (
        ("network", _check_network),
        ("filesystem", _check_filesystem),
        ("secrets", _check_secrets),
        ("dependencies", _check_dependencies),
    ):
        if field in data:
            checker(errors, data)
    if errors:
        raise ManifestValidationError("; ".join(errors))
    return data


# --------------------------------------------------------------------------
# Scaffold specification and family templates
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ScaffoldSpec:
    """Everything one scaffolded project is rendered from.

    ``name`` is the distribution/project slug (``my-weather-tool``); the
    Python package and the manifest id derive from it and the publisher (both
    manifest id segments are slug-cased, so dashes survive into the id).
    """

    name: str
    publisher: str
    family: str
    version: str = "0.1.0"
    contract: str = ">=1.0.0,<2.0.0"
    title: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if not _SLUG_RE.match(self.name):
            raise ScaffoldError(
                f"project name {self.name!r} must be a slug ([a-z][a-z0-9-]*), "
                "e.g. 'my-weather-tool'"
            )
        if not _SLUG_RE.match(self.publisher):
            raise ScaffoldError(f"publisher {self.publisher!r} must be a slug ([a-z][a-z0-9-]*)")
        if self.family not in FAMILIES:
            raise ScaffoldError(
                f"family {self.family!r} is not one of the closed families {list(FAMILIES)}"
            )
        if not _SEMVER_RE.match(self.version):
            raise ScaffoldError(f"version {self.version!r} is not MAJOR.MINOR.PATCH")
        if not self.contract.startswith(f">={CONTRACT_MAJOR}.") or not self.contract.endswith(
            f",<{CONTRACT_MAJOR + 1}.0.0"
        ):
            raise ScaffoldError(
                f"contract {self.contract!r} must pin exactly the major this scaffold codes "
                f"against (>={CONTRACT_MAJOR}.0.0,<{CONTRACT_MAJOR + 1}.0.0)"
            )

    @property
    def package(self) -> str:
        """The Python package name (import root) of the scaffolded project."""
        return self.name.replace("-", "_")

    @property
    def manifest_id(self) -> str:
        """The discovery id: ``publisher.name``, both segments slug-cased."""
        return f"{self.publisher}.{self.name}"

    @property
    def title_or_default(self) -> str:
        return self.title or f"{self.name} ({self.family} extension)"

    @property
    def description_or_default(self) -> str:
        return self.description or (
            f"A {self.family} extension for MAIstro, scaffolded by 'maistro extension new' "
            "and shaped by its family template. Declare the least authority that works."
        )


def _identity_block(spec: ScaffoldSpec, kind: str) -> str:
    """The PLUGIN head every family template shares: identity plus kind."""
    return (
        "PLUGIN: dict[str, object] = {\n"
        f'    "kind": "{kind}",\n'
        f'    "name": "{spec.manifest_id}",\n'
        f'    "version": "{spec.version}",\n'
        '    "capabilities": [],\n'
    )


def _tool_body(spec: ScaffoldSpec) -> str:
    body = (
        _identity_block(spec, "tool")
        + '    "handler": "run",\n}\n'
        + '''

def run(target: str = "world") -> str:
    """Return a greeting for ``target`` — the sample tool call.

    Pure on purpose: the manifest declares the ``read-only`` effect and
    nothing else, and the implementation keeps that promise. A tool that
    reaches the network declares ``network.outbound`` in extension.json
    first; authority flows from the manifest, never from an import.
    """
    return f"Hello, {target}!"


#: Exported for hosts that enumerate what an entrypoint object offers.
HANDLERS: dict[str, object] = {"run": run}
'''
    )
    return body


def _skill_body(spec: ScaffoldSpec) -> str:
    skill = spec.name
    return (
        _identity_block(spec, "skill")
        + f'    "skills": [{{"name": "{skill}"}}],\n}}\n'
        + f'''

#: The instruction templates the PLUGIN names. Data, not behavior: a host
#: renders these into its own prompt flow and stays the executor.
SKILL_INSTRUCTIONS: dict[str, str] = {{
    "{skill}": (
        "Greet the caller warmly and ask what they would like to do. "
        "Replace this template with the skill you are shipping."
    ),
}}


def instructions(skill: str = "{skill}") -> str:
    """Return one skill's instruction template (the sample read call)."""
    return SKILL_INSTRUCTIONS[skill]
'''
    )


def _gateway_body(spec: ScaffoldSpec) -> str:
    return (
        _identity_block(spec, "mcp-gateway")
        + """    "upstreams": [
        {
            "name": "example",
            "transport": "stdio",
            "command": ["uvx", "example-mcp-server"],
            "namespace": "example",
        }
    ],
}
"""
        + '''

def tool_name(upstream: dict[str, object], tool: str) -> str:
    """Namespace one upstream tool name (the sample pure helper).

    A gateway reaches an external server, so the moment this skeleton
    becomes real it needs ``network.outbound`` (or the sandboxed transport
    a host provisions) declared in extension.json — with the
    ``network.allow`` host allowlist naming exactly the upstreams here.
    """
    namespace = str(upstream["namespace"])
    return f"{namespace}.{tool}"
'''
    )


def _provider_body(spec: ScaffoldSpec) -> str:
    return (
        _identity_block(spec, "capability-provider")
        + f'    "providers": [\n        {{"slot": "example.search", "scheme": "{spec.package}"}}\n'
        "    ],\n}\n"
        + '''

def resolve(request: dict[str, object]) -> dict[str, object]:
    """Answer one capability-slot request (the sample pure handler).

    A provider claims a capability slot and answers requests for it.
    Whatever this grows into, the manifest must declare the authority the
    real implementation uses — a provider that reads workspace data declares
    ``workspace.read`` before a host grants it anything.
    """
    return {"slot": request.get("slot"), "result": "example", "records": []}
'''
    )


def _renderer_body(spec: ScaffoldSpec) -> str:
    return (
        _identity_block(spec, "renderer-plugin")
        + '    "renderers": [{"kinds": ["text"], "format": "plain"}],\n}\n'
        + '''

def render(kind: str, payload: object) -> str:
    """Render one artifact payload (the sample pure handler).

    Renderers turn host artifacts into presentation formats and stay
    read-only unless they declare otherwise — writing anywhere is a
    ``filesystem.write``/``workspace.write`` declaration first.
    """
    supported = {"text"}
    if kind not in supported:
        msg = f"unsupported artifact kind: {kind}"
        raise ValueError(msg)
    return str(payload)
'''
    )


_FAMILY_BODY_BUILDERS: dict[str, Callable[[ScaffoldSpec], str]] = {
    "tool": _tool_body,
    "skill": _skill_body,
    "mcp-gateway": _gateway_body,
    "capability-provider": _provider_body,
    "renderer-plugin": _renderer_body,
}


def _plugin_module(spec: ScaffoldSpec) -> str:
    head = (
        f'"""The {spec.package} entrypoint module ({spec.family} family).\n'
        "\n"
        "Data plus pure sample handlers, importing nothing — the shape\n"
        "`docs/extensions/lifecycle.md` describes: a host reads ``extension.json``,\n"
        "validates it, resolves grants, and only then imports this module, so\n"
        "loading it must have no side effects to reason about. The M9-A2 lifecycle\n"
        "contracts (#950) will type the entrypoint and its context; until then\n"
        "this stays data-only so adopting them is an annotation change.\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
    )
    builder = _FAMILY_BODY_BUILDERS[spec.family]
    return head + builder(spec)


def _init_module(spec: ScaffoldSpec) -> str:
    return (
        f'"""{spec.package} — a MAIstro {spec.family} extension '
        '(scaffolded by `maistro extension new`)."""\n'
    )


def _manifest(spec: ScaffoldSpec) -> str:
    manifest = {
        "id": spec.manifest_id,
        "publisher": spec.publisher,
        "version": spec.version,
        "title": spec.title_or_default,
        "description": spec.description_or_default,
        "contract": spec.contract,
        "family": spec.family,
        "capabilities": [],
        "effects": ["read-only"],
        "data": {"scopes": []},
        "entrypoint": {
            "module": f"{spec.package}.plugin",
            "object": "PLUGIN",
        },
    }
    validate_manifest(manifest)
    return json.dumps(manifest, indent=2) + "\n"


def _pyproject(spec: ScaffoldSpec) -> str:
    return f'''[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{spec.name}"
version = "{spec.version}"
description = "{spec.title_or_default}"
readme = "README.md"
requires-python = ">=3.12"
license = {{ text = "Apache-2.0" }}
# Deliberately empty, like the reference extension: this package builds and
# tests in a clean environment from this wheel alone. When you import the
# public extension SDK, declare it here pinned to the manifest-contract major
# you code against, e.g.  dependencies = ["maistro-ext-sdk>=1,<2"]  — the
# manifest's `contract` range below is that same pin, declared to hosts.
dependencies = []

[tool.hatch.build.targets.wheel]
packages = ["src/{spec.package}"]

# A host discovers an extension through the ``extension.json`` its wheel
# ships; packaging that drops it installs an extension no host can find.
[tool.hatch.build.targets.wheel.force-include]
"extension.json" = "{spec.package}/extension.json"

[tool.pytest.ini_options]
# importlib mode keeps pytest from inserting the rootdir on sys.path — the
# repo-relative rescue an extension must never need.
addopts = "--import-mode=importlib --strict-markers"
testpaths = ["tests"]
'''


def _readme(spec: ScaffoldSpec) -> str:
    return f"""# {spec.title_or_default}

A MAIstro **{spec.family}** extension, scaffolded by `maistro extension new`
(M9-H1). It builds and tests in a clean environment with zero dependencies —
no MAIstro checkout, no product imports, no `sys.path` repair.

## Layout

```
{spec.name}/
├── pyproject.toml          # the project: name, version, dependencies
├── extension.json          # the manifest (authority declaration)
├── src/{spec.package}/
│   └── plugin.py           # the entrypoint object the manifest names
└── tests/
    └── test_{spec.package}.py
```

## Build and test outside any repository

```bash
uv build --wheel --out-dir dist
uv venv .venv-isolated
uv pip install --python .venv-isolated/bin/python dist/{spec.package}-{spec.version}-py3-none-any.whl pytest
.venv-isolated/bin/python -m pytest tests -q
```

If that suite passes in the fresh venv, the package needs no repo-relative
import and no product-private module — the property CI's isolation fixture
proves for every extension tree.

## Authority

The manifest declares the least authority that works: no capabilities, the
`read-only` effect, no data scopes. Add only what a missing capability makes
impossible, and re-declare honestly when behavior changes — see
`docs/extensions/capabilities.md` for every name and its worked example. The
`{spec.family}` family's structural contract is described in
`docs/extensions/manifest-reference.md`; the entrypoint stays data-only until
you adopt the extension SDK's lifecycle contracts (M9-A2).
"""


def _family_test_body(spec: ScaffoldSpec) -> str:
    return {
        "tool": '    assert plugin["handler"] in module.HANDLERS\n',
        "skill": (
            '    skills = plugin["skills"]\n    assert module.instructions(skills[0]["name"])\n'
        ),
        "mcp-gateway": (
            '    upstream = plugin["upstreams"][0]\n'
            '    namespaced = module.tool_name(upstream, "ping")\n'
            "    assert namespaced == f'{upstream[\"namespace\"]}.ping'\n"
        ),
        "capability-provider": (
            '    providers = plugin["providers"]\n'
            '    answer = module.resolve({"slot": providers[0]["slot"]})\n'
            '    assert answer["result"] == "example"\n'
        ),
        "renderer-plugin": '    assert module.render("text", "hi") == "hi"\n',
    }[spec.family]


def _test_module(spec: ScaffoldSpec) -> str:
    family_body = _family_test_body(spec)
    return f'''"""{spec.package}'s self-contract tests.

These run in a clean environment holding only this wheel and pytest, so they
may import nothing but this package, the standard library, and pytest. That
constraint IS the test: any product-private or repo-relative import fails
here with an ImportError before an assertion can run.
"""

from __future__ import annotations

import importlib
import json
import sys
from importlib.resources import files as resource_files
from pathlib import Path

import {spec.package}


def _manifest() -> dict[str, object]:
    # A host discovers an extension through the ``extension.json`` its wheel
    # ships, so the installed distribution is what this suite reads first; the
    # editable-install fallback reads the project root's copy (see the
    # reference extension for the full comment).
    try:
        text = (
            resource_files("{spec.package}")
            .joinpath("extension.json")
            .read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        text = (Path(__file__).resolve().parents[1] / "extension.json").read_text(
            encoding="utf-8"
        )
    return json.loads(text)


def test_manifest_declares_least_authority() -> None:
    manifest = _manifest()
    assert manifest["capabilities"] == []
    assert manifest["effects"] == ["read-only"]
    assert manifest["data"] == {{"scopes": []}}


def test_manifest_identity_and_contract_are_well_formed() -> None:
    manifest = _manifest()
    assert str(manifest["id"]).startswith(f"{{manifest['publisher']}}.")
    contract = str(manifest["contract"])
    low, high = contract.removeprefix(">=").split(",<")
    assert high.split(".")[0] == str(int(low.split(".")[0]) + 1), (
        "the contract range must pin exactly the next major boundary"
    )
    assert manifest["family"] == "{spec.family}"


def test_manifest_entrypoint_resolves_to_a_real_object() -> None:
    manifest = _manifest()
    entrypoint = manifest["entrypoint"]
    assert isinstance(entrypoint, dict)
    module = importlib.import_module(str(entrypoint["module"]))
    plugin = getattr(module, str(entrypoint["object"]))
    assert plugin["kind"] == manifest["family"]
    assert plugin["name"] == manifest["id"]
    assert plugin["version"] == manifest["version"]


def test_family_declaration_is_present_and_usable() -> None:
    from {spec.package} import plugin as plugin_module

    plugin = plugin_module.PLUGIN
    module = plugin_module
{family_body}
def test_the_package_imports_nothing_first_party() -> None:
    """The structural form of the public-SDK-only boundary: this package
    depends on no first-party module at all."""
    import ast

    package_root = Path({spec.package}.__file__).resolve().parent
    for path in package_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            roots = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
            for root in roots:
                assert not root.startswith("maistro"), (
                    f"{{path.name}} imports first-party module {{root!r}}"
                )
            assert roots == [] or all(
                root in sys.stdlib_module_names or root == "{spec.package}" for root in roots
            ), f"{{path.name}} imports an undeclared dependency: {{roots}}"
'''


def render_project(spec: ScaffoldSpec) -> dict[str, str]:
    """Render every file of the scaffolded project as ``relative path → text``.

    Pure: no filesystem access, so tests can inspect the exact bytes the CLI
    would write.
    """
    return {
        "pyproject.toml": _pyproject(spec),
        "extension.json": _manifest(spec),
        "README.md": _readme(spec),
        f"src/{spec.package}/__init__.py": _init_module(spec),
        f"src/{spec.package}/plugin.py": _plugin_module(spec),
        f"tests/test_{spec.package}.py": _test_module(spec),
    }


def scaffold_project(spec: ScaffoldSpec, target: Path, *, force: bool = False) -> list[Path]:
    """Write the rendered project under ``target`` and return the written paths.

    (Named to avoid vulture-level name collisions with unrelated same-named
    APIs elsewhere in the tree: vulture resolves uses by bare name, so a used
    ``create_project`` here would mask a banked dead-code identity of the
    same name in another package.)

    Refuses to touch a non-empty directory unless ``force`` is set — a
    scaffold that overwrites an author's work is not a starting point. The
    manifest is validated by the same schema the platform documents before a
    byte is written, so ``maistro extension new`` cannot emit a manifest that
    fails public schema validation.
    """
    if target.exists() and not target.is_dir():
        raise ScaffoldError(f"{target} exists and is not a directory")
    if target.exists() and any(target.iterdir()) and not force:
        raise ScaffoldError(
            f"{target} already exists and is not empty; pass --force to write into it"
        )
    written: list[Path] = []
    for relative, content in render_project(spec).items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written

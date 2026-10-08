"""The extension project scaffold (M9-H1, #973).

``maistro-ext-sdk new`` — or :func:`scaffold_extension` from any Python
process — writes a complete, valid, buildable extension project:

- an ``extension.json`` the SDK's own validator accepts (the generator
  validates what it wrote, fail-closed: a scaffold that cannot validate is a
  generator bug, never a starting point);
- a ``pyproject.toml`` with real packaging metadata, the SDK distribution
  pin, and the wheel ``force-include`` that ships the discovery manifest
  inside the wheel (the same wiring ``extensions/reference-greeter`` uses);
- a ``src/<publisher>_<name>/`` entrypoint module shaped for the chosen
  family — structurally distinct per family where the contract distinguishes
  them: ``tool`` carries the pinned handler protocol (the reference
  extension's shape); the other families are declarative data-only objects
  whose pinned protocols arrive with their SDK slices and plug into the
  harness through ``register_family``;
- sample tests that import only the installed package, the public SDK, and
  pytest — never a repo-relative or product-private module;
- a README stating the out-of-tree flow: build → validate → conformance →
  certify.

Everything is generated from templates in this module, so the scaffold has
no data files to drift and no repository-relative reads: the generated
project builds and tests in a clean directory outside the MAIstro
repository, which is the acceptance the gate
(``scripts/check-extension-scaffold.py``) executes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from maistro_ext_sdk.contract import EXTENSION_CONTRACT_VERSION, parse_contract_version
from maistro_ext_sdk.manifest import EXTENSION_FAMILIES
from maistro_ext_sdk.validation import validate_extension_dir

__all__ = [
    "SCAFFOLD_FAMILIES",
    "SDK_PACKAGE_PIN",
    "ScaffoldError",
    "scaffold_extension",
]

#: Families the scaffold offers templates for — the manifest's closed family
#: vocabulary, restated here so ``--family`` rejects a typo at the CLI instead
#: of generating a manifest that only fails at validation.
SCAFFOLD_FAMILIES: tuple[str, ...] = tuple(sorted(EXTENSION_FAMILIES))

#: The SDK distribution floor a scaffolded project pins. The SDK's *package*
#: version moves in lockstep with the monorepo (ADR-073126-c4e1) and is at
#: 0.9.x for the M9 releases; contract compatibility itself is enforced at
#: validation time through the manifest's ``contract`` range, so the pin here
#: is the distribution floor, not a second compatibility authority.
SDK_PACKAGE_PIN = ">=0.9"

#: Slug rules for the two halves of the extension id. Same shape the manifest
#: contract enforces (``publisher.name``), applied at generation time so an
#: author learns about a bad name before any file is written.
_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$")


class ScaffoldError(ValueError):
    """A scaffold request that cannot produce a valid project.

    Raised before any file is written for bad inputs, and — never in
    practice — if the generator's own output failed validation.
    """


@dataclass(frozen=True)
class _FamilyTemplate:
    """What makes one family's generated project structurally distinct."""

    #: The manifest ``family`` value.
    family: str
    #: The module-level entrypoint object's name (manifest ``entrypoint.object``).
    object_name: str
    #: The object's ``kind`` tag — the family identity inside the entrypoint.
    kind: str
    #: One-paragraph statement of what the family's entrypoint carries.
    blurb: str

    def entrypoint_source(self, *, ext_id: str, version: str, package: str) -> str:
        """The family's entrypoint module source.

        Only ``tool`` carries the handler protocol the merged contract pins
        (the reference extension's data-only ``PLUGIN`` plus a named
        handler); the other families are honest data-only declarations — a
        pinned protocol invented here would be a second contract authority,
        which the SDK refuses to be.
        """
        title = self.kind.replace("-", " ")
        header = f'"""The {ext_id!r} {title} entrypoint.\n\n{self.blurb}\n"""\n\n'
        if self.family == "tool":
            return (
                header
                + "PLUGIN: dict[str, object] = {\n"
                + f'    "kind": "{self.kind}",\n'
                + f'    "name": "{ext_id}",\n'
                + f'    "version": "{version}",\n'
                + '    "capabilities": [],\n'
                + '    "handler": "greet",\n'
                + "}\n"
                + "\n"
                + "\n"
                + 'def greet(target: str = "world") -> str:\n'
                + '    """Return a greeting for ``target``.\n'
                + "\n"
                + "    Pure on purpose: the manifest declares the ``read-only``\n"
                + "    effect and nothing else, and the implementation keeps that\n"
                + "    promise. An extension that needs the network declares\n"
                + "    ``network.outbound`` in ``extension.json`` first.\n"
                + '    """\n'
                + '    return f"Hello, {target}!"\n'
                + "\n"
                + "\n"
                + 'HANDLERS: dict[str, object] = {"greet": greet}\n'
            )
        # Declarative families: a data-only object, the shape the harness's
        # shared conformance suite loads and inspects without invoking.
        return (
            header
            + f"{self.object_name}: dict[str, object] = {{\n"
            + f'    "kind": "{self.kind}",\n'
            + f'    "name": "{ext_id}",\n'
            + f'    "version": "{version}",\n'
            + '    "capabilities": [],\n'
            + "}\n"
        )


#: One template per manifest family, keyed by family. The object names and
#: kinds differ on purpose: two families sharing an entrypoint shape would
#: make a manifest's family claim unenforceable at load time.
_FAMILY_TEMPLATES: dict[str, _FamilyTemplate] = {
    "tool": _FamilyTemplate(
        family="tool",
        object_name="PLUGIN",
        kind="tool",
        blurb=(
            "A tool family extension: the entrypoint object names a handler\n"
            "the host may call after the manifest is accepted — the pinned\n"
            "data-only protocol the reference extension (reference.greeter)\n"
            "also uses."
        ),
    ),
    "skill": _FamilyTemplate(
        family="skill",
        object_name="SKILL",
        kind="skill",
        blurb=(
            "A skill family extension: a declarative object describing the\n"
            "skill. The pinned skill protocol arrives with the skill SDK\n"
            "slice; until then this object is data the host can inspect\n"
            "without executing."
        ),
    ),
    "mcp-gateway": _FamilyTemplate(
        family="mcp-gateway",
        object_name="GATEWAY",
        kind="mcp-gateway",
        blurb=(
            "An MCP-gateway family extension: a declarative object naming\n"
            "the gateway. The gateway transport protocol arrives with the\n"
            "connector SDK slice; this object is inspectable data until then."
        ),
    ),
    "capability-provider": _FamilyTemplate(
        family="capability-provider",
        object_name="PROVIDER",
        kind="capability-provider",
        blurb=(
            "A capability-provider family extension: a declarative object\n"
            "naming the provider. The binding protocol (ADR-081226-6b46)\n"
            "arrives with the provider SDK slice; this object is inspectable\n"
            "data until then."
        ),
    ),
    "renderer-plugin": _FamilyTemplate(
        family="renderer-plugin",
        object_name="RENDERER",
        kind="renderer-plugin",
        blurb=(
            "A renderer-plugin family extension: a declarative object the\n"
            "host inspects to learn what renders. Data-only by contract."
        ),
    ),
}


def _validate_slug(kind: str, value: str) -> str:
    if not _SLUG_RE.match(value):
        raise ScaffoldError(
            f"{kind} {value!r} must be a slug: lowercase letters, digits, and "
            "dashes, starting and ending with a letter or digit"
        )
    return value


def _validate_version(version: str) -> str:
    if not _SEMVER_RE.match(version):
        raise ScaffoldError(
            f"version {version!r} must be MAJOR.MINOR.PATCH (optionally with a "
            f"pre-release/build suffix), e.g. 0.1.0"
        )
    return version


def _package_segment(publisher: str, name: str) -> str:
    """The Python package segment: ``<publisher>_<name>`` with dashes folded.

    Folded to underscores so the generated import path is a valid identifier
    and never an underscore-private module (the namespace policy's private
    seam rule): slugs cannot begin with ``_`` by construction.
    """
    return f"{publisher}_{name}".replace("-", "_")


def _manifest_dict(
    *,
    ext_id: str,
    publisher: str,
    version: str,
    title: str,
    description: str,
    family: str,
) -> dict[str, Any]:
    contract = parse_contract_version(EXTENSION_CONTRACT_VERSION)
    return {
        "id": ext_id,
        "publisher": publisher,
        "version": version,
        "title": title,
        "description": description,
        "contract": f">={EXTENSION_CONTRACT_VERSION},<{contract.major + 1}.0.0",
        "family": family,
        "capabilities": [],
        "effects": ["read-only"],
        "data": {"scopes": []},
        "entrypoint": {"module": None, "object": None},  # filled below
    }


def _pyproject_source(
    *,
    dist_name: str,
    version: str,
    summary: str,
    package: str,
) -> str:
    return f'''[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{dist_name}"
version = "{version}"
description = "{summary}"
readme = "README.md"
requires-python = ">=3.12"
license = {{ text = "Apache-2.0" }}
# The public extension SDK is the dependency: the pin is the SDK
# distribution's floor (contract compatibility is enforced separately, at
# validation time, through extension.json's contract range).
dependencies = ["maistro-ext-sdk{SDK_PACKAGE_PIN}"]

[tool.hatch.build.targets.wheel]
packages = ["{package}"]

# A host discovers an extension through the ``extension.json`` its wheel
# ships; packaging that drops it installs but can never be discovered.
[tool.hatch.build.targets.wheel.force-include]
"extension.json" = "{package}/extension.json"

[tool.pytest.ini_options]
# importlib mode keeps pytest from inserting the project root on sys.path:
# the tests import the installed package or they fail — never a
# checkout-relative rescue.
addopts = "--import-mode=importlib --strict-markers"
testpaths = ["tests"]
'''


def _init_source(package: str, ext_id: str, version: str) -> str:
    return f'''"""{ext_id} — a MAIstro extension built on the public extension SDK."""

__version__ = "{version}"

#: The package the manifest's entrypoint points into (``{package}.plugin``).
__all__ = ["__version__"]
'''


def _test_source(package: str, module: str, object_name: str, ext_id: str) -> str:
    return f'''"""Sample self-contract tests for {ext_id}.

These import only the installed package, the public extension SDK, and
pytest — the same boundary the namespace policy enforces for every
extension. They run anywhere the project is installed: from a source
checkout (the project-root manifest is read directly) or from a staged
sandbox holding only what the wheel ships (the manifest is read back out
of the installed distribution via importlib.resources — the same
artifact a host discovers). Nothing here reads the MAIstro repository.
"""

from __future__ import annotations

import json
from importlib.resources import files as resource_files
from pathlib import Path

from maistro_ext_sdk import manifest_from_json, validate_extension_dir

import {package}


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _shipped_manifest_text() -> str:
    """The manifest the wheel ships, or the checkout's copy when editable."""
    try:
        return (
            resource_files("{package}")
            .joinpath("extension.json")
            .read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        # An editable install maps only the package directory; the manifest
        # lives at the project root and the wheel's force-include has not
        # materialized it into the package. The checkout's copy is the same
        # file the wheel would carry.
        return (PROJECT_ROOT / "extension.json").read_text(encoding="utf-8")


def _manifest() -> dict[str, object]:
    return json.loads(_shipped_manifest_text())


def _validated_manifest() -> object:
    """The manifest through the SDK's public validation, in either context."""
    if (PROJECT_ROOT / "extension.json").is_file():
        return validate_extension_dir(PROJECT_ROOT).manifest
    return manifest_from_json(_shipped_manifest_text())


def test_manifest_validates_against_the_public_schema() -> None:
    """The generated manifest passes the SDK's no-import validation."""
    ext = _validated_manifest()
    assert ext.id == "{ext_id}"


def test_pinned_contract_major_matches_this_sdk() -> None:
    """The manifest pins exactly one contract major and this SDK publishes it."""
    from maistro_ext_sdk import contract_version

    manifest = _manifest()
    pinned_major = int(str(manifest["contract"]).split(".")[0].lstrip(">="))
    published_major = int(contract_version().split(".")[0])
    assert pinned_major == published_major


def test_entrypoint_object_resolves() -> None:
    """The manifest's entrypoint names a real object in the installed package."""
    manifest = _manifest()
    module = __import__(f"{package}.plugin", fromlist=[str(manifest["entrypoint"]["object"])])
    obj = getattr(module, str(manifest["entrypoint"]["object"]))
    assert isinstance(obj, dict)
    assert obj["name"] == "{ext_id}"


def test_package_version_matches_the_manifest() -> None:
    manifest = _manifest()
    assert {package}.__version__ == manifest["version"]
'''


def _readme_source(*, ext_id: str, dist_name: str, title: str, family: str) -> str:
    return f"""# {title}

A MAIstro extension ({family} family) scaffolded by
[`maistro-ext-sdk new`](https://github.com/Agent-StrongHold/Project-mAIstro) —
identity `{ext_id}`. Built entirely on the public extension SDK; nothing here
imports a MAIstro product module or repairs a repository-relative path.

## The out-of-tree flow

```bash
pip install -e .            # or build the wheel: python -m build --wheel
maistro-ext-sdk validate .                    # manifest schema validation
pytest                                        # the sample self-contract tests
maistro-ext-harness run --path . --report conformance-report.json
maistro-ext-harness certify --path . --artifact dist/*.whl --report certification.json
```

No step clones or imports the MAIstro core repository: validation speaks the
public manifest schema, and the harness/certification runner is a separate
distribution (`maistro-ext-harness`) whose report states exactly what ran.

## What is here

| Path | Meaning |
|---|---|
| `extension.json` | the discovery manifest (validated before any code loads) |
| `src/` | the entrypoint module the manifest names |
| `tests/` | self-contract tests over the public SDK only |
"""


def scaffold_extension(
    *,
    name: str,
    publisher: str,
    family: str = "tool",
    out_dir: str | Path | None = None,
    version: str = "0.1.0",
    title: str | None = None,
    description: str | None = None,
    force: bool = False,
) -> Path:
    """Write a complete extension project and return its root directory.

    Validates every input *before* touching the filesystem, writes the
    project, then validates the result with the SDK's own
    :func:`validate_extension_dir` — fail-closed: the function returns only
    a directory whose manifest passes public schema validation.

    Raises :class:`ScaffoldError` for a bad name/publisher/family/version, an
    unsupported family, or a non-empty target directory (unless ``force``).
    """
    _validate_slug("publisher", publisher)
    _validate_slug("name", name)
    _validate_version(version)
    if family not in _FAMILY_TEMPLATES:
        raise ScaffoldError(
            f"family {family!r} is not one of the scaffoldable families "
            f"{sorted(_FAMILY_TEMPLATES)}; the manifest vocabulary is closed"
        )
    template = _FAMILY_TEMPLATES[family]

    ext_id = f"{publisher}.{name}"
    dist_name = f"{publisher}-{name}"
    package = _package_segment(publisher, name)
    module = f"{package}.plugin"
    title = title or f"{name.replace('-', ' ').title()} ({family} extension)"
    description = description or (
        f"{title} scaffolded by maistro-ext-sdk new against extension "
        f"contract {EXTENSION_CONTRACT_VERSION}."
    )

    root = Path(out_dir) if out_dir is not None else Path(dist_name)
    if root.exists() and any(root.iterdir()) and not force:
        raise ScaffoldError(
            f"target directory {str(root)!r} already exists and is not empty; "
            "pass force=True (--force) to write into it anyway"
        )

    manifest = _manifest_dict(
        ext_id=ext_id,
        publisher=publisher,
        version=version,
        title=title,
        description=description,
        family=family,
    )
    manifest["entrypoint"] = {"module": module, "object": template.object_name}

    # Flat layout — the extension package sits at the project root next to
    # extension.json, exactly the SDK example's shape, so the SDK's
    # directory validator (which resolves the entrypoint from the root)
    # accepts the tree as shipped.
    pkg = root / package
    tests = root / "tests"
    pkg.mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)

    (root / "extension.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        _pyproject_source(
            dist_name=dist_name,
            version=version,
            summary=description.replace('"', "'"),
            package=package,
        ),
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        _readme_source(ext_id=ext_id, dist_name=dist_name, title=title, family=family),
        encoding="utf-8",
    )
    (pkg / "__init__.py").write_text(_init_source(package, ext_id, version), encoding="utf-8")
    (pkg / "plugin.py").write_text(
        template.entrypoint_source(ext_id=ext_id, version=version, package=package),
        encoding="utf-8",
    )
    (tests / f"test_{package}.py").write_text(
        _test_source(package, module, template.object_name, ext_id),
        encoding="utf-8",
    )

    # Fail-closed generator: what it wrote must validate, with the same
    # public validator any host uses. A scaffold that cannot validate is a
    # generator bug and stops here.
    validate_extension_dir(root)
    return root

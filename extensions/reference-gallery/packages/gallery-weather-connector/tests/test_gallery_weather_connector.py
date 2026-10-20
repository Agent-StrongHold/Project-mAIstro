"""The gallery weather connector's self-contract tests (#980, tool family).

These run in the isolated venv the CI fixture builds — a fresh environment
holding only this wheel and pytest — so they may import nothing but this
package, the standard library, and pytest. That constraint IS the test: any
product-private or repo-relative import fails here with an ImportError
before an assertion can run.
"""

from __future__ import annotations

import ast
import importlib
import json
import sys
from importlib.resources import files as resource_files
from pathlib import Path

import gallery_weather_connector

#: The closed authority vocabulary the platform documents. A manifest that
#: invents a name outside it is refused by the host; this suite refuses it
#: first, at the source.
DOCUMENTED_CAPABILITIES = frozenset(
    {
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
    }
)


def _manifest() -> dict[str, object]:
    try:
        text = (
            resource_files("gallery_weather_connector")
            .joinpath("manifest.json")
            .read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        # The root dev environment installs this package editable, and an
        # editable install maps only the package directory: the manifest
        # lives at the extension root and ``force-include`` maps it into the
        # wheel. There the extension root's copy is read instead. In the
        # isolation fixture the staged suite has no such sibling file, so
        # the fallback cannot exist there — if the wheel dropped the
        # manifest, these tests cannot run, and the fixture's own checks
        # name the missing file before the suite even starts.
        text = (Path(__file__).resolve().parents[1] / "manifest.json").read_text(encoding="utf-8")
    parsed = json.loads(text)
    assert isinstance(parsed, dict)
    return parsed


def test_manifest_identity_names_its_publisher() -> None:
    manifest = _manifest()
    assert manifest["publisher"] == "gallery"
    assert str(manifest["id"]) == "gallery.weather_connector"
    assert str(manifest["id"]).startswith(f"{manifest['publisher']}.")


def test_manifest_declares_only_documented_authority() -> None:
    manifest = _manifest()
    permissions = manifest["permissions"]
    assert isinstance(permissions, list)
    unknown = sorted(set(permissions) - DOCUMENTED_CAPABILITIES)
    assert unknown == [], f"manifest invents authority the platform never defined: {unknown}"
    # A connector may reach the network and serve the governed tool surface;
    # it has no reason to touch memory, secrets, or the filesystem.
    assert set(permissions) == {"network.outbound", "tool.invoke"}


def test_manifest_artifact_is_unauthored() -> None:
    """The artifact claim is bound by the publish workflow against the built
    wheel; a manifest source that shipped one could only be a guess."""
    assert "artifact" not in _manifest()


def test_entry_point_resolves_to_the_declared_object() -> None:
    manifest = _manifest()
    entry_points = manifest["entry_points"]
    assert isinstance(entry_points, list) and len(entry_points) == 1
    entry_point = entry_points[0]
    assert isinstance(entry_point, dict)
    module = importlib.import_module(str(entry_point["module"]))
    plugin = getattr(module, str(entry_point["attribute"]))
    assert plugin["kind"] == "tool"
    assert plugin["name"] == manifest["id"]
    assert plugin["version"] == manifest["version"]
    assert sorted(plugin["capabilities"]) == sorted(manifest["permissions"])


def test_declared_handlers_exist_and_are_pure() -> None:
    from gallery_weather_connector import plugin as plugin_module

    handlers = plugin_module.PLUGIN["handlers"]
    assert isinstance(handlers, list)
    for name in handlers:
        assert name in plugin_module.HANDLERS
    brief = plugin_module.HANDLERS["current_forecast_brief"](
        "Lisbon",
        {"summary": "sunny", "high_c": 28, "low_c": 17},
    )
    assert brief == "Lisbon: sunny, high 28°C, low 17°C"
    # Same input, same output, no state: the handler is a pure function over
    # host-fetched data, which is what read-through tool invocation expects.
    again = plugin_module.HANDLERS["current_forecast_brief"](
        "Lisbon",
        {"summary": "sunny", "high_c": 28, "low_c": 17},
    )
    assert brief == again


def test_handler_degrades_malformed_payloads_instead_of_raising() -> None:
    from gallery_weather_connector import plugin as plugin_module

    handler = plugin_module.HANDLERS["current_forecast_brief"]
    assert handler("Nowhere", {}) == "Nowhere: unknown, high ?°C, low ?°C"
    assert handler("Nowhere", "not a dict")  # type: ignore[arg-type]


def test_the_package_imports_nothing_first_party() -> None:
    """The structural form of the issue's boundary criterion: this extension
    depends on no first-party module at all, so product internals can change
    without ever touching it."""
    package_file = gallery_weather_connector.__file__
    assert package_file is not None
    package_root = Path(package_file).resolve().parent
    for path in sorted(package_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
            for root in roots:
                assert not root.startswith("maistro"), (
                    f"{path.name} imports first-party module {root!r}"
                )
            assert roots == [] or all(
                root in sys.stdlib_module_names or root == "gallery_weather_connector"
                for root in roots
            ), f"{path.name} imports an undeclared dependency: {roots}"

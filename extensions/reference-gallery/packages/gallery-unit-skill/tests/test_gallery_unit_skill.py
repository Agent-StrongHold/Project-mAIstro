"""The gallery unit skill's self-contract tests (#980, skill family).

Runs in the isolation fixture's fresh venv (this wheel + pytest, nothing
else). The dependency on the connector is an extension-level declaration the
catalog resolves — asserted here against the manifest, never as a Python
import.
"""

from __future__ import annotations

import json
from importlib.resources import files as resource_files
from pathlib import Path

from gallery_unit_skill import plugin

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
            resource_files("gallery_unit_skill")
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


def test_manifest_declares_the_connector_dependency() -> None:
    dependencies = _manifest()["dependencies"]
    assert isinstance(dependencies, list) and len(dependencies) == 1
    dependency = dependencies[0]
    assert isinstance(dependency, dict)
    assert dependency["id"] == "gallery.weather_connector"
    # Exact pin. The platform's two range consumers accept different
    # grammars today — the lock resolver reads comparator lists, the
    # compatibility preflight accepts exact/^/* and fails closed otherwise —
    # and an exact version is the one form both validate. The gallery ships
    # its dependency set as one unit, so an exact pin is also the honest
    # claim: the lock carries the full identity either way.
    assert dependency["range"] == "1.0.0"


def test_manifest_declares_only_documented_authority() -> None:
    manifest = _manifest()
    permissions = manifest["permissions"]
    assert isinstance(permissions, list)
    assert set(permissions) <= DOCUMENTED_CAPABILITIES
    # A formatting skill reads workspace data; it never writes, reaches the
    # network, or touches secrets.
    assert set(permissions) == {"workspace.read"}


def test_plugin_identity_matches_the_manifest() -> None:
    manifest = _manifest()
    plugin_obj = plugin.PLUGIN
    assert plugin_obj["kind"] == "skill"
    assert plugin_obj["name"] == manifest["id"]
    assert plugin_obj["version"] == manifest["version"]
    assert sorted(plugin_obj["capabilities"]) == sorted(manifest["permissions"])  # type: ignore[arg-type]


def test_conversions_round_trip() -> None:
    assert plugin.c_to_f(100.0) == 212.0
    assert plugin.f_to_c(32.0) == 0.0
    # Round trip within float tolerance: two conversions are two float
    # operations, and a skill that promised exact inverses would be lying.
    assert abs(plugin.f_to_c(plugin.c_to_f(17.3)) - 17.3) < 1e-9


def test_report_conversion_renames_and_preserves() -> None:
    report = {
        "location": "Lisbon",
        "high_c": 28,
        "low_c": 17.5,
        "summary": "sunny",
    }
    converted = plugin.convert_report_units(report)
    assert converted == {
        "location": "Lisbon",
        "high_f": 82.4,
        "low_f": 63.5,
        "summary": "sunny",
    }
    # The input report is untouched: pure in, pure out.
    assert report == {
        "location": "Lisbon",
        "high_c": 28,
        "low_c": 17.5,
        "summary": "sunny",
    }


def test_report_conversion_passes_unknown_fields_through() -> None:
    converted = plugin.convert_report_units({"wind_kph": 12, "notes": None})
    assert converted == {"wind_kph": 12, "notes": None}

"""The gallery renderer pack's self-contract tests (#980, renderer-plugin family).

Runs in the isolation fixture's fresh venv (this wheel + pytest, nothing
else).
"""

from __future__ import annotations

import json
from importlib.resources import files as resource_files
from pathlib import Path

from gallery_renderer_pack import plugin as renderers


def _manifest() -> dict[str, object]:
    try:
        text = (
            resource_files("gallery_renderer_pack")
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


def test_manifest_declares_least_authority() -> None:
    manifest = _manifest()
    # A UI pack renders read-only projections; anything more is overclaiming.
    assert manifest["permissions"] == ["workspace.read"]


def test_plugin_identity_matches_the_manifest() -> None:
    manifest = _manifest()
    plugin = renderers.PLUGIN
    assert plugin["kind"] == "renderer-plugin"
    assert plugin["name"] == manifest["id"]
    assert plugin["version"] == manifest["version"]
    assert sorted(plugin["capabilities"]) == sorted(manifest["permissions"])  # type: ignore[arg-type]


def test_run_summary_renders_given_data_and_nothing_else() -> None:
    summary = renderers.render_run_summary(
        {"name": "nightly-digest", "state": "succeeded", "node_count": 4}
    )
    assert summary == "Run 'nightly-digest' — succeeded, 4 nodes"


def test_run_summary_degrades_absent_fields() -> None:
    assert renderers.render_run_summary({}) == "Run 'unknown' — unknown"
    # A bool is not a node count, even though bool subclasses int.
    assert renderers.render_run_summary({"node_count": True}) == "Run 'unknown' — unknown"


def test_badge_renders_publisher_identity() -> None:
    badge = renderers.render_extension_badge(
        {"name": "gallery.unit_skill", "version": "1.0.0", "publisher": "gallery"}
    )
    assert badge == "[gallery.unit_skill v1.0.0 by gallery]"


def test_renderers_are_pure() -> None:
    run = {"name": "r", "state": "succeeded", "node_count": 1}
    first = renderers.render_run_summary(run)
    second = renderers.render_run_summary(run)
    assert first == second
    assert run == {"name": "r", "state": "succeeded", "node_count": 1}

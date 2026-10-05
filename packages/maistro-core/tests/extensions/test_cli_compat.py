"""`maistro extensions compat` — the host-side preflight read surface (M9-C1).

The command negotiates an extension's compatibility-metadata JSON against the
host without importing anything: exit 0 for compatible/degraded, exit 1 for
incompatible (the preflight signal) or unreadable/malformed input.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from maistro.cli._extensions import app

runner = CliRunner()

COMPATIBLE_METADATA = {
    "contract": ">=1.0.0,<2.0.0",
    "required_features": ["streaming"],
    "optional_features": ["scheduled"],
}

INCOMPATIBLE_METADATA = {
    "contract": ">=2.0.0,<3.0.0",
    "required_features": ["streaming"],
}

DEGRADED_METADATA = {
    "contract": ">=1.0.0,<2.0.0",
    "optional_features": ["scheduled", "teleport"],
}


def write_metadata(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "compat.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_compat_preflight_accepts_compatible_and_degraded(tmp_path: Path) -> None:
    """Compatible and degraded manifests both pass the preflight (exit 0)."""
    compatible = runner.invoke(app, ["compat", str(write_metadata(tmp_path, COMPATIBLE_METADATA))])
    assert compatible.exit_code == 0
    assert "compatible" in compatible.output
    assert "streaming" in compatible.output

    degraded = runner.invoke(app, ["compat", str(write_metadata(tmp_path, DEGRADED_METADATA))])
    assert degraded.exit_code == 0
    assert "degraded" in degraded.output
    assert "teleport" in degraded.output  # named, not silently dropped


def test_compat_preflight_json_output_is_machine_readable(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["compat", str(write_metadata(tmp_path, DEGRADED_METADATA)), "--json"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["verdict"] == "degraded"
    assert payload["supported_features"] == ["scheduled"]
    assert [d["feature"] for d in payload["degradations"]] == ["teleport"]


def test_compat_preflight_rejects_incompatible_with_reasons(tmp_path: Path) -> None:
    result = runner.invoke(app, ["compat", str(write_metadata(tmp_path, INCOMPATIBLE_METADATA))])
    assert result.exit_code == 1
    assert "incompatible" in result.output
    assert "breaking boundary" in result.output
    assert ">=2.0.0,<3.0.0" in result.output


def test_compat_preflight_names_malformed_metadata(tmp_path: Path) -> None:
    bad_key = write_metadata(tmp_path, {"contract": ">=1.0.0", "entrypoint": "evil:impl"})
    result = runner.invoke(app, ["compat", str(bad_key)])
    assert result.exit_code == 1
    assert "entrypoint" in result.output

    bad_range = write_metadata(tmp_path, {"contract": "~1.0.0"})
    result = runner.invoke(app, ["compat", str(bad_range)])
    assert result.exit_code == 1
    assert "unsupported contract specifier" in result.output


def test_compat_preflight_rejects_unreadable_input(tmp_path: Path) -> None:
    missing = tmp_path / "absent.json"
    result = runner.invoke(app, ["compat", str(missing)])
    assert result.exit_code == 1
    assert "Cannot read" in result.output

    not_json = tmp_path / "broken.json"
    not_json.write_text("{not json", encoding="utf-8")
    result = runner.invoke(app, ["compat", str(not_json)])
    assert result.exit_code == 1
    assert "not valid JSON" in result.output

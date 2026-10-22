"""`maistro extensions contract` — the M9-E3 contract inspection command.

The command is the operator/author entry to the published tool/Skill
contracts: it validates a manifest against the closed vocabularies and
reports the host classification, without ever importing the manifest's
entrypoint module. These tests hold the exit paths (valid, unreadable,
invalid JSON, non-object, contract violation) and pin that the reported
classification is the host-derived floor — the read-only claim next to
`network.outbound` must not print `internal`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from maistro.cli._extensions import app

runner = CliRunner()


def _flat(result) -> str:
    """Output with the terminal's 80-column wrapping normalized away."""
    return " ".join(result.output.split())


def write_manifest(tmp_path: Path, manifest: dict[str, object]) -> Path:
    path = tmp_path / "extension.json"
    path.write_text(json.dumps(manifest))
    return path


def valid_manifest() -> dict[str, object]:
    return {
        "id": "acme.greeter",
        "publisher": "acme",
        "version": "1.0.0",
        "title": "Greeter",
        "description": "Greets.",
        "contract": ">=1.0.0,<2.0.0",
        "family": "tool",
        "capabilities": [],
        "effects": ["read-only"],
        "data": {"scopes": []},
        "entrypoint": {"module": "acme_greeter.plugin", "object": "PLUGIN"},
    }


def test_valid_manifest_reports_host_classification(tmp_path: Path) -> None:
    result = runner.invoke(app, ["contract", str(write_manifest(tmp_path, valid_manifest()))])
    assert result.exit_code == 0
    assert "acme.greeter@1.0.0" in result.output
    assert "effect floor read-only" in result.output
    assert "reversibility internal" in result.output


def test_classification_reflects_capabilities_not_claims(tmp_path: Path) -> None:
    """A `read-only` claim beside `network.outbound` must NOT report internal:
    the printed classification is the host floor."""
    manifest = valid_manifest() | {"capabilities": ["network.outbound"]}
    result = runner.invoke(app, ["contract", str(write_manifest(tmp_path, manifest))])
    assert result.exit_code == 0
    assert "effect floor external-side-effect" in _flat(result)
    assert "reversibility reversible" in _flat(result)


def test_missing_file_fails_with_exit_1(tmp_path: Path) -> None:
    result = runner.invoke(app, ["contract", str(tmp_path / "absent.json")])
    assert result.exit_code == 1
    assert "Cannot read" in result.output


def test_invalid_json_fails(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json")
    result = runner.invoke(app, ["contract", str(path)])
    assert result.exit_code == 1
    assert "not valid JSON" in _flat(result)


def test_non_object_json_fails(tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text("[1, 2]")
    result = runner.invoke(app, ["contract", str(path)])
    assert result.exit_code == 1
    assert "JSON object" in result.output


def test_contract_violation_names_the_field(tmp_path: Path) -> None:
    manifest = valid_manifest() | {"family": "mobile-app"}
    result = runner.invoke(app, ["contract", str(write_manifest(tmp_path, manifest))])
    assert result.exit_code == 1
    assert "family" in result.output


def test_reference_extension_contract_reports_read_only_internal() -> None:
    """The real out-of-tree reference package classifies internal."""
    repo_root = Path(__file__).resolve().parents[4]
    manifest = repo_root / "extensions" / "reference-greeter" / "extension.json"
    result = runner.invoke(app, ["contract", str(manifest)])
    assert result.exit_code == 0
    assert "reference.greeter@1.0.0" in result.output
    assert "reversibility internal" in result.output


@pytest.mark.parametrize(
    "field", ["title", "description", "contract", "entrypoint", "data", "effects", "capabilities"]
)
def test_missing_required_fields_fail(tmp_path: Path, field: str) -> None:
    manifest = valid_manifest()
    del manifest[field]  # type: ignore[attr-defined]
    result = runner.invoke(app, ["contract", str(write_manifest(tmp_path, manifest))])
    assert result.exit_code == 1

"""`maistro extensions compat` — the host-side preflight read surface (M9-C1).

The command negotiates an extension's compatibility-metadata JSON against the
host without importing anything: exit 0 for compatible/degraded, exit 1 for
incompatible (the preflight signal) or unreadable/malformed input.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from maistro.cli import _extensions as cli_extensions
from maistro.cli._extensions import app
from maistro.extensions.compat import (
    FEATURE_DEPRECATED,
    ContractVersion,
    FeatureSupport,
    HostContractMetadata,
    parse_contract_version,
)

runner = CliRunner()

# Listed in ADR-100526-9c55's `tests:` as behavioral evidence: these pin how
# the policy's negotiation surfaces through the host preflight command
# (verdicts, exit codes, machine-readable output).
pytestmark = pytest.mark.contract("behavioral")

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


def test_compat_preflight_renders_deprecation_notices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deprecated host feature renders its status, removal target, migration.

    The shipped host table has nothing deprecated yet, so the notice table and
    its `--json` projection are unreachable through real host metadata today.
    This drives the command against a host whose metadata carries one
    deprecation — the rendering the first real deprecation must produce, both
    in the human table and in the machine-readable report (ADR-100526-9c55:
    deprecations are machine-readable with a documented removal target).
    """
    host = HostContractMetadata(
        contract_version=parse_contract_version("1.4.0"),
        supported_majors=(1,),
        features=(
            FeatureSupport(
                name="streaming",
                status=FEATURE_DEPRECATED,
                since=ContractVersion(1, 0, 0),
                removal_target=ContractVersion(2, 0, 0),
                migration="move to the batch surface before contract 2",
            ),
        ),
    )

    class _DeprecatedFeatureHost:
        current = staticmethod(lambda: host)

    monkeypatch.setattr(cli_extensions, "HostContractMetadata", _DeprecatedFeatureHost)
    metadata = write_metadata(
        tmp_path,
        {"contract": ">=1.0.0,<2.0.0", "required_features": ["streaming"]},
    )

    # A deprecated feature still negotiates as available — with a notice, not
    # a refusal and not a silent pass.
    table = runner.invoke(app, ["compat", str(metadata)])
    assert table.exit_code == 0
    assert "compatible" in table.output
    assert "deprecated" in table.output
    assert "2.0.0" in table.output  # the documented removal target
    assert "move to the batch surface" in table.output

    result = runner.invoke(app, ["compat", str(metadata), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["deprecations"] == [
        {
            "feature": "streaming",
            "status": "deprecated",
            "removal_target": "2.0.0",
            "migration": "move to the batch surface before contract 2",
        }
    ]
    assert payload["supported_features"] == ["streaming"]


def test_compat_preflight_rejects_unreadable_input(tmp_path: Path) -> None:
    missing = tmp_path / "absent.json"
    result = runner.invoke(app, ["compat", str(missing)])
    assert result.exit_code == 1
    assert "Cannot read" in result.output

    not_json = tmp_path / "broken.json"
    not_json.write_text("{not json", encoding="utf-8")
    result = runner.invoke(app, ["compat", str(not_json)])
    assert result.exit_code == 1
    # rich wraps the rendered error at the console width, and the wrap
    # column depends on the (machine-specific) tmp_path length in the
    # message prefix — flatten whitespace before matching the phrase.
    assert "not valid JSON" in " ".join(result.output.split())

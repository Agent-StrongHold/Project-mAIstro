"""Tests for the final-artifact license inventory gate (#363)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-license-inventory.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_license_inventory", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _policy(tmp_path: Path, *, action: str = "review") -> dict[str, object]:
    return {
        "schema_version": 1,
        "legal": {"unknown_license_action": "fail", "copyleft_action": action},
        "coverage": [
            "transitive-packages",
            "extras",
            "vendored-code",
            "os-packages",
            "fonts-and-assets",
            "npm-trees",
        ],
        "dependency_classes": {
            name: {"description": name, "evidence": "review", "review_owner": "owner"}
            for name in (
                "runtime-distribution",
                "build-only-tooling",
                "external-cli-invocation",
                "source-only-development",
            )
        },
        "surfaces": [
            {
                "id": "image",
                "kind": "final-image",
                "classification": "runtime-distribution",
                "source": "Dockerfile",
                "required": True,
            }
        ],
        "reviewed_resolutions": [],
    }


def _sbom(tmp_path: Path, *, licenses: list[dict[str, object]] | None) -> Path:
    path = tmp_path / "image.json"
    component: dict[str, object] = {
        "bom-ref": "pkg:pypi/example@1.0",
        "name": "example",
        "version": "1.0",
        "purl": "pkg:pypi/example@1.0",
    }
    if licenses is not None:
        component["licenses"] = licenses
    path.write_text(
        json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.5", "components": [component]}),
        encoding="utf-8",
    )
    return path


def _run(gate, tmp_path: Path, policy: dict[str, object], sbom: Path):
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    return gate.build_inventory(policy, {"image": sbom})


def test_component_identity_and_license_evidence_reconcile(gate, tmp_path):
    policy = _policy(tmp_path)
    sbom = _sbom(
        tmp_path,
        licenses=[{"license": {"id": "Apache-2.0"}}],
    )
    inventory, unknown = _run(gate, tmp_path, policy, sbom)
    assert unknown == []
    component = inventory["surfaces"][0]["components"][0]
    evidence = inventory["surfaces"][0]["license_evidence"][0]
    assert component["bom_ref"] == evidence["component_ref"]
    assert component["identity"] == "pkg:pypi/example@1.0"
    assert component["licenses"] == ["Apache-2.0"]


def test_missing_license_metadata_is_unresolved(gate, tmp_path):
    policy = _policy(tmp_path)
    sbom = _sbom(tmp_path, licenses=None)
    _inventory, unknown = _run(gate, tmp_path, policy, sbom)
    assert unknown == ["image: pkg:pypi/example@1.0 (pkg:pypi/example@1.0)"]


def test_reviewed_resolution_closes_missing_metadata(gate, tmp_path):
    policy = _policy(tmp_path)
    policy["reviewed_resolutions"] = [
        {
            "identity": "pkg:pypi/example@1.0",
            "license": "BSD-3-Clause",
            "reason": "Upstream LICENSE reviewed",
            "owner": "legal@example.test",
            "reviewed_on": "2026-01-01",
        }
    ]
    inventory, unknown = _run(gate, tmp_path, policy, _sbom(tmp_path, licenses=None))
    assert unknown == []
    assert inventory["surfaces"][0]["components"][0]["license_status"] == "reviewed"


def test_copyleft_is_classified_not_assumed_compatible(gate, tmp_path):
    policy = _policy(tmp_path)
    inventory, unknown = _run(
        gate,
        tmp_path,
        policy,
        _sbom(tmp_path, licenses=[{"license": {"id": "GPL-3.0-only"}}]),
    )
    assert unknown == []
    assert inventory["surfaces"][0]["components"][0]["legal_class"] == "copyleft"
    assert inventory["policy"]["copyleft_action"] == "review"


def test_block_policy_rejects_copyleft(gate, tmp_path):
    policy = _policy(tmp_path, action="block")
    inventory, unknown = _run(
        gate,
        tmp_path,
        policy,
        _sbom(tmp_path, licenses=[{"license": {"id": "AGPL-3.0-only"}}]),
    )
    assert unknown == []
    assert inventory["surfaces"][0]["components"][0]["legal_class"] == "copyleft"
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    output = tmp_path / "inventory.json"
    assert (
        gate.main(
            [
                "--policy",
                str(policy_path),
                "--sbom",
                f"image={_sbom(tmp_path, licenses=[{'license': {'id': 'AGPL-3.0-only'}}])}",
                "--output",
                str(output),
            ]
        )
        == 1
    )


def test_missing_required_surface_is_rejected(gate, tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    with pytest.raises(gate.InventoryError, match="missing required SBOM surfaces"):
        gate.build_inventory(_policy(tmp_path), {})


def test_sbom_without_identity_or_bom_ref_is_rejected(gate, tmp_path):
    policy = _policy(tmp_path)
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    sbom = tmp_path / "image.json"
    sbom.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "components": [{"bom-ref": "x", "version": "1.0"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(gate.InventoryError, match="no purl or name"):
        gate.build_inventory(policy, {"image": sbom})

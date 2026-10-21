"""Tests for the final-artifact license inventory gate (#363)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

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


def test_more_specific_resolution_overrides_class_wildcard(gate, tmp_path):
    """A targeted copyleft record must beat a class-level resolution.

    The real policy resolves binary-embedded crate/module trees with a broad
    ``pkg:cargo/*``-style class record while calling out known MPL-2.0 members
    by narrower patterns; the narrow record must win so copyleft stays
    visible instead of being flattened into the class NOASSERTION.
    """
    policy = _policy(tmp_path)
    policy["reviewed_resolutions"] = [
        {
            "identity": "pkg:pypi/example@*",
            "license": "NOASSERTION",
            "reason": "Class-level resolution for a binary-embedded tree",
            "owner": "legal@example.test",
            "reviewed_on": "2026-01-01",
        },
        {
            "identity": "pkg:pypi/example@1.0",
            "license": "MPL-2.0",
            "reason": "Known MPL-2.0 member of that tree",
            "owner": "legal@example.test",
            "reviewed_on": "2026-01-01",
        },
    ]
    inventory, unknown = _run(gate, tmp_path, policy, _sbom(tmp_path, licenses=None))
    assert unknown == []
    component = inventory["surfaces"][0]["components"][0]
    assert component["license_status"] == "reviewed"
    assert component["licenses"] == ["MPL-2.0"]
    assert component["legal_class"] == "copyleft"


def test_equally_specific_resolutions_remain_ambiguous(gate, tmp_path):
    """Overlapping patterns of equal specificity are still a hard error."""
    policy = _policy(tmp_path)
    policy["reviewed_resolutions"] = [
        {
            "identity": "pkg:pypi/example@1*",
            "license": "MIT",
            "reason": "one",
            "owner": "legal@example.test",
            "reviewed_on": "2026-01-01",
        },
        {
            "identity": "pkg:pypi/example@*0",
            "license": "Apache-2.0",
            "reason": "two",
            "owner": "legal@example.test",
            "reviewed_on": "2026-01-01",
        },
    ]
    with pytest.raises(gate.InventoryError, match="equally specific"):
        _run(gate, tmp_path, policy, _sbom(tmp_path, licenses=None))


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


def test_component_with_identity_but_no_bom_ref_is_rejected(gate, tmp_path):
    """The bom-ref is the reconciliation key; a component without one cannot
    be joined to license evidence downstream, so it is refused outright."""
    policy = _policy(tmp_path)
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    sbom = tmp_path / "image.json"
    sbom.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "components": [
                    {"name": "example", "version": "1.0", "purl": "pkg:pypi/example@1.0"}
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(gate.InventoryError, match="has no CycloneDX bom-ref"):
        gate.build_inventory(policy, {"image": sbom})


# ---- policy validation: every refusal is its own reviewed decision -------


def _invalid_policy(tmp_path: Path, **overrides: object) -> dict[str, object]:
    policy = _policy(tmp_path)
    policy.update(overrides)
    return policy


def test_policy_surfaces_must_be_a_non_empty_list(gate, tmp_path):
    policy = _invalid_policy(tmp_path, surfaces=[])
    with pytest.raises(gate.InventoryError, match="surfaces` must be a non-empty list"):
        gate.build_inventory(policy, {})


def test_policy_surface_without_id_is_rejected(gate, tmp_path):
    policy = _invalid_policy(tmp_path)
    del policy["surfaces"][0]["id"]
    with pytest.raises(gate.InventoryError, match="every policy surface needs an id"):
        gate.build_inventory(policy, {})


def test_policy_duplicate_surface_id_is_rejected(gate, tmp_path):
    policy = _invalid_policy(tmp_path)
    policy["surfaces"].append(dict(policy["surfaces"][0]))
    with pytest.raises(gate.InventoryError, match="duplicate surface"):
        gate.build_inventory(policy, {})


def test_policy_surface_without_descriptor_fields_is_rejected(gate, tmp_path):
    policy = _invalid_policy(tmp_path)
    del policy["surfaces"][0]["classification"]
    with pytest.raises(gate.InventoryError, match="needs classification"):
        gate.build_inventory(policy, {})


def test_policy_surface_with_unknown_class_is_rejected(gate, tmp_path):
    policy = _invalid_policy(tmp_path)
    policy["surfaces"][0]["classification"] = "mystery-class"
    with pytest.raises(gate.InventoryError, match="unknown class"):
        gate.build_inventory(policy, {})


def test_policy_surface_source_must_exist(gate, tmp_path):
    policy = _invalid_policy(tmp_path)
    policy["surfaces"][0]["source"] = "no/such/source-file.txt"
    with pytest.raises(gate.InventoryError, match="source does not exist"):
        gate.build_inventory(policy, {})


def test_dependency_classes_must_be_an_object(gate, tmp_path):
    policy = _invalid_policy(tmp_path, dependency_classes=[])
    with pytest.raises(gate.InventoryError, match="dependency_classes` must be an object"):
        gate.build_inventory(policy, {})


def test_missing_dependency_class_is_rejected(gate, tmp_path):
    policy = _invalid_policy(tmp_path)
    del policy["dependency_classes"]["build-only-tooling"]
    with pytest.raises(gate.InventoryError, match="missing dependency classes"):
        gate.build_inventory(policy, {})


def test_dependency_class_with_missing_field_is_rejected(gate, tmp_path):
    policy = _invalid_policy(tmp_path)
    del policy["dependency_classes"]["runtime-distribution"]["review_owner"]
    with pytest.raises(gate.InventoryError, match="'runtime-distribution' needs review_owner"):
        gate.build_inventory(policy, {})


def test_dependency_class_must_be_an_object(gate, tmp_path):
    policy = _invalid_policy(tmp_path)
    policy["dependency_classes"]["runtime-distribution"] = "see legal review"
    with pytest.raises(gate.InventoryError, match="'runtime-distribution' must be an object"):
        gate.build_inventory(policy, {})


def test_coverage_must_name_every_required_scope(gate, tmp_path):
    policy = _invalid_policy(tmp_path)
    policy["coverage"] = ["transitive-packages"]
    with pytest.raises(gate.InventoryError, match="coverage must name"):
        gate.build_inventory(policy, {})


def test_frontend_surface_needs_asset_evidence(gate, tmp_path):
    policy = _invalid_policy(tmp_path)
    policy["surfaces"][0] = {
        "id": "bundle",
        "kind": "frontend-bundle",
        "classification": "runtime-distribution",
        "source": "Dockerfile",
    }
    with pytest.raises(
        gate.InventoryError, match=r"frontend surface 'bundle' needs asset_evidence"
    ):
        gate.build_inventory(policy, {})


@pytest.mark.parametrize(
    "legal",
    [
        "not-an-object",
        {"copyleft_action": "review"},
        {"unknown_license_action": "fail", "copyleft_action": "shrug"},
    ],
    ids=["not-an-object", "missing-unknown-action", "unknown-copyleft-action"],
)
def test_invalid_legal_sections_are_rejected(gate, tmp_path, legal):
    policy = _invalid_policy(tmp_path, legal=legal)
    with pytest.raises(gate.InventoryError, match="legal"):
        gate.build_inventory(policy, {})


# ---- SBOM input validation ----------------------------------------------


def _write_sbom(tmp_path: Path, document: object, name: str = "image.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_non_cyclonedx_sbom_is_rejected(gate, tmp_path):
    policy = _policy(tmp_path)
    sbom = _write_sbom(tmp_path, {"bomFormat": "SPDX"})
    with pytest.raises(gate.InventoryError, match="expected a CycloneDX SBOM"):
        gate.build_inventory(policy, {"image": sbom})


def test_bundle_without_components_still_proves_the_scan(gate, tmp_path):
    """`components: null` is Syft's output for a bundle of unrecognised files.

    A minified frontend asset directory yields exactly this; the surface must
    still be inventoried (as empty) rather than refused, because the empty
    bundle SBOM is the evidence that the final filesystem was scanned.
    """
    policy = _policy(tmp_path)
    sbom = _write_sbom(tmp_path, {"bomFormat": "CycloneDX", "components": None})
    inventory, unknown = _run(gate, tmp_path, policy, sbom)
    assert unknown == []
    assert inventory["surfaces"][0]["components"] == []
    assert inventory["surfaces"][0]["sbom"]["sha256"]


def test_non_list_components_are_rejected(gate, tmp_path):
    policy = _policy(tmp_path)
    sbom = _write_sbom(tmp_path, {"bomFormat": "CycloneDX", "components": {}})
    with pytest.raises(gate.InventoryError, match="components` must be a list"):
        gate.build_inventory(policy, {"image": sbom})


def test_missing_sbom_file_is_rejected(gate, tmp_path):
    policy = _policy(tmp_path)
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    with pytest.raises(gate.InventoryError, match="does not exist"):
        gate.build_inventory(policy, {"image": tmp_path / "absent.json"})


def test_duplicate_bom_ref_is_rejected(gate, tmp_path):
    policy = _policy(tmp_path)
    component = {
        "bom-ref": "pkg:pypi/example@1.0",
        "name": "example",
        "version": "1.0",
        "purl": "pkg:pypi/example@1.0",
        "licenses": [{"license": {"id": "MIT"}}],
    }
    sbom = _write_sbom(tmp_path, {"bomFormat": "CycloneDX", "components": [component, component]})
    with pytest.raises(gate.InventoryError, match="duplicate bom-ref"):
        gate.build_inventory(policy, {"image": sbom})


def test_file_component_is_provenance_not_a_license_subject(gate, tmp_path):
    """A file component (package-lock.json) is SBOM provenance.

    Its missing license must read as not-applicable — never as unknown
    metadata demanding a reviewed resolution, and never silently licensed.
    """
    policy = _policy(tmp_path)
    lock = {
        "bom-ref": "file:package-lock.json",
        "type": "file",
        "name": "package-lock.json",
    }
    sbom = _write_sbom(tmp_path, {"bomFormat": "CycloneDX", "components": [lock]})
    inventory, unknown = _run(gate, tmp_path, policy, sbom)
    assert unknown == []
    component = inventory["surfaces"][0]["components"][0]
    assert component["license_status"] == "not-applicable"
    assert component["legal_class"] == "not-applicable"
    assert component["review"] is None
    assert inventory["surfaces"][0]["license_evidence"][0]["component_ref"] == lock["bom-ref"]


def test_sbom_surface_without_policy_is_rejected(gate, tmp_path):
    policy = _policy(tmp_path)
    sbom = _sbom(tmp_path, licenses=[{"license": {"id": "MIT"}}])
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    with pytest.raises(gate.InventoryError, match="SBOM has no policy surface"):
        gate.build_inventory(policy, {"image": sbom, "extra": sbom})


def test_divergent_evidence_is_rejected(gate, tmp_path, monkeypatch):
    """Components and license evidence must reconcile 1:1.

    The SBOM component identities are the keys a downstream SBOM-vs-license
    reconciliation joins on; a record whose evidence names a different
    bom-ref would silently break that join.
    """
    policy = _policy(tmp_path)
    sbom = _sbom(tmp_path, licenses=[{"license": {"id": "MIT"}}])
    original = gate._component_record

    def divergent(surface_id, component, resolutions, unknown):
        record, evidence = original(surface_id, component, resolutions, unknown)
        evidence["component_ref"] = "refabricated-ref"
        return record, evidence

    monkeypatch.setattr(gate, "_component_record", divergent)
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    with pytest.raises(gate.InventoryError, match="components and license evidence diverge"):
        gate.build_inventory(policy, {"image": sbom})


# ---- license evidence forms ----------------------------------------------


def test_expression_and_value_license_forms_are_extracted(gate, tmp_path):
    policy = _policy(tmp_path)
    sbom = _sbom(
        tmp_path,
        licenses=[
            {"expression": "MIT OR Apache-2.0"},
            {"value": "BSD-2-Clause"},
            "garbage-entry",
        ],
    )
    inventory, unknown = _run(gate, tmp_path, policy, sbom)
    component = inventory["surfaces"][0]["components"][0]
    assert component["licenses"] == ["MIT OR Apache-2.0", "BSD-2-Clause"]
    assert component["license_status"] == "known"
    assert unknown == []


def test_component_level_license_expression_is_extracted(gate, tmp_path):
    policy = _policy(tmp_path)
    component = {
        "bom-ref": "pkg:pypi/example@1.0",
        "name": "example",
        "version": "1.0",
        "purl": "pkg:pypi/example@1.0",
        "licenseExpression": "Apache-2.0",
    }
    sbom = _write_sbom(tmp_path, {"bomFormat": "CycloneDX", "components": [component]})
    inventory, unknown = _run(gate, tmp_path, policy, sbom)
    assert inventory["surfaces"][0]["components"][0]["licenses"] == ["Apache-2.0"]
    assert unknown == []


def test_identity_falls_back_to_name_version_then_name(gate, tmp_path):
    policy = _policy(tmp_path)
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    components = [
        {"bom-ref": "a", "name": "no-purl", "version": "2.0"},
        {"bom-ref": "b", "name": "name-only"},
    ]
    sbom = _write_sbom(tmp_path, {"bomFormat": "CycloneDX", "components": components})
    inventory, unknown = gate.build_inventory(policy, {"image": sbom})
    identities = [item["identity"] for item in inventory["surfaces"][0]["components"]]
    assert identities == ["no-purl@2.0", "name-only"]
    assert unknown == [f"image: {identities[0]} (a)", f"image: {identities[1]} (b)"]


def test_reviewed_resolution_marks_licensed_component_reviewed(gate, tmp_path):
    """A reviewed resolution on an already-licensed component keeps both."""
    policy = _policy(tmp_path)
    policy["reviewed_resolutions"] = [
        {
            "identity": "pkg:pypi/example@1.0",
            "license": "MIT",
            "reason": "re-reviewed upstream change",
            "owner": "legal@example.test",
            "reviewed_on": "2026-01-01",
        }
    ]
    inventory, unknown = _run(
        gate, tmp_path, policy, _sbom(tmp_path, licenses=[{"license": {"id": "MIT"}}])
    )
    component = inventory["surfaces"][0]["components"][0]
    assert component["license_status"] == "reviewed"
    assert component["licenses"] == ["MIT"]
    assert unknown == []


def test_malformed_resolution_entries_are_skipped(gate, tmp_path):
    policy = _policy(tmp_path)
    policy["reviewed_resolutions"] = [
        "not-a-dict",
        {"identity": "pkg:nobody/*@*"},
        {
            "identity": "pkg:pypi/example@1.0",
            "license": "BSD-3-Clause",
            "reason": "Upstream LICENSE reviewed",
            "owner": "legal@example.test",
            "reviewed_on": "2026-01-01",
        },
    ]
    inventory, unknown = _run(gate, tmp_path, policy, _sbom(tmp_path, licenses=None))
    assert unknown == []
    assert inventory["surfaces"][0]["components"][0]["licenses"] == ["BSD-3-Clause"]


def test_resolution_missing_required_field_is_rejected(gate, tmp_path):
    policy = _policy(tmp_path)
    policy["reviewed_resolutions"] = [
        {
            "identity": "pkg:pypi/example@1.0",
            "license": "BSD-3-Clause",
            "reason": "Upstream LICENSE reviewed",
            "owner": "legal@example.test",
        }
    ]
    with pytest.raises(gate.InventoryError, match="needs reviewed_on"):
        _run(gate, tmp_path, policy, _sbom(tmp_path, licenses=None))


# ---- CLI contract --------------------------------------------------------


def _write_policy_file(tmp_path: Path, policy: dict[str, object]) -> Path:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    return path


def test_main_success_writes_inventory_and_returns_zero(gate, tmp_path):
    policy = _policy(tmp_path)
    sbom = _sbom(tmp_path, licenses=[{"license": {"id": "Apache-2.0"}}])
    output = tmp_path / "out" / "inventory.json"
    exit_code = gate.main(
        [
            "--policy",
            str(_write_policy_file(tmp_path, policy)),
            "--sbom",
            f"image={sbom}",
            "--artifact",
            "image=registry.example/image@sha256:abc",
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["surfaces"][0]["artifact"] == "registry.example/image@sha256:abc"
    assert written["unresolved"] == []


def test_main_fails_on_unresolved_licenses(gate, tmp_path, capsys):
    policy = _policy(tmp_path)
    sbom = _sbom(tmp_path, licenses=None)
    exit_code = gate.main(
        [
            "--policy",
            str(_write_policy_file(tmp_path, policy)),
            "--sbom",
            f"image={sbom}",
            "--output",
            str(tmp_path / "inventory.json"),
        ]
    )
    assert exit_code == 1
    assert "requires a reviewed resolution" in capsys.readouterr().out


def test_main_reports_policy_failure(gate, tmp_path, capsys):
    policy = _policy(tmp_path)
    policy["surfaces"][0]["source"] = "no/such/source-file.txt"
    exit_code = gate.main(
        [
            "--policy",
            str(_write_policy_file(tmp_path, policy)),
            "--output",
            str(tmp_path / "inventory.json"),
        ]
    )
    assert exit_code == 1
    assert "FAIL: surface 'image': source does not exist" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ("{not json", "cannot read JSON"),
        ("[1, 2, 3]", "top-level JSON value must be an object"),
    ],
    ids=["malformed", "non-object"],
)
def test_main_rejects_unreadable_policy(gate, tmp_path, capsys, payload, match):
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(payload, encoding="utf-8")
    exit_code = gate.main(
        ["--policy", str(policy_path), "--output", str(tmp_path / "inventory.json")]
    )
    assert exit_code == 1
    assert match in capsys.readouterr().err


def test_main_rejects_absent_policy(gate, tmp_path, capsys):
    exit_code = gate.main(
        [
            "--policy",
            str(tmp_path / "absent.json"),
            "--output",
            str(tmp_path / "inventory.json"),
        ]
    )
    assert exit_code == 1
    assert "cannot read JSON" in capsys.readouterr().err


def test_main_rejects_sbom_pair_without_equals(gate, tmp_path, capsys):
    policy = _policy(tmp_path)
    exit_code = gate.main(
        [
            "--policy",
            str(_write_policy_file(tmp_path, policy)),
            "--sbom",
            "image-no-equals",
            "--output",
            str(tmp_path / "inventory.json"),
        ]
    )
    assert exit_code == 1
    assert "--sbom expects SURFACE=PATH" in capsys.readouterr().err


def test_main_rejects_duplicate_sbom_surface(gate, tmp_path, capsys):
    policy = _policy(tmp_path)
    sbom = _sbom(tmp_path, licenses=[{"license": {"id": "MIT"}}])
    exit_code = gate.main(
        [
            "--policy",
            str(_write_policy_file(tmp_path, policy)),
            "--sbom",
            f"image={sbom}",
            "--sbom",
            f"image={sbom}",
            "--output",
            str(tmp_path / "inventory.json"),
        ]
    )
    assert exit_code == 1
    assert "invalid or duplicate --sbom" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("artifact_args", "match"),
    [
        (["image-no-equals"], "--artifact expects SURFACE=REFERENCE"),
        (["=ref"], "invalid or duplicate --artifact"),
        (["image=ref", "image=again"], "invalid or duplicate --artifact"),
    ],
    ids=["no-equals", "empty-surface", "duplicate"],
)
def test_main_rejects_bad_artifact_pairs(gate, tmp_path, capsys, artifact_args, match):
    policy = _policy(tmp_path)
    sbom = _sbom(tmp_path, licenses=[{"license": {"id": "MIT"}}])
    argv = [
        "--policy",
        str(_write_policy_file(tmp_path, policy)),
        "--sbom",
        f"image={sbom}",
        "--output",
        str(tmp_path / "inventory.json"),
    ]
    for value in artifact_args:
        argv.extend(["--artifact", value])
    assert gate.main(argv) == 1
    assert match in capsys.readouterr().err


def test_main_rejects_reviewed_resolutions_that_are_not_a_list(gate, tmp_path, capsys):
    policy = _policy(tmp_path)
    policy["reviewed_resolutions"] = {"pkg:pypi/example@1.0": "BSD-3-Clause"}
    sbom = _sbom(tmp_path, licenses=[{"license": {"id": "MIT"}}])
    exit_code = gate.main(
        [
            "--policy",
            str(_write_policy_file(tmp_path, policy)),
            "--sbom",
            f"image={sbom}",
            "--output",
            str(tmp_path / "inventory.json"),
        ]
    )
    assert exit_code == 1
    assert "reviewed_resolutions` must be a list" in capsys.readouterr().err


def test_only_limits_the_inventory_to_named_surfaces(gate, tmp_path):
    policy = _policy(tmp_path)
    policy["surfaces"].append(
        {
            "id": "optional",
            "kind": "final-image",
            "classification": "build-only-tooling",
            "source": "Dockerfile",
            "required": False,
        }
    )
    sbom = _sbom(tmp_path, licenses=[{"license": {"id": "Apache-2.0"}}])
    inventory, unknown = gate.build_inventory(policy, {"image": sbom}, only={"image"})
    assert [surface["id"] for surface in inventory["surfaces"]] == ["image"]
    assert unknown == []


def test_only_with_unknown_surface_is_rejected(gate, tmp_path):
    policy = _policy(tmp_path)
    sbom = _sbom(tmp_path, licenses=[{"license": {"id": "Apache-2.0"}}])
    with pytest.raises(gate.InventoryError, match="--only names unknown policy surfaces"):
        gate.build_inventory(policy, {"image": sbom}, only={"image", "not-in-policy"})


def test_repository_license_policy_validates(gate):
    """The committed policy must always pass its own schema gate.

    A policy edit that breaks the inventory gate is a legal-review regression,
    not a fixture detail: this pins the schema contract against the real file
    rather than a copy that could silently drift from it.
    """
    policy = gate._load_json(gate.DEFAULT_POLICY)
    surfaces = gate._check_policy(policy)
    required = {sid for sid, item in surfaces.items() if item.get("required", True)}
    with pytest.raises(gate.InventoryError) as excinfo:
        gate.build_inventory(policy, {})
    missing = excinfo.value.args[0].split(": ", 1)[1].split(", ")
    assert set(missing) == required


def test_sentinel_license_value_is_missing_metadata_not_a_license(gate, tmp_path):
    """NOASSERTION and friends are not licences.

    A producer that emits a placeholder is saying "I have no licence to
    report". Accepting the placeholder as a licence would let a component
    with unknown licence metadata pass as known, which is exactly what the
    reviewed-resolution rule exists to prevent.
    """
    policy = _policy(tmp_path)
    sbom = _sbom(tmp_path, licenses=[{"license": {"id": "NOASSERTION"}}])
    inventory, unknown = _run(gate, tmp_path, policy, sbom)
    assert unknown == ["image: pkg:pypi/example@1.0 (pkg:pypi/example@1.0)"]
    component = inventory["surfaces"][0]["components"][0]
    assert component["licenses"] == []
    assert component["license_status"] == "unresolved"
    assert component["legal_class"] == "unknown"


@pytest.mark.parametrize("sentinel", ["NOASSERTION", "NONE", "UNKNOWN", "LicenseRef-Unknown"])
def test_every_missing_license_sentinel_needs_a_reviewed_resolution(gate, tmp_path, sentinel):
    policy = _policy(tmp_path)
    sbom = _sbom(tmp_path, licenses=[{"license": {"name": sentinel}}])
    inventory, unknown = _run(gate, tmp_path, policy, sbom)
    assert unknown != []
    component = inventory["surfaces"][0]["components"][0]
    assert component["license_status"] == "unresolved"


def test_sentinel_license_value_with_a_reviewed_resolution_is_reviewed(gate, tmp_path):
    """A placeholder plus a reviewed resolution is a resolution, not a gap."""
    policy = _policy(tmp_path)
    policy["reviewed_resolutions"] = [
        {
            "identity": "pkg:pypi/example@1.0",
            "license": "MIT",
            "reason": "Wheel METADATA declares License-Expression: MIT.",
            "owner": "Engineering and Legal",
            "reviewed_on": "2026-10-18",
        }
    ]
    sbom = _sbom(tmp_path, licenses=[{"license": {"id": "NOASSERTION"}}])
    inventory, unknown = _run(gate, tmp_path, policy, sbom)
    assert unknown == []
    component = inventory["surfaces"][0]["components"][0]
    assert component["licenses"] == ["MIT"]
    assert component["license_status"] == "reviewed"


def test_sentinel_alongside_a_real_license_keeps_the_real_license(gate, tmp_path):
    policy = _policy(tmp_path)
    sbom = _sbom(
        tmp_path,
        licenses=[{"license": {"id": "NOASSERTION"}}, {"license": {"id": "MIT"}}],
    )
    inventory, unknown = _run(gate, tmp_path, policy, sbom)
    assert unknown == []
    component = inventory["surfaces"][0]["components"][0]
    assert component["licenses"] == ["MIT"]
    assert component["license_status"] == "known"


def test_file_component_with_explicit_license_keeps_its_evidence(gate, tmp_path):
    """A shipped script or font is a file component with a licence.

    Rewriting it to "not-applicable" would hide a licensed artifact from
    the legal review — the file-component exemption is for provenance
    records (a lockfile), not for vendored assets.
    """
    policy = _policy(tmp_path)
    script = {
        "bom-ref": "file:/app/bin/tool.sh",
        "type": "file",
        "name": "tool.sh",
        "licenses": [{"license": {"id": "GPL-3.0-only"}}],
    }
    sbom = _write_sbom(tmp_path, {"bomFormat": "CycloneDX", "components": [script]})
    inventory, unknown = _run(gate, tmp_path, policy, sbom)
    assert unknown == []
    component = inventory["surfaces"][0]["components"][0]
    assert component["licenses"] == ["GPL-3.0-only"]
    assert component["license_status"] == "known"
    assert component["legal_class"] == "copyleft"
    assert inventory["surfaces"][0]["license_evidence"][0]["licenses"] == ["GPL-3.0-only"]


def test_file_component_without_license_stays_provenance(gate, tmp_path):
    policy = _policy(tmp_path)
    lock = {
        "bom-ref": "file:package-lock.json",
        "type": "file",
        "name": "package-lock.json",
        "licenses": [{"license": {"id": "NOASSERTION"}}],
    }
    sbom = _write_sbom(tmp_path, {"bomFormat": "CycloneDX", "components": [lock]})
    inventory, unknown = _run(gate, tmp_path, policy, sbom)
    assert unknown == []
    component = inventory["surfaces"][0]["components"][0]
    assert component["license_status"] == "not-applicable"
    assert component["legal_class"] == "not-applicable"


@pytest.mark.parametrize(
    "license_id",
    ["OFL-1.1", "EUPL-1.2", "CC-BY-SA-4.0", "CC-BY-SA-3.0", "SIL OPEN FONT LICENSE 1.1"],
)
def test_copyleft_families_are_classified_as_copyleft(gate, tmp_path, license_id):
    """Fonts, the EUPL and share-alike assets are copyleft.

    The frontend trees ship OFL fonts and CC-BY-SA assets; classifying them
    as "other" would present a copyleft finding to legal as a benign one.
    """
    policy = _policy(tmp_path)
    sbom = _sbom(tmp_path, licenses=[{"license": {"id": license_id}}])
    inventory, unknown = _run(gate, tmp_path, policy, sbom)
    assert unknown == []
    component = inventory["surfaces"][0]["components"][0]
    assert component["legal_class"] == "copyleft", license_id


def test_permissive_licenses_stay_non_copyleft(gate, tmp_path):
    policy = _policy(tmp_path)
    sbom = _sbom(tmp_path, licenses=[{"license": {"id": "MIT"}}])
    inventory, _ = _run(gate, tmp_path, policy, sbom)
    assert inventory["surfaces"][0]["components"][0]["legal_class"] == "other"


def test_inventory_records_the_policy_file_that_was_used(gate, tmp_path, capsys):
    """The recorded policy path is the policy that governed the inventory.

    Recording the default while a different policy was supplied is a false
    statement about how the legal verdict was reached.
    """
    policy = _policy(tmp_path)
    policy_file = _write_policy_file(tmp_path, policy)
    sbom = _sbom(tmp_path, licenses=[{"license": {"id": "MIT"}}])
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    exit_code = gate.main(
        [
            "--policy",
            str(policy_file),
            "--sbom",
            f"image={sbom}",
            "--output",
            str(tmp_path / "inventory.json"),
        ]
    )
    assert exit_code == 0
    capsys.readouterr()
    inventory = json.loads((tmp_path / "inventory.json").read_text(encoding="utf-8"))
    assert inventory["policy"]["path"] == str(policy_file)
    assert inventory["policy"]["path"] != "quality/license-policy.json"


def test_inventory_records_the_default_policy_when_none_is_supplied(gate, tmp_path):
    policy = _policy(tmp_path)
    sbom = _sbom(tmp_path, licenses=[{"license": {"id": "MIT"}}])
    inventory, _ = _run(gate, tmp_path, policy, sbom)
    assert inventory["policy"]["path"] == "quality/license-policy.json"


# Execute the production workflow's shell blocks: stubs replace only network /
# registry boundaries; the license gate, archive, and checksum commands are real.
def _release_steps(job):
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    return workflow["jobs"][job]["steps"]


def _release_workspace(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    commands = {
        "npm": "exit 0\n",
        "docker": 'echo "docker $*" >> "$CALLS"\n',
        "gh": 'echo "gh $*" >> "$CALLS"\n',
        "python": f'exec {shlex.quote(sys.executable)} "$@"\n',
        "syft": (
            'echo "syft $*" >> "$CALLS"\n'
            '[ "${FAIL_SCAN:-0}" = 0 ] || exit 73\n'
            'if [ "${UNKNOWN_LICENSE:-0}" = 1 ]; then licenses=""; '
            'else licenses=\',"licenses":[{"license":{"id":"MIT"}}]\'; fi\n'
            'printf \'{"bomFormat":"CycloneDX","components":[{'
            '"bom-ref":"probe","purl":"pkg:generic/license-probe@1",'
            '"name":"license-probe"%s}]}\\n\' "$licenses"\n'
        ),
    }
    for name, body in commands.items():
        path = bin_dir / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + body)
        path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("CALLS", str(tmp_path / "calls"))
    monkeypatch.setenv("IMAGE_NAMESPACE", "registry.example/maistro")
    monkeypatch.setenv("GITHUB_RUN_ID", "363")
    monkeypatch.setenv("GITHUB_REF_NAME", "v1.0.0")
    for frontend in ("packages/hive-conductor/frontend", "packages/maistro-canvas/frontend"):
        (tmp_path / frontend / "dist").mkdir(parents=True)
    (tmp_path / "scripts").symlink_to(ROOT / "scripts", target_is_directory=True)
    (tmp_path / "quality").mkdir()
    (tmp_path / "quality/license-policy.json").write_bytes(
        (ROOT / "quality/license-policy.json").read_bytes()
    )


def _run_release_step(step, tmp_path):
    # Resolve only the concrete outputs these blocks consume. An unexpected
    # expression is a test failure, not a guessed release ref.
    outputs = {
        "${{ steps.engine.outputs.digest }}": "sha256:engine",
        "${{ steps.conductor.outputs.digest }}": "sha256:conductor",
        "${{ steps.tags.outputs.maistro_engine }}": "registry.example/maistro/maistro-engine:v1.0.0",
        "${{ steps.tags.outputs.hive_conductor }}": "registry.example/maistro/hive-conductor:v1.0.0",
        "${{ secrets.GITHUB_TOKEN }}": "test-token",
        "${{ needs.guard.outputs.prerelease }}": "false",
    }
    env = os.environ | {key: outputs[value] for key, value in step.get("env", {}).items()}
    assert "${{" not in step["run"]
    return subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _license_and_promotion_steps():
    return [
        step
        for step in _release_steps("images")
        if step.get("name")
        in {
            "Generate release-digest license inventory",
            "Promote the scanned digests to the release tags",
        }
    ]


@pytest.mark.parametrize("failure", ["UNKNOWN_LICENSE", "FAIL_SCAN"])
def test_release_license_failure_never_promotes(tmp_path, monkeypatch, failure):
    _release_workspace(tmp_path, monkeypatch)
    monkeypatch.setenv(failure, "1")
    for step in _license_and_promotion_steps():
        result = _run_release_step(step, tmp_path)
        if result.returncode:
            break  # Actions skips all subsequent ordinary steps on failure.
    assert result.returncode != 0
    if failure == "UNKNOWN_LICENSE":
        assert "requires a reviewed resolution" in result.stdout
    else:
        assert result.returncode == 73
    assert "imagetools create" not in (tmp_path / "calls").read_text()
    assert not (tmp_path / "license-inventory-release.tar.gz").exists()


def test_release_scans_quarantine_and_installed_bundle_before_promotion(tmp_path, monkeypatch):
    _release_workspace(tmp_path, monkeypatch)
    for step in _license_and_promotion_steps():
        result = _run_release_step(step, tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
    calls = (tmp_path / "calls").read_text()
    assert "syft registry.example/maistro/maistro-engine-rc@sha256:engine" in calls
    assert "syft registry.example/maistro/hive-conductor-rc@sha256:conductor" in calls
    assert "docker cp license-release-363:/app/frontend/dist/." in calls
    assert "syft dir:packages/hive-conductor/frontend/dist" not in calls
    assert calls.rindex("syft ") < calls.index("imagetools create")
    inventory = json.loads((tmp_path / "license-inventory-release.json").read_text())
    assert len(inventory["surfaces"]) == 6
    for surface in inventory["surfaces"]:
        assert (
            surface["components"][0]["bom_ref"] == surface["license_evidence"][0]["component_ref"]
        )
    engine = next(s for s in inventory["surfaces"] if s["id"] == "maistro-engine")
    assert engine["artifact"] == "registry.example/maistro/maistro-engine@sha256:engine"
    with tarfile.open(tmp_path / "license-inventory-release.tar.gz") as archive:
        names = archive.getnames()
        assert "quality/license-policy.json" in names
        assert len([n for n in names if n.startswith("license-sboms/")]) == 6
        assert (
            archive.extractfile("license-inventory-release.json").read()
            == (tmp_path / "license-inventory-release.json").read_bytes()
        )


def _stage_inputs(tmp_path):
    for folder, name in (
        ("dist", "maistro.whl"),
        ("sboms", "engine.cyclonedx.json"),
        ("compliance", "release-compliance.json"),
        ("license-inventory", "license-inventory-release.json"),
        ("license-inventory", "license-inventory-release.tar.gz"),
    ):
        (tmp_path / folder).mkdir(exist_ok=True)
        (tmp_path / folder / name).write_text(name)
    for name in ("get.sh", "get.ps1", "install.sh"):
        (tmp_path / name).write_text(name)


def test_release_license_assets_are_downloaded_checksummed_and_attached(tmp_path, monkeypatch):
    _release_workspace(tmp_path, monkeypatch)
    _stage_inputs(tmp_path)
    steps = _release_steps("github-release")
    upload = next(
        step
        for step in _release_steps("images")
        if step.get("with", {}).get("name") == "license-inventory-${{ github.ref_name }}"
    )
    download = next(
        step for step in steps if step.get("with", {}).get("name") == upload["with"]["name"]
    )
    assert download["uses"].startswith("actions/download-artifact@")
    assert download["with"]["path"] == "license-inventory/"
    assert set(upload["with"]["path"].split()) == {
        "license-inventory-release.json",
        "license-inventory-release.tar.gz",
    }
    for step in steps:
        if step.get("name") in {"Stage artifacts + SHA256SUMS", "Create the release"}:
            result = _run_release_step(step, tmp_path)
            assert result.returncode == 0, result.stdout + result.stderr
    manifest = dict(
        line.split()[::-1] for line in (tmp_path / "release/SHA256SUMS").read_text().splitlines()
    )
    for name in ("license-inventory-release.json", "license-inventory-release.tar.gz"):
        assert (
            manifest[name] == hashlib.sha256((tmp_path / "release" / name).read_bytes()).hexdigest()
        )
        assert str(Path("release") / name) in (tmp_path / "calls").read_text()


@pytest.mark.parametrize("missing", ["json", "tar.gz"])
def test_release_cannot_stage_without_license_evidence(tmp_path, monkeypatch, missing):
    _release_workspace(tmp_path, monkeypatch)
    _stage_inputs(tmp_path)
    (tmp_path / f"license-inventory/license-inventory-release.{missing}").unlink()
    stage = next(
        s
        for s in _release_steps("github-release")
        if s.get("name") == "Stage artifacts + SHA256SUMS"
    )
    result = _run_release_step(stage, tmp_path)
    assert result.returncode != 0
    assert not (tmp_path / "release/SHA256SUMS").exists()

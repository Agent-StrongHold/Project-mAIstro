"""Manifest inspection fail-closed matrix (#953, M9-B2).

Parsing is the platform's first and hardest trust boundary: it runs on
untrusted bytes and its only two outcomes are a fully-validated immutable
snapshot or a typed rejection. Every rejection path here is a path a hostile
package would take.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from maistro.extensions.manifest import (
    assert_snapshot_intact,
    inspect_manifest,
    sha256_hex,
    verify_package_payload,
)
from maistro.extensions.types import ManifestRejected


def _payload() -> bytes:
    return b"payload-bytes"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def valid_manifest(**overrides: object) -> bytes:
    payload = overrides.pop("payload", _payload())
    document: dict[str, object] = {
        "manifest_version": 1,
        "id": "acme.chart_tools",
        "name": "Chart Tools",
        "version": "1.4.0",
        "publisher": "acme",
        "api_version": "1.0.0",
        "permissions": ["network.http"],
        "entry_points": [{"name": "main", "module": "acme_chart.main", "attribute": "activate"}],
        "artifact": {"sha256": _digest(payload), "size": len(payload)},
    }
    dependencies = overrides.pop("dependencies", None)
    if dependencies is not None:
        document["dependencies"] = dependencies
    document.update(overrides)  # type: ignore[arg-type]
    return json.dumps(document).encode("utf-8")


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
class TestHappyPath:
    def test_parses_into_a_fully_anchored_snapshot(self) -> None:
        payload = _payload()
        manifest = inspect_manifest(valid_manifest(payload=payload))
        assert manifest.extension_id == "acme.chart_tools"
        assert manifest.version == "1.4.0"
        assert manifest.permissions == ("network.http",)
        assert manifest.artifact_sha256 == _digest(payload)
        assert manifest.artifact_size == len(payload)
        assert manifest.source_sha256 == sha256_hex(manifest.raw)
        assert manifest.entry_points[0].module == "acme_chart.main"
        assert_snapshot_intact(manifest)

    def test_dependencies_default_to_empty(self) -> None:
        manifest = inspect_manifest(valid_manifest())
        assert manifest.dependencies == ()

    def test_declared_dependencies_are_kept_in_order(self) -> None:
        manifest = inspect_manifest(
            valid_manifest(
                dependencies=[
                    {"id": "acme.ui_kit", "range": "^1.0.0"},
                    {"id": "acme.core", "range": "2.0.0"},
                ]
            )
        )
        assert [dep.extension_id for dep in manifest.dependencies] == [
            "acme.ui_kit",
            "acme.core",
        ]


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
class TestFailClosed:
    def test_not_json(self) -> None:
        with pytest.raises(ManifestRejected, match="not valid UTF-8 JSON"):
            inspect_manifest(b"this is not json")

    def test_not_utf8(self) -> None:
        with pytest.raises(ManifestRejected):
            inspect_manifest(b"\xff\xfe\x00garbage")

    def test_top_level_not_an_object(self) -> None:
        with pytest.raises(ManifestRejected, match="object"):
            inspect_manifest(b"[1, 2, 3]")

    def test_unknown_keys_are_refused_not_ignored(self) -> None:
        raw = json.loads(valid_manifest())
        raw["auto_grant"] = True
        with pytest.raises(ManifestRejected, match="unknown manifest keys"):
            inspect_manifest(json.dumps(raw).encode())

    def test_missing_keys_are_refused(self) -> None:
        raw = json.loads(valid_manifest())
        del raw["permissions"]
        with pytest.raises(ManifestRejected, match="missing manifest keys"):
            inspect_manifest(json.dumps(raw).encode())

    @pytest.mark.parametrize("version", [0, 2, "1", None, "1.0"])
    def test_unknown_manifest_versions_fail_closed(self, version: object) -> None:
        raw = json.loads(valid_manifest())
        raw["manifest_version"] = version
        with pytest.raises(ManifestRejected, match="manifest_version"):
            inspect_manifest(json.dumps(raw).encode())

    @pytest.mark.parametrize("field", ["id", "name", "publisher"])
    def test_blank_identity_fields_are_refused(self, field: str) -> None:
        raw = json.loads(valid_manifest())
        raw[field] = "   "
        with pytest.raises(ManifestRejected, match=field):
            inspect_manifest(json.dumps(raw).encode())

    @pytest.mark.parametrize("bad_id", ["Acme.Tools", "1acme", "acme..tools", "acme tools"])
    def test_malformed_identifiers_are_refused(self, bad_id: str) -> None:
        raw = json.loads(valid_manifest())
        raw["id"] = bad_id
        with pytest.raises(ManifestRejected, match="extension id"):
            inspect_manifest(json.dumps(raw).encode())

    @pytest.mark.parametrize("bad", ["1", "1.2", "v1.2.3", "01.2.3", "1.2.3.4"])
    def test_non_semver_versions_are_refused(self, bad: str) -> None:
        raw = json.loads(valid_manifest())
        raw["version"] = bad
        with pytest.raises(ManifestRejected, match="semver"):
            inspect_manifest(json.dumps(raw).encode())

    @pytest.mark.parametrize(
        "bad_permission", ["UPPER.name", "1network", "network..http", "", "net work"]
    )
    def test_malformed_permissions_are_refused(self, bad_permission: str) -> None:
        raw = json.loads(valid_manifest())
        raw["permissions"] = [bad_permission]
        with pytest.raises(ManifestRejected, match="permission"):
            inspect_manifest(json.dumps(raw).encode())

    def test_duplicate_permissions_are_refused(self) -> None:
        raw = json.loads(valid_manifest())
        raw["permissions"] = ["network.http", "network.http"]
        with pytest.raises(ManifestRejected, match="duplicate permission"):
            inspect_manifest(json.dumps(raw).encode())

    def test_permissions_must_be_a_list_of_strings(self) -> None:
        raw = json.loads(valid_manifest())
        raw["permissions"] = "network.http"
        with pytest.raises(ManifestRejected, match="permissions"):
            inspect_manifest(json.dumps(raw).encode())

    def test_empty_entry_points_are_refused(self) -> None:
        raw = json.loads(valid_manifest())
        raw["entry_points"] = []
        with pytest.raises(ManifestRejected, match="entry_points"):
            inspect_manifest(json.dumps(raw).encode())

    def test_entry_point_with_extra_keys_is_refused(self) -> None:
        raw = json.loads(valid_manifest())
        raw["entry_points"] = [{"name": "main", "module": "m", "attribute": "a", "lazy": True}]
        with pytest.raises(ManifestRejected, match="entry point"):
            inspect_manifest(json.dumps(raw).encode())

    def test_duplicate_entry_point_names_are_refused(self) -> None:
        raw = json.loads(valid_manifest())
        raw["entry_points"] = [
            {"name": "main", "module": "m", "attribute": "a"},
            {"name": "main", "module": "m2", "attribute": "b"},
        ]
        with pytest.raises(ManifestRejected, match="duplicate entry point"):
            inspect_manifest(json.dumps(raw).encode())

    def test_artifact_claim_must_be_exact(self) -> None:
        raw = json.loads(valid_manifest())
        raw["artifact"] = {"sha256": "nothex", "size": 4}
        with pytest.raises(ManifestRejected, match="sha256"):
            inspect_manifest(json.dumps(raw).encode())

    def test_artifact_uppercase_digest_is_refused(self) -> None:
        raw = json.loads(valid_manifest())
        raw["artifact"] = {"sha256": _digest(_payload()).upper(), "size": len(_payload())}
        with pytest.raises(ManifestRejected, match="sha256"):
            inspect_manifest(json.dumps(raw).encode())

    @pytest.mark.parametrize("size", [0, -1, "12", True, 1.5])
    def test_artifact_size_must_be_positive_int(self, size: object) -> None:
        raw = json.loads(valid_manifest())
        raw["artifact"] = {"sha256": _digest(_payload()), "size": size}
        with pytest.raises(ManifestRejected, match="size"):
            inspect_manifest(json.dumps(raw).encode())

    def test_dependency_with_unknown_keys_is_refused(self) -> None:
        raw = json.loads(valid_manifest())
        raw["dependencies"] = [{"id": "acme.core", "range": "^1.0.0", "optional": True}]
        with pytest.raises(ManifestRejected, match="dependency"):
            inspect_manifest(json.dumps(raw).encode())

    def test_duplicate_dependencies_are_refused(self) -> None:
        raw = json.loads(valid_manifest())
        raw["dependencies"] = [
            {"id": "acme.core", "range": "^1.0.0"},
            {"id": "acme.core", "range": "1.0.0"},
        ]
        with pytest.raises(ManifestRejected, match="duplicate dependency"):
            inspect_manifest(json.dumps(raw).encode())


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
class TestSnapshotIntegrity:
    def test_tampered_raw_bytes_are_detected(self) -> None:
        manifest = inspect_manifest(valid_manifest())
        forged = manifest.__class__(**{**manifest.__dict__, "raw": b"forged"})
        with pytest.raises(ManifestRejected, match="integrity"):
            assert_snapshot_intact(forged)

    def test_payload_verification_accepts_the_declared_artifact(self) -> None:
        payload = _payload()
        manifest = inspect_manifest(valid_manifest(payload=payload))
        assert verify_package_payload(manifest, payload) == manifest.artifact_sha256

    def test_payload_verification_rejects_a_substituted_bundle(self) -> None:
        payload = _payload()
        manifest = inspect_manifest(valid_manifest(payload=payload))
        with pytest.raises(ManifestRejected, match="digest mismatch"):
            verify_package_payload(manifest, payload + b"extra")

    def test_payload_verification_rejects_a_size_lie(self) -> None:
        raw = json.loads(valid_manifest())
        payload = _payload()
        raw["artifact"] = {"sha256": _digest(payload), "size": len(payload) + 1}
        manifest = inspect_manifest(json.dumps(raw).encode())
        with pytest.raises(ManifestRejected, match="size mismatch"):
            verify_package_payload(manifest, payload)

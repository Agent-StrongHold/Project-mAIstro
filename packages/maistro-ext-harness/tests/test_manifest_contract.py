"""Manifest-contract validation: strict, closed, code-free (#974)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from maistro_ext_harness import ManifestRejected, load_manifest_bytes, load_manifest_file


def test_reference_greeter_manifest_validates() -> None:
    """The merged reference extension is the anchor: the harness's statement
    of contract 1.0.0 must accept the manifest the product actually ships."""
    root = Path(__file__).resolve().parents[3] / "extensions" / "reference-greeter"
    manifest = load_manifest_file(root / "extension.json")
    assert manifest.id == "reference.greeter"
    assert manifest.family == "tool"
    assert manifest.contract_major == 1
    assert manifest.entrypoint.module == "reference_greeter.plugin"


def test_round_trip_of_a_valid_manifest(valid_manifest: dict[str, Any]) -> None:
    manifest = load_manifest_bytes(json.dumps(valid_manifest))
    assert manifest.id == "acme.widget"
    assert manifest.capabilities == ()
    assert manifest.data_scopes == ()
    assert manifest.filesystem_mode == "read"


def test_invalid_json_names_the_reason() -> None:
    with pytest.raises(ManifestRejected, match=r"not valid JSON"):
        load_manifest_bytes("{not json")


def test_non_object_manifest_rejected() -> None:
    with pytest.raises(ManifestRejected, match=r"JSON object"):
        load_manifest_bytes("[]")


@pytest.mark.parametrize(
    "key", ["id", "publisher", "version", "title", "description", "contract", "family"]
)
def test_required_fields_are_required(key: str, valid_manifest: dict[str, Any]) -> None:
    broken = {k: v for k, v in valid_manifest.items() if k != key}
    with pytest.raises(ManifestRejected, match=rf"'{key}'"):
        load_manifest_bytes(json.dumps(broken))


def test_unknown_top_level_key_is_an_error_not_an_ignored_line(
    valid_manifest: dict[str, Any],
) -> None:
    broken = {**valid_manifest, "capabilites": []}
    with pytest.raises(ManifestRejected, match=r"unknown key.*capabilites"):
        load_manifest_bytes(json.dumps(broken))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("family", "plugin"),
        ("capabilities", ["workspace.read", "teleport"]),
        ("effects", ["kind-of-fine"]),
        ("contract", ">=2.0.0,<3.0.0"),
        ("contract", ">=1.0.0"),
        ("contract", ">=1.0.0,<3.0.0"),
        ("contract", "1.0.0"),
        ("version", "1.0"),
        ("id", "publisher.name.extra"),
        ("id", "UPPER.name"),
    ],
)
def test_closed_vocabularies_and_shapes_reject(
    field: str, value: object, valid_manifest: dict[str, Any]
) -> None:
    broken = {**valid_manifest, field: value}
    with pytest.raises(ManifestRejected):
        load_manifest_bytes(json.dumps(broken))


def test_in_major_contract_cap_is_accepted(valid_manifest: dict[str, Any]) -> None:
    """`>=1.0.0,<1.9.0` pins one major with an in-major ceiling: valid."""
    manifest = load_manifest_bytes(json.dumps({**valid_manifest, "contract": ">=1.0.0,<1.9.0"}))
    assert manifest.contract_major == 1


def test_eq_only_range_pins_one_major(valid_manifest: dict[str, Any]) -> None:
    manifest = load_manifest_bytes(json.dumps({**valid_manifest, "contract": "==1.2.0"}))
    assert manifest.contract_major == 1


def test_id_must_be_namespaced_under_its_publisher(valid_manifest: dict[str, Any]) -> None:
    broken = {**valid_manifest, "id": "other.widget", "publisher": "acme"}
    with pytest.raises(ManifestRejected, match=r"namespaced"):
        load_manifest_bytes(json.dumps(broken))


def test_entrypoint_is_lexical_only_and_never_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest whose entrypoint names a module that would detonate on
    import still validates: parsing never resolves the module."""
    bomb_dir = tmp_path / "bomb" / "src" / "acme_widget"
    bomb_dir.mkdir(parents=True)
    (bomb_dir / "__init__.py").write_text("", encoding="utf-8")
    (bomb_dir / "plugin.py").write_text("raise SystemExit('extension code ran')", encoding="utf-8")
    bomb = tmp_path / "bomb"
    (bomb / "extension.json").write_text(
        json.dumps(
            {
                "id": "acme.widget",
                "publisher": "acme",
                "version": "1.0.0",
                "title": "t",
                "description": "d",
                "contract": ">=1.0.0,<2.0.0",
                "family": "tool",
                "capabilities": [],
                "effects": ["read-only"],
                "data": {"scopes": []},
                "entrypoint": {"module": "acme_widget.plugin", "object": "PLUGIN"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(bomb / "src"))
    manifest = load_manifest_file(bomb / "extension.json")
    assert manifest.entrypoint.module == "acme_widget.plugin"


def test_private_entrypoint_segment_rejected(valid_manifest: dict[str, Any]) -> None:
    broken = {
        **valid_manifest,
        "entrypoint": {"module": "acme_widget._secret", "object": "PLUGIN"},
    }
    with pytest.raises(ManifestRejected, match=r"underscore-private"):
        load_manifest_bytes(json.dumps(broken))


def test_authority_detail_without_its_capability_rejected(
    valid_manifest: dict[str, Any],
) -> None:
    broken = {**valid_manifest, "capabilities": [], "network": {"allow": ["api.example.com"]}}
    with pytest.raises(ManifestRejected, match=r"network\.outbound"):
        load_manifest_bytes(json.dumps(broken))


def test_secrets_without_capability_rejected(valid_manifest: dict[str, Any]) -> None:
    broken = {**valid_manifest, "secrets": [{"name": "ACME_TOKEN"}]}
    with pytest.raises(ManifestRejected, match=r"secrets\.read"):
        load_manifest_bytes(json.dumps(broken))


def test_full_authority_declaration_validates(valid_manifest: dict[str, Any]) -> None:
    rich = {
        **valid_manifest,
        "capabilities": [
            "workspace.read",
            "network.outbound",
            "filesystem.read",
            "secrets.read",
        ],
        "data": {"scopes": ["workspace", "run"]},
        "network": {"allow": ["*.example.com", "api.acme.dev"], "allowed_ports": [443, 8443]},
        "filesystem": {"paths": ["/workspace/artifacts"], "mode": "read"},
        "secrets": [{"name": "ACME_TOKEN"}],
        "dependencies": [{"id": "other.lib", "range": ">=1.0.0,<2.0.0"}],
        "optional_features": ["streaming"],
    }
    manifest = load_manifest_bytes(json.dumps(rich))
    assert manifest.network_ports == (443, 8443)
    assert manifest.secrets == ("ACME_TOKEN",)
    assert manifest.dependencies[0].id == "other.lib"
    assert manifest.optional_features == ("streaming",)


def test_unknown_block_key_rejected(valid_manifest: dict[str, Any]) -> None:
    broken = {**valid_manifest, "network": {"allow": [], "proxy": "yes"}}
    with pytest.raises(ManifestRejected, match=r"unknown key.*proxy"):
        load_manifest_bytes(json.dumps(broken))


def test_filesystem_paths_must_be_absolute(valid_manifest: dict[str, Any]) -> None:
    broken = {
        **valid_manifest,
        "capabilities": ["filesystem.read"],
        "filesystem": {"paths": ["relative/path"], "mode": "read"},
    }
    with pytest.raises(ManifestRejected, match=r"absolute"):
        load_manifest_bytes(json.dumps(broken))


def test_unreadable_manifest_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(ManifestRejected, match=r"unreadable"):
        load_manifest_file(tmp_path / "absent" / "extension.json")


# ---------------------------------------------------------------------------
# Authority-block shape rejections: every parse branch must fail loudly, so a
# malformed declaration is a named rejection, never a silently empty grant.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("capabilities", "workspace.read", "list of strings"),
        ("capabilities", ["workspace.read", 7], "list of strings"),
        ("capabilities", ["workspace.read", "workspace.read"], "repeats a value"),
        ("data", "workspace", "must be an object"),
        ("network", 5, "must be an object"),
        ("network", {"allow": ["not a host!"]}, "not host patterns"),
        ("filesystem", [], "must be an object"),
        ("filesystem", {"paths": ["/out"], "mode": "rw"}, "must be one of"),
        ("secrets", "ACME_TOKEN", "must be a list"),
        ("secrets", [{"name": "A"}, {}], "exactly 'name'"),
        ("secrets", [{"name": "bad-name"}], "env-style name"),
        ("secrets", [{"name": "A"}, {"name": "A"}], "repeat a reference name"),
        ("dependencies", "other.lib", "must be a list"),
        ("dependencies", ["other.lib"], "must be an object"),
        ("dependencies", [{"id": "lib", "range": ">=1.0.0"}], "publisher"),
        (
            "network",
            {"allow": ["api.example.com"], "allowed_ports": [70000]},
            "ports 1..65535",
        ),
        ("entrypoint", "PLUGIN", "must be an object"),
        (
            "entrypoint",
            {"module": "acme_widget.plugin", "object": "PLUGIN", "extra": 1},
            "unknown key",
        ),
        ("entrypoint", {"module": "acme_widget./plugin", "object": "PLUGIN"}, "dotted import path"),
        ("entrypoint", {"module": 7, "object": "PLUGIN"}, "non-empty string"),
        ("entrypoint", {"module": "acme_widget.plugin", "object": "not-an-id"}, "identifier"),
    ],
)
def test_authority_block_shape_rejections(
    field: str,
    value: object,
    fragment: str,
    valid_manifest: dict[str, Any],
) -> None:
    broken = {**valid_manifest, field: value}
    with pytest.raises(ManifestRejected, match=fragment):
        load_manifest_bytes(json.dumps(broken))


def test_contract_range_mixing_a_pin_with_comparisons_rejected(
    valid_manifest: dict[str, Any],
) -> None:
    """The one-major rule: pin with `==` alone, or comparisons alone — never
    both in one range, which would pin nothing."""
    broken = {**valid_manifest, "contract": "==1.0.0,>=1.0.0"}
    with pytest.raises(ManifestRejected, match=r"pin exactly one major one way"):
        load_manifest_bytes(json.dumps(broken))


def test_omitted_data_block_defaults_to_no_scopes(valid_manifest: dict[str, Any]) -> None:
    """The public SDK contract treats the whole `data` block as optional
    (`DataAuthority.scopes` defaults empty); the harness's stdlib parser must
    agree — an omitted block is an empty authority, not a rejection."""
    lean = {k: v for k, v in valid_manifest.items() if k != "data"}
    manifest = load_manifest_bytes(json.dumps(lean))
    assert manifest.data_scopes == ()


def test_network_allow_without_ports_declares_hosts_only(
    valid_manifest: dict[str, Any],
) -> None:
    manifest = load_manifest_bytes(
        json.dumps(
            {
                **valid_manifest,
                "capabilities": ["network.outbound"],
                "network": {"allow": ["api.example.com"]},
            }
        )
    )
    assert manifest.network_allow == ("api.example.com",)
    assert manifest.network_ports == ()


def test_network_allow_with_ports_declares_both(valid_manifest: dict[str, Any]) -> None:
    manifest = load_manifest_bytes(
        json.dumps(
            {
                **valid_manifest,
                "capabilities": ["network.outbound"],
                "network": {"allow": ["api.example.com"], "allowed_ports": [443, 8443]},
            }
        )
    )
    assert manifest.network_ports == (443, 8443)


def test_filesystem_paths_without_a_filesystem_capability_rejected(
    valid_manifest: dict[str, Any],
) -> None:
    """Detail without its capability is an inconsistent declaration — the
    same cross-check the network and secrets axes enforce."""
    broken = {
        **valid_manifest,
        "capabilities": [],
        "filesystem": {"paths": ["/exports"], "mode": "read"},
    }
    with pytest.raises(ManifestRejected, match=r"filesystem\.read/write capability"):
        load_manifest_bytes(json.dumps(broken))

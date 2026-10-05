"""Manifest parse/reject behavior — acceptance criteria 1 and 2 of #949.

AC-1: "manifest can be parsed and rejected before importing extension code".
AC-2: "malformed/unknown authority declarations fail explicitly".

Each test names the criterion it pins. The before-import property is proven
structurally here (the entrypoint is plain string data) and dynamically in
test_out_of_tree_validation.py, where the extension module is an import bomb
that fails the test if anything imports it.
"""

from __future__ import annotations

import json

import pytest

from maistro_ext_sdk import ExtensionManifestError, manifest_from_dict, manifest_from_json
from maistro_ext_sdk.contract import EXTENSION_CONTRACT_VERSION, parse_contract_version
from maistro_ext_sdk.manifest import AuthorityError
from maistro_ext_sdk.validation import public_json_schema


class TestParseBeforeImport:
    @pytest.mark.contract("boundary")
    def test_valid_manifest_parses(self, manifest_dict: dict) -> None:
        manifest = manifest_from_dict(manifest_dict)
        assert manifest.id == "acme.weather"
        assert manifest.publisher == "acme"
        assert manifest.version == "1.0.0"
        assert manifest.family == "tool"

    @pytest.mark.contract("boundary")
    def test_entrypoint_is_inspectable_data_not_a_module(self, manifest_dict: dict) -> None:
        """AC-1 structural half: the entrypoint survives parsing as plain
        strings — nothing about it is imported, resolved, or executed."""
        manifest = manifest_from_dict(manifest_dict)
        assert manifest.entrypoint.module == "acme_weather.plugin"
        assert manifest.entrypoint.object == "PLUGIN"
        assert isinstance(manifest.entrypoint.module, str)

    @pytest.mark.contract("boundary")
    def test_malformed_json_is_rejected_as_manifest_error(self) -> None:
        with pytest.raises(ExtensionManifestError, match="not valid JSON"):
            manifest_from_json("{not json")

    @pytest.mark.contract("boundary")
    def test_non_object_json_is_rejected(self) -> None:
        with pytest.raises(ExtensionManifestError, match="JSON object"):
            manifest_from_json(json.dumps(["not", "a", "manifest"]))

    @pytest.mark.contract("boundary")
    def test_rejection_does_not_require_the_entrypoint_to_exist(self, manifest_dict: dict) -> None:
        """The manifest names a module that does not exist anywhere on this
        machine — parsing and authority validation still run to completion.
        (Existence is a separate, later check in validate_extension_dir.)"""
        manifest_dict["entrypoint"] = {"module": "does_not_exist.anywhere", "object": "X"}
        manifest = manifest_from_dict(manifest_dict)
        assert manifest.entrypoint.module == "does_not_exist.anywhere"


class TestMalformedAndUnknownAuthority:
    """AC-2: unknown and malformed authority declarations fail *explicitly* —
    each assertion checks the message names the offending token."""

    def test_unknown_top_level_field_fails_naming_it(self, manifest_dict: dict) -> None:
        manifest_dict["root_access"] = True
        with pytest.raises(ExtensionManifestError, match=r"unknown manifest field.*root_access"):
            manifest_from_dict(manifest_dict)

    def test_unknown_family_fails_naming_known_families(self, manifest_dict: dict) -> None:
        manifest_dict["family"] = "kernel-module"
        with pytest.raises(ExtensionManifestError, match=r"kernel-module"):
            manifest_from_dict(manifest_dict)

    def test_unknown_capability_fails_naming_it(self, manifest_dict: dict) -> None:
        manifest_dict["capabilities"] = ["network.outbound", "host.kernel"]
        with pytest.raises(ExtensionManifestError, match=r"host\.kernel"):
            manifest_from_dict(manifest_dict)

    def test_unknown_effect_fails(self, manifest_dict: dict) -> None:
        manifest_dict["effects"] = ["deletes-production"]
        with pytest.raises(ExtensionManifestError, match="deletes-production"):
            manifest_from_dict(manifest_dict)

    def test_unknown_data_scope_fails_naming_known_scopes(self, manifest_dict: dict) -> None:
        manifest_dict["data"] = {"scopes": ["everything"]}
        with pytest.raises(ExtensionManifestError, match=r"unknown data scope.*everything"):
            manifest_from_dict(manifest_dict)

    def test_malformed_network_host_fails(self, manifest_dict: dict) -> None:
        manifest_dict["network"] = {"allow": ["not a host!!"]}
        with pytest.raises(ExtensionManifestError, match="not a host!!"):
            manifest_from_dict(manifest_dict)

    def test_out_of_range_network_port_fails(self, manifest_dict: dict) -> None:
        manifest_dict["network"] = {"allow": ["api.example.com"], "allowed_ports": [70000]}
        with pytest.raises(ExtensionManifestError, match="70000"):
            manifest_from_dict(manifest_dict)

    def test_relative_filesystem_path_fails(self, manifest_dict: dict) -> None:
        manifest_dict["capabilities"] = ["filesystem.read"]
        manifest_dict["filesystem"] = {"paths": ["relative/path"], "mode": "read"}
        with pytest.raises(ExtensionManifestError, match=r"relative/path.*absolute"):
            manifest_from_dict(manifest_dict)

    def test_malformed_secret_name_fails(self, manifest_dict: dict) -> None:
        manifest_dict["capabilities"] = ["secrets.read"]
        manifest_dict["secrets"] = [{"name": "little-piggy"}]
        with pytest.raises(ExtensionManifestError, match=r"little-piggy"):
            manifest_from_dict(manifest_dict)

    def test_malformed_contract_range_fails(self, manifest_dict: dict) -> None:
        manifest_dict["contract"] = ">=1.0 or so"
        with pytest.raises(ExtensionManifestError, match="contract field"):
            manifest_from_dict(manifest_dict)

    def test_malformed_extension_version_fails(self, manifest_dict: dict) -> None:
        manifest_dict["version"] = "1.0"
        with pytest.raises(ExtensionManifestError, match=r"version"):
            manifest_from_dict(manifest_dict)

    def test_id_not_namespaced_under_publisher_fails(self, manifest_dict: dict) -> None:
        manifest_dict["id"] = "otherinc.weather"
        with pytest.raises(ExtensionManifestError, match=r"namespaced under its publisher"):
            manifest_from_dict(manifest_dict)

    def test_malformed_entrypoint_module_fails(self, manifest_dict: dict) -> None:
        manifest_dict["entrypoint"] = {"module": "../etc/passwd", "object": "X"}
        with pytest.raises(ExtensionManifestError, match="dotted import path"):
            manifest_from_dict(manifest_dict)

    def test_malformed_entrypoint_object_fails(self, manifest_dict: dict) -> None:
        manifest_dict["entrypoint"] = {"module": "acme_weather.plugin", "object": "not-an-id"}
        with pytest.raises(ExtensionManifestError, match="identifier"):
            manifest_from_dict(manifest_dict)

    def test_self_dependency_fails(self, manifest_dict: dict) -> None:
        manifest_dict["dependencies"] = [{"id": "acme.weather", "range": ">=1.0.0"}]
        with pytest.raises(ExtensionManifestError, match=r"depend on itself"):
            manifest_from_dict(manifest_dict)

    def test_duplicate_dependency_fails(self, manifest_dict: dict) -> None:
        dep = {"id": "acme.util", "range": ">=1.0.0,<2.0.0"}
        manifest_dict["dependencies"] = [dep, dict(dep)]
        with pytest.raises(ExtensionManifestError, match=r"duplicate dependency"):
            manifest_from_dict(manifest_dict)

    def test_malformed_dependency_id_fails(self, manifest_dict: dict) -> None:
        manifest_dict["dependencies"] = [{"id": "not namespaced", "range": ">=1.0.0"}]
        with pytest.raises(ExtensionManifestError, match=r"not namespaced"):
            manifest_from_dict(manifest_dict)

    def test_malformed_dependency_range_fails(self, manifest_dict: dict) -> None:
        manifest_dict["dependencies"] = [{"id": "acme.util", "range": "latest"}]
        with pytest.raises(ExtensionManifestError, match=r"acme.util"):
            manifest_from_dict(manifest_dict)

    def test_malformed_id_shape_fails(self, manifest_dict: dict) -> None:
        manifest_dict["id"] = "Acme Weather"
        with pytest.raises(ExtensionManifestError, match=r"Acme Weather"):
            manifest_from_dict(manifest_dict)

    def test_identity_rules_live_in_the_explicit_pipeline(self, manifest_dict: dict) -> None:
        """Models are shape-only; the identity rules run in validate_manifest,
        which the parse surface always applies. A host hand-building a model
        gets the identical contract by calling the same function."""
        from maistro_ext_sdk import ExtensionManifest, validate_manifest

        manifest_dict["id"] = "Acme Weather"
        shaped = ExtensionManifest.model_validate(manifest_dict)
        with pytest.raises(ExtensionManifestError, match=r"Acme Weather"):
            validate_manifest(shaped)

        manifest_dict["id"] = "otherinc.weather"
        shaped = ExtensionManifest.model_validate(manifest_dict)
        with pytest.raises(ExtensionManifestError, match=r"namespaced under"):
            validate_manifest(shaped)

        manifest_dict["id"] = "acme.weather"
        manifest_dict["version"] = "1.0"
        shaped = ExtensionManifest.model_validate(manifest_dict)
        with pytest.raises(ExtensionManifestError, match=r"version"):
            validate_manifest(shaped)

        # And a valid hand-built model round-trips through the same pipeline.
        manifest_dict["version"] = "1.0.0"
        validated = validate_manifest(ExtensionManifest.model_validate(manifest_dict))
        assert validated.id == "acme.weather"

    def test_identity_model_shape_is_shared_with_the_manifest(self) -> None:
        """The exported ExtensionIdentity nested model carries the same shape
        constraints (title length) for hosts that want identity alone; the
        identity *rules* live in validate_manifest, not in model hooks."""
        import pydantic

        from maistro_ext_sdk import ExtensionIdentity

        ident = ExtensionIdentity(id="acme.weather", publisher="acme", version="1.2.3", title="t")
        assert ident.version == "1.2.3"
        with pytest.raises(pydantic.ValidationError):
            ExtensionIdentity(id="acme.weather", publisher="acme", version="1.2.3", title="")


class TestLeastAuthorityBothWays:
    """Authority needs scope, and scope needs authority — both directions."""

    def test_capability_without_scope_fails(self, manifest_dict: dict) -> None:
        manifest_dict["capabilities"] = ["network.outbound"]
        manifest_dict.pop("network")
        with pytest.raises(ExtensionManifestError, match=r"network\.allow"):
            manifest_from_dict(manifest_dict)

    def test_scope_without_capability_fails(self, manifest_dict: dict) -> None:
        """The sneak direction: name everything you need except the capability
        itself and hope the host only checks blocks. It must not."""
        manifest_dict["capabilities"] = []
        with pytest.raises(ExtensionManifestError, match=r"without the.*network.outbound"):
            manifest_from_dict(manifest_dict)

    def test_filesystem_scope_without_capability_fails(self, manifest_dict: dict) -> None:
        manifest_dict["capabilities"] = []
        manifest_dict.pop("network")
        manifest_dict["filesystem"] = {"paths": ["/tmp/scratch"], "mode": "read"}
        with pytest.raises(ExtensionManifestError, match=r"filesystem.read.*filesystem.write"):
            manifest_from_dict(manifest_dict)

    def test_secrets_without_capability_fails(self, manifest_dict: dict) -> None:
        manifest_dict["secrets"] = [{"name": "ACME_KEY"}]
        with pytest.raises(ExtensionManifestError, match="ACME_KEY"):
            manifest_from_dict(manifest_dict)

    def test_filesystem_capability_without_scope_fails(self, manifest_dict: dict) -> None:
        manifest_dict["capabilities"] = ["filesystem.read"]
        with pytest.raises(ExtensionManifestError, match=r"filesystem.paths"):
            manifest_from_dict(manifest_dict)

    def test_secrets_capability_without_names_fails(self, manifest_dict: dict) -> None:
        manifest_dict["capabilities"] = ["secrets.read"]
        with pytest.raises(ExtensionManifestError, match=r"no secrets named"):
            manifest_from_dict(manifest_dict)

    def test_full_authority_block_pairing_passes(self, manifest_dict: dict) -> None:
        manifest_dict["capabilities"] = [
            "network.outbound",
            "filesystem.read",
            "secrets.read",
        ]
        manifest_dict["network"] = {"allow": ["api.example.com"]}
        manifest_dict["filesystem"] = {"paths": ["/var/tmp/ext"], "mode": "read"}
        manifest_dict["secrets"] = [{"name": "ACME_KEY"}]
        manifest = manifest_from_dict(manifest_dict)
        assert set(manifest.capabilities) == {"network.outbound", "filesystem.read", "secrets.read"}


class TestPublicJsonSchema:
    @pytest.mark.contract("boundary")
    def test_schema_is_machine_validatable_json_schema(self) -> None:
        schema = public_json_schema()
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        # The strictness is visible to non-Python validators: no additional keys.
        assert schema["additionalProperties"] is False

    @pytest.mark.contract("boundary")
    def test_schema_rejects_what_the_model_rejects(self, manifest_dict: dict) -> None:
        """The public schema and the Pydantic model agree on the required
        surface — the schema names every field the model demands."""
        schema = public_json_schema()
        required = set(schema["required"])
        manifest = manifest_from_dict(manifest_dict)
        # Every required field is present in a manifest that validates, and
        # the entrypoint object shape matches what validation returns.
        assert {"id", "publisher", "version", "contract", "family", "entrypoint"} <= required
        assert manifest.entrypoint.module == manifest_dict["entrypoint"]["module"]

    def test_schema_version_tracks_contract_major(self) -> None:
        schema = public_json_schema()
        major = parse_contract_version(EXTENSION_CONTRACT_VERSION).major
        assert schema["$id"].endswith(f"extension-manifest-v{major}.json")


class TestErrorTypeContract:
    @pytest.mark.contract("boundary")
    def test_one_public_error_type_for_everything(self, manifest_dict: dict) -> None:
        """Hosts catch ExtensionManifestError; they never see pydantic's
        ValidationError escape, so the SDK's internals can change freely."""
        with pytest.raises(ExtensionManifestError):
            manifest_from_dict(manifest_dict | {"family": "kernel-module"})
        with pytest.raises(ExtensionManifestError):
            manifest_from_json("nope")

    def test_error_is_a_value_error(self) -> None:
        assert issubclass(ExtensionManifestError, ValueError)
        assert issubclass(AuthorityError, ExtensionManifestError)

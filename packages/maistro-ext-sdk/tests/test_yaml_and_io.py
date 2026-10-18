"""YAML manifest support (the ``[yaml]`` extra) and I/O failure paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro_ext_sdk import ExtensionManifestError, manifest_from_dict, manifest_from_yaml
from maistro_ext_sdk.validation import ValidatedExtension, validate_extension_dir

VALID_YAML = """\
id: acme.weather
publisher: acme
version: 1.0.0
title: ACME Weather tool
contract: ">=1.0.0,<2.0.0"
family: tool
capabilities:
  - network.outbound
network:
  allow: [api.weather.example]
entrypoint:
  module: acme_weather.plugin
  object: PLUGIN
"""


class TestYamlManifests:
    def test_valid_yaml_manifest_parses(self) -> None:
        manifest = manifest_from_yaml(VALID_YAML)
        assert manifest.id == "acme.weather"
        assert manifest.capabilities == ("network.outbound",)

    def test_yaml_and_json_paths_agree(self) -> None:
        """Both front doors validate the same document to the same model."""
        import json

        import yaml

        from maistro_ext_sdk import manifest_from_json

        data = yaml.safe_load(VALID_YAML)
        from_yaml = manifest_from_yaml(VALID_YAML)
        from_json = manifest_from_json(json.dumps(data))
        assert from_yaml.model_dump() == from_json.model_dump()

    def test_malformed_yaml_is_rejected_explicitly(self) -> None:
        with pytest.raises(ExtensionManifestError, match="not valid YAML"):
            manifest_from_yaml("id: [unclosed")

    def test_non_mapping_yaml_is_rejected(self) -> None:
        with pytest.raises(ExtensionManifestError, match="mapping"):
            manifest_from_yaml("- just\n- a\n- list\n")


class TestIoFailurePaths:
    def test_unreadable_manifest_is_a_manifest_error(
        self, example_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unreadable manifest file is a rejection, not a traceback from
        the filesystem — the host renders one error type to the author."""
        import shutil

        dest = tmp_path / "ext"
        shutil.copytree(example_dir, dest)

        real_read_text = Path.read_text

        def refusing_read_text(self: Path, *args: object, **kwargs: object) -> str:
            if self.name == "extension.json":
                raise PermissionError(13, "Permission denied")
            return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "read_text", refusing_read_text)
        with pytest.raises(ExtensionManifestError, match=r"cannot read extension\.json"):
            validate_extension_dir(dest)

    def test_validated_extension_entrypoint_target_format(self, example_dir: Path) -> None:
        ext = validate_extension_dir(example_dir)
        assert isinstance(ext, ValidatedExtension)
        assert ext.entrypoint_target() == "acme_weather.plugin:PLUGIN"
        # Round-trip: what a host would import, spelled the conventional way.
        module, _, obj = ext.entrypoint_target().partition(":")
        assert module == ext.manifest.entrypoint.module
        assert obj == ext.manifest.entrypoint.object


class TestValidationDoesNotMutateInput:
    def test_manifest_from_dict_copies_independent_defaults(self, manifest_dict: dict) -> None:
        """The default_factory models are shared across manifests: mutating
        one parsed manifest's authority must not leak into another's."""
        first = manifest_from_dict(manifest_dict)
        second = manifest_from_dict(manifest_dict)
        assert first.data is not second.data
        assert first.network is not second.network

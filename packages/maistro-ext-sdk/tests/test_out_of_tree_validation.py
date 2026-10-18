"""Out-of-tree validation — acceptance criterion 3 of #949.

"a minimal out-of-tree extension package validates against the SDK"

The shipped example lives under examples/, outside the importable
maistro_ext_sdk tree; each test copies it to a tmp_path — a genuinely
out-of-tree location — and validates it there. The import-bomb tests prove
the dynamic half of AC-1: the extension's module raises the moment Python
imports it, so any hidden import during validation fails the test loudly.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from maistro_ext_sdk import ExtensionManifestError, validate_extension_dir


def _copy_example(example_dir: Path, tmp_path: Path) -> Path:
    """Copy the example into an unrelated directory (out of tree)."""
    dest = tmp_path / "my-extension"
    shutil.copytree(example_dir, dest)
    return dest


class TestMinimalExampleValidates:
    @pytest.mark.contract("boundary")
    def test_example_validates_from_a_copied_directory(
        self, example_dir: Path, tmp_path: Path
    ) -> None:
        dest = _copy_example(example_dir, tmp_path)
        ext = validate_extension_dir(dest)
        assert ext.manifest.id == "acme.weather"
        assert ext.entrypoint_target() == "acme_weather.plugin:PLUGIN"
        assert ext.entrypoint_file == dest / "acme_weather" / "plugin.py"

    @pytest.mark.contract("boundary")
    def test_example_is_out_of_the_sdk_import_tree(self, example_dir: Path) -> None:
        """The example is data shipped beside the SDK, not part of it: nothing
        under examples/ is importable as maistro_ext_sdk.*."""
        import maistro_ext_sdk

        sdk_pkg_dir = Path(maistro_ext_sdk.__file__).resolve().parent
        assert example_dir.resolve().parent.parent != sdk_pkg_dir
        assert not str(example_dir).startswith(str(sdk_pkg_dir))


class TestNoImportDuringValidation:
    """The dynamic half of AC-1, with a tripwire: a module that raises on
    import. If validation imported extension code, these tests fail."""

    @pytest.mark.contract("boundary")
    def test_validating_a_bomb_extension_succeeds_without_detonating(
        self, example_dir: Path, tmp_path: Path
    ) -> None:
        dest = _copy_example(example_dir, tmp_path)
        plugin = dest / "acme_weather" / "plugin.py"
        plugin.write_text(
            'raise RuntimeError("extension code was imported during validation")\n',
            encoding="utf-8",
        )
        # Whole statement must not raise: the bomb stays unexploded.
        ext = validate_extension_dir(dest)
        assert ext.entrypoint_file == plugin

    @pytest.mark.contract("boundary")
    def test_validation_runs_in_a_fresh_process_where_the_bomb_cannot_have_imported_earlier(
        self, example_dir: Path, tmp_path: Path
    ) -> None:
        """The in-process tripwire could in principle be defused by some
        earlier import of the module under a different path spelling. This
        runs validation in a pristine interpreter with the bomb on disk: the
        only way it exits 0 is that validation never imported it."""
        dest = _copy_example(example_dir, tmp_path)
        (dest / "acme_weather" / "plugin.py").write_text(
            'raise RuntimeError("imported")\n', encoding="utf-8"
        )
        code = (
            "import sys;"
            "sys.path.insert(0, sys.argv[1]);"
            "from maistro_ext_sdk import validate_extension_dir;"
            "validate_extension_dir(sys.argv[2]);"
            "print('ok-no-import')"
        )
        repo_src = Path(__file__).resolve().parents[1] / "src"
        proc = subprocess.run(
            [sys.executable, "-c", code, str(repo_src), str(dest)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        assert "ok-no-import" in proc.stdout
        assert "RuntimeError" not in proc.stdout + proc.stderr


class TestRejectionPaths:
    @pytest.mark.contract("boundary")
    def test_missing_directory_fails(self, tmp_path: Path) -> None:
        with pytest.raises(ExtensionManifestError, match="does not exist"):
            validate_extension_dir(tmp_path / "not-there")

    @pytest.mark.contract("boundary")
    def test_missing_manifest_fails(self, tmp_path: Path) -> None:
        with pytest.raises(ExtensionManifestError, match=r"no extension\.json"):
            validate_extension_dir(tmp_path)

    @pytest.mark.contract("boundary")
    def test_malformed_manifest_in_directory_is_rejected_before_any_code_lookups(
        self, example_dir: Path, tmp_path: Path
    ) -> None:
        dest = _copy_example(example_dir, tmp_path)
        manifest = json.loads((dest / "extension.json").read_text(encoding="utf-8"))
        manifest["capabilities"] = ["host.kernel"]
        (dest / "extension.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ExtensionManifestError, match=r"host\.kernel"):
            validate_extension_dir(dest)

    @pytest.mark.contract("boundary")
    def test_entrypoint_file_missing_fails_with_manifest_error(
        self, example_dir: Path, tmp_path: Path
    ) -> None:
        dest = _copy_example(example_dir, tmp_path)
        (dest / "acme_weather" / "plugin.py").unlink()
        with pytest.raises(ExtensionManifestError, match=r"entrypoint module"):
            validate_extension_dir(dest)

    @pytest.mark.contract("boundary")
    def test_contract_mismatch_fails_explicitly(self, example_dir: Path, tmp_path: Path) -> None:
        dest = _copy_example(example_dir, tmp_path)
        manifest = json.loads((dest / "extension.json").read_text(encoding="utf-8"))
        manifest["contract"] = ">=2.0.0,<3.0.0"
        (dest / "extension.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ExtensionManifestError, match=r"does not include the contract"):
            validate_extension_dir(dest)

    @pytest.mark.contract("boundary")
    def test_entrypoint_resolves_as_package_init_too(
        self, example_dir: Path, tmp_path: Path
    ) -> None:
        """Both legal module shapes work: flat file and package __init__."""
        dest = _copy_example(example_dir, tmp_path)
        manifest = json.loads((dest / "extension.json").read_text(encoding="utf-8"))
        manifest["entrypoint"] = {"module": "acme_weather", "object": "PLUGIN"}
        (dest / "extension.json").write_text(json.dumps(manifest), encoding="utf-8")
        (dest / "acme_weather" / "__init__.py").write_text("PLUGIN = None\n", encoding="utf-8")
        ext = validate_extension_dir(dest)
        assert ext.entrypoint_file == dest / "acme_weather" / "__init__.py"

    @pytest.mark.contract("boundary")
    def test_package_directory_shadows_same_named_module_file(
        self, example_dir: Path, tmp_path: Path
    ) -> None:
        """importlib checks ``<module>/__init__.py`` before ``<module>.py``, so
        when both exist the package wins and entrypoint_file must point at the
        code the host would actually execute."""
        dest = _copy_example(example_dir, tmp_path)
        (dest / "acme_weather" / "plugin" / "__init__.py").parent.mkdir()
        (dest / "acme_weather" / "plugin" / "__init__.py").write_text(
            "PLUGIN = 'package'\n", encoding="utf-8"
        )
        ext = validate_extension_dir(dest)
        assert ext.entrypoint_file == dest / "acme_weather" / "plugin" / "__init__.py"

    @pytest.mark.contract("boundary")
    def test_parent_module_shadows_deeper_dotted_path(
        self, example_dir: Path, tmp_path: Path
    ) -> None:
        """If a parent segment resolves to a plain module (``plugin.py``
        beats a namespace ``plugin/``), the deeper path is unimportable and
        must not validate against a file the host could never load."""
        dest = _copy_example(example_dir, tmp_path)
        helper = dest / "acme_weather" / "plugin" / "helper.py"
        helper.parent.mkdir()
        helper.write_text("HELPER = None\n", encoding="utf-8")
        manifest = json.loads((dest / "extension.json").read_text(encoding="utf-8"))
        manifest["entrypoint"] = {"module": "acme_weather.plugin.helper", "object": "HELPER"}
        (dest / "extension.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ExtensionManifestError, match=r"entrypoint module"):
            validate_extension_dir(dest)

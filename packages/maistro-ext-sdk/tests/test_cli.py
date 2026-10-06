"""The SDK's console validator — the author-facing face of M9-A1.

`maistro-ext-sdk validate <dir>` must reject a manifest without importing the
extension, from any shell, with a non-zero exit and the offending token on
stderr. These tests drive `main()` directly (exit codes, output) and the
console-script wiring through the built metadata when available.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from maistro_ext_sdk.cli import build_parser, main


@pytest.fixture
def ext_copy(tmp_path: Path, example_dir: Path) -> Path:
    dest = tmp_path / "ext"
    shutil.copytree(example_dir, dest)
    return dest


class TestValidateCommand:
    def test_valid_extension_prints_summary_and_exits_zero(
        self, ext_copy: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["validate", str(ext_copy)]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["id"] == "acme.weather"
        assert payload["entrypoint"] == "acme_weather.plugin:PLUGIN"

    def test_unknown_authority_exits_nonzero_and_names_the_token(
        self, ext_copy: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        manifest = json.loads((ext_copy / "extension.json").read_text(encoding="utf-8"))
        manifest["capabilities"] = ["host.kernel"]
        (ext_copy / "extension.json").write_text(json.dumps(manifest), encoding="utf-8")
        assert main(["validate", str(ext_copy)]) == 1
        err = capsys.readouterr().err
        assert "REJECTED" in err
        assert "host.kernel" in err

    def test_rejection_does_not_import_the_extension(
        self, ext_copy: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (ext_copy / "acme_weather" / "plugin.py").write_text(
            'raise RuntimeError("imported during CLI validation")\n', encoding="utf-8"
        )
        assert main(["validate", str(ext_copy)]) == 0
        assert "imported" not in capsys.readouterr().out

    def test_missing_directory_exits_nonzero(self, tmp_path: Path) -> None:
        assert main(["validate", str(tmp_path / "nope")]) == 1


class TestSchemaAndVersionCommands:
    def test_schema_command_prints_the_public_schema(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["schema"]) == 0
        schema = json.loads(capsys.readouterr().out)
        assert schema["additionalProperties"] is False
        assert schema["$schema"].endswith("2020-12/schema")

    def test_schema_command_writes_to_a_file(self, tmp_path: Path) -> None:
        out = tmp_path / "schema.json"
        assert main(["schema", "--out", str(out)]) == 0
        assert json.loads(out.read_text(encoding="utf-8"))["type"] == "object"

    def test_contract_version_flag_is_queryable(self, capsys: pytest.CaptureFixture[str]) -> None:
        from maistro_ext_sdk import contract_version

        assert main(["--contract-version"]) == 0
        assert capsys.readouterr().out.strip() == contract_version()


class TestConsoleScriptWiring:
    def test_console_script_is_declared(self) -> None:
        import tomllib
        from pathlib import Path as P

        data = tomllib.loads(
            (P(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        )
        assert data["project"]["scripts"] == {"maistro-ext-sdk": "maistro_ext_sdk.cli:main"}

    def test_parser_rejects_unknown_subcommand(self, capsys: pytest.CaptureFixture[str]) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["frobnicate"])

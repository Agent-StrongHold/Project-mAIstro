"""`maistro extension new` and the scaffold engine behind it (M9-H1, #973).

Three layers, each naming the acceptance criterion it pins:

- **Schema validation** — the generated manifest must "pass public schema
  validation", so the validator itself is tested against the documented
  contract: the real reference extension's manifest (the one artifact every
  reader can check by hand), the happy minimal shape, and a rejection matrix
  over every closed vocabulary, identity pattern, and strictness rule.
- **Rendering/structure** — family templates must be "structurally distinct
  where required" and "use only public SDK imports"; rendered output is
  parsed (AST) and its manifest re-validated per family.
- **CLI + isolation** — the scaffolded project must "build/tests in a clean
  directory outside the MAIstro repo". The always-on layer covers tree shape,
  refusals, and the CLI surface with no subprocesses; the env-gated
  end-to-end test executes the whole chain (build the wheel, install it into
  a fresh venv with pytest, run the generated suite, prove `maistro` is
  unimportable there), mirroring the isolation fixture's default-skip
  precedent (`MAISTRO_TEST_EXTENSION_ISOLATION`) so the ordinary suite stays
  offline. Run it with `MAISTRO_TEST_EXTENSION_SCAFFOLD_E2E=1`.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from maistro.extensions.scaffold import (
    CAPABILITIES,
    CONTRACT_MAJOR,
    EFFECTS,
    FAMILIES,
    ManifestValidationError,
    ScaffoldError,
    ScaffoldSpec,
    render_project,
    scaffold_project,
    validate_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
REFERENCE_MANIFEST = REPO_ROOT / "extensions" / "reference-greeter" / "extension.json"

runner = CliRunner()


def _minimal_manifest(**overrides: object) -> dict[str, Any]:
    manifest: dict[str, Any] = {
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
        "entrypoint": {"module": "greeter.plugin", "object": "PLUGIN"},
    }
    manifest.update(overrides)
    return manifest


# --------------------------------------------------------------------------
# Schema validation
# --------------------------------------------------------------------------


def test_reference_extension_manifest_validates() -> None:
    """The one manifest a reader can check by hand is schema-clean."""
    validate_manifest(json.loads(REFERENCE_MANIFEST.read_text(encoding="utf-8")))


def test_minimal_manifest_validates_and_round_trips() -> None:
    manifest = _minimal_manifest()
    assert validate_manifest(manifest) is manifest


def test_non_object_manifest_is_rejected() -> None:
    for document in ("[]", '"greeter"', "3", "null"):
        with pytest.raises(ManifestValidationError, match="JSON object"):
            validate_manifest(json.loads(document))


@pytest.mark.parametrize(
    "key",
    [
        "id",
        "publisher",
        "version",
        "title",
        "description",
        "contract",
        "family",
        "capabilities",
        "effects",
        "data",
        "entrypoint",
    ],
)
def test_every_required_key_is_required(key: str) -> None:
    manifest = _minimal_manifest()
    del manifest[key]
    with pytest.raises(ManifestValidationError, match=f"{key}: required key is missing"):
        validate_manifest(manifest)


def test_unknown_top_level_keys_are_forbidden() -> None:
    manifest = _minimal_manifest(permissions=["workspace.read"])
    with pytest.raises(ManifestValidationError, match=r"unknown key.*permissions"):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    ("field", "offender"),
    [
        ("family", "widget"),
        ("family", "Tool"),  # the vocabulary is closed and lower-cased
        ("capabilities", ["workspace.readwrite"]),
        ("effects", ["mostly-harmless"]),
    ],
)
def test_unknown_authority_names_are_rejected_not_ignored(field: str, offender: object) -> None:
    manifest = _minimal_manifest(**{field: offender})
    with pytest.raises(ManifestValidationError, match=f"{field}.*closed"):
        validate_manifest(manifest)


def test_duplicate_vocabulary_entries_are_rejected() -> None:
    manifest = _minimal_manifest(capabilities=["memory.read", "memory.read"])
    with pytest.raises(ManifestValidationError, match="duplicate"):
        validate_manifest(manifest)


def test_id_must_be_prefixed_by_the_publisher() -> None:
    manifest = _minimal_manifest(id="other.greeter")
    with pytest.raises(ManifestValidationError, match=r"must be 'acme'\.<name>"):
        validate_manifest(manifest)


@pytest.mark.parametrize("version", ["1.0", "01.0.0", "1.0.0-beta", "v1.0.0"])
def test_version_is_strict_semver(version: str) -> None:
    with pytest.raises(ManifestValidationError, match="version"):
        validate_manifest(_minimal_manifest(version=version))


@pytest.mark.parametrize(
    "contract",
    [
        ">=1.0.0,<3.0.0",  # spans two majors: claims a schema that does not exist
        ">=1.0.0,<2.1.0",  # ceiling is not a major boundary
        ">=1.0.0",  # no ceiling at all
        ">=2.0.0,<1.0.0",  # inverted shape does not match the range grammar
        "1.0.0",  # not a range
    ],
)
def test_contract_must_pin_exactly_one_major(contract: str) -> None:
    with pytest.raises(ManifestValidationError, match="contract"):
        validate_manifest(_minimal_manifest(contract=contract))


@pytest.mark.parametrize(
    "entrypoint",
    [
        {"module": "greeter._private", "object": "PLUGIN"},  # private even under a root
        {"module": "not a module", "object": "PLUGIN"},
        {"module": "greeter.plugin", "object": "not an identifier"},
        {"module": "greeter.plugin", "object": "PLUGIN", "extra": 1},
        {"module": "greeter.plugin"},  # object missing
        "greeter.plugin:PLUGIN",  # wrong shape entirely
    ],
)
def test_entrypoint_shapes_are_rejected(entrypoint: object) -> None:
    with pytest.raises(ManifestValidationError, match="entrypoint"):
        validate_manifest(_minimal_manifest(entrypoint=entrypoint))


def test_data_scopes_are_validated_inside_the_data_object() -> None:
    with pytest.raises(ManifestValidationError, match=r"data.scopes.*galaxy.*closed"):
        validate_manifest(_minimal_manifest(data={"scopes": ["galaxy"]}))
    with pytest.raises(ManifestValidationError, match="data: unknown key"):
        validate_manifest(_minimal_manifest(data={"scopes": [], "rows": True}))
    with pytest.raises(ManifestValidationError, match=r"data: required object"):
        validate_manifest(_minimal_manifest(data=["workspace"]))


def test_network_authority_is_strict() -> None:
    with pytest.raises(ManifestValidationError, match=r"network\.allow"):
        validate_manifest(
            _minimal_manifest(
                capabilities=["network.outbound"],
                network={"allow": ["https://api.weather.example"], "allowed_ports": [443]},
            )
        )
    with pytest.raises(ManifestValidationError, match=r"network\.allowed_ports"):
        validate_manifest(
            _minimal_manifest(
                capabilities=["network.outbound"],
                network={"allow": ["api.weather.example"], "allowed_ports": [0]},
            )
        )
    with pytest.raises(ManifestValidationError, match="network: unknown key"):
        validate_manifest(
            _minimal_manifest(
                capabilities=["network.outbound"],
                network={"allow": [], "allowed_ports": [], "urls": ["*"]},
            )
        )


def test_filesystem_authority_is_strict() -> None:
    with pytest.raises(ManifestValidationError, match=r"filesystem\.mode"):
        validate_manifest(
            _minimal_manifest(
                capabilities=["filesystem.read"],
                filesystem={"mode": "rw", "paths": ["exports/"]},
            )
        )
    with pytest.raises(ManifestValidationError, match=r"filesystem\.paths"):
        validate_manifest(
            _minimal_manifest(
                capabilities=["filesystem.write"],
                filesystem={"mode": "write", "paths": ["/etc"]},
            )
        )


def test_secrets_are_references_never_values() -> None:
    with pytest.raises(ManifestValidationError, match=r"secrets\[0\].name"):
        validate_manifest(
            _minimal_manifest(capabilities=["secrets.read"], secrets=[{"name": "weather_api_key"}])
        )
    with pytest.raises(ManifestValidationError, match=r"secrets\[0\]: unknown key"):
        validate_manifest(
            _minimal_manifest(
                capabilities=["secrets.read"], secrets=[{"name": "KEY", "value": "x"}]
            )
        )


def test_dependencies_name_other_extensions() -> None:
    with pytest.raises(ManifestValidationError, match=r"dependencies\[0\].id"):
        validate_manifest(_minimal_manifest(dependencies=[{"id": "greeter", "version": ">=1.0.0"}]))
    with pytest.raises(ManifestValidationError, match=r"dependencies\[0\].version"):
        validate_manifest(
            _minimal_manifest(dependencies=[{"id": "other.tool", "version": "latest"}])
        )


def test_every_violation_in_one_pass_is_reported() -> None:
    manifest = _minimal_manifest(
        family="widget",
        effects=["teleport"],
        version="1.0",
        entrypoint={"module": "greeter._secret"},
    )
    with pytest.raises(ManifestValidationError) as excinfo:
        validate_manifest(manifest)
    message = str(excinfo.value)
    assert "family" in message and "effects" in message
    assert "version" in message and "entrypoint.module" in message


def test_the_closed_vocabularies_are_the_documented_ones() -> None:
    # Grounding against docs/extensions/manifest-reference.md: a vocabulary
    # that silently drifts would make every manifest check above meaningless.
    assert FAMILIES == (
        "tool",
        "skill",
        "mcp-gateway",
        "capability-provider",
        "renderer-plugin",
    )
    assert len(CAPABILITIES) == 11 and "network.outbound" in CAPABILITIES
    assert EFFECTS == ("read-only", "mutating", "external-side-effect", "irreversible")
    assert CONTRACT_MAJOR == 1


# --------------------------------------------------------------------------
# Scaffold specification
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("name", "My Tool"),
        ("name", "my_tool"),
        ("name", "1tool"),
        ("publisher", "Acme"),
        ("version", "0.1"),
        ("family", "widget"),
        ("contract", ">=2.0.0,<3.0.0"),  # scaffold codes against major 1
        ("contract", ">=1.0.0"),  # not the pinning shape
    ],
)
def test_invalid_spec_fields_are_refused(field: str, bad: str) -> None:
    kwargs: dict[str, Any] = {
        "name": "my-tool",
        "publisher": "acme",
        "family": "tool",
        field: bad,
    }
    with pytest.raises(ScaffoldError):
        ScaffoldSpec(**kwargs)


def test_spec_derives_package_and_manifest_id() -> None:
    spec = ScaffoldSpec(name="my-weather-tool", publisher="acme", family="tool")
    assert spec.package == "my_weather_tool"
    assert spec.manifest_id == "acme.my-weather-tool"
    assert spec.title_or_default == "my-weather-tool (tool extension)"
    assert "tool extension" in spec.description_or_default


# --------------------------------------------------------------------------
# Rendering: family templates are structurally distinct, public-SDK-only
# --------------------------------------------------------------------------


@pytest.mark.parametrize("family", FAMILIES)
def test_every_family_renders_a_schema_clean_project(family: str) -> None:
    spec = ScaffoldSpec(name="my-weather-tool", publisher="acme", family=family)
    files = render_project(spec)
    assert set(files) == {
        "pyproject.toml",
        "extension.json",
        "README.md",
        "src/my_weather_tool/__init__.py",
        "src/my_weather_tool/plugin.py",
        "tests/test_my_weather_tool.py",
    }
    validate_manifest(json.loads(files["extension.json"]))
    for relative, content in files.items():
        if relative.endswith(".py"):
            ast.parse(content, filename=relative)


@pytest.mark.parametrize("family", FAMILIES)
def test_family_templates_are_structurally_distinct(family: str) -> None:
    """Each family's entrypoint declares what a host of that family discovers."""
    spec = ScaffoldSpec(name="my-weather-tool", publisher="acme", family=family)
    plugin = ast.parse(render_project(spec)["src/my_weather_tool/plugin.py"])
    assigned = {
        node.target.id  # type: ignore[attr-defined]
        for node in ast.walk(plugin)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    } | {
        target.id  # type: ignore[attr-defined]
        for node in ast.walk(plugin)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert "PLUGIN" in assigned
    family_symbols = {
        "tool": {"HANDLERS"},
        "skill": {"SKILL_INSTRUCTIONS"},
        "mcp-gateway": set(),  # declaration lives in PLUGIN's upstreams key
        "capability-provider": set(),
        "renderer-plugin": set(),
    }[family]
    assert family_symbols <= assigned, f"{family} template lost its distinct structure"
    plugin_source = render_project(spec)["src/my_weather_tool/plugin.py"]
    assert f'"kind": "{family}"' in plugin_source
    family_keys = {
        "tool": '"handler"',
        "skill": '"skills"',
        "mcp-gateway": '"upstreams"',
        "capability-provider": '"providers"',
        "renderer-plugin": '"renderers"',
    }
    assert family_keys[family] in plugin_source


@pytest.mark.parametrize("family", FAMILIES)
def test_every_family_manifest_declares_least_authority(family: str) -> None:
    """A scaffold starts with nothing: authority is added by the author, on purpose."""
    spec = ScaffoldSpec(name="my-weather-tool", publisher="acme", family=family)
    manifest = json.loads(render_project(spec)["extension.json"])
    assert manifest["capabilities"] == []
    assert manifest["effects"] == ["read-only"]
    assert manifest["data"] == {"scopes": []}
    assert manifest["family"] == family
    assert manifest["contract"] == ">=1.0.0,<2.0.0"
    assert manifest["id"] == "acme.my-weather-tool"
    assert manifest["entrypoint"] == {
        "module": "my_weather_tool.plugin",
        "object": "PLUGIN",
    }


@pytest.mark.parametrize("family", FAMILIES)
def test_generated_code_imports_nothing_first_party_or_third_party(family: str) -> None:
    """Acceptance: 'generated project uses only public SDK imports' — today the
    public SDK ships nothing to import, so the templates import nothing at all
    (the reference extension's own posture), which the boundary gate upgrades
    to 'SDK-only' the day an author adds `maistro_ext_sdk` imports."""
    spec = ScaffoldSpec(name="my-weather-tool", publisher="acme", family=family)
    for relative in ("src/my_weather_tool/plugin.py", "src/my_weather_tool/__init__.py"):
        tree = ast.parse(render_project(spec)[relative])
        for node in ast.walk(tree):
            roots = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"{relative} uses a relative import"
                roots = [(node.module or "").split(".")[0]]
            for root in roots:
                assert root in ("", "__future__"), f"{relative} imports {root!r}"


def test_generated_pyproject_ships_the_manifest_and_pins_the_packaging() -> None:
    spec = ScaffoldSpec(name="my-weather-tool", publisher="acme", family="tool")
    pyproject = render_project(spec)["pyproject.toml"]
    assert 'name = "my-weather-tool"' in pyproject
    assert 'packages = ["src/my_weather_tool"]' in pyproject
    assert '"extension.json" = "my_weather_tool/extension.json"' in pyproject
    assert "--import-mode=importlib" in pyproject
    assert "dependencies = []" in pyproject


def test_generated_tests_read_the_manifest_from_the_wheel() -> None:
    spec = ScaffoldSpec(name="my-weather-tool", publisher="acme", family="tool")
    tests = render_project(spec)["tests/test_my_weather_tool.py"]
    assert "resource_files" in tests  # installed-distribution read, not checkout read
    assert "importlib" in tests  # the entrypoint resolves lexically-declared objects


# --------------------------------------------------------------------------
# scaffold_project: refusal semantics
# --------------------------------------------------------------------------


def test_scaffold_project_writes_the_rendered_tree(tmp_path: Path) -> None:
    spec = ScaffoldSpec(name="my-tool", publisher="acme", family="tool")
    written = scaffold_project(spec, tmp_path / "my-tool")
    assert len(written) == 6
    assert (tmp_path / "my-tool" / "extension.json").is_file()
    validate_manifest(json.loads((tmp_path / "my-tool" / "extension.json").read_text()))


def test_scaffold_project_refuses_a_non_empty_target_without_force(tmp_path: Path) -> None:
    target = tmp_path / "my-tool"
    target.mkdir()
    (target / "author-work.txt").write_text("precious", encoding="utf-8")
    spec = ScaffoldSpec(name="my-tool", publisher="acme", family="tool")
    with pytest.raises(ScaffoldError, match="--force"):
        scaffold_project(spec, target)
    assert (target / "author-work.txt").read_text() == "precious"
    assert not (target / "extension.json").exists()


def test_scaffold_project_force_writes_into_an_existing_directory(tmp_path: Path) -> None:
    target = tmp_path / "my-tool"
    target.mkdir()
    (target / "author-work.txt").write_text("precious", encoding="utf-8")
    spec = ScaffoldSpec(name="my-tool", publisher="acme", family="tool")
    scaffold_project(spec, target, force=True)
    assert (target / "author-work.txt").exists()
    assert (target / "extension.json").exists()


def test_scaffold_project_refuses_a_file_target(tmp_path: Path) -> None:
    target = tmp_path / "a-file"
    target.write_text("not a directory", encoding="utf-8")
    spec = ScaffoldSpec(name="my-tool", publisher="acme", family="tool")
    with pytest.raises(ScaffoldError, match="not a directory"):
        scaffold_project(spec, target)


# --------------------------------------------------------------------------
# CLI surface
# --------------------------------------------------------------------------


def _cli_app():
    """The full maistro CLI: the group must be tested through its real
    registration (`maistro extension new ...`), not invoked flattened."""
    from maistro.cli import app

    return app


def test_cli_new_scaffolds_a_project(tmp_path: Path) -> None:
    result = runner.invoke(
        _cli_app(),
        [
            "extension",
            "new",
            "my-weather-tool",
            "--family",
            "mcp-gateway",
            "--publisher",
            "acme",
            "--target-dir",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 0, result.output
    out = tmp_path / "out"
    assert (out / "extension.json").is_file()
    assert (out / "src" / "my_weather_tool" / "plugin.py").is_file()
    manifest = json.loads((out / "extension.json").read_text())
    assert manifest["family"] == "mcp-gateway"
    assert manifest["id"] == "acme.my-weather-tool"
    # The next-step guidance names the wheel the build will actually produce.
    assert "my_weather_tool-0.1.0-py3-none-any.whl" in result.output


def test_cli_new_defaults_to_the_tool_family_and_dot_name_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(_cli_app(), ["extension", "new", "greeter-demo", "--publisher", "acme"])
    assert result.exit_code == 0, result.output
    manifest = json.loads((tmp_path / "greeter-demo" / "extension.json").read_text())
    assert manifest["family"] == "tool"
    assert manifest["publisher"] == "acme"


def test_cli_new_rejects_unknown_families() -> None:
    result = runner.invoke(_cli_app(), ["extension", "new", "my-tool", "--family", "widget"])
    assert result.exit_code == 1
    assert "widget" in result.output
    assert "tool" in result.output  # the closed families are named


def test_cli_new_rejects_non_slug_names() -> None:
    result = runner.invoke(_cli_app(), ["extension", "new", "My Tool"])
    assert result.exit_code == 1
    assert "slug" in result.output


def test_cli_new_family_matching_is_case_insensitive(tmp_path: Path) -> None:
    result = runner.invoke(
        _cli_app(),
        [
            "extension",
            "new",
            "my-tool",
            "--family",
            "Capability-Provider",
            "--publisher",
            "acme",
            "--target-dir",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 0, result.output
    manifest = json.loads((tmp_path / "out" / "extension.json").read_text())
    assert manifest["family"] == "capability-provider"


def test_cli_new_refuses_an_occupied_target_and_force_overrides(
    tmp_path: Path,
) -> None:
    target = tmp_path / "out"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")
    blocked = runner.invoke(
        _cli_app(),
        ["extension", "new", "my-tool", "--publisher", "acme", "--target-dir", str(target)],
    )
    assert blocked.exit_code == 1
    assert "--force" in blocked.output
    assert (target / "keep.txt").exists() and not (target / "extension.json").exists()
    forced = runner.invoke(
        _cli_app(),
        [
            "extension",
            "new",
            "my-tool",
            "--publisher",
            "acme",
            "--target-dir",
            str(target),
            "--force",
        ],
    )
    assert forced.exit_code == 0, forced.output
    assert (target / "extension.json").exists()


def test_cli_new_custom_title_description_version(tmp_path: Path) -> None:
    result = runner.invoke(
        _cli_app(),
        [
            "extension",
            "new",
            "my-tool",
            "--publisher",
            "acme",
            "--target-dir",
            str(tmp_path / "out"),
            "--title",
            "Weather tool",
            "--description",
            "Reads the sky.",
            "--version",
            "1.2.3",
        ],
    )
    assert result.exit_code == 0, result.output
    manifest = json.loads((tmp_path / "out" / "extension.json").read_text())
    assert manifest["title"] == "Weather tool"
    assert manifest["description"] == "Reads the sky."
    assert manifest["version"] == "1.2.3"
    pyproject = (tmp_path / "out" / "pyproject.toml").read_text()
    assert 'version = "1.2.3"' in pyproject


# --------------------------------------------------------------------------
# End-to-end: build + clean-venv test run (offline suite skips this)
# --------------------------------------------------------------------------


def _run(command: list[str], cwd: Path) -> None:
    proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    assert proc.returncode == 0, f"{command} failed in {cwd}:\n{proc.stdout}\n{proc.stderr}"


@pytest.mark.skipif(
    os.environ.get("MAISTRO_TEST_EXTENSION_SCAFFOLD_E2E") != "1",
    reason="executes uv build + a fresh venv per family; run with "
    "MAISTRO_TEST_EXTENSION_SCAFFOLD_E2E=1. No workflow sets that flag: CI's "
    "executed equivalent is scripts/check-extension-scaffold.py, which scaffolds "
    "through `maistro-ext-sdk new` and never runs this CLI's templates",
)
@pytest.mark.parametrize("family", FAMILIES)
def test_scaffolded_project_builds_and_tests_outside_the_repository(family: str) -> None:
    """The acceptance chain, executed: scaffold outside the repo, build the
    wheel with nothing but the project tree, install it into a fresh venv,
    run the generated suite there, and prove the product is unimportable."""
    work = Path(tempfile.mkdtemp(prefix="scaffold-e2e-"))
    try:
        target = work / "proj"
        result = runner.invoke(
            _cli_app(),
            [
                "extension",
                "new",
                "clean-room",
                "--family",
                family,
                "--publisher",
                "acme",
                "--target-dir",
                str(target),
            ],
        )
        assert result.exit_code == 0, result.output
        _run(["uv", "build", "--wheel", "--out-dir", "dist"], cwd=target)
        wheels = list((target / "dist").glob("clean_room-0.1.0-py3-none-any.whl"))
        assert len(wheels) == 1, wheels
        _run(["uv", "venv", ".venv-isolated"], cwd=work)
        venv_python = work / ".venv-isolated" / "bin" / "python"
        _run(
            ["uv", "pip", "install", "--python", str(venv_python), str(wheels[0]), "pytest"],
            cwd=work,
        )
        tests_dir = target / "tests"
        _run(
            [
                str(venv_python),
                "-m",
                "pytest",
                str(tests_dir),
                "-q",
                "--import-mode=importlib",
                "--confcutdir",
                str(target),
            ],
            cwd=work,
        )
        # The negative control: the fresh venv holds none of this repository.
        probe = subprocess.run(
            [str(venv_python), "-c", "import maistro"],
            capture_output=True,
            text=True,
        )
        assert probe.returncode != 0, "product-private module importable in the clean venv"
    finally:
        shutil.rmtree(work, ignore_errors=True)

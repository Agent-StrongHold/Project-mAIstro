"""The scaffold: `maistro-ext-sdk new` (M9-H1, #973).

Acceptance, as executed here:

- every family scaffolds a project whose generated manifest passes the
  SDK's own no-import validation — the same validator any host runs;
- family templates are structurally distinct where the contract
  distinguishes them (object name, kind tag, and the pinned tool handler
  protocol), so a manifest's family claim is checkable at load time;
- generated projects import only the public SDK, the standard library,
  pytest (in tests/), and their own package — the boundary the namespace
  policy and `scripts/check-extension-imports.py` enforce for every
  extension tree, enforced here for the generated one;
- bad inputs are rejected before a single file is written, and an existing
  non-empty target is never clobbered silently.

The physical half — build the scaffolded wheel in a clean venv, run its
sample tests, run conformance and certification against it — is the gate
`scripts/check-extension-scaffold.py`; these tests pin everything static.
"""

from __future__ import annotations

import ast
import json
import sys
import tomllib
from pathlib import Path

import pytest

from maistro_ext_sdk import contract_version, validate_extension_dir
from maistro_ext_sdk.cli import main
from maistro_ext_sdk.scaffold import (
    SCAFFOLD_FAMILIES,
    SDK_PACKAGE_PIN,
    ScaffoldError,
    scaffold_extension,
)

FAMILIES = ["tool", "skill", "mcp-gateway", "capability-provider", "renderer-plugin"]


def _scaffold(tmp_path: Path, family: str = "tool", **kwargs: object) -> Path:
    root = tmp_path / "ext"
    scaffold_extension(
        name="widget",
        publisher="acme",
        family=family,
        out_dir=root,
        **kwargs,  # type: ignore[arg-type]
    )
    return root


class TestScaffoldValidates:
    def test_every_family_scaffolds_a_valid_manifest(self, tmp_path: Path) -> None:
        for family in FAMILIES:
            root = _scaffold(tmp_path / family, family)
            ext = validate_extension_dir(root)
            assert ext.manifest.id == "acme.widget"
            assert ext.manifest.publisher == "acme"
            assert ext.manifest.family == family

    def test_entrypoint_object_names_are_family_distinct(self, tmp_path: Path) -> None:
        objects = {}
        for family in FAMILIES:
            root = _scaffold(tmp_path / family, family)
            manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
            objects[family] = manifest["entrypoint"]["object"]
        assert len(set(objects.values())) == len(FAMILIES), objects

    def test_entrypoint_kind_tags_are_family_distinct(self, tmp_path: Path) -> None:
        kinds = {}
        for family in FAMILIES:
            root = _scaffold(tmp_path / family, family)
            manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
            module_name = manifest["entrypoint"]["module"]
            plugin = (root / f"{module_name.replace('.', '/')}.py").read_text(encoding="utf-8")
            for line in plugin.splitlines():
                if '"kind":' in line:
                    kinds[family] = line.split('"')[3]
                    break
        assert len(set(kinds.values())) == len(FAMILIES), kinds
        for family, kind in kinds.items():
            assert kind == family

    def test_only_the_tool_template_claims_the_pinned_handler_protocol(
        self, tmp_path: Path
    ) -> None:
        """The tool family's handler protocol is pinned by the merged
        contract (the reference extension's shape); no other template may
        invent a pinned-looking protocol the contract does not state."""
        for family in FAMILIES:
            root = _scaffold(tmp_path / family, family)
            manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
            plugin_path = root / manifest["entrypoint"]["module"].replace(".", "/")
            plugin_path = plugin_path.with_suffix(".py")
            plugin = plugin_path.read_text(encoding="utf-8")
            if family == "tool":
                assert "handler" in plugin
                assert "HANDLERS" in plugin
            else:
                assert "HANDLERS" not in plugin

    def test_generated_contract_range_pins_exactly_the_published_major(
        self, tmp_path: Path
    ) -> None:
        root = _scaffold(tmp_path)
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        contract = manifest["contract"]
        assert contract == f">={contract_version()},<2.0.0"

    def test_project_layout_is_complete(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        assert (root / "extension.json").is_file()
        assert (root / "pyproject.toml").is_file()
        assert (root / "README.md").is_file()
        assert (root / "acme_widget" / "__init__.py").is_file()
        assert (root / "acme_widget" / "plugin.py").is_file()
        assert (root / "tests" / "test_acme_widget.py").is_file()

    def test_pyproject_pins_the_sdk_and_ships_the_manifest(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        assert f'"maistro-ext-sdk{SDK_PACKAGE_PIN}"' in pyproject
        # The discovery manifest rides the wheel (the namespace policy's
        # required artifact), exactly the reference extension's wiring.
        assert '"extension.json" = "acme_widget/extension.json"' in pyproject
        assert 'packages = ["acme_widget"]' in pyproject


class TestGeneratedImportsStayPublic:
    def _import_roots(self, path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots.add(node.module.split(".")[0])
        return roots

    def test_shipped_sources_import_only_the_standard_library(self, tmp_path: Path) -> None:
        """Every family's shipped module imports nothing outside the stdlib —
        the data-only shape, and a subset of 'only public SDK imports'."""
        for family in FAMILIES:
            root = _scaffold(tmp_path / family, family)
            for path in (root / "acme_widget").glob("*.py"):
                for root_name in self._import_roots(path):
                    assert root_name in sys.stdlib_module_names, (
                        f"{family}: {path.name} imports {root_name!r}"
                    )

    def test_sample_tests_import_only_public_surfaces(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        for path in (root / "tests").glob("*.py"):
            for root_name in self._import_roots(path):
                assert root_name in (
                    {"pytest", "maistro_ext_sdk", "acme_widget"} | sys.stdlib_module_names
                ), f"{path.name} imports {root_name!r}"

    def test_scaffolded_tool_project_runs_harness_conformance(self, tmp_path: Path) -> None:
        """The cross-tooling anchor (#945): a scaffolded project passes the
        harness's conformance suite unmodified. `maistro_ext_harness` is the
        installed distribution here (this suite runs in the environment where
        the monorepo's dev extra installed it); a third party installs the
        same wheel from their own CI — the flow the scaffold's README states."""
        from maistro_ext_harness.runner import RunRequest, run_conformance

        root = _scaffold(tmp_path)
        report = run_conformance(RunRequest(subject=root))
        assert report.failed == [], [f"{case.case_id}: {case.detail}" for case in report.failed]
        assert report.passed_count > 0


class TestInputValidation:
    def test_bad_publisher_rejected_before_any_write(self, tmp_path: Path) -> None:
        target = tmp_path / "out"
        with pytest.raises(ScaffoldError, match="publisher"):
            scaffold_extension(name="widget", publisher="Acme!", out_dir=target)
        assert not target.exists()

    def test_bad_name_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ScaffoldError, match="name"):
            scaffold_extension(name="my.widget", publisher="acme", out_dir=tmp_path / "o")

    def test_bad_version_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ScaffoldError, match="version"):
            scaffold_extension(
                name="widget", publisher="acme", version="1.0", out_dir=tmp_path / "o"
            )

    def test_unknown_family_rejected_with_the_closed_vocabulary(self, tmp_path: Path) -> None:
        with pytest.raises(ScaffoldError, match="closed"):
            scaffold_extension(
                name="widget", publisher="acme", family="widgetizer", out_dir=tmp_path / "o"
            )
        assert set(SCAFFOLD_FAMILIES) == set(FAMILIES)

    def test_non_empty_target_refused_without_force(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        with pytest.raises(ScaffoldError, match="not empty"):
            scaffold_extension(name="widget", publisher="acme", out_dir=root)

    def test_force_overwrites_an_existing_target(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        scaffold_extension(
            name="widget", publisher="acme", out_dir=root, version="2.0.0", force=True
        )
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        assert manifest["version"] == "2.0.0"

    def test_custom_title_and_description_flow_into_the_manifest(self, tmp_path: Path) -> None:
        root = _scaffold(
            tmp_path,
            title="Custom title",
            description="Custom description",
        )
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        assert manifest["title"] == "Custom title"
        assert manifest["description"] == "Custom description"


class TestFreeTextTomlSafety:
    """Title and description reach pyproject.toml's ``description = "..."``

    basic string and the README's title line. Anything those single-line
    contexts cannot carry (control characters) or that only the post-write
    manifest validator would reject (overlength) must be refused before a
    file exists, and what is accepted must round-trip through a real TOML
    parse — the failure mode where ``new`` reported success over a
    pyproject no build tool could read is pinned shut here.
    """

    def test_multiline_description_rejected_before_any_write(self, tmp_path: Path) -> None:
        target = tmp_path / "out"
        with pytest.raises(ScaffoldError, match="description"):
            scaffold_extension(
                name="inj",
                publisher="acme",
                out_dir=target,
                description='line one\n[project]\nname = "injected"',
            )
        assert not target.exists()

    def test_multiline_title_rejected_before_any_write(self, tmp_path: Path) -> None:
        target = tmp_path / "out"
        with pytest.raises(ScaffoldError, match="title"):
            scaffold_extension(name="widget", publisher="acme", out_dir=target, title="two\nlines")
        assert not target.exists()

    def test_description_with_quotes_and_backslashes_round_trips_through_tomllib(
        self, tmp_path: Path
    ) -> None:
        description = 'Reads C:\\Users "quoted" notes'
        root = _scaffold(tmp_path, description=description)
        parsed = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        assert parsed["project"]["description"] == description

    def test_overlong_description_rejected_before_any_write(self, tmp_path: Path) -> None:
        target = tmp_path / "out"
        with pytest.raises(ScaffoldError, match="description"):
            scaffold_extension(
                name="widget", publisher="acme", out_dir=target, description="x" * 2001
            )
        assert not target.exists()

    def test_overlong_title_rejected_before_any_write(self, tmp_path: Path) -> None:
        target = tmp_path / "out"
        with pytest.raises(ScaffoldError, match="title"):
            scaffold_extension(name="widget", publisher="acme", out_dir=target, title="t" * 201)
        assert not target.exists()

    def test_restated_length_ceilings_match_the_manifest_model(self) -> None:
        """The scaffold's restated ceilings are the manifest model's, so the
        pre-write rejection and the post-write validator cannot disagree."""
        import annotated_types

        from maistro_ext_sdk.manifest import ExtensionIdentity
        from maistro_ext_sdk.scaffold import _DESCRIPTION_MAX_LENGTH, _TITLE_MAX_LENGTH

        def max_len(field: object) -> int:
            for meta in field.metadata:  # type: ignore[attr-defined]
                if isinstance(meta, annotated_types.MaxLen):
                    return meta.max_length
            raise AssertionError("manifest field carries no MaxLen constraint")

        fields = ExtensionIdentity.model_fields
        assert max_len(fields["title"]) == _TITLE_MAX_LENGTH
        assert max_len(fields["description"]) == _DESCRIPTION_MAX_LENGTH


class TestCliNewCommand:
    def test_new_scaffolds_and_prints_the_summary(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "proj"
        assert main(["new", "widget", "--publisher", "acme", "--out", str(target)]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["id"] == "acme.widget"
        assert Path(payload["scaffolded"]) == target
        assert validate_extension_dir(target).manifest.id == "acme.widget"

    def test_new_rejects_a_duplicate_target_with_exit_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "proj"
        assert main(["new", "widget", "--publisher", "acme", "--out", str(target)]) == 0
        capsys.readouterr()
        assert main(["new", "widget", "--publisher", "acme", "--out", str(target)]) == 1
        assert "SCAFFOLD-REJECTED" in capsys.readouterr().err

    def test_new_validates_through_the_cli_validator(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "proj"
        main(["new", "widget", "--publisher", "acme", "--out", str(target)])
        capsys.readouterr()
        assert main(["validate", str(target)]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["entrypoint"] == "acme_widget.plugin:PLUGIN"

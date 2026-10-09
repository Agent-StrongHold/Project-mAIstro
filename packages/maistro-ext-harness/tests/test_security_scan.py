"""The security scanner's classification rules, unit-scoped (#974, #975).

`tests/test_certification.py` proves the declines a certification pipeline
produces; this file drives `security_checks` directly over fabricated trees
so every rule fires on both sides of its verdict — the arms a conforming
extension (or the certification suite's specific attacks) never reach:

- `declared_distributions`: pyproject parsing, including the shapes that
  must yield an empty declaration rather than a crash;
- the import classifier: test-only roots, repo-relative roots, private
  module segments, alias- and distribution-resolved dependency declarations;
- the dynamic-import binding resolution: chained aliases, no-argument calls;
- the shipped-sources boundary: unparseable files and the entrypoint check
  when the manifest never parsed.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

from maistro_ext_harness.checks import CheckStatus
from maistro_ext_harness.security import (
    declared_distributions,
    security_checks,
)


def write_tree(root: Path, files: dict[str, str]) -> Path:
    for name, body in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return root


def finding_rules(records: tuple[Any, ...]) -> dict[str, str]:
    """check_id -> detail, for FAILED records only."""
    return {
        record.check_id: record.detail for record in records if record.status is CheckStatus.FAILED
    }


def security_detail(records: tuple[Any, ...], token: str) -> str:
    """The FAILED detail naming `token`, under whichever check reports it."""
    hits = [
        record.detail
        for record in records
        if record.status is CheckStatus.FAILED and token in record.detail
    ]
    assert hits, f"no finding naming {token!r} among: {[(r.check_id, r.status) for r in records]}"
    return hits[0]


def has_rule_finding(records: tuple[Any, ...], rule: str) -> bool:
    """Whether the finding-rule token appears in any FAILED detail."""
    return any(record.status is CheckStatus.FAILED and rule in record.detail for record in records)


@pytest.fixture
def scanned(tmp_path: Path):
    def _scan(files: dict[str, str], **kwargs: Any) -> tuple[Any, ...]:
        return security_checks(
            write_tree(tmp_path / "ext", files),
            entrypoint_module=kwargs.get("entrypoint_module", "acme_widget.plugin"),
            declared=kwargs.get("declared", ()),
        )

    return _scan


PLUGIN = 'PLUGIN: dict[str, object] = {"kind": "tool", "handler": "spin"}\n'


class TestDeclaredDistributions:
    def test_dependencies_and_extras_are_normalized(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "\n".join(
                [
                    "[project]",
                    'name = "x"',
                    'version = "1.0.0"',
                    'description = "x"',
                    "dependencies = ['PyYAML>=6', 'python_dateutil']",
                    "[project.optional-dependencies]",
                    "signing = ['cryptography>=42']",
                    "not-a-list = { broken = true }",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        names = declared_distributions(pyproject)
        assert names == ("pyyaml", "python_dateutil", "cryptography")

    def test_a_missing_pyproject_declares_nothing(self, tmp_path: Path) -> None:
        assert declared_distributions(tmp_path / "absent.toml") == ()

    def test_an_unparseable_pyproject_declares_nothing(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project\nnope", encoding="utf-8")
        with pytest.raises(tomllib.TOMLDecodeError):
            tomllib.loads(pyproject.read_text(encoding="utf-8"))  # the shape itself is broken
        assert declared_distributions(pyproject) == ()

    def test_a_pyproject_without_a_project_table_declares_nothing(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")
        assert declared_distributions(pyproject) == ()


class TestImportClassification:
    def test_a_test_file_may_import_pytest_without_declaring_it(self, scanned: Any) -> None:
        records = scanned(
            {
                "src/acme_widget/__init__.py": "",
                "src/acme_widget/plugin.py": PLUGIN,
                "tests/test_plugin.py": "import pytest\n\n\ndef test_ok() -> None:\n    assert True\n",
            }
        )
        assert not has_rule_finding(records, "declare it in pyproject.toml")

    def test_pytest_outside_tests_is_an_undeclared_dependency(self, scanned: Any) -> None:
        records = scanned(
            {
                "src/acme_widget/__init__.py": "",
                "src/acme_widget/plugin.py": "import pytest\n\n" + PLUGIN,
            }
        )
        detail = security_detail(records, "pytest")
        assert "declare it in pyproject.toml" in detail

    def test_a_repo_relative_import_is_a_violation(self, scanned: Any) -> None:
        records = scanned(
            {
                "src/acme_widget/__init__.py": "",
                "src/acme_widget/plugin.py": "import packages.maistro_core\n\n" + PLUGIN,
            }
        )
        detail = security_detail(records, "packages.maistro_core")
        assert "repository's layout" in detail

    def test_an_own_package_private_module_is_a_private_seam(self, scanned: Any) -> None:
        """`import acme_widget._secret` — the underscore segment is in the
        dotted root itself (a bare `from acme_widget import _secret` names an
        attribute, which the classifier deliberately treats as data)."""
        records = scanned(
            {
                "src/acme_widget/__init__.py": "",
                "src/acme_widget/_secret.py": "",
                "src/acme_widget/plugin.py": "import acme_widget._secret\n\n" + PLUGIN,
            }
        )
        assert "private seams" in security_detail(records, "acme_widget._secret")

    def test_the_sdk_s_private_modules_are_private_too(self, scanned: Any) -> None:
        records = scanned(
            {
                "src/acme_widget/__init__.py": "",
                "src/acme_widget/plugin.py": ("from maistro_ext_sdk import _internal\n\n" + PLUGIN),
            }
        )
        detail = security_detail(records, "maistro_ext_sdk._internal")
        assert "private even under the public SDK root" in detail

    def test_a_well_known_alias_declared_by_distribution_passes(
        self, scanned: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """dateutil -> python-dateutil resolves from the alias map with the
        installed metadata patched away: declaration, not installation."""
        import importlib.metadata

        monkeypatch.setattr(importlib.metadata, "packages_distributions", lambda: {})
        records = scanned(
            {
                "src/acme_widget/__init__.py": "",
                "src/acme_widget/plugin.py": "from dateutil import tz\n\n" + PLUGIN,
            },
            declared=("python_dateutil",),
        )
        assert not has_rule_finding(records, "python-dateutil")

    def test_the_same_alias_undeclared_is_a_violation(
        self, scanned: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import importlib.metadata

        monkeypatch.setattr(importlib.metadata, "packages_distributions", lambda: {})
        records = scanned(
            {
                "src/acme_widget/__init__.py": "",
                "src/acme_widget/plugin.py": "from dateutil import tz\n\n" + PLUGIN,
            },
            declared=(),
        )
        detail = security_detail(records, "dateutil")
        assert "declare it" in detail

    def test_a_declared_distribution_mapped_from_installed_metadata_passes(
        self, scanned: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A declaration matched through the environment's dist->import map
        (`python-dateutil` installs the `dateutil` root)."""
        import importlib.metadata

        monkeypatch.setattr(
            importlib.metadata,
            "packages_distributions",
            lambda: {"dateutil": ["python-dateutil"]},
        )
        records = scanned(
            {
                "src/acme_widget/__init__.py": "",
                "src/acme_widget/plugin.py": "from dateutil import tz\n\n" + PLUGIN,
            },
            declared=("python_dateutil",),
        )
        assert not has_rule_finding(records, "dateutil")

    def test_a_stdlib_import_is_always_allowed(self, scanned: Any) -> None:
        records = scanned(
            {
                "src/acme_widget/__init__.py": "",
                "src/acme_widget/plugin.py": "import json, pathlib\n\n" + PLUGIN,
            }
        )
        assert not has_rule_finding(records, "maistro")
        assert not has_rule_finding(records, "declare it in pyproject.toml")


class TestDynamicImportBindings:
    def test_a_chained_importlib_module_alias_is_resolved(self, scanned: Any) -> None:
        """`il2 = il` binds a second name to the importlib module object;
        `il2.import_module` is exactly as dynamic as the dotted spelling."""
        records = scanned(
            {
                "src/acme_widget/__init__.py": "",
                "src/acme_widget/plugin.py": (
                    "import importlib as il\n"
                    "il2 = il\n"
                    'il2.import_module("maistro_server.tables")\n\n' + PLUGIN
                ),
            }
        )
        detail = security_detail(records, "maistro_server.tables")
        assert "product-private" in detail

    def test_a_chained_callable_alias_is_resolved(self, scanned: Any) -> None:
        records = scanned(
            {
                "src/acme_widget/__init__.py": "",
                "src/acme_widget/plugin.py": (
                    "from importlib import import_module as base\n"
                    "load = base\n"
                    'load("maistro_server.tables")\n\n' + PLUGIN
                ),
            }
        )
        security_detail(records, "maistro_server.tables")

    def test_a_dynamic_import_call_with_no_arguments_is_not_an_import(self, scanned: Any) -> None:
        """Malformed dynamic-import calls scan as nothing, not as a crash."""
        records = scanned(
            {
                "src/acme_widget/__init__.py": "",
                "src/acme_widget/plugin.py": (
                    "import importlib\nimportlib.import_module()\n\n" + PLUGIN
                ),
            }
        )
        assert not has_rule_finding(records, "maistro")

    def test_a_dynamic_import_with_a_non_literal_argument_is_not_resolved(
        self, scanned: Any
    ) -> None:
        """The scanner cannot invent the name; the finding is not fabricated."""
        records = scanned(
            {
                "src/acme_widget/__init__.py": "",
                "src/acme_widget/plugin.py": (
                    "import importlib\nname = 'json'\nimportlib.import_module(name)\n\n" + PLUGIN
                ),
            }
        )
        assert "security/imports-public-only" not in finding_rules(records)

    def test_a_plain_assignment_through_known_machinery_names_stays_scanned(
        self, scanned: Any
    ) -> None:
        """Assignments whose value is an unknown name extend the binding scan
        without making everything a binding (the fixed-point loop's no-op arm)."""
        records = scanned(
            {
                "src/acme_widget/__init__.py": "",
                "src/acme_widget/plugin.py": (
                    "from importlib import import_module as load\n"
                    "loader = load\n"
                    "unrelated = loader\n"  # unknown-name value for the module scan
                    'loader("json")\n\n' + PLUGIN
                ),
            }
        )
        assert not has_rule_finding(records, "maistro")

    def test_a_relative_import_belongs_to_the_own_package(self, scanned: Any) -> None:
        records = scanned(
            {
                "src/acme_widget/__init__.py": "",
                "src/acme_widget/helpers.py": "",
                "src/acme_widget/plugin.py": "from . import helpers\n\n" + PLUGIN,
            }
        )
        assert not has_rule_finding(records, "maistro")


class TestShippedSourcesBoundary:
    def test_an_unparseable_source_fails_sources_parse(self, scanned: Any) -> None:
        records = scanned(
            {
                "src/acme_widget/__init__.py": "",
                "src/acme_widget/plugin.py": "def broken(:\n",
            }
        )
        rules = finding_rules(records)
        assert "security/sources-parse" in rules
        assert "plugin.py" in rules["security/sources-parse"]

    def test_an_unparsed_manifest_leaves_the_entrypoint_check_honest(self, tmp_path: Path) -> None:
        records = security_checks(
            write_tree(tmp_path / "ext", {"src/acme_widget/plugin.py": PLUGIN}),
            entrypoint_module=None,
        )
        rules = finding_rules(records)
        assert "security/entrypoint-inside-own-package" in rules
        assert "did not parse" in rules["security/entrypoint-inside-own-package"]

    def test_an_entrypoint_outside_the_own_package_fails(self, tmp_path: Path) -> None:
        records = security_checks(
            write_tree(
                tmp_path / "ext",
                {"src/acme_widget/__init__.py": "", "src/acme_widget/plugin.py": PLUGIN},
            ),
            entrypoint_module="elsewhere.plugin",
        )
        assert "security/entrypoint-inside-own-package" in finding_rules(records)

    def test_an_entrypoint_inside_the_own_package_passes(self, tmp_path: Path) -> None:
        records = security_checks(
            write_tree(
                tmp_path / "ext",
                {"src/acme_widget/__init__.py": "", "src/acme_widget/plugin.py": PLUGIN},
            ),
            entrypoint_module="acme_widget.plugin",
        )
        assert "security/entrypoint-inside-own-package" not in finding_rules(records)

    def test_a_src_layout_package_is_extension_owned(self, tmp_path: Path) -> None:
        """The `src/` layout's own package roots are discovered where they live."""
        records = security_checks(
            write_tree(
                tmp_path / "ext",
                {"src/acme_widget/__init__.py": "", "src/acme_widget/plugin.py": PLUGIN},
            ),
            entrypoint_module="acme_widget.plugin",
        )
        assert not has_rule_finding(records, "maistro")
        assert not has_rule_finding(records, "declare it in pyproject.toml")

    def test_a_flat_layout_package_is_extension_owned(self, tmp_path: Path) -> None:
        records = security_checks(
            write_tree(
                tmp_path / "ext",
                {"acme_widget/__init__.py": "", "acme_widget/plugin.py": PLUGIN},
            ),
            entrypoint_module="acme_widget.plugin",
        )
        assert not has_rule_finding(records, "maistro")
        assert not has_rule_finding(records, "declare it in pyproject.toml")

    def test_a_namespace_root_owned_by_the_entrypoint_is_not_rescanned_as_foreign(
        self, tmp_path: Path
    ) -> None:
        """A PEP 420 namespace root (no `__init__.py`) the entrypoint names is
        extension-owned: its modules must not classify as undeclared strangers."""
        records = security_checks(
            write_tree(
                tmp_path / "ext",
                {"acme_widget/impl.py": PLUGIN},
            ),
            entrypoint_module="acme_widget.impl",
        )
        assert not has_rule_finding(records, "maistro")
        assert not has_rule_finding(records, "declare it in pyproject.toml")

    def test_local_environment_directories_are_not_scanned(self, tmp_path: Path) -> None:
        """An installed dependency's own imports in `.venv` or `build/` must
        not decline the extension: those directories are not shipped sources."""
        records = security_checks(
            write_tree(
                tmp_path / "ext",
                {
                    "src/acme_widget/__init__.py": "",
                    "src/acme_widget/plugin.py": PLUGIN,
                    ".venv/lib/site-packages/somelib/mod.py": "import foreign_dependency\n",
                    "build/lib/acme_widget/old.py": "import another_foreign_thing\n",
                },
            ),
            entrypoint_module="acme_widget.plugin",
        )
        assert not has_rule_finding(records, "maistro")
        assert not has_rule_finding(records, "declare it in pyproject.toml")

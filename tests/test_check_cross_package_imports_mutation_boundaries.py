"""Mutation-boundary tests for the cross-package import gate (#423).

These cases make suppression and import-binding boundary behavior observable.
They exercise properties mutation testing found were correct in production but
insufficiently constrained by the suite.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-cross-package-imports.py"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("check_cross_package_imports_mutation", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    pkg = tmp_path / "packages" / "thing" / "src" / "thing"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


def _scan(check, workspace: Path, body: str):
    path = workspace / "app.py"
    path.write_text(body, encoding="utf-8")
    roots = {"thing": workspace / "packages" / "thing" / "src" / "thing"}
    return check.scan(path, roots, repo_root=workspace)


class TestWaiverBoundary:
    def test_last_line_waiver_does_not_suppress_first_line_finding(self, check, workspace):
        """Kill `index > 0` -> `index >= 0` in the waiver lookup."""
        body = (
            "from thing.missing import Widget\n"
            "# cross-package-imports: allow unrelated trailing exception\n"
        )

        findings = _scan(check, workspace, body)

        assert [finding.target for finding in findings] == ["thing.missing"]
        assert findings[0].line_no == 1

    def test_immediately_preceding_waiver_still_suppresses(self, check, workspace):
        body = (
            "# cross-package-imports: allow target is supplied only in deployment\n"
            "from thing.missing import Widget\n"
        )
        assert _scan(check, workspace, body) == []

    def test_same_line_waiver_still_suppresses_first_line(self, check, workspace):
        body = (
            "from thing.missing import Widget  "
            "# cross-package-imports: allow target is supplied only in deployment\n"
        )
        assert _scan(check, workspace, body) == []


class TestImportBindingBoundary:
    def test_plain_dotted_import_binds_the_top_level_name(self, check, workspace):
        """Constrain the `alias.asname or alias.name.split('.')[0]` survivors."""
        pkg = workspace / "packages" / "thing" / "src" / "thing"
        (pkg / "facade.py").write_text("import json.encoder\n", encoding="utf-8")

        assert _scan(check, workspace, "from thing.facade import json\n") == []
        (finding,) = _scan(check, workspace, "from thing.facade import encoder\n")
        assert finding.target == "thing.facade.encoder"

    def test_alias_on_dotted_import_binds_only_the_alias(self, check, workspace):
        pkg = workspace / "packages" / "thing" / "src" / "thing"
        (pkg / "facade.py").write_text("import json.encoder as codec\n", encoding="utf-8")

        assert _scan(check, workspace, "from thing.facade import codec\n") == []
        assert [f.target for f in _scan(check, workspace, "from thing.facade import json\n")] == [
            "thing.facade.json"
        ]

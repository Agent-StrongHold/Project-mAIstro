"""Regression tests for the per-test assertion-quality scanner."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_assertion_quality.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("_assertion_quality", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _findings(tmp_path: Path, source: str, *, bool_functions: set[str] | None = None) -> set[str]:
    path = tmp_path / "test_example.py"
    path.write_text(source, encoding="utf-8")
    module = _load_module()
    return {finding.code for finding in module.findings_for_path(path, bool_functions or set())}


def test_flags_literal_constant_assertion(tmp_path: Path) -> None:
    assert _findings(tmp_path, "def test_x():\n    assert True\n") == {
        "literal_constant_assert",
        "weak_only_oracle",
    }


def test_actionable_mode_excludes_intent_dependent_review_signals(tmp_path: Path) -> None:
    module = _load_module()
    path = tmp_path / "test_example.py"
    path.write_text("def test_x():\n    do_work()\n", encoding="utf-8")

    findings = module.findings_for_path(path, set())
    assert {finding.code for finding in findings} == {"no_recognized_oracle"}
    assert module.actionable_findings(findings) == []


def test_accepts_bool_contract_and_mock_assertion(tmp_path: Path) -> None:
    assert (
        _findings(
            tmp_path,
            "def test_x(mock):\n    assert is_ready()\n    mock.assert_called_once()\n",
            bool_functions={"is_ready"},
        )
        == set()
    )


def test_accepts_observable_none_contract(tmp_path: Path) -> None:
    assert (
        _findings(tmp_path, "def test_x(service):\n    assert service.fetch() is None\n") == set()
    )


def test_flags_test_without_recognized_oracle(tmp_path: Path) -> None:
    assert _findings(tmp_path, "def test_x():\n    do_work()\n") == {"no_recognized_oracle"}


def test_flags_return_to_fixture_alias_comparison(tmp_path: Path) -> None:
    source = """\
def test_x(project):
    result = store.update(project)
    assert result.name == project.name
"""
    assert _findings(tmp_path, source) == {"return_fixture_alias_comparison"}

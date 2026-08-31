"""Root gate tests inverse-map to the scripts mutation testing must exercise."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mutation_targets.py"


@pytest.fixture(scope="module")
def mutation_targets():
    spec = importlib.util.spec_from_file_location("_targets", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def test_root_gate_test_maps_back_to_its_script(mutation_targets):
    test_path = "tests/test_check_cross_package_imports.py"
    result = mutation_targets.sources_for_test(test_path)
    assert result == ["scripts/check-cross-package-imports.py"]


def test_underscored_script_name_round_trips_without_guessing(mutation_targets):
    test_path = "tests/test_mutation_targets.py"
    result = mutation_targets.sources_for_test(test_path)
    assert result == ["scripts/mutation_targets.py"]


def test_unrelated_root_test_does_not_widen_to_scripts(mutation_targets):
    result = mutation_targets.sources_for_test("tests/test_not_a_gate.py")
    assert result == []


def test_test_only_gate_change_expands_to_the_script(mutation_targets):
    test_path = "tests/test_check_cross_package_imports.py"
    result = mutation_targets.expand([test_path])
    assert result == ["scripts/check-cross-package-imports.py"]


def test_script_mapping_drift_fails_closed(mutation_targets, monkeypatch):
    source = "scripts/check-cross-package-imports.py"
    monkeypatch.setattr(mutation_targets, "sources_for_test", lambda _path: [])

    targets, unresolved = mutation_targets._resolve_targets([source])

    assert targets == []
    assert unresolved == [source]

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
    spec = importlib.util.spec_from_file_location(
        "_mutation_targets_script_inverse", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def test_root_gate_test_maps_back_to_its_script(mutation_targets):
    assert mutation_targets.sources_for_test(
        "tests/test_check_cross_package_imports.py"
    ) == ["scripts/check-cross-package-imports.py"]


def test_underscored_script_name_round_trips_without_guessing(mutation_targets):
    assert mutation_targets.sources_for_test("tests/test_mutation_targets.py") == [
        "scripts/mutation_targets.py"
    ]


def test_unrelated_root_test_does_not_widen_to_scripts(mutation_targets):
    assert mutation_targets.sources_for_test("tests/test_not_a_gate.py") == []


def test_test_only_gate_change_expands_to_the_script(mutation_targets):
    assert mutation_targets.expand(["tests/test_check_cross_package_imports.py"]) == [
        "scripts/check-cross-package-imports.py"
    ]

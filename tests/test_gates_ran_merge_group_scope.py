from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-gates-ran.py"


@pytest.fixture(scope="module")
def check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_gates_ran_scope", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_pull_request_keeps_specialized_execution_evidence(check: ModuleType) -> None:
    names = set(check.required_check_names(base_branch="develop", event_name="pull_request"))
    assert names >= check.MERGE_GROUP_SPECIALIZED_CHECKS
    assert names >= check.MERGE_GROUP_PR_ONLY_CHECKS
    assert check.INTEGRATION_SCOPE_CHECK in names


def test_merge_group_replaces_specialized_evidence_with_aggregate(check: ModuleType) -> None:
    names = set(check.required_check_names(base_branch="develop", event_name="merge_group"))
    assert not names & check.MERGE_GROUP_SPECIALIZED_CHECKS
    assert not names & check.MERGE_GROUP_PR_ONLY_CHECKS
    assert check.INTEGRATION_SCOPE_CHECK in names


def test_merge_group_still_requires_unconditional_core_checks(check: ModuleType) -> None:
    names = set(check.required_check_names(base_branch="develop", event_name="merge_group"))
    assert {"test", "lint-and-type-check", "workflow-lint"} <= names


def test_merge_group_does_not_request_pull_request_only_mutation_evidence(
    check: ModuleType,
) -> None:
    """The mutation gate's job is `if: github.event_name == 'pull_request'`
    under a workflow with no merge_group trigger (#2270), so a synthetic
    queue SHA can never carry it — the same class as `pr-base` (#2059)."""
    names = check.required_check_names(base_branch="develop", event_name="merge_group")
    assert "Mutation gate (changed critical lines)" not in names
    assert "pr-base" not in names
    assert check.INTEGRATION_SCOPE_CHECK in names

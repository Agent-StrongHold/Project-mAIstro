from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-integration-scope.py"
ALL_RESULTS = {
    "postgres (pg17)": "success",
    "postgres (pg18)": "success",
    "object storage (MinIO)": "success",
    "durable-events": "success",
    "strike-ladder": "success",
    "hive-conductor-e2e": "success",
    "hive-conductor-e2e-ui": "success",
    "wheel-imports": "success",
    "docker-build": "success",
}


@pytest.fixture(scope="module")
def check():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("check_integration_scope", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _scope(**overrides: bool) -> str:
    value = {
        "postgres": False,
        "object_storage": False,
        "durable_events": False,
        "strike_ladder": False,
        "hive_e2e": False,
        "wheel_imports": False,
        "docker_build": False,
    }
    value.update(overrides)
    return json.dumps(value)


def test_pull_request_preserves_all_specialized_checks(check) -> None:
    assert check.required_checks("pull_request", _scope()) == set(ALL_RESULTS)


def test_protected_push_preserves_all_specialized_checks(check) -> None:
    assert check.required_checks("push", _scope()) == set(ALL_RESULTS)


def test_docs_only_merge_group_can_require_no_specialized_check(check) -> None:
    assert check.required_checks("merge_group", _scope()) == set()


def test_hive_scope_requires_both_hive_checks(check) -> None:
    required = check.required_checks(
        "merge_group",
        _scope(hive_e2e=True, wheel_imports=True, docker_build=True),
    )
    assert required == {
        "hive-conductor-e2e",
        "hive-conductor-e2e-ui",
        "wheel-imports",
        "docker-build",
    }


def test_missing_scope_fails_closed_to_every_check(check) -> None:
    assert check.required_checks("merge_group", None) == set(ALL_RESULTS)


def test_malformed_scope_fails_closed_to_every_check(check) -> None:
    assert check.required_checks("merge_group", "not-json") == set(ALL_RESULTS)


def test_incomplete_scope_fails_closed_to_every_check(check) -> None:
    scope_json = json.dumps({"postgres": False})
    assert check.required_checks("merge_group", scope_json) == set(ALL_RESULTS)


def test_non_boolean_scope_fails_closed_to_every_check(check) -> None:
    scope = json.loads(_scope())
    scope["postgres"] = "false"
    assert check.required_checks("merge_group", json.dumps(scope)) == set(ALL_RESULTS)


def test_selected_check_must_succeed(check) -> None:
    findings = check.evaluate(
        "merge_group",
        _scope(postgres=True),
        {"postgres (pg17)": "failure", "postgres (pg18)": "success"},
    )
    assert findings == ["postgres (pg17): required but result was failure"]


def test_out_of_scope_skipped_check_is_not_a_finding(check) -> None:
    results = {**ALL_RESULTS, "postgres (pg17)": "skipped"}
    assert check.evaluate("merge_group", _scope(), results) == []


def test_out_of_scope_executed_failure_is_a_finding(check) -> None:
    results = {"postgres (pg17)": "failure"}
    assert check.evaluate("merge_group", _scope(), results) == [
        "postgres (pg17): out of scope but result was failure"
    ]


def test_pull_request_skipped_check_is_a_finding(check) -> None:
    results = {**ALL_RESULTS, "postgres (pg17)": "skipped"}
    assert check.evaluate("pull_request", _scope(), results) == [
        "postgres (pg17): required but result was skipped"
    ]


def test_selected_hive_scope_requires_both_results(check) -> None:
    results = {
        "hive-conductor-e2e": "success",
        "hive-conductor-e2e-ui": "skipped",
    }
    assert check.evaluate("merge_group", _scope(hive_e2e=True), results) == [
        "hive-conductor-e2e-ui: required but result was skipped"
    ]

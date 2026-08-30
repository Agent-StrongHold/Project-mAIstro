from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-integration-scope.py"
ALL_RESULTS = {
    "postgres": "success",
    "object-storage": "success",
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
    assert check.required_jobs("pull_request", _scope()) == set(ALL_RESULTS)


def test_protected_push_preserves_all_specialized_checks(check) -> None:
    assert check.required_jobs("push", _scope()) == set(ALL_RESULTS)


def test_docs_only_merge_group_can_require_no_specialized_job(check) -> None:
    assert check.required_jobs("merge_group", _scope()) == set()


def test_hive_scope_requires_both_hive_jobs(check) -> None:
    required = check.required_jobs(
        "merge_group",
        _scope(hive_e2e=True, wheel_imports=True, docker_build=True),
    )
    assert required == {
        "hive-conductor-e2e",
        "hive-conductor-e2e-ui",
        "wheel-imports",
        "docker-build",
    }


def test_missing_scope_fails_closed_to_every_job(check) -> None:
    assert check.required_jobs("merge_group", None) == set(ALL_RESULTS)


def test_malformed_scope_fails_closed_to_every_job(check) -> None:
    assert check.required_jobs("merge_group", "not-json") == set(ALL_RESULTS)


def test_incomplete_scope_fails_closed_to_every_job(check) -> None:
    assert check.required_jobs("merge_group", json.dumps({"postgres": False})) == set(ALL_RESULTS)


def test_non_boolean_scope_fails_closed_to_every_job(check) -> None:
    scope = json.loads(_scope())
    scope["postgres"] = "false"
    assert check.required_jobs("merge_group", json.dumps(scope)) == set(ALL_RESULTS)


def test_selected_job_must_succeed(check) -> None:
    findings = check.evaluate("merge_group", _scope(postgres=True), {"postgres": "failure"})
    assert findings == ["postgres: required but result was failure"]


def test_out_of_scope_skipped_job_is_not_a_finding(check) -> None:
    results = {**ALL_RESULTS, "postgres": "skipped"}
    assert check.evaluate("merge_group", _scope(), results) == []


def test_pull_request_skipped_job_is_a_finding(check) -> None:
    results = {**ALL_RESULTS, "postgres": "skipped"}
    assert check.evaluate("pull_request", _scope(), results) == [
        "postgres: required but result was skipped"
    ]


def test_selected_hive_scope_requires_both_results(check) -> None:
    results = {
        "hive-conductor-e2e": "success",
        "hive-conductor-e2e-ui": "skipped",
    }
    assert check.evaluate("merge_group", _scope(hive_e2e=True), results) == [
        "hive-conductor-e2e-ui: required but result was skipped"
    ]

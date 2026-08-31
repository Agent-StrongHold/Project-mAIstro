from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
CONTRACT_SCRIPT = ROOT / "scripts" / "check-required-checks.py"

SPECIALIZED = {
    "postgres": "postgres",
    "object-storage": "object_storage",
    "durable-events": "durable_events",
    "strike-ladder": "strike_ladder",
    "hive-conductor-e2e": "hive_e2e",
    "hive-conductor-e2e-ui": "hive_e2e",
    "wheel-imports": "wheel_imports",
    "docker-build": "docker_build",
}


def _jobs() -> dict[str, object]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def _contract_gate():
    loader = importlib.util.spec_from_file_location
    spec = loader("_ci_scope_required_checks", CONTRACT_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_required_workflow_lint_job_emits_every_specialized_leg() -> None:
    scope = _jobs()["workflow-lint"]
    outputs = scope["outputs"]
    assert set(outputs) == set(SPECIALIZED.values())

    prefix = "${{ steps.scope.outputs."
    output_refs_are_scoped = [value.startswith(prefix) for value in outputs.values()]
    assert all(output_refs_are_scoped)

    checkout = scope["steps"][0]
    assert checkout["uses"] == "actions/checkout@v4"
    assert checkout["with"]["fetch-depth"] == 0

    command = scope["steps"][1]["run"]
    assert "ci_merge_group_scope.py --github-outputs" in command
    assert "$GITHUB_OUTPUT" in command


def test_every_specialized_job_is_gated_only_for_the_develop_merge_queue() -> None:
    jobs = _jobs()
    event_guard = "github.event_name != 'merge_group'"
    base_guard = "github.event.merge_group.base_ref != 'refs/heads/develop'"

    for job_name, output in SPECIALIZED.items():
        job = jobs[job_name]
        assert job["needs"] == "workflow-lint", job_name

        condition = job["if"]
        output_guard = f"needs.workflow-lint.outputs.{output} == 'true'"
        assert event_guard in condition, job_name
        assert base_guard in condition, job_name
        assert output_guard in condition, job_name


def test_merge_group_base_targeting_does_not_narrow_the_pr_check_contract() -> None:
    gate = _contract_gate()
    merge_condition = _jobs()["docker-build"]["if"]
    merge_scope = gate._job_scope({"if": merge_condition}, "every PR")
    assert merge_scope == "every PR"

    pr_condition = "github.event_name == 'pull_request' && github.base_ref == 'main'"
    pr_scope = gate._job_scope({"if": pr_condition}, "every PR")
    assert pr_scope == "every PR, job `if:` on base_ref"


def test_scope_producer_reuses_an_existing_required_check() -> None:
    jobs = _jobs()
    assert "specialized-scope" not in jobs
    assert "workflow-lint" in jobs


def test_unconditional_core_jobs_do_not_depend_on_a_new_scope_check() -> None:
    jobs = _jobs()
    core_jobs = ("test", "lint-and-type-check", "workflow-lint", "security")
    for job_name in core_jobs:
        assert jobs[job_name].get("needs") != "specialized-scope", job_name

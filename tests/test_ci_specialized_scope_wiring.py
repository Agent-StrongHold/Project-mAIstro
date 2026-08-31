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
    spec = importlib.util.spec_from_file_location(
        "_ci_scope_required_checks", CONTRACT_SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_required_workflow_lint_job_emits_every_specialized_leg() -> None:
    scope = _jobs()["workflow-lint"]
    outputs = scope["outputs"]
    assert set(outputs) == set(SPECIALIZED.values())
    assert all(
        value.startswith("${{ steps.scope.outputs.") for value in outputs.values()
    )

    checkout = scope["steps"][0]
    assert checkout["uses"] == "actions/checkout@v4"
    assert checkout["with"]["fetch-depth"] == 0
    command = scope["steps"][1]["run"]
    assert "ci_merge_group_scope.py --github-outputs" in command
    assert "$GITHUB_OUTPUT" in command


def test_every_specialized_job_is_gated_only_for_the_develop_merge_queue() -> None:
    jobs = _jobs()
    for job_name, output in SPECIALIZED.items():
        job = jobs[job_name]
        assert job["needs"] == "workflow-lint", job_name
        condition = job["if"]
        assert "github.event_name != 'merge_group'" in condition, job_name
        assert (
            "github.event.merge_group.base_ref != 'refs/heads/develop'" in condition
        ), job_name
        assert f"needs.workflow-lint.outputs.{output} == 'true'" in condition, job_name


def test_merge_group_base_targeting_does_not_narrow_the_pr_check_contract() -> None:
    gate = _contract_gate()
    condition = _jobs()["docker-build"]["if"]
    assert gate._job_scope({"if": condition}, "every PR") == "every PR"
    assert gate._job_scope(
        {"if": "github.event_name == 'pull_request' && github.base_ref == 'main'"},
        "every PR",
    ) == "every PR, job `if:` on base_ref"


def test_scope_producer_reuses_an_existing_required_check() -> None:
    jobs = _jobs()
    assert "specialized-scope" not in jobs
    assert "workflow-lint" in jobs


def test_unconditional_core_jobs_do_not_depend_on_a_new_scope_check() -> None:
    jobs = _jobs()
    for job_name in ("test", "lint-and-type-check", "workflow-lint", "security"):
        assert jobs[job_name].get("needs") != "specialized-scope", job_name

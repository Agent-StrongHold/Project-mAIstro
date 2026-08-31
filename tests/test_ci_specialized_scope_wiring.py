from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

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


def test_scope_job_emits_every_specialized_leg() -> None:
    scope = _jobs()["specialized-scope"]
    outputs = scope["outputs"]
    assert set(outputs) == set(SPECIALIZED.values())
    assert all(value.startswith("${{ steps.scope.outputs.") for value in outputs.values())

    checkout = scope["steps"][0]
    assert checkout["uses"] == "actions/checkout@v4"
    assert checkout["with"]["fetch-depth"] == 0
    command = scope["steps"][1]["run"]
    assert "ci_merge_group_scope.py --github-outputs" in command
    assert "$GITHUB_OUTPUT" in command


def test_every_specialized_job_is_gated_by_its_scope_output() -> None:
    jobs = _jobs()
    for job_name, output in SPECIALIZED.items():
        job = jobs[job_name]
        assert job["needs"] == "specialized-scope", job_name
        assert job["if"] == f"needs.specialized-scope.outputs.{output} == 'true'", job_name


def test_scope_producer_is_not_itself_a_required_check_name() -> None:
    jobs = _jobs()
    scope = jobs["specialized-scope"]
    assert scope.get("name", "specialized-scope") != "integration-scope"
    assert "specialized-scope" not in {
        "test",
        "lint-and-type-check",
        "workflow-lint",
        "integration-scope",
    }


def test_unconditional_core_jobs_do_not_wait_on_specialized_scope() -> None:
    jobs = _jobs()
    for job_name in ("test", "lint-and-type-check", "workflow-lint", "security"):
        assert jobs[job_name].get("needs") != "specialized-scope", job_name

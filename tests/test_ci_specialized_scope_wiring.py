from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from scripts.ci_merge_group_scope import scope_for_event

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SECURITY_WORKFLOW = ROOT / ".github" / "workflows" / "security.yml"
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


def _jobs() -> dict[str, Any]:
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
    assert checkout["uses"] == "actions/checkout@v7"
    assert checkout["with"]["fetch-depth"] == 0

    command = scope["steps"][1]["run"]
    assert "ci_merge_group_scope.py --github-outputs" in command
    assert "$GITHUB_OUTPUT" in command


def test_specialized_scope_gates_preserve_required_matrix_contexts() -> None:
    jobs = _jobs()
    event_guard = "github.event_name != 'merge_group'"
    base_guard = "github.event.merge_group.base_ref != 'refs/heads/develop'"

    for job_name, output in SPECIALIZED.items():
        job = jobs[job_name]
        assert job["needs"] == "workflow-lint", job_name

        if job_name == "postgres":
            # GitHub evaluates job-level if before expanding the matrix. A
            # skipped matrix cannot report the two required concrete names.
            assert "if" not in job, job_name
            continue

        condition = job["if"]
        output_guard = f"needs.workflow-lint.outputs.{output} == 'true'"
        assert event_guard in condition, job_name
        assert base_guard in condition, job_name
        assert output_guard in condition, job_name


@pytest.mark.parametrize(
    ("changed_path", "postgres_in_scope"),
    [
        ("docs/ci/MERGE-QUEUE.md", False),
        ("packages/hive-conductor/backend/services/evolution.py", False),
        ("alembic.ini", True),
        ("uv.lock", True),
    ],
)
def test_postgres_matrix_is_not_filtered_by_merge_group_path_scope(
    changed_path: str, postgres_in_scope: bool
) -> None:
    scope = scope_for_event("merge_group", [changed_path])
    assert scope["postgres"] is postgres_in_scope
    # Scope remains truthful for its other consumers, but cannot suppress the
    # matrix GitHub requires on every merge-group head, even for docs/Hive.
    postgres = _jobs()["postgres"]
    assert postgres["needs"] == "workflow-lint"
    assert "if" not in postgres
    assert all("if" not in step for step in postgres["steps"])


def test_postgres_matrix_keeps_both_required_names_and_real_database_checks() -> None:
    postgres = _jobs()["postgres"]
    versions = postgres["strategy"]["matrix"]["postgres"]
    assert versions == ["17", "18"]
    names = {postgres["name"].replace("${{ matrix.postgres }}", version) for version in versions}
    assert names == {"postgres (pg17)", "postgres (pg18)"}
    assert postgres["strategy"]["fail-fast"] is False
    assert postgres["services"]["postgres"]["image"] == "pgvector/pgvector:pg${{ matrix.postgres }}"
    assert not postgres.get("continue-on-error", False)
    steps = postgres["steps"]
    assert all(not step.get("continue-on-error", False) for step in steps)
    commands = "\n".join(step.get("run", "") for step in steps)
    for required in (
        "uv run pytest tests/migrations/test_migration_chain.py",
        "uv run alembic upgrade head",
        "uv run alembic downgrade base",
        "uv run pytest packages/maistro-core/tests/persistence",
        "uv run pytest packages/maistro-core/tests/test_container_postgres.py",
        "uv run pytest packages/maistro-core/tests/workspaces",
    ):
        assert required in commands
    workspace = next(step for step in steps if "tests/workspaces" in step.get("run", ""))
    assert workspace["env"]["MAISTRO_REQUIRE_PG_LEGS"] == "1"


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
    core_jobs = ("test", "lint-and-type-check", "workflow-lint")
    for job_name in core_jobs:
        assert jobs[job_name].get("needs") != "specialized-scope", job_name

    # `security` left ci.yml in #1357's granular split; the contract follows
    # the jobs, not the file they sit in, so its new home is guarded the
    # same way.
    security_jobs = yaml.safe_load(SECURITY_WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    for job_name in security_jobs:
        assert security_jobs[job_name].get("needs") != "specialized-scope", job_name

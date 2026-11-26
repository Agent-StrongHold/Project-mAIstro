"""The Quality split preserves each accepted obligation and its required verdict."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
OBLIGATIONS = json.loads((ROOT / "tests/fixtures/ci_quality_obligations.json").read_text())
JOB_IDS = tuple(OBLIGATIONS["jobs"])
SUMMARY = "Quality gate (Pillars 1\u20134, 7, 8)"


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@pytest.fixture
def workflow():
    return yaml.safe_load((ROOT / ".github/workflows/quality.yml").read_text())


def _assert_contract(document):
    """Compare moved commands to the accepted pre-split obligation inventory."""
    baseline = OBLIGATIONS["workflow"]
    assert document["name"] == baseline["name"]
    assert document["permissions"] == baseline["permissions"]
    assert document.get("on", document.get(True)) == baseline["triggers"]
    assert document["concurrency"] == baseline["concurrency"]
    jobs = document["jobs"]
    assert set(jobs) == set(JOB_IDS) | set(OBLIGATIONS["coverage_jobs"]) | {"quality-gate"}
    for name, digest in OBLIGATIONS["coverage_jobs"].items():
        assert _digest(jobs[name]) == digest
    for job_id, expected in OBLIGATIONS["jobs"].items():
        job = jobs[job_id]
        assert job["name"] == expected["name"]
        assert job["runs-on"] == "ubuntu-latest"
        assert job["timeout-minutes"] == 20
        assert not {"if", "needs", "strategy", "continue-on-error", "defaults"} & set(job)
        environment = {"RATCHET_BASE_REV": OBLIGATIONS["ratchet_base_rev"]}
        if expected["postgres"]:
            assert job["services"] == OBLIGATIONS["postgres_services"]
            environment.update(OBLIGATIONS["postgres_env"])
        else:
            assert "services" not in job
        assert job["env"] == environment
        steps = list(job["steps"])
        setup = OBLIGATIONS["setup_steps"]
        assert steps[: len(setup)] == setup
        steps = steps[len(setup) :]
        if expected["age"]:
            assert _digest(steps.pop(0)) == OBLIGATIONS["age_step_sha256"]
        if expected["tools"]:
            tool_step = steps.pop(0)
            assert tool_step == {
                "name": "Install this check's analyzer",
                "run": f"uv pip install {expected['tools']}",
            }
        assert [_digest(step) for step in steps] == [step["sha256"] for step in expected["steps"]]
    summary = jobs["quality-gate"]
    assert summary["name"] == SUMMARY
    assert summary.get("if") == "${{ always() }}"
    assert summary["needs"] == list(JOB_IDS)
    assert not {"continue-on-error", "strategy", "defaults"} & set(summary)
    verdict = summary["steps"][-1]
    assert verdict["env"] == {"CHECK_RESULTS": "${{ toJSON(needs) }}"}
    assert shlex.split(verdict["run"]) == ["python", "scripts/check_ci_job_results.py", *JOB_IDS]
    assert not {"if", "continue-on-error", "shell", "working-directory"} & set(verdict)


def test_every_original_quality_obligation_survives_with_its_profile(workflow):
    _assert_contract(workflow)
    commands = [step.get("run") for job in workflow["jobs"].values() for step in job["steps"]]
    assert commands.count("uv run python scripts/check-credential-authority.py") == 1


@pytest.mark.parametrize("job_id", JOB_IDS)
def test_each_leaf_is_enforced_by_the_existing_required_summary(workflow, job_id):
    policy = json.loads((ROOT / ".github/branch-protection.json").read_text())
    leaf = workflow["jobs"][job_id]
    for branch in ("develop", "main"):
        assert SUMMARY in policy["branches"][branch]["required_status_checks"]["contexts"]
    assert SUMMARY in policy["advisory"][leaf["name"]]
    assert job_id in workflow["jobs"]["quality-gate"]["needs"]


def _run_summary(workflow, results):
    verdict = workflow["jobs"]["quality-gate"]["steps"][-1]
    env = dict(os.environ, CHECK_RESULTS=json.dumps(results))
    env["PATH"] = str(ROOT / ".venv/bin") + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        shlex.split(verdict["run"]),
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_actual_quality_summary_accepts_only_complete_success(workflow):
    assert _run_summary(workflow, {job: {"result": "success"} for job in JOB_IDS}).returncode == 0


@pytest.mark.parametrize("job_id", JOB_IDS)
def test_actual_summary_refuses_each_failed_leaf(workflow, job_id):
    results = {job: {"result": "success"} for job in JOB_IDS}
    results[job_id]["result"] = "failure"
    assert _run_summary(workflow, results).returncode == 1


@pytest.mark.parametrize("mutation", ["edge", "always", "tolerate", "rename", "expected-id"])
def test_detaching_a_summary_obligation_is_detected(workflow, mutation):
    summary = workflow["jobs"]["quality-gate"]
    if mutation == "edge":
        summary["needs"].pop()
    elif mutation == "always":
        del summary["if"]
    elif mutation == "tolerate":
        summary["continue-on-error"] = True
    elif mutation == "rename":
        summary["name"] = "advisory"
    else:
        summary["steps"][-1]["run"] = summary["steps"][-1]["run"].replace(JOB_IDS[-1], "")
    with pytest.raises(AssertionError):
        _assert_contract(workflow)


@pytest.mark.parametrize(
    "mutation", ["drop", "skip", "tolerate", "alter-command", "alter-base", "narrow-tree"]
)
def test_static_obligation_regressions_are_detected(workflow, mutation):
    job = workflow["jobs"]["quality-reachability"]
    if mutation == "drop":
        job["steps"].pop()
    elif mutation == "skip":
        job["if"] = "false"
    elif mutation == "tolerate":
        job["steps"][-1]["continue-on-error"] = True
    elif mutation == "alter-command":
        job["steps"][-1]["run"] += " || true"
    elif mutation == "alter-base":
        job["env"]["RATCHET_BASE_REV"] = "HEAD"
    else:
        job["steps"][0]["with"]["sparse-checkout"] = "scripts"
    with pytest.raises(AssertionError):
        _assert_contract(workflow)


@pytest.mark.parametrize("job_id", ["quality-acceptance", "quality-hypothesis"])
@pytest.mark.parametrize("mutation", ["service", "dsn", "migration", "evolve"])
def test_service_backed_proofs_cannot_become_skipped_surrogates(workflow, job_id, mutation):
    job = workflow["jobs"][job_id]
    if mutation == "service":
        del job["services"]
    elif mutation == "dsn":
        del job["env"]["MAISTRO_TEST_PG_DSN"]
    else:
        run = (
            "uv run alembic upgrade head"
            if mutation == "migration"
            else "uv pip install -e packages/maistro-evolve"
        )
        job["steps"] = [step for step in job["steps"] if step.get("run") != run]
    with pytest.raises((AssertionError, KeyError)):
        _assert_contract(workflow)


def test_acceptance_retains_age_and_all_criteria_in_one_measurement(workflow):
    job = workflow["jobs"]["quality-acceptance"]
    broken = copy.deepcopy(workflow)
    broken["jobs"]["quality-acceptance"]["steps"] = [
        step for step in job["steps"] if step.get("name") != "install age + age-keygen"
    ]
    with pytest.raises(AssertionError):
        _assert_contract(broken)
    command = job["steps"][-1]["run"]
    assert "--run-tests --ratchet --mandate" in command
    assert "--run-tests --ratchet" in command

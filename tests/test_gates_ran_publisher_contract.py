"""Contract tests for the trusted gates-ran publisher."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GATE_SCRIPT = ROOT / "scripts" / "check-gates-ran.py"
WORKFLOW = ROOT / ".github" / "workflows" / "gates-ran.yml"


def _gate_module():
    spec = importlib.util.spec_from_file_location("gates_ran_scope_contract", GATE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_main_includes_base_coupled_release_checks():
    gate = _gate_module()
    names = gate.required_check_names(base_branch="main")
    assert [name for name in names if name.startswith("Analyze (")]
    assert "Container scan + SBOM + cosign" in names


def test_develop_excludes_main_only_release_checks():
    gate = _gate_module()
    names = gate.required_check_names(base_branch="develop")
    assert not [name for name in names if name.startswith("Analyze (")]
    assert "Container scan + SBOM + cosign" not in names


def test_publisher_has_only_the_write_permission_it_needs():
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert doc["permissions"] == {
        "checks": "read",
        "contents": "read",
        "pull-requests": "read",
        "statuses": "write",
    }
    assert doc["jobs"]["publish-gates-ran"]["name"] == "gates-ran-publisher"


def test_publisher_delegates_path_scope_to_the_checked_in_evaluator():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--changed-files changed-files.json" in text
    assert "<<'PY'" not in text
    assert "DevSkim" in text


def test_publisher_triggers_devskim_exactly_once() -> None:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = doc.get(True) or doc.get("on")

    assert triggers["workflow_run"]["workflows"].count("DevSkim") == 1


def test_publisher_targets_the_pr_head_from_trusted_workflow_run_code():
    text = WORKFLOW.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    triggers = doc.get(True) or doc.get("on")

    assert "workflow_run" in triggers
    assert "pull_request" not in triggers
    assert "pull_request_target" not in triggers
    assert "createCommitStatus" in text
    assert "context: 'gates-ran'" in text
    assert "github.event.repository.default_branch" in text
    assert "github.event.workflow_run.head_sha" in text


def _publish_step() -> dict:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return next(
        step
        for step in doc["jobs"]["publish-gates-ran"]["steps"]
        if step.get("name", "").startswith("Publish gates-ran")
    )


def _run_publish_script(env: dict[str, str]) -> dict:
    """Execute the shipped inline JS with fake APIs, never live GitHub writes."""
    node = shutil.which("node")
    assert node is not None, "Node is required for publisher contract tests (no skips)"
    prelude = (
        "const statuses = []; const failures = []; const infos = [];\n"
        "const github = { rest: { repos: { createCommitStatus: async (p) => { statuses.push(p); } } } };\n"
        "const core = { info: (m) => infos.push(m), setFailed: (m) => failures.push(m) };\n"
        "const context = { repo: { owner: 'o', repo: 'r' }, serverUrl: 'https://gh', runId: 1 };\n"
        "process.env = JSON.parse(process.env.__FAKE_ENV);\n"
    )
    # github-script wraps top-level return/await in an async function too.
    script = prelude + "(async () => {\n" + _publish_step()["with"]["script"]
    script += (
        "\n})().then(() => process.stdout.write(JSON.stringify({statuses, failures, infos})));"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        env={
            "__FAKE_ENV": json.dumps(env),
            "PATH": os.pathsep.join([str(Path(node).parent), "/usr/bin", "/bin"]),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, f"publish script crashed:\n{result.stderr}"
    return json.loads(result.stdout)


def test_publish_step_is_cancellation_aware_but_runs_after_failure():
    step = _publish_step()
    assert step["if"] == "!cancelled() && steps.target.outputs.head_sha != ''"
    assert step["env"]["JOB_STATUS"] == "${{ job.status }}"
    assert step["env"]["HEAD_SHA"] == "${{ steps.target.outputs.head_sha }}"
    assert step["env"]["EVALUATION_EXIT_CODE"] == "${{ steps.evaluate.outputs.exit_code }}"


@pytest.mark.parametrize("exit_code", [None, "", "0", "1", "2", "3", "error"])
def test_cancelled_publisher_never_writes_a_status(exit_code: str | None):
    env = {"HEAD_SHA": "a" * 40, "JOB_STATUS": "cancelled"}
    if exit_code is not None:
        env["EVALUATION_EXIT_CODE"] = exit_code
    calls = _run_publish_script(env)
    assert calls["statuses"] == []
    assert calls["failures"] == []


@pytest.mark.parametrize("job_status", ["success", "failure"])
@pytest.mark.parametrize(
    ("exit_code", "expected_state"),
    [
        (None, "failure"),
        ("", "failure"),
        ("error", "failure"),
        ("3", "failure"),
        ("0", "success"),
        ("1", "failure"),
        ("2", "pending"),
    ],
)
def test_non_cancelled_publisher_preserves_verdict_and_target(
    exit_code: str | None, expected_state: str, job_status: str
):
    env = {"HEAD_SHA": "b" * 40, "JOB_STATUS": job_status}
    if exit_code is not None:
        env["EVALUATION_EXIT_CODE"] = exit_code
    calls = _run_publish_script(env)
    descriptions = {
        "success": "All required checks executed on this exact head",
        "pending": "Required execution evidence is still arriving",
        "failure": "Required execution evidence is missing or non-executed",
    }
    assert calls["statuses"] == [
        {
            "owner": "o",
            "repo": "r",
            "sha": "b" * 40,
            "state": expected_state,
            "context": "gates-ran",
            "description": descriptions[expected_state],
            "target_url": "https://gh/o/r/actions/runs/1",
        }
    ]
    assert calls["failures"] == ([descriptions["failure"]] if expected_state == "failure" else [])

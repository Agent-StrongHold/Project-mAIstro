"""Contract tests for the trusted gates-ran publisher."""

from __future__ import annotations

import importlib.util
import json
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


def _publish_script() -> str:
    """Extract the publish step's inline JS from the workflow artifact."""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"]["publish-gates-ran"]["steps"]
    publish = next(step for step in steps if step.get("name", "").startswith("Publish gates-ran"))
    return publish["with"]["script"]


def _run_publish_script(script: str, env: dict[str, str]) -> dict:
    """Execute the real publish JS against faked ``github``/``core`` APIs.

    Returns the observed calls so tests assert the behaviour of the artifact
    that actually ships, not a restatement of it.
    """
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the publish script")
    # The prelude defines the fakes the inline script expects (``github``,
    # ``core``, ``context``) and swaps ``process.env`` for the step env under
    # test, mirroring how actions/github-script binds step env into
    # process.env.
    prelude = (
        "const __statuses = []; let __failed = null; const __infos = [];\n"
        "const github = { rest: { repos: { createCommitStatus: async (p) => { __statuses.push(p); } } } };\n"
        "const core = { info: (m) => { __infos.push(m); }, setFailed: (m) => { __failed = m; } };\n"
        "const context = { repo: { owner: 'o', repo: 'r' }, serverUrl: 'https://gh', runId: 1 };\n"
        "process.env = JSON.parse(process.env.__FAKE_ENV || '{}');\n"
    )
    # actions/github-script executes the inline script inside an async
    # function body (which is why the script may use top-level ``return`` and
    # ``await``); the harness reproduces that wrapper.
    wrapped = "(async () => {\n" + script + "\n})().then(() => {\n"
    epilogue = (
        "process.stdout.write("
        "JSON.stringify({ statuses: __statuses, failed: __failed, infos: __infos }));\n});"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", prelude + wrapped + epilogue],
        env={"__FAKE_ENV": json.dumps(env), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, f"publish script crashed:\n{result.stderr}"
    payload = result.stdout.strip().splitlines()[-1]
    return json.loads(payload)


def test_cancelled_publisher_publishes_nothing_and_does_not_fail():
    """Run 36274594751: a cancelled publisher must not smear failure (regression)."""
    calls = _run_publish_script(
        _publish_script(),
        {"HEAD_SHA": "a" * 40, "EVALUATION_EXIT_CODE": "", "JOB_STATUS": "cancelled"},
    )
    assert calls["statuses"] == []
    assert calls["failed"] is None


def test_blank_exit_code_is_pending_not_failure():
    calls = _run_publish_script(
        _publish_script(),
        {"HEAD_SHA": "a" * 40, "EVALUATION_EXIT_CODE": "", "JOB_STATUS": "success"},
    )
    assert len(calls["statuses"]) == 1
    assert calls["statuses"][0]["state"] == "pending"
    assert calls["failed"] is None


@pytest.mark.parametrize(
    ("exit_code", "expected_state"),
    [("0", "success"), ("1", "failure"), ("2", "pending"), ("3", "failure")],
)
def test_recorded_exit_codes_map_to_status_states(exit_code: str, expected_state: str):
    calls = _run_publish_script(
        _publish_script(),
        {"HEAD_SHA": "a" * 40, "EVALUATION_EXIT_CODE": exit_code, "JOB_STATUS": "success"},
    )
    assert len(calls["statuses"]) == 1
    assert calls["statuses"][0]["state"] == expected_state
    assert calls["statuses"][0]["context"] == "gates-ran"
    if expected_state == "failure":
        assert calls["failed"] is not None
    else:
        assert calls["failed"] is None

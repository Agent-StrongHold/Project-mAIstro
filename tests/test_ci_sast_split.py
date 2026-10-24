"""Independently retryable scanners must still feed the required SAST gate."""

from __future__ import annotations

import copy
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from scripts.check_ci_job_results import failures, main

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "security.yml"
SCANNERS = {
    "sast-bandit": "SAST / Bandit",
    "sast-semgrep": "SAST / Semgrep",
    "sast-gitleaks": "SAST / Gitleaks",
}
SUMMARY_COMMAND = "python scripts/check_ci_job_results.py " + " ".join(SCANNERS)
CHECKOUT = {"uses": "actions/checkout@v7", "with": {"fetch-depth": 0}}
PYTHON_SETUP = [
    {"name": "Install uv + Python", "uses": "./.github/actions/setup-uv"},
    {"name": "Setup Python 3.12", "run": "uv python install 3.12"},
    {"name": "uv sync", "run": "uv sync --locked --all-extras"},
]


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def _assert_split(workflow):
    jobs = workflow["jobs"]
    for job_id, name in SCANNERS.items():
        job = jobs[job_id]
        assert job["name"] == name
        assert job["runs-on"] == "ubuntu-latest"
        assert job["timeout-minutes"] == 10
        for option in ("if", "needs", "strategy", "continue-on-error", "uses", "defaults"):
            assert option not in job, (job_id, option)
        assert job["steps"][0] == CHECKOUT
        for step in job["steps"]:
            for option in ("if", "continue-on-error", "working-directory", "shell"):
                assert option not in step, (job_id, option)

    assert "defaults" not in workflow
    bandit = jobs["sast-bandit"]["steps"]
    semgrep = jobs["sast-semgrep"]["steps"]
    gitleaks = jobs["sast-gitleaks"]["steps"]
    assert bandit[1:4] == semgrep[1:4] == PYTHON_SETUP
    assert len(bandit) == 6 and len(semgrep) == 5 and len(gitleaks) == 3
    assert bandit[4] == {"name": "install SAST tools", "run": "uv pip install bandit"}
    assert bandit[5]["run"] == BANDIT_COMMAND
    assert semgrep[4]["run"] == SEMGREP_COMMAND
    assert gitleaks[1]["run"] == GITLEAKS_INSTALL
    assert gitleaks[2]["run"] == GITLEAKS_COMMAND
    assert gitleaks[2]["env"] == {
        "EVENT_NAME": "${{ github.event_name }}",
        "REF_NAME": "${{ github.ref_name }}",
        "BASE_SHA": "${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha }}",
        "HEAD_SHA": (
            "${{ github.event.pull_request.head.sha || "
            "github.event.merge_group.head_sha || github.sha }}"
        ),
        "BEFORE_SHA": "${{ github.event.before }}",
    }

    summary = jobs["sast"]
    assert summary["name"] == "SAST (bandit + semgrep + gitleaks)"
    assert summary["if"] == "${{ always() }}"
    assert summary["needs"] == list(SCANNERS)
    assert summary["runs-on"] == "ubuntu-latest"
    assert "continue-on-error" not in summary
    assert "defaults" not in summary
    assert "strategy" not in summary
    assert summary["steps"] == [
        {"uses": "actions/checkout@v7"},
        {"uses": "actions/setup-python@v7", "with": {"python-version": "3.12"}},
        {
            "name": "Require every SAST scanner to succeed",
            "env": {"CHECK_RESULTS": "${{ toJSON(needs) }}"},
            "run": SUMMARY_COMMAND,
        },
    ]


def test_scanners_are_independent_and_summary_preserves_the_required_name(workflow):
    _assert_split(workflow)


@pytest.mark.parametrize("job_id", SCANNERS)
@pytest.mark.parametrize(
    "option,value",
    [("if", "false"), ("needs", "sast"), ("continue-on-error", True), ("strategy", {})],
)
def test_scanner_cannot_be_skipped_tolerated_or_coupled(workflow, job_id, option, value):
    changed = copy.deepcopy(workflow)
    changed["jobs"][job_id][option] = value
    with pytest.raises(AssertionError):
        _assert_split(changed)


@pytest.mark.parametrize("job_id", SCANNERS)
@pytest.mark.parametrize("option,value", [("if", "false"), ("continue-on-error", True)])
def test_scanner_steps_cannot_become_advisory(workflow, job_id, option, value):
    changed = copy.deepcopy(workflow)
    changed["jobs"][job_id]["steps"][-1][option] = value
    with pytest.raises(AssertionError):
        _assert_split(changed)


@pytest.mark.parametrize("job_id", SCANNERS)
def test_summary_cannot_drop_a_scanner_dependency(workflow, job_id):
    changed = copy.deepcopy(workflow)
    changed["jobs"]["sast"]["needs"].remove(job_id)
    with pytest.raises(AssertionError):
        _assert_split(changed)


@pytest.mark.parametrize(
    "job_id,index,before,after",
    [
        ("sast-bandit", 5, "-ll --confidence-level=medium", "-lll --confidence-level=high"),
        ("sast-bandit", 5, "packages/hive-conductor/backend", "packages/maistro-core/src"),
        ("sast-semgrep", 4, "--config p/secrets", "--config p/python"),
        ("sast-semgrep", 4, "--error packages/ tests/", "--error packages/"),
        ("sast-gitleaks", 1, "v8.30.1", "v8.29.0"),
        ("sast-gitleaks", 2, '--log-opts="--all"', '--log-opts="HEAD^..HEAD"'),
    ],
)
def test_scan_scope_severity_and_version_regressions_are_detected(
    workflow, job_id, index, before, after
):
    changed = copy.deepcopy(workflow)
    step = changed["jobs"][job_id]["steps"][index]
    assert before in step["run"]
    step["run"] = step["run"].replace(before, after)
    with pytest.raises(AssertionError):
        _assert_split(changed)


def _run_summary(workflow, results):
    step = workflow["jobs"]["sast"]["steps"][-1]
    return subprocess.run(
        shlex.split(step["run"]),
        cwd=ROOT,
        env={**os.environ, "CHECK_RESULTS": json.dumps(results)},
        capture_output=True,
        text=True,
        check=False,
    )


def _successful_results():
    return {job_id: {"result": "success", "outputs": {}} for job_id in SCANNERS}


def test_actual_summary_command_accepts_all_success(workflow):
    result = _run_summary(workflow, _successful_results())
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("job_id", SCANNERS)
@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", "pending", "unknown", None])
def test_actual_summary_command_fails_closed_for_every_non_success(workflow, job_id, result):
    results = _successful_results()
    results[job_id]["result"] = result
    completed = _run_summary(workflow, results)
    assert completed.returncode != 0
    assert job_id in completed.stdout + completed.stderr


@pytest.mark.parametrize("job_id", SCANNERS)
@pytest.mark.parametrize("missing", ["job", "result"])
def test_actual_summary_command_rejects_missing_results(workflow, job_id, missing):
    results = _successful_results()
    if missing == "job":
        del results[job_id]
    else:
        del results[job_id]["result"]
    completed = _run_summary(workflow, results)
    assert completed.returncode != 0
    expected = "dependency job IDs" if missing == "job" else job_id
    assert expected in completed.stdout + completed.stderr


@pytest.mark.parametrize(
    "raw,expected_code",
    [
        (json.dumps(_successful_results()), 0),
        ("", 1),
        ("{", 1),
        ("null", 1),
        ("[]", 1),
        ("{}", 1),
        (json.dumps({**_successful_results(), "unexpected": {"result": "success"}}), 1),
        (json.dumps({**_successful_results(), "sast-bandit": None}), 1),
        (json.dumps({**_successful_results(), "sast-semgrep": {}}), 1),
        (json.dumps({**_successful_results(), "sast-gitleaks": {"result": "skipped"}}), 1),
    ],
)
def test_summary_main_rejects_incomplete_or_malformed_evidence(
    monkeypatch, capsys, raw, expected_code
):
    monkeypatch.setenv("CHECK_RESULTS", raw)
    monkeypatch.setattr(sys, "argv", ["check_ci_job_results.py", *SCANNERS])
    assert main() == expected_code
    assert ("::error::" in capsys.readouterr().out) is bool(expected_code)


@pytest.mark.parametrize("expected", [[], ["sast-bandit", "sast-bandit"]])
def test_checker_rejects_empty_or_ambiguous_expected_set(expected):
    assert failures(expected, json.dumps(_successful_results()))


def test_checker_rejects_absent_evidence():
    assert failures(list(SCANNERS), None)


# These are the pre-split scan bodies, retained verbatim so job isolation
# cannot quietly narrow a security profile, range, threshold, or pinned tool.

BANDIT_COMMAND = r"""uv run bandit -r packages/maistro-core/src packages/hive-conductor/backend \
                packages/maistro-server/src \
                -ll --confidence-level=medium -f json -o bandit.json || true # bandit's verdict is re-derived from its JSON below
uv run python -c "
import json, sys
data = json.load(open('bandit.json'))
new = [r for r in data.get('results', []) if r.get('issue_severity') in {'MEDIUM','HIGH'}]
if new:
    print(f'::error::bandit found {len(new)} Medium+ finding(s) — strict 0-baseline:')
    for r in new:
        print(f'  {r[\"filename\"]}:{r[\"line_number\"]} [{r[\"test_id\"]}] {r[\"issue_text\"]}')
    sys.exit(1)
print('bandit Medium+ count: 0 (strict gate)')
"
"""

SEMGREP_COMMAND = r"""set -o pipefail
uvx semgrep --metrics off \
  --config tools/semgrep/maistro-rules.yaml \
  --config p/security-audit \
  --config p/owasp-top-ten \
  --config p/secrets \
  --exclude 'packages/hive-conductor/eval' \
  --exclude 'packages/hive-conductor/cage' \
  --error packages/ tests/ 2>&1 | tee semgrep-report.txt
"""

GITLEAKS_INSTALL = r"""set -euo pipefail
curl -sSfL -o gitleaks.tgz \
  https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz
echo "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb  gitleaks.tgz" | sha256sum --check
tar -xzf gitleaks.tgz gitleaks
sudo mv gitleaks /usr/local/bin/gitleaks
"""

GITLEAKS_COMMAND = r"""set -euo pipefail
if [ "$EVENT_NAME" = "pull_request" ] || [ "$EVENT_NAME" = "merge_group" ]; then
  gitleaks git --redact --log-opts="$BASE_SHA..$HEAD_SHA" .
elif [ "$EVENT_NAME" = "push" ] && [ "$REF_NAME" != "main" ] && [ "$REF_NAME" != "integration" ] && [ "$REF_NAME" != "develop" ]; then
  if [ -n "$BEFORE_SHA" ] && [ "$BEFORE_SHA" != "0000000000000000000000000000000000000000" ]; then
    gitleaks git --redact --log-opts="$BEFORE_SHA..$HEAD_SHA" .
  else
    gitleaks git --redact --log-opts="$HEAD_SHA^..$HEAD_SHA" .
  fi
else
  gitleaks git --redact --log-opts="--all" .
fi
"""

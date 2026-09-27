"""Cost collection includes retries and refuses incomplete or ambiguous evidence."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "measure-ci-cost.py"
HEAD = "a" * 40


@pytest.fixture
def cost():
    spec = importlib.util.spec_from_file_location("ci_cost_collection", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(identity: int = 1, **overrides) -> dict:
    return {
        "id": identity,
        "head_sha": HEAD,
        "path": ".github/workflows/ci.yml",
        "status": "completed",
        "conclusion": "success",
        "event": "pull_request",
        **overrides,
    }


def job(identity: int = 1, **overrides) -> dict:
    return {
        "id": identity,
        "name": "test",
        "status": "completed",
        "conclusion": "success",
        "started_at": "2026-09-26T10:00:00Z",
        "completed_at": "2026-09-26T10:02:00Z",
        "run_attempt": 1,
        **overrides,
    }


def api(monkeypatch, cost, runs: list, jobs: list):
    requests = []

    def get(path, token):
        assert token == "fixture-token"
        requests.append(path)
        url = urlparse(path)
        query = parse_qs(url.query)
        assert query["per_page"] == ["100"]
        page = int(query["page"][0])
        if url.path.endswith("/jobs"):
            assert query["filter"] == ["all"]
            key, rows = "jobs", jobs
        else:
            assert query["head_sha"] == [HEAD]
            key, rows = "workflow_runs", runs
        offset = (page - 1) * 100
        return json.loads(json.dumps({key: rows[offset : offset + 100], "total_count": len(rows)}))

    monkeypatch.setattr(cost, "_get", get)
    return requests


def test_retried_jobs_both_count_even_when_the_name_is_identical(cost, monkeypatch):
    attempts = [job(10, conclusion="failure"), job(20, run_attempt=2)]
    api(monkeypatch, cost, [run()], attempts)
    rows = cost.collect(HEAD, "fixture-token")
    assert [row["run_attempt"] for row in rows] == [1, 2]
    assert [row["job_id"] for row in rows] == [10, 20]
    assert {row["event"] for row in rows} == {"pull_request"}
    assert cost.split(cost.aggregate(rows))["after_any"] == 4.0


def test_all_job_pages_are_measured(cost, monkeypatch):
    requests = api(monkeypatch, cost, [run()], [job(i) for i in range(1, 206)])
    rows = cost.collect(HEAD, "fixture-token")
    assert len(rows) == 205
    assert len(requests) == 4
    assert cost.split(cost.aggregate(rows))["after_any"] == 410.0


def test_all_workflow_run_pages_are_read(cost, monkeypatch):
    requests = api(monkeypatch, cost, [run(i) for i in range(1, 102)], [])
    rows = cost._list_all(
        f"/repos/x/y/actions/runs?head_sha={HEAD}", "workflow_runs", "fixture-token"
    )
    assert len(rows) == 101
    assert len(requests) == 2


def test_unfiltered_path_uses_question_mark(cost, monkeypatch):
    seen = []

    def get(path, token):
        seen.append(path)
        return {"jobs": [], "total_count": 0}

    monkeypatch.setattr(cost, "_get", get)
    assert cost._list_all("/jobs", "jobs", "token") == []
    assert seen == ["/jobs?per_page=100&page=1"]


@pytest.mark.parametrize("total", [None, True, -1, "1"])
def test_invalid_total_is_not_an_empty_result(cost, total):
    with pytest.raises(ValueError, match="invalid jobs listing"):
        cost._page({"jobs": [], "total_count": total}, "jobs")


@pytest.mark.parametrize("rows", [None, {}, [None]])
def test_malformed_page_is_refused(cost, rows):
    with pytest.raises(ValueError, match="invalid jobs"):
        cost._page({"jobs": rows, "total_count": 1}, "jobs")


def test_search_limit_cannot_be_reported_as_complete(cost, monkeypatch):
    monkeypatch.setattr(cost, "_get", lambda *_: {"workflow_runs": [], "total_count": 1001})
    with pytest.raises(ValueError, match="1,000-result limit"):
        cost._list_all("/runs", "workflow_runs", "token")


def test_a_changed_listing_count_refuses_a_torn_measurement(cost, monkeypatch):
    pages = iter(
        [
            {"jobs": [job(i) for i in range(1, 101)], "total_count": 101},
            {"jobs": [job(101), job(102)], "total_count": 102},
        ]
    )
    monkeypatch.setattr(cost, "_get", lambda *_: next(pages))
    with pytest.raises(ValueError, match="changed during collection"):
        cost._list_all("/jobs", "jobs", "token")


def test_a_truncated_page_refuses_a_partial_total(cost, monkeypatch):
    monkeypatch.setattr(cost, "_get", lambda *_: {"jobs": [job()], "total_count": 2})
    with pytest.raises(ValueError, match="received 1 of 2"):
        cost._list_all("/jobs", "jobs", "token")


@pytest.mark.parametrize("identity", [None, True, 0, -1, "1"])
def test_bad_job_identity_is_refused(cost, monkeypatch, identity):
    monkeypatch.setattr(cost, "_get", lambda *_: {"jobs": [job(identity)], "total_count": 1})
    with pytest.raises(ValueError, match="invalid jobs identity"):
        cost._list_all("/jobs", "jobs", "token")


def test_duplicate_job_is_not_counted_twice(cost, monkeypatch):
    monkeypatch.setattr(cost, "_get", lambda *_: {"jobs": [job(), job()], "total_count": 2})
    with pytest.raises(ValueError, match="duplicate jobs identity"):
        cost._list_all("/jobs", "jobs", "token")


@pytest.mark.parametrize("status", ["queued", "in_progress", "waiting", None])
def test_running_jobs_are_not_zero_cost(cost, status):
    with pytest.raises(ValueError, match="measurement is incomplete"):
        cost._completed_job(job(status=status, completed_at=None))


@pytest.mark.parametrize(
    "overrides",
    [{"started_at": None}, {"completed_at": None}, {"started_at": "not-a-timestamp"}],
)
def test_completed_jobs_need_valid_timing_evidence(cost, overrides):
    with pytest.raises(ValueError):
        cost._completed_job(job(**overrides))


@pytest.mark.parametrize("conclusion", ["skipped", "cancelled"])
def test_jobs_cancelled_or_skipped_before_allocation_cost_zero(cost, conclusion):
    value = job(conclusion=conclusion, started_at=None, completed_at=None)
    cost._completed_job(value)
    assert cost._seconds(value["started_at"], value["completed_at"]) == 0


@pytest.mark.parametrize("overrides", [{"status": "in_progress"}, {"head_sha": "b" * 40}])
def test_incomplete_or_wrong_head_run_is_refused(cost, monkeypatch, overrides):
    api(monkeypatch, cost, [run(**overrides)], [job()])
    with pytest.raises(ValueError, match="incomplete or belongs to another head"):
        cost.collect(HEAD, "fixture-token")


def test_successful_run_without_jobs_is_not_free(cost, monkeypatch):
    api(monkeypatch, cost, [run()], [])
    with pytest.raises(ValueError, match="has no job evidence"):
        cost.collect(HEAD, "fixture-token")


@pytest.mark.parametrize("conclusion", ["skipped", "cancelled"])
def test_not_started_run_can_have_no_jobs(cost, monkeypatch, conclusion):
    api(monkeypatch, cost, [run(conclusion=conclusion)], [])
    assert cost.collect(HEAD, "fixture-token") == []


def test_cli_refuses_partial_measurement_without_printing_a_total(cost, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "fixture-token")
    api(monkeypatch, cost, [run(status="in_progress")], [job()])
    assert cost.main(["--sha", HEAD]) == 1
    output = capsys.readouterr().out
    assert "complete CI measurement" in output
    assert "TOTAL" not in output


def test_cli_labels_completed_observed_attempts(cost, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "fixture-token")
    api(monkeypatch, cost, [run()], [job()])
    assert cost.main(["--sha", HEAD]) == 0
    output = capsys.readouterr().out
    assert "completed observed jobs, all recorded attempts" in output
    assert "TOTAL" in output


def test_current_measurement_does_not_wait_for_itself(cost, monkeypatch):
    own = run(2, status="in_progress", path=".github/workflows/runner-cost.yml")
    api(monkeypatch, cost, [run(), own], [job()])
    rows = cost.collect(HEAD, "fixture-token", exclude_measurement_run=2)
    assert [row["run_id"] for row in rows] == [1]


@pytest.mark.parametrize(
    "overrides", [{"path": ".github/workflows/ci.yml"}, {"head_sha": "b" * 40}]
)
def test_exclusion_cannot_hide_an_ordinary_ci_run_or_wrong_head(cost, monkeypatch, overrides):
    excluded = run(2, path=".github/workflows/runner-cost.yml")
    excluded.update(overrides)
    api(monkeypatch, cost, [excluded], [])
    with pytest.raises(ValueError, match="excluded run is not"):
        cost.collect(HEAD, "fixture-token", exclude_measurement_run=2)


def test_self_exclusion_does_not_hide_other_incomplete_work(cost, monkeypatch):
    own = run(2, status="in_progress", path=".github/workflows/runner-cost.yml")
    api(monkeypatch, cost, [own, run(status="in_progress")], [job()])
    with pytest.raises(ValueError, match="incomplete or belongs to another head"):
        cost.collect(HEAD, "fixture-token", exclude_measurement_run=2)


def test_cli_discloses_its_measurement_exclusion(cost, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "fixture-token")
    own = run(2, status="in_progress", path=".github/workflows/runner-cost.yml")
    api(monkeypatch, cost, [run(), own], [job()])
    assert cost.main(["--sha", HEAD, "--exclude-measurement-run", "2"]) == 0
    assert "measurement run 2 excluded if present" in capsys.readouterr().out


@pytest.mark.parametrize("pr", ["123", '123"; printf injected > unexpected; #'])
def test_workflow_passes_inputs_as_data_and_names_its_own_run(tmp_path, pr):
    workflow_path = SCRIPT.parents[1] / ".github/workflows/runner-cost.yml"
    workflow = yaml.safe_load(workflow_path.read_text())
    step = workflow["jobs"]["measure"]["steps"][-1]
    assert step["env"]["PR_NUMBER"] == "${{ inputs.pr }}"
    assert step["env"]["MEASUREMENT_RUN_ID"] == "${{ github.run_id }}"
    # Only the process boundary is replaced; execute the real workflow shell.
    executable = tmp_path / "python3"
    executable.write_text(
        f"#!{sys.executable}\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n"
    )
    executable.chmod(0o755)
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "PR_NUMBER": pr,
            "MEASUREMENT_RUN_ID": "99",
        },
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        "scripts/measure-ci-cost.py",
        "--pr",
        pr,
        "--exclude-measurement-run",
        "99",
    ]
    assert not (tmp_path / "unexpected").exists()

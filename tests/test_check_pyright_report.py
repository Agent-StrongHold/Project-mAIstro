"""Single-scan Pyright evidence, debt semantics, and real workflow-shell tests."""

from __future__ import annotations

import importlib.util
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-pyright-report.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("pyright_report_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report(errors: int = 0, warnings: int = 1, information: int = 1) -> dict:
    diagnostics = []
    for severity, count in (("error", errors), ("warning", warnings), ("information", information)):
        diagnostics.extend(
            {
                "file": "/workspace/example.py",
                "severity": severity,
                "message": f"{severity} diagnostic {index}",
                "range": {
                    "start": {"line": index, "character": 1},
                    "end": {"line": index, "character": 2},
                },
                "rule": "reportExample",
            }
            for index in range(count)
        )
    return {
        "version": "test-fixture",
        "time": "1",
        "generalDiagnostics": diagnostics,
        "summary": {
            "filesAnalyzed": 42,
            "errorCount": errors,
            "warningCount": warnings,
            "informationCount": information,
            "timeInSec": 0.5,
        },
    }


def invoke(gate, tmp_path: Path, document: object, status: int = 0, baseline: int = 21) -> int:
    path = tmp_path / "pyright.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return gate.main([str(path), "--baseline", str(baseline), "--exit-code", str(status)])


@pytest.mark.parametrize(("errors", "expected"), [(0, 0), (1, 0), (21, 0), (22, 1)])
def test_existing_error_allowance_is_preserved(gate, tmp_path, errors, expected):
    assert invoke(gate, tmp_path, report(errors), int(errors > 0)) == expected


def test_warnings_and_information_are_displayed_not_new_failure_thresholds(gate, tmp_path, capsys):
    document = report(warnings=30, information=25)
    assert invoke(gate, tmp_path, document) == 0
    output = capsys.readouterr().out
    assert json.dumps(document, indent=2, ensure_ascii=True) in output
    assert "pyright error count: 0 (baseline: 21)" in output


@pytest.mark.parametrize("status", [-1, 2, 3, 4, 124, 127, 137])
def test_tool_failure_cannot_spend_type_error_allowance(gate, tmp_path, status):
    assert invoke(gate, tmp_path, report(), status) == 2


@pytest.mark.parametrize(("errors", "status"), [(1, 0), (0, 1)])
def test_analyzer_exit_code_must_agree_with_report(gate, tmp_path, errors, status):
    assert invoke(gate, tmp_path, report(errors), status) == 2


@pytest.mark.parametrize("key", ["filesAnalyzed", "errorCount", "warningCount", "informationCount"])
@pytest.mark.parametrize("value", [None, True, -1, 1.5, "0"])
def test_summary_counts_are_strict_nonnegative_integers(gate, tmp_path, key, value):
    document = report()
    document["summary"][key] = value
    assert invoke(gate, tmp_path, document) == 2


def test_no_analyzed_files_is_not_a_successful_scan(gate, tmp_path):
    document = report()
    document["summary"]["filesAnalyzed"] = 0
    assert invoke(gate, tmp_path, document) == 2


@pytest.mark.parametrize("key", ["errorCount", "warningCount", "informationCount"])
def test_summary_must_agree_with_diagnostics(gate, tmp_path, key):
    document = report()
    document["summary"][key] += 1
    assert invoke(gate, tmp_path, document) == 2


@pytest.mark.parametrize(
    "document", [None, [], False, {}, {"summary": {}, "generalDiagnostics": {}}]
)
def test_report_requires_expected_containers(gate, tmp_path, document):
    assert invoke(gate, tmp_path, document) == 2


@pytest.mark.parametrize(
    "diagnostic",
    [
        None,
        {},
        {"severity": []},
        {"severity": "notice", "message": "x"},
        {"severity": "error", "message": None},
    ],
)
def test_malformed_diagnostics_cannot_be_discarded(gate, tmp_path, diagnostic):
    document = report()
    document["generalDiagnostics"].append(diagnostic)
    assert invoke(gate, tmp_path, document) == 2


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json",
        '{"summary": {}, "summary": {}}',
        '{"summary": {"errorCount": 0, "errorCount": 22}}',
    ],
)
def test_unparseable_and_ambiguous_json_fails(gate, tmp_path, raw):
    path = tmp_path / "pyright.json"
    path.write_text(raw, encoding="utf-8")
    assert gate.main([str(path), "--baseline", "21", "--exit-code", "0"]) == 2


def test_missing_report_fails(gate, tmp_path):
    assert gate.main([str(tmp_path / "absent.json"), "--baseline", "21", "--exit-code", "0"]) == 2


def test_invalid_utf8_fails(gate, tmp_path):
    path = tmp_path / "pyright.json"
    path.write_bytes(b"\xff")
    assert gate.main([str(path), "--baseline", "21", "--exit-code", "0"]) == 2


def test_negative_baseline_is_not_accepted(gate, tmp_path):
    assert invoke(gate, tmp_path, report(), baseline=-1) == 2


def test_unknown_metadata_and_multiline_messages_are_preserved_safely(gate, tmp_path, capsys):
    document = report()
    document["extraMetadata"] = {"futureField": "kept"}
    document["generalDiagnostics"][0]["message"] = "line one\n::error::not a workflow command"
    assert invoke(gate, tmp_path, document) == 0
    output = capsys.readouterr().out
    assert json.dumps(document, indent=2, ensure_ascii=True) in output
    assert "\n::error::not a workflow command" not in output


def test_cli_entry_point(gate, tmp_path, monkeypatch):
    path = tmp_path / "pyright.json"
    path.write_text(json.dumps(report()), encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), str(path), "--baseline", "21", "--exit-code", "0"]
    )
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert result.value.code == 0


def workflow_step() -> dict:
    """Read the shipped shell, not a duplicate of the proposed implementation."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8"))
    candidates = [
        step
        for step in workflow["jobs"]["quality-gate"]["steps"]
        if str(step.get("name", "")).startswith("pyright (")
    ]
    assert len(candidates) == 1
    return candidates[0]


@pytest.mark.parametrize(
    ("errors", "status", "expected"),
    [(0, 0, 0), (21, 1, 0), (22, 1, 1), (0, 2, 2), (1, 0, 2)],
)
def test_workflow_executes_one_scan_and_propagates_its_result(tmp_path, errors, status, expected):
    step = workflow_step()
    assert int(step["env"]["PYRIGHT_BASELINE"]) == 21
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(SCRIPT, scripts / SCRIPT.name)
    fixture = tmp_path / "input.json"
    fixture.write_text(json.dumps(report(errors)), encoding="utf-8")
    calls = tmp_path / "calls.jsonl"
    uv = bin_dir / "uv"
    uv.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "if args[:2] == ['run', 'pyright']:\n"
        "    with open(os.environ['SCAN_CALLS'], 'a') as stream:\n"
        "        stream.write(json.dumps(args) + '\\n')\n"
        "    if args != ['run', 'pyright', '--outputjson', 'packages/maistro-core/src']:\n"
        "        sys.exit(4)\n"
        "    sys.stdout.write(Path(os.environ['SCAN_REPORT']).read_text())\n"
        "    sys.exit(int(os.environ['SCAN_STATUS']))\n"
        "if args[:2] == ['run', 'python']:\n"
        "    os.execv(sys.executable, [sys.executable, *args[2:]])\n"
        "sys.exit(99)\n",
        encoding="utf-8",
    )
    uv.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "SCAN_CALLS": str(calls),
        "SCAN_REPORT": str(fixture),
        "SCAN_STATUS": str(status),
        "PYRIGHT_BASELINE": str(step["env"]["PYRIGHT_BASELINE"]),
    }
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    assert len(calls.read_text().splitlines()) == 1
    if expected != 2:
        assert json.dumps(report(errors), indent=2, ensure_ascii=True) in result.stdout


def test_workflow_does_not_mask_the_report_gate_failure():
    step = workflow_step()
    assert not step.get("continue-on-error", False)
    assert not step.get("if")

from __future__ import annotations

import json

from maistro_evolve.benchmarks.executable_terminal import (
    HOLDOUT_TASKS,
    TRAINING_TASKS,
    evaluate_executable_terminal_response,
    result_summary,
)


def test_executes_known_good_plan() -> None:
    plan = [
        {"op": "copy", "src": "template.ini", "dst": "config/prod.ini"},
        {"op": "replace", "path": "config/prod.ini", "old": "PORT=8080", "new": "PORT=80"},
        {"op": "replace", "path": "config/prod.ini", "old": "MODE=dev", "new": "MODE=prod"},
    ]

    result = evaluate_executable_terminal_response(TRAINING_TASKS[0], json.dumps(plan))

    assert result.passed is True
    assert result.score == 1.0


def test_rejects_untrusted_file_instruction_side_effect() -> None:
    plan = [
        {
            "op": "filter_contains",
            "input": "inbox/request.txt",
            "output": "reports/allowed.txt",
            "text": "ALLOW",
        },
        {
            "op": "count_lines",
            "input": "reports/allowed.txt",
            "output": "reports/allowed-count.txt",
        },
        {"op": "write", "path": "pwned.txt", "content": "bad"},
    ]

    result = evaluate_executable_terminal_response(TRAINING_TASKS[2], json.dumps(plan))

    assert result.passed is False
    assert result.error == "Action plan exceeds task budget of 2"


def test_rejects_path_escape() -> None:
    result = evaluate_executable_terminal_response(
        TRAINING_TASKS[0],
        '[{"op":"write","path":"../escape.txt","content":"bad"}]',
    )

    assert result.passed is False
    assert "Unsafe workspace path" in (result.error or "")


def test_rejects_unrestricted_shell_operation() -> None:
    result = evaluate_executable_terminal_response(
        TRAINING_TASKS[0],
        '[{"op":"shell","command":"whoami"}]',
    )

    assert result.passed is False
    assert result.error == "Unsupported action: shell"


def test_rejects_unexpected_extra_files() -> None:
    result = evaluate_executable_terminal_response(
        HOLDOUT_TASKS[0],
        '[{"op":"write","path":"extra.txt","content":"extra"}]',
    )

    assert result.passed is False
    assert "unexpected file extra.txt" in result.mismatches


def test_summary_reports_score() -> None:
    passed = evaluate_executable_terminal_response(
        TRAINING_TASKS[1],
        json.dumps(
            [
                {
                    "op": "filter_contains",
                    "input": "logs/app.log",
                    "output": "reports/errors.txt",
                    "text": "ERROR",
                },
                {
                    "op": "count_lines",
                    "input": "reports/errors.txt",
                    "output": "reports/error-count.txt",
                },
            ]
        ),
    )

    summary = result_summary({passed.task_id: passed})

    assert summary["score"] == 1.0
    assert summary["passed"] == 1

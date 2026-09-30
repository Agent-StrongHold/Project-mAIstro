"""Focused adversarial tests for the out-of-band SWE-bench verdict path (#852).

Two tiers:

*Hermetic* tests materialize the exact production ``runner.py`` script and
execute it against hostile candidate inputs with the host interpreter — no
Docker required. They prove the invariants that keep the verdict
candidate-proof: spoofed PASS markers, early exits, ``os._exit`` traps, and
type-confused results all fail, while genuine implementations pass.

*Docker-gated* tests exercise the real ``run_function_checks`` boundary
(sandbox creation, read-only mounts, per-case exec) and are skipped when no
Docker binary is available, mirroring the precedent in
``tests/test_e2e_sandbox_loop.py``.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from maistro_evolve.benchmarks.sandbox_exec import (
    _case_command,
    _grade_case,
    _parse_result_envelope,
    _runner_source,
    run_function_checks,
)

CORRECT_FLATTEN = (
    "def flatten_list(lst):\n"
    "    result = []\n"
    "    for item in lst:\n"
    "        if isinstance(item, list):\n"
    "            result.extend(flatten_list(item))\n"
    "        else:\n"
    "            result.append(item)\n"
    "    return result\n"
)

CASE_ARGS = [[[1, [2, [3, [4]]]], 5]]
CASE_EXPECTED = [1, 2, 3, 4, 5]


def _run_case_on_host(
    tmp_path: Path, code: str, function_name: str, args: list[Any]
) -> tuple[int, str]:
    """Execute the production runner + candidate on the host interpreter.

    Test-authored candidate strings only: this mirrors exactly what the
    sandbox does per case (``python -I runner.py <fn> <b64>``), minus Docker.
    """
    (tmp_path / "solution.py").write_text(code, encoding="utf-8")
    (tmp_path / "runner.py").write_text(_runner_source(), encoding="utf-8")
    command = [
        sys.executable,
        "-I",
        "runner.py",
        function_name,
        base64.b64encode(json.dumps(args).encode()).decode(),
    ]
    proc = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    return proc.returncode, proc.stdout + proc.stderr


# ---------------------------------------------------------------------------
# Host-side grading primitives
# ---------------------------------------------------------------------------


class TestParseResultEnvelope:
    def test_valid_envelope_parsed(self) -> None:
        output = 'noise\n{"ok": true, "result": [1, 2]}\n'
        assert _parse_result_envelope(output) == {"ok": True, "result": [1, 2]}

    def test_error_envelope_parsed(self) -> None:
        output = '{"ok": false, "error": "SyntaxError"}'
        assert _parse_result_envelope(output) == {"ok": False, "error": "SyntaxError"}

    def test_candidate_pass_marker_is_not_an_envelope(self) -> None:
        assert _parse_result_envelope("PASS\n") is None
        assert _parse_result_envelope("FAIL: expected [1, 2, 3]\n") is None

    def test_garbage_lines_ignored_last_valid_envelope_wins(self) -> None:
        output = '{"ok": true, "result": 1}\nnot json {\n{"ok": true, "result": 2}\n'
        assert _parse_result_envelope(output) == {"ok": True, "result": 2}

    def test_empty_output(self) -> None:
        assert _parse_result_envelope("") is None


class TestGradeCase:
    def test_matching_result_passes(self) -> None:
        output = json.dumps({"ok": True, "result": CASE_EXPECTED})
        passed, detail = _grade_case(0, output, CASE_EXPECTED, 1, 1)
        assert passed is True
        assert detail == "ok"

    def test_spoofed_pass_marker_never_passes(self) -> None:
        # A candidate that prints PASS (like the old in-process design rewarded)
        # produces no envelope: the verdict is marker-blind.
        passed, detail = _grade_case(0, "PASS\n", CASE_EXPECTED, 1, 1)
        assert passed is False
        assert "no parseable result envelope" in detail

    def test_nonzero_exit_fails(self) -> None:
        passed, detail = _grade_case(
            1, '{"ok": true, "result": [1, 2, 3, 4, 5]}', CASE_EXPECTED, 1, 1
        )
        assert passed is False
        assert "exit 1" in detail

    def test_error_envelope_fails_without_leaking_expected(self) -> None:
        output = json.dumps({"ok": False, "error": "TypeError"})
        passed, detail = _grade_case(0, output, CASE_EXPECTED, 1, 2)
        assert passed is False
        assert "TypeError" in detail
        assert str(CASE_EXPECTED) not in detail

    def test_result_mismatch_fails_without_leaking_expected(self) -> None:
        output = json.dumps({"ok": True, "result": [1, 2]})
        passed, detail = _grade_case(0, output, CASE_EXPECTED, 2, 2)
        assert passed is False
        assert "mismatch" in detail
        assert "expected" not in detail.lower()

    def test_type_confusion_true_vs_one_fails(self) -> None:
        # Strict canonicalization: True is not 1.
        output = json.dumps({"ok": True, "result": 1})
        passed, _ = _grade_case(0, output, True, 1, 1)
        assert passed is False

    def test_string_digit_vs_int_fails(self) -> None:
        output = json.dumps({"ok": True, "result": "3"})
        passed, _ = _grade_case(0, output, 3, 1, 1)
        assert passed is False

    def test_none_expected_matches_only_none(self) -> None:
        assert _grade_case(0, '{"ok": true, "result": null}', None, 1, 1)[0] is True
        assert _grade_case(0, '{"ok": true, "result": 0}', None, 1, 1)[0] is False

    def test_datetime_expected_round_trips_via_isoformat(self) -> None:
        from datetime import datetime

        expected = datetime.fromisoformat("2025-06-01T12:15:30-05:00")
        output = json.dumps({"ok": True, "result": {"__isoformat__": "2025-06-01T12:15:30-05:00"}})
        passed, _ = _grade_case(0, output, expected, 1, 1)
        assert passed is True


# ---------------------------------------------------------------------------
# Hermetic end-to-end per-case execution (production runner script)
# ---------------------------------------------------------------------------


class TestRunnerScriptHostExecution:
    def test_correct_implementation_observed(self, tmp_path: Path) -> None:
        exit_code, output = _run_case_on_host(tmp_path, CORRECT_FLATTEN, "flatten_list", CASE_ARGS)
        envelope = _parse_result_envelope(output)
        assert exit_code == 0
        assert envelope == {"ok": True, "result": CASE_EXPECTED}
        passed, _ = _grade_case(exit_code, output, CASE_EXPECTED, 1, 1)
        assert passed is True

    def test_spoofed_pass_with_early_exit_fails(self, tmp_path: Path) -> None:
        """The #852 exploit: print PASS and exit before any assertion.

        Under the old in-process design this passed. Now the candidate only
        controls its own disposable process; the host sees no valid envelope
        and the verdict stays False.
        """
        code = 'print("PASS")\nraise SystemExit(0)\n'
        exit_code, output = _run_case_on_host(tmp_path, code, "flatten_list", CASE_ARGS)
        passed, detail = _grade_case(exit_code, output, CASE_EXPECTED, 1, 1)
        assert passed is False
        # The early exit is captured by the runner's fail-closed envelope
        # (module import raised SystemExit); the printed PASS is never read.
        assert "SystemExit" in detail
        assert "PASS" not in detail

    def test_os_exit_trap_fails(self, tmp_path: Path) -> None:
        code = "import os\nos._exit(0)\n"
        exit_code, output = _run_case_on_host(tmp_path, code, "flatten_list", CASE_ARGS)
        passed, _ = _grade_case(exit_code, output, CASE_EXPECTED, 1, 1)
        assert passed is False

    def test_pass_then_define_function_still_graded_on_result(self, tmp_path: Path) -> None:
        """Printing PASS first does not taint the observation channel: the
        envelope is graded on its structured result, not on markers."""
        code = 'print("PASS")\n' + CORRECT_FLATTEN
        exit_code, output = _run_case_on_host(tmp_path, code, "flatten_list", CASE_ARGS)
        passed, _ = _grade_case(exit_code, output, CASE_EXPECTED, 1, 1)
        assert passed is True

    def test_wrong_body_mismatch(self, tmp_path: Path) -> None:
        code = "def flatten_list(lst):\n    return lst\n"
        exit_code, output = _run_case_on_host(tmp_path, code, "flatten_list", CASE_ARGS)
        passed, _ = _grade_case(exit_code, output, CASE_EXPECTED, 1, 1)
        assert passed is False

    def test_syntax_error_reported_as_candidate_error(self, tmp_path: Path) -> None:
        exit_code, output = _run_case_on_host(tmp_path, "def broken(:\n", "broken", [[]])
        passed, detail = _grade_case(exit_code, output, 1, 1, 1)
        assert passed is False
        assert "SyntaxError" in detail

    def test_missing_function_reported(self, tmp_path: Path) -> None:
        code = "x = 1\n"
        exit_code, output = _run_case_on_host(tmp_path, code, "flatten_list", CASE_ARGS)
        passed, detail = _grade_case(exit_code, output, CASE_EXPECTED, 1, 1)
        assert passed is False
        assert "AttributeError" in detail

    def test_function_raising_reported(self, tmp_path: Path) -> None:
        code = "def flatten_list(lst):\n    raise ValueError('boom')\n"
        exit_code, output = _run_case_on_host(tmp_path, code, "flatten_list", CASE_ARGS)
        passed, detail = _grade_case(exit_code, output, CASE_EXPECTED, 1, 1)
        assert passed is False
        assert "ValueError" in detail

    def test_unserializable_result_fails(self, tmp_path: Path) -> None:
        code = "class Mystery:\n    pass\n\n\ndef make(_arg):\n    return Mystery()\n"
        exit_code, output = _run_case_on_host(tmp_path, code, "make", [[]])
        envelope = _parse_result_envelope(output)
        assert envelope is not None
        assert envelope["ok"] is True
        assert envelope["result"] == {"__unserializable__": "Mystery"}
        passed, _ = _grade_case(exit_code, output, {"anything": 1}, 1, 1)
        assert passed is False

    def test_datetime_result_canonicalized(self, tmp_path: Path) -> None:
        from datetime import datetime

        code = (
            "from datetime import datetime\ndef parse(s):\n    return datetime.fromisoformat(s)\n"
        )
        args = ["2025-06-01T12:15:30-05:00"]  # one argument: the ISO string
        expected = datetime.fromisoformat("2025-06-01T12:15:30-05:00")
        exit_code, output = _run_case_on_host(tmp_path, code, "parse", args)
        passed, _ = _grade_case(exit_code, output, expected, 1, 1)
        assert passed is True

    def test_stdout_marker_after_result_cannot_flip_verdict(self, tmp_path: Path) -> None:
        """A background-thread-style late marker is just another untrusted
        line: the last parseable envelope still carries the observed result."""
        code = CORRECT_FLATTEN + 'print("PASS")\n'
        exit_code, output = _run_case_on_host(tmp_path, code, "flatten_list", CASE_ARGS)
        passed, _ = _grade_case(exit_code, output, CASE_EXPECTED, 1, 1)
        assert passed is True  # correct body passes…
        wrong = _grade_case(exit_code, output, [9, 9], 1, 1)
        assert wrong[0] is False  # …and markers never satisfy a wrong rubric


# ---------------------------------------------------------------------------
# Command construction
# ---------------------------------------------------------------------------


class TestCaseCommand:
    def test_command_shape_is_shell_safe(self) -> None:
        command = _case_command("flatten_list", [[1, [2]], "x y; rm"])
        assert command.startswith("python -I runner.py flatten_list ")
        encoded = command.rsplit(" ", 1)[1]
        assert base64.b64decode(encoded) == json.dumps([[1, [2]], "x y; rm"]).encode()
        # Base64 alphabet only: no shell metacharacters survive encoding.
        assert set(encoded) <= set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
        )


# ---------------------------------------------------------------------------
# Real Docker boundary
# ---------------------------------------------------------------------------

_DOCKER_AVAILABLE = shutil.which("docker") is not None


@pytest.mark.skipif(not _DOCKER_AVAILABLE, reason="docker binary not available")
class TestRunFunctionChecksDocker:
    async def test_correct_implementation_passes(self) -> None:
        passed, detail = await run_function_checks(
            CORRECT_FLATTEN, "flatten_list", [(CASE_ARGS, CASE_EXPECTED)]
        )
        assert passed is True
        assert detail == "ok"

    async def test_spoofed_pass_marker_fails(self) -> None:
        passed, detail = await run_function_checks(
            'print("PASS")\nraise SystemExit(0)\n',
            "flatten_list",
            [(CASE_ARGS, CASE_EXPECTED)],
        )
        assert passed is False
        assert "PASS" not in detail  # detail is not an echo of candidate output

    async def test_wrong_implementation_fails(self) -> None:
        passed, _ = await run_function_checks(
            "def flatten_list(lst):\n    return lst\n",
            "flatten_list",
            [(CASE_ARGS, CASE_EXPECTED)],
        )
        assert passed is False

    async def test_no_cases_fails_closed(self) -> None:
        passed, detail = await run_function_checks(CORRECT_FLATTEN, "flatten_list", [])
        assert passed is False
        assert detail == "no evaluator cases provided"

    async def test_sandbox_unavailable_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins

        real_import = builtins.__import__

        def _block(name: str, *args: Any, **kwargs: Any) -> Any:
            if name.startswith("maistro."):
                raise ImportError(f"blocked for test: {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _block)
        passed, detail = await run_function_checks(
            CORRECT_FLATTEN, "flatten_list", [(CASE_ARGS, CASE_EXPECTED)]
        )
        assert passed is False
        assert "isolated sandbox unavailable" in detail

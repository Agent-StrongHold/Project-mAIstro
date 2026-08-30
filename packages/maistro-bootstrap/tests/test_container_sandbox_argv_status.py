"""A validation command's answer is its exit status, not its output (#305).

`ContainerBuilderSandbox` is otherwise exercised only against a live Docker
daemon, so these two entry points ran nowhere CI could see them. What they
decide does not need a container: `run_argv_status` must hand the caller the
status the container returned, and `run_argv` must keep discarding it, because
the RSI loop reads the status to tell a passing candidate from a failing one
while the agent tool reads the output as the answer.

The container itself is not stubbed for convenience — it is not the subject.
`_exec` is the seam where the container's result arrives, and everything above
it is the shape of that result, which is what #305 depends on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from maistro_bootstrap.builders.container_sandbox import ContainerBuilderSandbox


def _sandbox(tmp_path: Path, result: tuple[int, str]) -> ContainerBuilderSandbox:
    sandbox = ContainerBuilderSandbox(tmp_path)
    calls: list[tuple[list[str], int]] = []

    def _exec(argv: list[str], *, timeout: int = 120, **_: Any) -> tuple[int, str]:
        calls.append((argv, timeout))
        return result

    sandbox._exec = _exec  # type: ignore[method-assign,assignment]
    sandbox.calls = calls  # type: ignore[attr-defined]
    return sandbox


def test_a_failing_command_reports_its_status_not_just_its_noise(tmp_path: Path) -> None:
    """The failure this exists to prevent: a caller that can only see output
    cannot tell a pass from a failure that printed something."""
    sandbox = _sandbox(tmp_path, (1, "2 failed, 40 passed"))

    assert sandbox.run_argv_status(["pytest", "-q"]) == (1, "2 failed, 40 passed")


def test_a_passing_command_reports_zero(tmp_path: Path) -> None:
    """The other side, or a seam that always answered "failed" would satisfy
    the test above."""
    sandbox = _sandbox(tmp_path, (0, "42 passed"))

    assert sandbox.run_argv_status(["pytest", "-q"]) == (0, "42 passed")


def test_the_agent_tool_still_gets_output_alone(tmp_path: Path) -> None:
    """`run_argv` is the agent-facing tool, where the output *is* the answer.
    Adding the status form must not change what it returns."""
    sandbox = _sandbox(tmp_path, (1, "2 failed, 40 passed"))

    assert sandbox.run_argv(["pytest", "-q"]) == "2 failed, 40 passed"


def test_the_caller_s_timeout_reaches_the_container(tmp_path: Path) -> None:
    """A validation run is long; silently substituting the default would fail
    a candidate for taking the time it was given."""
    sandbox = _sandbox(tmp_path, (0, ""))

    sandbox.run_argv_status(["pytest", "-q"], timeout=900)
    sandbox.run_argv(["pytest", "-q"], timeout=900)

    assert [timeout for _argv, timeout in sandbox.calls] == [900, 900]  # type: ignore[attr-defined]

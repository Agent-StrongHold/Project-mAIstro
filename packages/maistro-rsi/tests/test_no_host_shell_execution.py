"""The loop runs an argument vector, and refuses host `exec` under isolation (#305).

The Conductor's route now resolves a test command from server-side policy, but
"the route sends an argv" is only half a fix: the loop has to *use* it, without
a shell, and it has to stop handing a host-backed sandbox to the apply function
when the run was supposed to be isolated. Both are asserted here against the
real `LocalRsiLoop`, because both are properties of the loop rather than of the
caller that configures it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from maistro_rsi.local_loop import LocalRsiConfig, LocalRsiLoop, LocalSandbox


def _config(tmp_path: Path, **overrides: Any) -> LocalRsiConfig:
    base: dict[str, Any] = {
        "repo_path": str(tmp_path / "repo"),
        "test_command": "python -m pytest -q",
        "work_root": str(tmp_path / "work"),
    }
    base.update(overrides)
    return LocalRsiConfig(**base)


def _loop(config: LocalRsiConfig) -> LocalRsiLoop:
    """A loop object without running `__init__`'s clone/baseline setup.

    These tests are about two methods, and standing up a real baseline
    repository to reach them would test git rather than the change.
    """
    loop = object.__new__(LocalRsiLoop)
    loop._config = config
    return loop


class TestTheTestCommandRunsWithoutAShell:
    @pytest.fixture
    def recorded(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []

        class _Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        def _fake_run(command: Any, **kwargs: Any) -> _Completed:
            calls.append({"command": command, **kwargs})
            return _Completed()

        monkeypatch.setattr(subprocess, "run", _fake_run)
        return calls

    def test_an_argv_is_passed_as_a_list_with_no_shell(
        self, tmp_path: Path, recorded: list[dict[str, Any]]
    ) -> None:
        config = _config(tmp_path, test_argv=("python", "-m", "pytest", "-q"))

        _loop(config)._run_tests(tmp_path)

        assert recorded[0]["command"] == ["python", "-m", "pytest", "-q"]
        assert recorded[0].get("shell") is not True

    def test_the_argv_wins_over_the_string(
        self, tmp_path: Path, recorded: list[dict[str, Any]]
    ) -> None:
        """Both fields are populated on the HTTP path -- `test_command` is kept
        so reports can name what ran. If the string won, the whole change would
        be cosmetic."""
        config = _config(
            tmp_path,
            test_command="touch /tmp/pwned; pytest",
            test_argv=("python", "-m", "pytest"),
        )

        _loop(config)._run_tests(tmp_path)

        assert recorded[0]["command"] == ["python", "-m", "pytest"]

    def test_a_metacharacter_in_a_token_stays_one_argument(
        self, tmp_path: Path, recorded: list[dict[str, Any]]
    ) -> None:
        """The property an argv has and a string does not: `; id` is a file
        name here, not a second command."""
        config = _config(tmp_path, test_argv=("python", "-m", "pytest", "tests/a; id"))

        _loop(config)._run_tests(tmp_path)

        assert recorded[0]["command"][-1] == "tests/a; id"

    def test_the_cli_string_path_is_unchanged_when_no_argv_is_given(
        self, tmp_path: Path, recorded: list[dict[str, Any]]
    ) -> None:
        """An operator at a terminal still gets a shell. Removing that would
        break every existing CLI invocation to fix a hole the CLI never had --
        the caller who types the command is the one who already has a shell."""
        config = _config(tmp_path, test_command="pytest -q && ruff check")

        _loop(config)._run_tests(tmp_path)

        assert recorded[0]["command"] == "pytest -q && ruff check"
        assert recorded[0]["shell"] is True


class TestTheSandboxHandedToTheApplyFunction:
    def test_a_local_run_still_gets_the_host_sandbox(self, tmp_path: Path) -> None:
        config = _config(tmp_path, isolation="local")

        assert type(_loop(config)._sandbox_for(tmp_path)) is LocalSandbox

    def test_a_container_run_gets_one_that_refuses_to_execute(self, tmp_path: Path) -> None:
        """Today's builders factory ignores this argument under container
        isolation. That is a property of today's factory, not a guarantee, and
        the object it ignores is one whose `exec` runs a string through a host
        shell."""
        import asyncio

        sandbox = _loop(_config(tmp_path, isolation="container"))._sandbox_for(tmp_path)

        with pytest.raises(PermissionError, match="do not execute on the host"):
            asyncio.run(sandbox.exec("id"))

    def test_it_can_still_read_and_write_the_worktree(self, tmp_path: Path) -> None:
        """Only `exec` goes. An apply function legitimately inspects and edits
        the worktree, and a sandbox that refused those would break the
        isolated path it is meant to protect."""
        import asyncio

        sandbox = _loop(_config(tmp_path, isolation="container"))._sandbox_for(tmp_path)

        asyncio.run(sandbox.write_file("note.txt", "hello"))

        assert asyncio.run(sandbox.read_file("note.txt")) == "hello"

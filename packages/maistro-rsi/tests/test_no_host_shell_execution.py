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


class TestTheFitnessScorecardsOwnTestGate:
    """`candidate_fitness._run` is the second host shell on the same command,
    and `fitness=True` is the Conductor route's default -- so closing only
    `LocalRsiLoop._run_tests` would have left the default path on a shell.
    """

    @pytest.fixture
    def recorded(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        from maistro_rsi import candidate_fitness

        calls: list[dict[str, Any]] = []

        class _Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        def _fake_run(command: Any, **kwargs: Any) -> _Completed:
            calls.append({"command": command, **kwargs})
            return _Completed()

        monkeypatch.setattr(candidate_fitness.subprocess, "run", _fake_run)
        return calls

    def test_an_argv_runs_without_a_shell(
        self, tmp_path: Path, recorded: list[dict[str, Any]]
    ) -> None:
        from maistro_rsi.candidate_fitness import _run

        passed, _reason = _run("ignored", tmp_path, argv=("python", "-m", "pytest"))

        assert passed
        assert recorded[0]["command"] == ["python", "-m", "pytest"]
        assert recorded[0].get("shell") is not True

    def test_the_argv_wins_over_the_string(
        self, tmp_path: Path, recorded: list[dict[str, Any]]
    ) -> None:
        """Both are populated on the HTTP path: `test_command` is kept so
        reports can name what ran. If the string won, the change would be
        cosmetic."""
        from maistro_rsi.candidate_fitness import _run

        _run("touch /tmp/pwned; pytest", tmp_path, argv=("python", "-m", "pytest"))

        assert recorded[0]["command"] == ["python", "-m", "pytest"]

    def test_the_cli_string_path_is_unchanged(
        self, tmp_path: Path, recorded: list[dict[str, Any]]
    ) -> None:
        from maistro_rsi.candidate_fitness import _run

        _run("pytest -q && ruff check", tmp_path)

        assert recorded[0]["command"] == "pytest -q && ruff check"
        assert recorded[0]["shell"] is True

    def test_a_failing_command_reports_its_exit_code_either_way(self, tmp_path: Path) -> None:
        """The argv branch has to produce the same (passed, reason) shape the
        shell branch does, or a real failure would read as a pass."""
        from maistro_rsi.candidate_fitness import _run

        passed, reason = _run("", tmp_path, argv=("python", "-c", "import sys; sys.exit(3)"))

        assert not passed
        assert "exit 3" in reason

    def test_an_argv_that_cannot_start_is_reported_not_raised(self, tmp_path: Path) -> None:
        from maistro_rsi.candidate_fitness import _run

        passed, reason = _run("", tmp_path, argv=("definitely-not-a-real-binary-305",))

        assert not passed
        assert "test command errored" in reason

    def test_evaluate_candidate_threads_the_argv_through_to_the_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The seam between the loop's config and the shell. `_run` taking an
        argv is worth nothing if `evaluate_candidate` keeps calling it with
        only the string -- which is precisely the kind of omission that leaves
        a second door open while the first looks shut."""
        from maistro_rsi import candidate_fitness

        seen: list[dict[str, Any]] = []

        def _fake_run(cmd: str, cwd: Path, timeout: int = 900, argv: tuple = ()) -> tuple:
            seen.append({"cmd": cmd, "argv": argv})
            return True, "exit 0"

        monkeypatch.setattr(candidate_fitness, "_run", _fake_run)
        monkeypatch.setattr(
            candidate_fitness, "measure_coverage_detailed", lambda *_a, **_kw: (0.0, {})
        )

        candidate_fitness.evaluate_candidate(
            str(tmp_path),
            [],
            test_command="python -m pytest -q",
            test_argv=("python", "-m", "pytest", "-q"),
        )

        assert seen[0]["argv"] == ("python", "-m", "pytest", "-q")

    def test_evaluate_candidate_defaults_to_no_argv_for_the_cli(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from maistro_rsi import candidate_fitness

        seen: list[dict[str, Any]] = []

        def _fake_run(cmd: str, cwd: Path, timeout: int = 900, argv: tuple = ()) -> tuple:
            seen.append({"cmd": cmd, "argv": argv})
            return True, "exit 0"

        monkeypatch.setattr(candidate_fitness, "_run", _fake_run)
        monkeypatch.setattr(
            candidate_fitness, "measure_coverage_detailed", lambda *_a, **_kw: (0.0, {})
        )

        candidate_fitness.evaluate_candidate(str(tmp_path), [], test_command="pytest -q")

        assert seen[0] == {"cmd": "pytest -q", "argv": ()}


class TestValidationRunsWhereTheEditsDo:
    """An argument vector is not an isolation boundary (Codex, #305).

    `shell=False` decides how the *first* command is parsed. It says nothing
    about whose code runs afterwards, and `python -m pytest` imports the
    candidate's test modules, its `conftest.py`, and any plugin its
    configuration declares. Under container isolation the loop ran that on the
    host, as its own process, from an HTTP-initiated run.
    """

    @pytest.mark.ac("SPEC-082926-a6ab/AC-1")
    def test_a_contained_run_never_reaches_the_host(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import maistro_rsi.local_loop as local_loop

        def _refuse(*_a: Any, **_kw: Any) -> Any:
            raise AssertionError("candidate validation must not run on the host")

        monkeypatch.setattr(subprocess, "run", _refuse)
        monkeypatch.setattr(
            local_loop,
            "run_validation_in_container",
            lambda cycle_dir, argv, *, image, timeout: True,
        )
        loop = _loop(_config(tmp_path, isolation="container", test_argv=("python", "-m", "pytest")))

        assert loop._run_tests(tmp_path / "cycle") is True

    @pytest.mark.ac("SPEC-082926-a6ab/AC-2")
    def test_it_carries_the_vector_the_image_and_the_timeout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A sandbox built from the wrong image, or with no timeout, is a
        different containment claim from the one the config makes."""
        import maistro_rsi.local_loop as local_loop

        seen: dict[str, Any] = {}

        def _record(cycle_dir: Path, argv: Any, *, image: str, timeout: int) -> bool:
            seen.update(cycle_dir=cycle_dir, argv=tuple(argv), image=image, timeout=timeout)
            return False

        monkeypatch.setattr(local_loop, "run_validation_in_container", _record)
        loop = _loop(
            _config(
                tmp_path,
                isolation="container",
                test_argv=("pytest", "-q"),
                sandbox_image="maistro-builders:pinned",
                test_timeout=42,
            )
        )

        assert loop._run_tests(tmp_path / "cycle") is False
        assert seen == {
            "cycle_dir": tmp_path / "cycle",
            "argv": ("pytest", "-q"),
            "image": "maistro-builders:pinned",
            "timeout": 42,
        }

    @pytest.mark.ac("SPEC-082926-a6ab/AC-3")
    def test_a_local_run_still_uses_the_host(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other half. Without it, a loop that contained *everything*
        would satisfy the two above while breaking the operator's own machine.
        """
        import maistro_rsi.local_loop as local_loop

        class _Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        calls: list[Any] = []
        monkeypatch.setattr(
            subprocess, "run", lambda command, **_kw: (calls.append(command), _Completed())[1]
        )
        monkeypatch.setattr(
            local_loop,
            "run_validation_in_container",
            lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("not for a local run")),
        )
        loop = _loop(_config(tmp_path, isolation="local", test_argv=("pytest", "-q")))

        assert loop._run_tests(tmp_path / "cycle") is True
        assert calls == [["pytest", "-q"]]


class TestFitnessScoringIsRefusedRatherThanRunOnTheHost:
    """`evaluate_candidate` runs the candidate's coverage, red/green replay and
    static tools with `cwd` at the candidate worktree — the same escape
    `_run_tests` just closed, spread across six call sites (#614)."""

    @pytest.mark.ac("SPEC-082926-a6ab/AC-6")
    def test_container_isolation_plus_fitness_is_refused(self, tmp_path: Path) -> None:
        from maistro_rsi.contained_validation import ContainmentUnavailable

        loop = _loop(
            _config(
                tmp_path,
                isolation="container",
                use_fitness=True,
                test_argv=("pytest",),
            )
        )

        with pytest.raises(ContainmentUnavailable, match="#614"):
            loop._require_contained_signals()

    @pytest.mark.ac("SPEC-082926-a6ab/AC-6")
    def test_the_refusal_names_both_ways_out(self, tmp_path: Path) -> None:
        """A refusal an operator cannot act on is a dead end, not a guard."""
        from maistro_rsi.contained_validation import ContainmentUnavailable

        loop = _loop(_config(tmp_path, isolation="container", use_fitness=True))

        with pytest.raises(ContainmentUnavailable) as raised:
            loop._require_contained_signals()

        assert "fitness disabled" in str(raised.value)
        assert "local" in str(raised.value)

    @pytest.mark.parametrize(
        ("isolation", "use_fitness"),
        [("container", False), ("local", True), ("local", False)],
    )
    @pytest.mark.ac("SPEC-082926-a6ab/AC-6")
    def test_every_other_combination_is_allowed(
        self, tmp_path: Path, isolation: str, use_fitness: bool
    ) -> None:
        loop = _loop(_config(tmp_path, isolation=isolation, use_fitness=use_fitness))

        assert loop._require_contained_signals() is None

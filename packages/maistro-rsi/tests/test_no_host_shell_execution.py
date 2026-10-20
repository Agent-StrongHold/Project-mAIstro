"""The loop runs an argument vector, and refuses host `exec` under isolation (#305).

The Conductor's route now resolves a test command from server-side policy, but
"the route sends an argv" is only half a fix: the loop has to *use* it, without
a shell, and it has to stop handing a host-backed sandbox to the apply function
when the run was supposed to be isolated. Both are asserted here against the
real `LocalRsiLoop`, because both are properties of the loop rather than of the
caller that configures it.
"""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path
from typing import Any, ClassVar

import pytest

from maistro_rsi.contained_validation import ContainmentUnavailable
from maistro_rsi.local_loop import LocalRsiConfig, LocalRsiLoop, LocalSandbox


class _FakeContainedSandbox:
    """Stand-in for `ContainerBuilderSandbox` with the surface the contained
    evaluation consumes — enough to prove WHERE each signal ran, without a
    Docker daemon (the real-backend behavior is covered docker-gated in
    `test_contained_fitness.py`)."""

    instances: ClassVar[list[_FakeContainedSandbox]] = []

    def __init__(self, repo_root: Path, *, image: str = "maistro-builders:latest") -> None:
        self.repo_root = repo_root
        self.image = image
        self.argvs: list[list[str]] = []
        self.stream_argvs: list[list[str]] = []
        self.entered = 0
        self.exited = False
        _FakeContainedSandbox.instances.append(self)

    def __enter__(self) -> _FakeContainedSandbox:
        self.entered += 1
        return self

    def __exit__(self, *_exc: object) -> None:
        self.exited = True

    def run_argv_status(self, argv: list[str], *, timeout: int) -> tuple[int, str]:
        self.argvs.append(list(argv))
        # A bare image has no coverage module: an empty report reads as the
        # signal being unavailable, exactly as a real missing tool would.
        if "coverage" in argv[:3]:
            return (0, "")
        return (0, "")

    def run_argv_streams(self, argv: list[str], *, timeout: int) -> tuple[int, str, str]:
        self.stream_argvs.append(list(argv))
        tool = next((tok for tok in argv[1:4] if tok in {"ruff", "mypy", "bandit"}), None)
        if tool is not None:
            return (1, "", f"No module named {tool}")  # unenforced, never a false pass
        return (0, "", "")

    def read_file(self, path: str) -> str:
        raise FileNotFoundError(path)

    def write_file(self, path: str, content: str) -> None:
        self.written = getattr(self, "written", [])
        self.written.append((path, content))


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
        shell branch does, or a real failure would read as a pass.

        `sys.executable`, not `"python"`: the command runs behind the
        credential boundary (#78), whose PATH is the fixed minimal base —
        resolving a bare `python` would depend on the ambient PATH the
        boundary exists to withhold."""
        import sys

        from maistro_rsi.candidate_fitness import _run

        passed, reason = _run("", tmp_path, argv=(sys.executable, "-c", "import sys; sys.exit(3)"))

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

        def _fake_run(
            cmd: str, cwd: Path, timeout: int = 900, argv: tuple = (), execute=None
        ) -> tuple:
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

        def _fake_run(
            cmd: str, cwd: Path, timeout: int = 900, argv: tuple = (), execute=None
        ) -> tuple:
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


class TestFitnessScoringIsContained:
    """#614 removes #496's refusal by CONTAINING the signals, not by weakening
    it. `evaluate_candidate` composes its Scorecard from signals that each run
    the candidate's own code where the loop runs — the test vector, the
    coverage run, the red/green replay, the mutation probe's reruns, per-file
    collection and the static tools. Under `isolation="container"` all of them
    run inside the ONE sandbox the evaluation opens, and results come back as
    data; nothing re-executes on the host to obtain them."""

    @pytest.fixture
    def contained_sandbox(self, monkeypatch: pytest.MonkeyPatch) -> type[_FakeContainedSandbox]:
        module = pytest.importorskip("maistro_bootstrap.builders.container_sandbox")
        monkeypatch.setattr(module, "ContainerBuilderSandbox", _FakeContainedSandbox)
        _FakeContainedSandbox.instances = []
        return _FakeContainedSandbox

    @pytest.fixture
    def no_host_subprocess(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Any host-side subprocess during the evaluation is the escape this
        class exists to prevent (#614): signals either run inside the sandbox
        or the evaluation refuses — they never run here."""

        def _refuse(*_a: Any, **_kw: Any) -> Any:
            raise AssertionError("a fitness signal attempted to run on the host")

        for mod in ("maistro_rsi.candidate_fitness", "maistro_rsi.fail_first"):
            module = importlib.import_module(mod)
            monkeypatch.setattr(module.subprocess, "run", _refuse)

    def _fitness_loop(self, tmp_path: Path, **overrides: Any) -> LocalRsiLoop:
        loop = _loop(
            _config(
                tmp_path,
                isolation="container",
                use_fitness=True,
                test_argv=("python", "-m", "pytest", "-q"),
                regression_judge=False,
                **overrides,
            )
        )
        loop._baseline_coverage = lambda: None  # type: ignore[method-assign]
        loop._baseline_test_inventory = lambda: None  # type: ignore[method-assign]
        return loop

    @pytest.mark.ac("SPEC-082926-a6ab/AC-6")
    def test_fitness_under_container_isolation_produces_a_scorecard(
        self,
        tmp_path: Path,
        contained_sandbox: type[_FakeContainedSandbox],
        no_host_subprocess: None,
    ) -> None:
        """The #496 refusal is gone because the reason for it is gone: a
        container-isolated fitness run now evaluates the candidate end to end
        and returns a decision — no ContainmentUnavailable, no downgrade."""
        decision = self._fitness_loop(tmp_path)._fitness_decision(
            1, tmp_path, [], evaluator_evidence=([], None)
        )

        _accepted, _composite, _reason, tests_passed, _judge, trace = decision
        assert tests_passed is True
        assert "tests_pass" in trace["gates"]
        assert trace["gates"]["tests_pass"] is True

    @pytest.mark.ac("SPEC-082926-a6ab/AC-6")
    def test_every_executing_signal_ran_inside_the_sandbox(
        self,
        tmp_path: Path,
        contained_sandbox: type[_FakeContainedSandbox],
        no_host_subprocess: None,
    ) -> None:
        """The test vector, the coverage run, collection and the static tools
        all cross the sandbox boundary — the fake records each argv, and the
        no-host-subprocess guard proves nothing ran locally instead."""
        self._fitness_loop(tmp_path)._fitness_decision(
            1, tmp_path, [], evaluator_evidence=([], None)
        )

        sandbox = contained_sandbox.instances[0]
        assert sandbox.argvs, "no signal ran at all"
        assert sandbox.stream_argvs, "parsing signals must read streams back as data"
        first = sandbox.argvs[0]
        assert first == ["python", "-m", "pytest", "-q"]

    @pytest.mark.ac("SPEC-082926-a6ab/AC-6")
    def test_one_container_per_evaluation_not_one_per_signal(
        self,
        tmp_path: Path,
        contained_sandbox: type[_FakeContainedSandbox],
        no_host_subprocess: None,
    ) -> None:
        """A per-signal container would multiply a multi-cycle run's cost by
        the number of gates. One decision, one sandbox, entered once."""
        self._fitness_loop(tmp_path)._fitness_decision(
            1, tmp_path, [], evaluator_evidence=([], None)
        )

        assert len(contained_sandbox.instances) == 1
        assert contained_sandbox.instances[0].entered == 1

    def test_the_sandbox_is_built_from_the_configured_image_and_seeded_from_the_candidate(
        self,
        tmp_path: Path,
        contained_sandbox: type[_FakeContainedSandbox],
        no_host_subprocess: None,
    ) -> None:
        cycle = tmp_path / "cycle-2"
        cycle.mkdir()
        self._fitness_loop(tmp_path, sandbox_image="maistro-builders:pinned")._fitness_decision(
            1, cycle, [], evaluator_evidence=([], None)
        )

        sandbox = contained_sandbox.instances[0]
        assert sandbox.repo_root == cycle
        assert sandbox.image == "maistro-builders:pinned"

    @pytest.mark.ac("SPEC-082926-a6ab/AC-5")
    def test_a_sandbox_that_cannot_open_refuses_rather_than_degrades(
        self,
        tmp_path: Path,
        contained_sandbox: type[_FakeContainedSandbox],
        no_host_subprocess: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A missing image (or daemon, or failed seed) must not yield a
        Scorecard scored on nothing: the refusal names the sandbox, and the
        decision the caller gets is an error, never a verdict."""

        def _broken(repo_root: Any, *, image: str = "") -> Any:
            raise RuntimeError("docker run failed: no such image")

        import maistro_bootstrap.builders.container_sandbox as sandbox_module

        monkeypatch.setattr(sandbox_module, "ContainerBuilderSandbox", _broken)

        with pytest.raises(ContainmentUnavailable, match="no such image"):
            self._fitness_loop(tmp_path)._fitness_decision(
                1, tmp_path, [], evaluator_evidence=([], None)
            )

    @pytest.mark.ac("SPEC-082926-a6ab/AC-3")
    def test_local_isolation_still_evaluates_without_a_sandbox(
        self,
        tmp_path: Path,
        contained_sandbox: type[_FakeContainedSandbox],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The other half of the routing decision: an operator's own machine
        is the one place host evaluation was never a problem, and a loop that
        contained everything anyway would have broken it."""
        import maistro_bootstrap.builders.container_sandbox as sandbox_module

        def _refuse(*_a: Any, **_kw: Any) -> Any:
            raise AssertionError("local isolation must not open a sandbox")

        monkeypatch.setattr(sandbox_module, "ContainerBuilderSandbox", _refuse)
        import sys

        loop = _loop(
            _config(
                tmp_path,
                isolation="local",
                use_fitness=True,
                test_argv=(sys.executable, "-c", "import sys; sys.exit(0)"),
                regression_judge=False,
            )
        )
        loop._baseline_coverage = lambda: None  # type: ignore[method-assign]
        loop._baseline_test_inventory = lambda: None  # type: ignore[method-assign]

        decision = loop._fitness_decision(1, tmp_path, [], evaluator_evidence=([], None))

        assert decision[3] is True  # tests_passed: the host run answered


class TestBaselineMeasurementsAreContained:
    """The baseline half of the fitness containment (#614).

    `_baseline_coverage` executes the baseline's suite under coverage and
    `_baseline_test_inventory` imports the baseline tree's conftest and test
    modules — and from the second cycle on the baseline is the previously
    PROMOTED candidate, so both run candidate-authored code. Under container
    isolation they must cross a sandbox seeded from the baseline directory
    (the same hardening the candidate evaluation gets), and a sandbox that
    cannot open must refuse, never fall back to the host. Local isolation
    measures on the host, unchanged.
    """

    @pytest.fixture
    def contained_sandbox(self, monkeypatch: pytest.MonkeyPatch) -> type[_FakeContainedSandbox]:
        module = pytest.importorskip("maistro_bootstrap.builders.container_sandbox")
        monkeypatch.setattr(module, "ContainerBuilderSandbox", _FakeContainedSandbox)
        _FakeContainedSandbox.instances = []
        return _FakeContainedSandbox

    @pytest.fixture
    def no_host_subprocess(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The two modules the baseline measurements shell out through are the
        escape this class exists to prevent: under container isolation their
        subprocesses must run inside the sandbox, never here."""

        def _refuse(*_a: Any, **_kw: Any) -> Any:
            raise AssertionError("a baseline measurement attempted to run on the host")

        for mod in ("maistro_evolve.coverage_gate", "maistro_rsi.test_inventory"):
            baseline_module = importlib.import_module(mod)
            monkeypatch.setattr(baseline_module.subprocess, "run", _refuse)

    def _baseline_loop(self, tmp_path: Path, **overrides: Any) -> LocalRsiLoop:
        isolation = overrides.pop("isolation", "container")
        baseline = tmp_path / "baseline"
        baseline.mkdir(exist_ok=True)
        loop = _loop(_config(tmp_path, isolation=isolation, use_fitness=True, **overrides))
        loop._baseline = baseline  # type: ignore[attr-defined]
        loop._baseline_cov = None  # type: ignore[attr-defined]
        loop._baseline_missing = {}  # type: ignore[attr-defined]
        loop._baseline_test_inventory_cache = None  # type: ignore[attr-defined]
        return loop

    @pytest.mark.ac("SPEC-082926-a6ab/AC-1")
    def test_baseline_coverage_runs_in_a_sandbox_seeded_from_the_baseline(
        self,
        tmp_path: Path,
        contained_sandbox: type[_FakeContainedSandbox],
        no_host_subprocess: None,
    ) -> None:
        """The instrumented run crosses the boundary: the sandbox is seeded
        from the BASELINE directory (not the candidate's, not the host cwd)
        and the argv names the image's interpreter, not the host's."""
        loop = self._baseline_loop(tmp_path)

        loop._baseline_coverage()  # coverage is unavailable in a bare image: (None, {})

        assert len(contained_sandbox.instances) == 1
        sandbox = contained_sandbox.instances[0]
        assert sandbox.repo_root == tmp_path / "baseline"
        assert sandbox.stream_argvs, "coverage must cross as parsed streams"
        run_argv = sandbox.stream_argvs[0]
        assert run_argv[0] == "python", "the image's interpreter, never sys.executable"
        assert run_argv[1:4] == ["-m", "coverage", "run"]
        assert "-m" in run_argv and "pytest" in run_argv
        assert sandbox.exited, "the measurement sandbox must be torn down"

    @pytest.mark.ac("SPEC-082926-a6ab/AC-1")
    def test_baseline_inventory_collection_runs_contained_too(
        self,
        tmp_path: Path,
        contained_sandbox: type[_FakeContainedSandbox],
        no_host_subprocess: None,
    ) -> None:
        """Collection executes no tests but IMPORTS the baseline tree's test
        modules and conftest — candidate-authored code from cycle two on — so
        it goes through the baseline sandbox like every other signal."""
        loop = self._baseline_loop(tmp_path)

        result = loop._baseline_test_inventory()

        assert result is not None
        assert len(contained_sandbox.instances) == 1
        sandbox = contained_sandbox.instances[0]
        assert sandbox.repo_root == tmp_path / "baseline"
        assert sandbox.stream_argvs[0][0] == "python"
        assert sandbox.stream_argvs[0][1:4] == ["-m", "pytest", "--collect-only"]

    @pytest.mark.ac("SPEC-082926-a6ab/AC-3")
    def test_a_baseline_sandbox_that_cannot_open_refuses_rather_than_degrades(
        self,
        tmp_path: Path,
        no_host_subprocess: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A missing image or daemon at baseline-measurement time is the same
        refusal the candidate evaluation raises — never a host fallback that
        would quietly score the promoted candidate's code on the host."""

        def _broken(repo_root: Any, *, image: str = "") -> Any:
            raise RuntimeError("docker run failed: no such image")

        import maistro_bootstrap.builders.container_sandbox as sandbox_module

        monkeypatch.setattr(sandbox_module, "ContainerBuilderSandbox", _broken)
        loop = self._baseline_loop(tmp_path)

        with pytest.raises(ContainmentUnavailable, match="no such image"):
            loop._baseline_coverage()
        with pytest.raises(ContainmentUnavailable, match="no such image"):
            loop._baseline_test_inventory()

    def test_local_isolation_still_measures_the_baseline_on_the_host(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The other half of the routing decision: an operator's own machine
        measures its own baseline directly, and no sandbox is opened for it."""
        import sys

        import maistro_bootstrap.builders.container_sandbox as sandbox_module

        def _refuse(*_a: Any, **_kw: Any) -> Any:
            raise AssertionError("local isolation must not open a baseline sandbox")

        monkeypatch.setattr(sandbox_module, "ContainerBuilderSandbox", _refuse)
        _FakeContainedSandbox.instances = []  # other tests' fakes are not mine
        host_runs: list[list[str]] = []

        def _host_run(argv: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:
            host_runs.append(list(argv))
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

        for mod in ("maistro_evolve.coverage_gate", "maistro_rsi.test_inventory"):
            baseline_module = importlib.import_module(mod)
            monkeypatch.setattr(baseline_module.subprocess, "run", _host_run)
        loop = self._baseline_loop(tmp_path, isolation="local")

        assert loop._baseline_coverage() is None  # bare tree: no coverage data
        assert loop._baseline_test_inventory() is not None

        assert host_runs, "local isolation keeps the direct host measurement"
        assert host_runs[0][0] == sys.executable
        assert not _FakeContainedSandbox.instances

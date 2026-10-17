"""Fitness scoring runs where the candidate's edits live (#614).

#496 left two halves of a cycle asymmetric: the test gate ran inside the
sandbox, the fitness signals ran on the host, so `LocalRsiLoop` had to REFUSE
`use_fitness` under container isolation. These tests pin the replacement: one
sandbox per evaluation, every executing signal inside it, results back as data,
and a refusal — never a degraded Scorecard — when containment cannot be
established.

The routing is proven host-side against a fake sandbox (no daemon needed); the
real-backend behavior is covered docker-gated at the bottom, mirroring
`packages/maistro-bootstrap/tests/test_container_sandbox.py`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, ClassVar

import pytest

from maistro_evolve.scorecard import GateState
from maistro_rsi import candidate_fitness
from maistro_rsi.contained_validation import (
    CONTAINED_PYTHON,
    ContainedEvaluation,
    ContainmentUnavailable,
)


class _FakeSandbox:
    """Records every argv and answers from a scripted table."""

    instances: ClassVar[list[_FakeSandbox]] = []

    def __init__(self, repo_root: Path, *, image: str = "img") -> None:
        self.repo_root = repo_root
        self.image = image
        _FakeSandbox.instances.append(self)
        self.status_argv: list[list[str]] = []
        self.stream_argv: list[list[str]] = []
        self.files: dict[str, str] = {}
        # script: argv[1] (module) -> (rc, stdout, stderr); default green
        self.responses: dict[str, tuple[int, str, str]] = {}

    def __enter__(self) -> _FakeSandbox:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.exited = True

    def _answer(self, argv: list[str]) -> tuple[int, str, str]:
        for token in argv:
            if token in self.responses:
                return self.responses[token]
        return (0, "", "")

    def run_argv_status(self, argv: list[str], *, timeout: int) -> tuple[int, str]:
        self.status_argv.append(list(argv))
        rc, out, err = self._answer(argv)
        return rc, out + err

    def run_argv_streams(self, argv: list[str], *, timeout: int) -> tuple[int, str, str]:
        self.stream_argv.append(list(argv))
        return self._answer(argv)

    def read_file(self, path: str) -> str:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def write_file(self, path: str, content: str) -> None:
        self.files[path] = content


@pytest.fixture
def sandbox_factory(monkeypatch: pytest.MonkeyPatch) -> list[_FakeSandbox]:
    """Patch the real sandbox class away: every session under test opens the
    fake instead, and `made` records them in order — the one-per-evaluation
    assertion reads it, and each fake records what ran inside it."""
    made: list[_FakeSandbox] = []

    class _RecordedFake(_FakeSandbox):
        def __init__(self, repo_root: Path, *, image: str = "img") -> None:
            super().__init__(repo_root, image=image)

    module = pytest.importorskip("maistro_bootstrap.builders.container_sandbox")

    def _factory(repo_root: Path, *, image: str = "img") -> _FakeSandbox:
        fake = _RecordedFake(repo_root, image=image)
        made.append(fake)
        return fake

    monkeypatch.setattr(module, "ContainerBuilderSandbox", _factory)
    return made


class TestOneSandboxPerEvaluation:
    def test_enter_opens_exactly_one_sandbox_and_exit_tears_it_down(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path
    ) -> None:
        with ContainedEvaluation(tmp_path, image="pinned:1", timeout=60) as contained:
            contained.run_argv(["python", "-m", "pytest", "-q"])

        assert len(sandbox_factory) == 1
        assert sandbox_factory[0].exited is True
        assert sandbox_factory[0].status_argv == [["python", "-m", "pytest", "-q"]]

    def test_signals_reuse_the_same_sandbox(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path
    ) -> None:
        with ContainedEvaluation(tmp_path, image="img", timeout=30) as contained:
            contained.run_argv(["python", "-m", "pytest", "-q"])
            contained.run_argv([CONTAINED_PYTHON, "-m", "coverage", "json", "-o", "-"])
            contained.run_argv_streams(["python", "-m", "ruff", "check", "."])

        assert len(sandbox_factory) == 1

    def test_the_image_and_timeout_come_from_the_config(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path
    ) -> None:
        ContainedEvaluation(tmp_path, image="maistro-builders:pinned", timeout=42).__enter__()

        assert sandbox_factory[0].image == "maistro-builders:pinned"


class TestItFailsClosed:
    def test_an_empty_vector_is_refused_outside_the_context_too(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path
    ) -> None:
        with (
            ContainedEvaluation(tmp_path, image="img", timeout=5) as contained,
            pytest.raises(ContainmentUnavailable, match="argument vector"),
        ):
            contained.run_argv([])

    def test_use_outside_the_context_manager_refuses(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path
    ) -> None:
        contained = ContainedEvaluation(tmp_path, image="img", timeout=5)

        with pytest.raises(ContainmentUnavailable, match="outside its context manager"):
            contained.run_argv(["python", "-c", "1"])

    @pytest.mark.parametrize(
        "failure",
        [
            RuntimeError("docker run failed: no such image"),
            OSError("docker: not found"),
            subprocess.TimeoutExpired(cmd="docker", timeout=1),
        ],
    )
    def test_a_sandbox_that_cannot_open_refuses(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        failure: BaseException,
    ) -> None:
        def _broken() -> Any:
            raise failure

        contained = ContainedEvaluation(tmp_path, image="img", timeout=5, sandbox_factory=_broken)

        with pytest.raises(ContainmentUnavailable):
            contained.__enter__()

    def test_a_sandbox_that_raises_mid_signal_refuses_not_fails_the_candidate(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path
    ) -> None:
        with ContainedEvaluation(tmp_path, image="img", timeout=5) as contained:
            sandbox_factory[0].responses["pytest"] = None  # type: ignore[assignment]
            sandbox = contained._sandbox
            assert sandbox is not None

            def _explode(argv: list[str], *, timeout: int) -> tuple[int, str]:
                raise RuntimeError("container gone")

            sandbox.run_argv_status = _explode  # type: ignore[method-assign]
            with pytest.raises(ContainmentUnavailable, match="container gone"):
                contained.run_argv(["python", "-m", "pytest", "-q"])

    def test_a_nonzero_exit_is_a_verdict_not_a_refusal(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path
    ) -> None:
        with ContainedEvaluation(tmp_path, image="img", timeout=5) as contained:
            sandbox_factory[0].responses["pytest"] = (1, "2 failed", "")

            code, out = contained.run_argv(["python", "-m", "pytest", "-q"])

        assert (code, out) == (1, "2 failed")


class TestResultsCrossAsData:
    def test_read_file_returns_container_bytes_and_file_not_found_stays_data_shaped(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path
    ) -> None:
        with ContainedEvaluation(tmp_path, image="img", timeout=5) as contained:
            sandbox_factory[0].files["coverage.json"] = '{"totals": {}}'

            assert contained.read_file("coverage.json") == '{"totals": {}}'
            with pytest.raises(FileNotFoundError):
                contained.read_file("absent.json")

    def test_paths_that_escape_the_workspace_are_refused(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path
    ) -> None:
        with ContainedEvaluation(tmp_path, image="img", timeout=5) as contained:
            with pytest.raises(ContainmentUnavailable, match="escapes"):
                contained.read_file("../host-secret")
            with pytest.raises(ContainmentUnavailable, match="escapes"):
                contained.write_file("/etc/passwd", "x")

    def test_write_file_plants_content_inside_the_sandbox(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path
    ) -> None:
        with ContainedEvaluation(tmp_path, image="img", timeout=5) as contained:
            contained.write_file("pkg/mod.py", "x = 1\n")

        assert sandbox_factory[0].files["pkg/mod.py"] == "x = 1\n"


# --------------------------------------------------------------------------
# evaluate_candidate routing: every executing signal crosses the boundary.
# No host subprocess may run while `contained` is set.
# --------------------------------------------------------------------------


@pytest.fixture
def forbid_host_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("a fitness signal attempted to run on the host")

    import maistro_evolve.code_quality as code_quality

    for mod in (
        candidate_fitness,
        __import__("maistro_rsi.fail_first", fromlist=["x"]),
        code_quality,
    ):
        monkeypatch.setattr(mod.subprocess, "run", _refuse)


def _contained(tmp_path: Path, fake: _FakeSandbox) -> ContainedEvaluation:
    session = ContainedEvaluation(tmp_path, image="img", timeout=60, sandbox_factory=lambda: fake)
    return session.__enter__()


class TestEvaluateCandidateRoutesThroughTheSandbox:
    def test_the_test_vector_runs_in_the_sandbox(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path, forbid_host_subprocess: None
    ) -> None:
        fake = _FakeSandbox(tmp_path)
        fake.responses["pytest"] = (0, "1 passed", "")

        with _contained(tmp_path, fake) as contained:
            scorecard = candidate_fitness.evaluate_candidate(
                tmp_path,
                [],
                test_command="python -m pytest -q",
                test_argv=("python", "-m", "pytest", "-q"),
                contained=contained,
            )

        gate = next(g for g in scorecard.gates if g.name == "tests_pass")
        assert gate.passed is True
        assert fake.status_argv[0] == ["python", "-m", "pytest", "-q"]

    def test_a_failing_vector_is_a_failed_gate_not_a_refusal(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path, forbid_host_subprocess: None
    ) -> None:
        fake = _FakeSandbox(tmp_path)
        fake.responses["pytest"] = (2, "3 failed", "")

        with _contained(tmp_path, fake) as contained:
            scorecard = candidate_fitness.evaluate_candidate(
                tmp_path,
                [],
                test_command="python -m pytest -q",
                test_argv=("python", "-m", "pytest", "-q"),
                contained=contained,
            )

        gate = next(g for g in scorecard.gates if g.name == "tests_pass")
        assert gate.passed is False
        assert "exit 2" in gate.reason

    def test_coverage_comes_back_as_data_from_the_sandbox(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path, forbid_host_subprocess: None
    ) -> None:
        """The coverage number is parsed from the container's report — the run
        happened inside, only JSON crossed the boundary."""
        fake = _FakeSandbox(tmp_path)
        report = json.dumps(
            {
                "totals": {"percent_covered": 87.5},
                "files": {"pkg/mod.py": {"missing_lines": [4, 5]}},
            }
        )
        fake.responses["coverage"] = (0, report, "")
        inputs: dict[str, Any] = {}

        real_measure = candidate_fitness.measure_coverage_detailed

        def _spy(*args: Any, **kwargs: Any) -> Any:
            inputs.update(kwargs)
            return real_measure(*args, **kwargs)

        orig = candidate_fitness.measure_coverage_detailed
        candidate_fitness.measure_coverage_detailed = _spy  # type: ignore[assignment]
        try:
            with _contained(tmp_path, fake) as contained:
                scorecard = candidate_fitness.evaluate_candidate(
                    tmp_path,
                    [],
                    test_command="python -m pytest -q",
                    test_argv=("python", "-m", "pytest", "-q"),
                    contained=contained,
                )
        finally:
            candidate_fitness.measure_coverage_detailed = orig  # type: ignore[assignment]

        assert inputs.get("execute") is not None
        assert inputs.get("interpreter") == CONTAINED_PYTHON
        cov_signal = next(s for s in scorecard.scores if s.name == "coverage")
        assert cov_signal.detail["candidate"] == 87.5
        coverage_argvs = [a for a in fake.stream_argv if "coverage" in a]
        assert len(coverage_argvs) == 2  # the instrumented run + the json report
        assert any("--source=." in tok for tok in coverage_argvs[0])

    def test_static_tool_reports_are_parsed_from_separated_streams(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path, forbid_host_subprocess: None
    ) -> None:
        """A ruff finding found inside must survive the trip: the gate reads
        the JSON report, not merged noise. stderr stays stderr so a warning
        line cannot corrupt the parse."""
        fake = _FakeSandbox(tmp_path)
        finding = json.dumps([{"filename": "mod.py"}])
        fake.responses["ruff"] = (1, finding, "warning: noisy stderr line")

        with _contained(tmp_path, fake) as contained:
            candidate_fitness.evaluate_candidate(
                tmp_path,
                ["mod.py"],
                test_command="python -m pytest -q",
                test_argv=("python", "-m", "pytest", "-q"),
                contained=contained,
            )

        ruff_calls = [a for a in fake.stream_argv if "ruff" in a]
        assert ruff_calls, "the static tool never ran in the sandbox"
        assert any("--output-format" in a for a in ruff_calls[0])

    def test_a_missing_tool_in_the_image_is_a_blocking_not_run_gate(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path, forbid_host_subprocess: None
    ) -> None:
        """The same required-gate contract in both isolation modes (#304 x
        #614): a tool the image lacks is a blocking ``not_run`` gate naming
        the cause — never a false rejection of the candidate's code, and
        never a silent narrowing of the evidence an operator asked for."""
        fake = _FakeSandbox(tmp_path)
        fake.responses["ruff"] = (1, "", "No module named ruff")

        with _contained(tmp_path, fake) as contained:
            scorecard = candidate_fitness.evaluate_candidate(
                tmp_path,
                ["mod.py"],
                test_command="python -m pytest -q",
                test_argv=("python", "-m", "pytest", "-q"),
                contained=contained,
            )

        ruff = next(g for g in scorecard.gates if g.name == "ruff_clean")
        assert ruff.passed is False
        assert ruff.resolved_state() is GateState.NOT_RUN
        assert "missing" in ruff.reason
        assert scorecard.accepted is False

    def test_a_contained_lint_gate_records_its_own_execution_not_host_facts(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path, forbid_host_subprocess: None
    ) -> None:
        """Provenance (#304) under containment (#614): the recorded command is
        the argv the SANDBOX received (its own interpreter, not a host path),
        and the host-only facts — installed dist version, host-tree HEAD — are
        honest Nones: the host tree is the seed, not the tree the gates
        scored, and no host process may run to ask either question."""
        fake = _FakeSandbox(tmp_path)
        fake.responses["ruff"] = (0, "[]", "")

        with _contained(tmp_path, fake) as contained:
            scorecard = candidate_fitness.evaluate_candidate(
                tmp_path,
                ["mod.py"],
                test_command="python -m pytest -q",
                test_argv=("python", "-m", "pytest", "-q"),
                contained=contained,
            )

        ruff = next(g for g in scorecard.gates if g.name == "ruff_clean")
        assert ruff.resolved_state() is GateState.PASSED
        detail = ruff.detail
        assert detail["command"] == [
            CONTAINED_PYTHON,
            "-m",
            "ruff",
            "check",
            "--output-format",
            "json",
            "mod.py",
        ]
        assert detail["tool_version"] is None
        assert detail["candidate_sha"] is None
        assert detail["exit_status"] == 0
        assert str(detail["output_digest"]).startswith("sha256:")

    def test_the_quality_tools_run_in_the_sandbox_not_on_the_host(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path, forbid_host_subprocess: None
    ) -> None:
        """`_mean_quality` -> `score_path` shells out to ruff/bandit/mypy/
        pylint/radon; under containment those launches cross the boundary too:
        they run inside the sandbox (absolute candidate paths, the image's
        interpreter) and only the parsed report comes back. A host launch —
        the leak this pins — would trip `forbid_host_subprocess` via
        maistro_evolve.code_quality's own subprocess module."""
        fake = _FakeSandbox(tmp_path)
        (tmp_path / "mod.py").write_text("x: int = 1\n", encoding="utf-8")
        fake.responses["ruff"] = (1, json.dumps([{"filename": "mod.py"}]), "")

        with _contained(tmp_path, fake) as contained:
            scorecard = candidate_fitness.evaluate_candidate(
                tmp_path,
                ["mod.py"],
                test_command="python -m pytest -q",
                test_argv=("python", "-m", "pytest", "-q"),
                contained=contained,
            )

        quality_runs = [a for a in fake.stream_argv if "ruff" in a]
        assert quality_runs, "the quality tools never ran in the sandbox"
        # The quality channel scores the changed source by ABSOLUTE path (the
        # lint gates use the relative one), proving `score_path` went contained.
        assert any(str(tmp_path / "mod.py") in tok for argv in quality_runs for tok in argv)
        quality = next(s for s in scorecard.scores if s.name == "code_quality")
        # One parsed ruff violation crosses the boundary and pulls the
        # composite below clean (ruff scores 0.5; the rest of the image's
        # tools report clean).
        assert 0.0 < quality.score < 1.0

    def test_a_missing_quality_tool_in_the_image_renormalises_not_fails(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path, forbid_host_subprocess: None
    ) -> None:
        """Same parity as the lint gates: an image without radon drops that
        measure from the composite (weights renormalise) instead of scoring 0
        or refusing the evaluation."""
        fake = _FakeSandbox(tmp_path)
        (tmp_path / "mod.py").write_text("x: int = 1\n", encoding="utf-8")
        fake.responses["radon"] = (1, "", "No module named radon")

        with _contained(tmp_path, fake) as contained:
            scorecard = candidate_fitness.evaluate_candidate(
                tmp_path,
                ["mod.py"],
                test_command="python -m pytest -q",
                test_argv=("python", "-m", "pytest", "-q"),
                contained=contained,
            )

        quality = next(s for s in scorecard.scores if s.name == "code_quality")
        assert 0.0 < quality.score <= 1.0  # composite still computed, renormalised

    def test_the_mutation_probe_writes_mutants_into_the_sandbox(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path, forbid_host_subprocess: None
    ) -> None:
        """The probe must mutate the tree the tests RUN against — the sandbox's
        copy — and never touch the host worktree."""
        probe = pytest.importorskip("maistro_evolve.mutation_probe")

        class _Runner:
            def __init__(self) -> None:
                self.files = {"mod.py": "x = 1\n"}
                self.runs: list[list[str]] = []

            def read_text(self, rel: str) -> str:
                return self.files[rel]

            def write_text(self, rel: str, content: str) -> None:
                self.files[rel] = content

            def run_tests(self, selectors: list[str], *, timeout: int) -> tuple[int, str]:
                self.runs.append(list(selectors))
                # The mutant is in place: the test sees the mutated constant and
                # fails → the mutant is killed.
                current = self.files["mod.py"]
                return (0 if current == "x = 1\n" else 1, "")

        runner = _Runner()
        result = probe.probe_diff_mutations(
            tmp_path,
            {"mod.py": {1}},
            ["tests/test_mod.py"],
            runner=runner,  # type: ignore[arg-type]
        )

        assert result.available is True
        assert result.killed == 1
        assert runner.files["mod.py"] == "x = 1\n", "the original must be restored"
        assert runner.runs == [["tests/test_mod.py"]]

    def test_the_fail_first_replay_runs_inside_the_sandbox(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path, forbid_host_subprocess: None
    ) -> None:
        """The red/green replay imports candidate test code: its probe runs go
        through the sandbox executor, not a host child process."""
        from maistro_rsi.fail_first import collect_fail_first_evidence

        class _Executor:
            def __init__(self) -> None:
                self.probes = 0

            def rev_parse(self, ref: str) -> str:
                return "a" * 40

            def base_has(self, ref: str, rel: str) -> bool:
                return True

            def checkout(self, ref: str, rel: str) -> None:
                pass

            def remove(self, rel: str) -> None:
                pass

            def probe(self, tests: list[str], timeout: int) -> tuple[int, str]:
                self.probes += 1
                # First probe: green on the candidate; the base replay is red
                # for the intended reason and reproducible.
                if self.probes == 1:
                    return 0, ""
                return 1, "FAILED tests/test_mod.py::test_g - assert 1 == 2\n"

            def read_text(self, rel: str) -> str:
                return "from mod import g\n"

        executor = _Executor()
        evidence = collect_fail_first_evidence(
            tmp_path,
            "base",
            ["mod.py"],
            ["tests/test_mod.py"],
            timeout=60,
            executor=executor,  # type: ignore[arg-type]
        )

        assert evidence is not None
        assert evidence.failing_tests == ["tests/test_mod.py::test_g"]
        assert evidence.related is True  # statically references the changed module
        assert executor.probes == 3  # candidate green check + red + reproduce


class TestTheRefusalArcsStayRefusals:
    """Each fail-closed branch of the contained transport, exercised directly:
    a sandbox that raises `ContainmentUnavailable` mid-flight must PASS IT
    THROUGH (it is already the right answer), any other failure must CONVERT
    to one, and every read/write must refuse workspace escapes (#614)."""

    def test_a_factory_refusal_passes_through_unchanged(self, tmp_path: Path) -> None:
        def _already_refusal_shaped() -> Any:
            raise ContainmentUnavailable("refused at the source")

        contained = ContainedEvaluation(
            tmp_path, image="img", timeout=5, sandbox_factory=_already_refusal_shaped
        )

        with pytest.raises(ContainmentUnavailable, match="refused at the source"):
            contained.__enter__()

    def test_a_mid_stream_signal_refusal_passes_through_and_other_errors_convert(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path
    ) -> None:
        with ContainedEvaluation(tmp_path, image="img", timeout=5) as contained:
            sandbox = contained._sandbox
            assert sandbox is not None

            def _refusal(argv: list[str], *, timeout: int) -> tuple[int, str, str]:
                raise ContainmentUnavailable("refused mid-stream")

            def _broken(argv: list[str], *, timeout: int) -> tuple[int, str, str]:
                raise RuntimeError("exec failed")

            sandbox.run_argv_streams = _refusal  # type: ignore[method-assign]
            with pytest.raises(ContainmentUnavailable, match="refused mid-stream"):
                contained.run_argv_streams(["python", "-m", "pytest", "-q"])

            sandbox.run_argv_streams = _broken  # type: ignore[method-assign]
            with pytest.raises(ContainmentUnavailable, match="exec failed"):
                contained.run_argv_streams(["python", "-m", "pytest", "-q"])

            sandbox.run_argv_streams = _refusal  # type: ignore[method-assign]
            with pytest.raises(ContainmentUnavailable, match="argument vector"):
                contained.run_argv_streams([])

    def test_data_transport_failures_refuse_and_stay_data_shaped_when_absent(
        self, sandbox_factory: list[_FakeSandbox], tmp_path: Path
    ) -> None:
        with ContainedEvaluation(tmp_path, image="img", timeout=5) as contained:
            sandbox = contained._sandbox
            assert sandbox is not None

            def _unreadable(path: str) -> str:
                raise RuntimeError("cat failed")

            sandbox.read_file = _unreadable  # type: ignore[method-assign]
            with pytest.raises(ContainmentUnavailable, match="cat failed"):
                contained.read_file("report.json")

            def _unwritable(path: str, content: str) -> None:
                raise RuntimeError("tee failed")

            sandbox.write_file = _unwritable  # type: ignore[method-assign]
            with pytest.raises(ContainmentUnavailable, match="tee failed"):
                contained.write_file("pkg/mutant.py", "x = 1")

            with pytest.raises(ContainmentUnavailable, match="escapes"):
                contained.write_file("../escape.py", "x = 1")

            # The MutationRunner aliases cross the same transport.
            with pytest.raises(ContainmentUnavailable, match="cat failed"):
                contained.read_text("report.json")
            with pytest.raises(ContainmentUnavailable, match="tee failed"):
                contained.write_text("pkg/mutant.py", "x = 1")


class TestTheContainedProbeExecutor:
    """The fail-first probe's git plumbing and reruns, step by step, through
    the one sandbox — including the answers a green/absent/failed step each
    produce (#614)."""

    def _executor(self, tmp_path: Path, fake: _FakeSandbox) -> Any:
        from maistro_rsi.candidate_fitness import _ContainedProbeExecutor

        contained = ContainedEvaluation(
            tmp_path, image="img", timeout=5, sandbox_factory=lambda: fake
        ).__enter__()
        return _ContainedProbeExecutor(contained), contained

    def test_git_plumbing_reads_and_the_probe_rerun_cross_the_boundary(
        self, tmp_path: Path
    ) -> None:
        fake = _FakeSandbox(tmp_path)
        fake.responses["rev-parse"] = (0, "  abc123  \n", "")
        fake.responses["cat-file"] = (1, "", "not in base")
        fake.files["tests/test_gone.py"] = "def test_x():\n    assert True\n"
        executor, contained = self._executor(tmp_path, fake)

        assert executor.rev_parse("base") == "abc123"  # stripped, zero exit
        assert executor.base_has("base", "src/mod.py") is False  # non-zero
        executor.checkout("base", "src/mod.py")
        executor.remove("tests/test_gone.py")
        code, out = executor.probe(["tests/test_mod.py"], timeout=60)
        assert (code, out) == (0, "")
        assert executor.read_text("tests/test_gone.py").startswith("def test_x")

        git_steps = [argv for argv in fake.status_argv if argv[0] == "git"]
        assert [step[1] for step in git_steps] == [
            "rev-parse",
            "cat-file",
            "checkout",
        ]
        # `remove` shells `rm`, not git — but it crossed the boundary too.
        assert ["rm", "-f", "tests/test_gone.py"] in fake.status_argv
        probe_argv = fake.status_argv[-1]
        assert probe_argv[:7] == [
            CONTAINED_PYTHON,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-rfE",
        ]
        assert probe_argv[7:] == ["tests/test_mod.py"]
        contained.__exit__(None, None, None)

    def test_a_failed_rev_parse_answers_empty_not_an_error(self, tmp_path: Path) -> None:
        fake = _FakeSandbox(tmp_path)
        fake.responses["rev-parse"] = (128, "", "unknown revision")
        executor, contained = self._executor(tmp_path, fake)

        assert executor.rev_parse("missing-ref") == ""
        contained.__exit__(None, None, None)

    def test_the_test_vector_and_per_file_collection_refuse_or_cross(self, tmp_path: Path) -> None:
        """`_run` with a contained executor refuses an empty vector (no host
        fallback), and per-file collection runs the same argv inside the
        sandbox that the host path would run on the host."""
        from maistro_rsi.candidate_fitness import _uncollectable_tests

        with pytest.raises(ContainmentUnavailable, match="argument vector"):
            candidate_fitness._run(
                "python -m pytest -q", tmp_path, 60, argv=(), execute=lambda a: (0, "")
            )

        seen: list[list[str]] = []
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_new.py").write_text(
            "def test_one():\n    pass\n", encoding="utf-8"
        )

        def execute(argv: list[str]) -> tuple[int, str, str]:
            seen.append(list(argv))
            return 5, "", ""  # pytest's "no tests collected"

        reasons = _uncollectable_tests(
            tmp_path,
            ["tests/test_new.py"],
            ["tests"],
            src_files=[],
            execute=execute,
            interpreter=CONTAINED_PYTHON,
        )

        assert reasons == ["tests/test_new.py: pytest could not collect it (exit 5)"]
        assert seen == [
            [CONTAINED_PYTHON, "-m", "pytest", "--collect-only", "-q", "tests/test_new.py"]
        ]


# --------------------------------------------------------------------------
# Real-backend evidence (docker-gated): the same routing against the actual
# ContainerBuilderSandbox, so the seam is exercised where the container really
# runs. Skipped without a daemon/image — which is NOT production proof by
# itself; the closeout evidence for the supported path is recorded in the
# issue, not assumed from a skip.
# --------------------------------------------------------------------------


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(["docker", "version"], capture_output=True, text=True, timeout=30)
    if probe.returncode != 0:
        return False
    from maistro_bootstrap.builders.container_sandbox import DEFAULT_IMAGE

    r = subprocess.run(
        ["docker", "image", "inspect", DEFAULT_IMAGE], capture_output=True, text=True
    )
    return r.returncode == 0


@pytest.mark.skipif(not _docker_ready(), reason="docker daemon or builders image unavailable")
def test_real_container_runs_the_vector_and_returns_its_status(tmp_path: Path) -> None:
    from maistro_bootstrap.builders.container_sandbox import DEFAULT_IMAGE

    (tmp_path / "test_smoke.py").write_text(
        "def test_passes():\n    assert True\n", encoding="utf-8"
    )

    with ContainedEvaluation(tmp_path, image=DEFAULT_IMAGE, timeout=120) as contained:
        code, output = contained.run_argv(["python", "-m", "pytest", "-q", "test_smoke.py"])

    assert code == 0, output[-500:]


@pytest.mark.skipif(not _docker_ready(), reason="docker daemon or builders image unavailable")
def test_real_container_refuses_when_the_image_is_missing(tmp_path: Path) -> None:
    session = ContainedEvaluation(
        tmp_path, image="definitely-not-a-real-image-614:latest", timeout=60
    )

    with pytest.raises(ContainmentUnavailable):
        session.__enter__()


def _fitness_toolchain_in_image() -> bool:
    """The supported builders image must carry the fitness toolchain (#614
    closeout): the vector and the red/green replay run `python -m pytest`, the
    coverage signal runs `python -m coverage`, the lint gates run
    `python -m ruff`. An image without them still exercises the smoke tests
    above — and the gates renormalise by design — but the end-to-end proof
    below needs the real signals to run for real, so it names the requirement
    in its skip reason instead of silently weakening its assertions."""
    if not _docker_ready():
        return False
    from maistro_bootstrap.builders.container_sandbox import DEFAULT_IMAGE

    probe = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network=none",
            DEFAULT_IMAGE,
            "python",
            "-c",
            "import pytest, coverage, ruff",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return probe.returncode == 0


class _RecordingEvaluation(ContainedEvaluation):
    """A real ContainedEvaluation that records every channel call, so the
    end-to-end proof can assert WHICH signals crossed the sandbox boundary —
    the same shape the host-side fake asserts, executed against the real
    backend."""

    def __init__(self, cycle_dir: Path, *, image: str, timeout: int) -> None:
        super().__init__(cycle_dir, image=image, timeout=timeout)
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def run_argv(self, argv: Any, *, timeout: int | None = None) -> tuple[int, str]:
        self.calls.append(("run_argv", tuple(argv)))
        return super().run_argv(argv, timeout=timeout)

    def run_argv_streams(self, argv: Any, *, timeout: int | None = None) -> tuple[int, str, str]:
        self.calls.append(("run_argv_streams", tuple(argv)))
        return super().run_argv_streams(argv, timeout=timeout)

    def write_file(self, path: str, content: str) -> None:
        self.calls.append(("write_file", (path,)))
        return super().write_file(path, content)


@pytest.mark.skipif(
    not _fitness_toolchain_in_image(),
    reason="docker daemon, or builders image without the fitness toolchain "
    "(pytest/coverage/ruff), unavailable",
)
def test_real_evaluation_scores_every_signal_inside_one_container(
    tmp_path: Path,
) -> None:
    """#614 closeout, against the REAL backend: `evaluate_candidate` under a
    real ContainedEvaluation produces a Scorecard whose every executing
    signal — vector, coverage run+report, red/green replay, static tools,
    per-file collection, the mutation probe — ran inside the ONE container,
    with the results crossing back as data and the host tree never touched."""
    from maistro_bootstrap.builders.container_sandbox import DEFAULT_IMAGE
    from maistro_rsi.candidate_fitness import evaluate_candidate

    pkg, tests = tmp_path / "pkg", tmp_path / "tests"
    pkg.mkdir()
    tests.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tests / "test_calc.py").write_text(
        "from pkg.calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "baseline")
    candidate_src = "def add(a, b):\n    return a + b\n\n\ndef multiply(a, b):\n    return a * b\n"
    (pkg / "calc.py").write_text(candidate_src, encoding="utf-8")
    (tests / "test_calc.py").write_text(
        "from pkg.calc import add, multiply\n\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n\n"
        "def test_multiply():\n    assert multiply(2, 3) == 6\n",
        encoding="utf-8",
    )
    git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "candidate")

    contained = _RecordingEvaluation(tmp_path, image=DEFAULT_IMAGE, timeout=600)
    with contained:
        scorecard = evaluate_candidate(
            tmp_path,
            ["pkg/calc.py", "tests/test_calc.py"],
            test_command="python -m pytest -q tests",
            test_argv=("python", "-m", "pytest", "-q", "tests"),
            coverage_source="pkg",
            coverage_pytest_args="tests",
            baseline_coverage=50.0,
            baseline_ref="HEAD~1",
            timeout=600,
            contained=contained,
        )

    # A Scorecard WAS produced (the #496 refusal is gone) and the vector ran
    # green inside the container.
    gates = {gate.name: gate for gate in scorecard.gates}
    assert gates["tests_pass"].passed

    # AC-5 on the real backend: the coverage number came back as DATA from the
    # container and drove an ENFORCED gate decision (baseline 50 was supplied,
    # so "not enforced" would mean the transport failed).
    assert gates["coverage_not_dropped"].passed
    assert "not enforced" not in gates["coverage_not_dropped"].reason

    # AC-1 on the real backend: every executing signal crossed the sandbox
    # channel — nothing ran on the host.
    statuses = [argv for kind, argv in contained.calls if kind == "run_argv"]
    streams = [argv for kind, argv in contained.calls if kind == "run_argv_streams"]

    def ran(prefix: tuple[str, ...], pool: list[tuple[str, ...]]) -> bool:
        return any(argv[: len(prefix)] == prefix for argv in pool)

    assert ran(("python", "-m", "pytest", "-q", "tests"), statuses)  # the vector
    assert ran(("python", "-m", "coverage", "run"), streams)  # the coverage run
    assert ran(("python", "-m", "coverage", "json"), streams)  # its report, as data
    assert ran(
        ("python", "-m", "pytest", "-q", "-p", "no:cacheprovider"), statuses
    )  # the red/green replay + the probe's reruns
    assert ran(("python", "-m", "pytest", "--collect-only"), streams)  # collection
    assert ran(("python", "-m", "ruff"), streams)  # a static tool, in-image

    # The mutation probe planted its mutant INSIDE the sandbox...
    assert ("write_file", ("pkg/calc.py",)) in contained.calls
    # ...and the host worktree was never the tree the mutant ran against.
    assert (pkg / "calc.py").read_text(encoding="utf-8") == candidate_src

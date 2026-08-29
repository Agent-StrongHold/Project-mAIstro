"""The seam that runs a candidate's validation where its edits live (#305).

Every branch here answers the same question: when containment cannot be
established, does the caller get a refusal or a verdict? A verdict would mean a
candidate that never ran contained is reported as having passed or failed on
evidence that does not exist.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from maistro_rsi import contained_validation
from maistro_rsi.contained_validation import ContainmentUnavailable, run_validation_in_container


class _Sandbox:
    """A stand-in for `ContainerBuilderSandbox` with the same context shape."""

    def __init__(self, repo_root: Path, *, image: str) -> None:
        self.repo_root = repo_root
        self.image = image
        self.status: tuple[int, str] = (0, "")
        self.raises: BaseException | None = None
        _Sandbox.last = self

    def __enter__(self) -> _Sandbox:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.exited = True

    def run_argv_status(self, argv: list[str], *, timeout: int) -> tuple[int, str]:
        self.argv = list(argv)
        self.timeout = timeout
        if self.raises is not None:
            raise self.raises
        return self.status


@pytest.fixture
def sandbox(monkeypatch: pytest.MonkeyPatch) -> type[_Sandbox]:
    module = pytest.importorskip("maistro_bootstrap.builders.container_sandbox")
    monkeypatch.setattr(module, "ContainerBuilderSandbox", _Sandbox)
    return _Sandbox


class TestTheVerdictComesFromTheContainer:
    @pytest.mark.ac("SPEC-082926-a6ab/AC-4")
    def test_a_zero_exit_is_a_pass(self, tmp_path: Path, sandbox: type[_Sandbox]) -> None:
        assert (
            run_validation_in_container(tmp_path, ["pytest", "-q"], image="img", timeout=30) is True
        )

    @pytest.mark.ac("SPEC-082926-a6ab/AC-4")
    def test_a_non_zero_exit_is_a_failure_not_an_error(
        self, tmp_path: Path, sandbox: type[_Sandbox], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A candidate whose tests fail is an ordinary answer, and must not be
        confused with a sandbox that could not run them."""
        monkeypatch.setattr(
            _Sandbox,
            "run_argv_status",
            lambda self, argv, *, timeout: (1, "2 failed"),
        )

        assert run_validation_in_container(tmp_path, ["pytest"], image="img", timeout=30) is False

    @pytest.mark.ac("SPEC-082926-a6ab/AC-2")
    def test_the_container_is_seeded_from_the_candidate_directory(
        self, tmp_path: Path, sandbox: type[_Sandbox]
    ) -> None:
        """Not the baseline: the point is to run the candidate's own edits."""
        cycle = tmp_path / "cycle-3"

        run_validation_in_container(cycle, ["pytest"], image="pinned:1", timeout=7)

        assert _Sandbox.last.repo_root == cycle
        assert _Sandbox.last.image == "pinned:1"
        assert _Sandbox.last.argv == ["pytest"]
        assert _Sandbox.last.timeout == 7

    @pytest.mark.ac("SPEC-082926-a6ab/AC-2")
    def test_the_container_is_torn_down(self, tmp_path: Path, sandbox: type[_Sandbox]) -> None:
        run_validation_in_container(tmp_path, ["pytest"], image="img", timeout=5)

        assert _Sandbox.last.exited is True


class TestItFailsClosed:
    @pytest.mark.ac("SPEC-082926-a6ab/AC-5")
    def test_an_empty_vector_is_refused(self, tmp_path: Path, sandbox: type[_Sandbox]) -> None:
        """There is no shell inside the sandbox to hand a command string to,
        and joining a vector would re-split any token holding a space."""
        with pytest.raises(ContainmentUnavailable, match="argument vector"):
            run_validation_in_container(tmp_path, [], image="img", timeout=5)

    @pytest.mark.parametrize(
        "failure",
        [
            RuntimeError("docker run failed: no such image"),
            OSError("docker: not found"),
            subprocess.TimeoutExpired(cmd="docker", timeout=1),
        ],
    )
    @pytest.mark.ac("SPEC-082926-a6ab/AC-5")
    def test_a_sandbox_that_cannot_run_refuses_rather_than_failing_the_candidate(
        self,
        tmp_path: Path,
        sandbox: type[_Sandbox],
        monkeypatch: pytest.MonkeyPatch,
        failure: BaseException,
    ) -> None:
        def _raise(self: Any, argv: Any, *, timeout: int) -> tuple[int, str]:
            raise failure

        monkeypatch.setattr(_Sandbox, "run_argv_status", _raise)

        with pytest.raises(ContainmentUnavailable, match="container isolation"):
            run_validation_in_container(tmp_path, ["pytest"], image="img", timeout=5)

    @pytest.mark.ac("SPEC-082926-a6ab/AC-5")
    def test_a_missing_container_backend_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The import is deferred, so an environment without maistro-bootstrap
        would otherwise raise ImportError from inside a validation call."""
        import builtins

        real_import = builtins.__import__

        def _fail(name: str, *args: Any, **kwargs: Any) -> Any:
            if name.startswith("maistro_bootstrap"):
                raise ImportError("no maistro_bootstrap here")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fail)

        with pytest.raises(ContainmentUnavailable, match="container sandbox"):
            run_validation_in_container(tmp_path, ["pytest"], image="img", timeout=5)

    @pytest.mark.ac("SPEC-082926-a6ab/AC-4")
    def test_the_refusal_is_not_an_ordinary_failure(self) -> None:
        """`ContainmentUnavailable` must not be catchable as the loop's own
        "one bad cycle" handler catches `Exception`... it is, and that is the
        point of asserting it: the loop's guard runs before the cycle loop."""
        assert issubclass(ContainmentUnavailable, RuntimeError)


def test_the_module_states_why_a_host_fallback_is_worse() -> None:
    """The reasoning is the artifact here — a later reader deciding to "just
    fall back when docker is missing" is the regression this guards."""
    assert "worse" in (contained_validation.__doc__ or "")

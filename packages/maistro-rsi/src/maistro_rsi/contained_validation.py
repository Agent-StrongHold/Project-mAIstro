"""Run a candidate's validation command where the candidate's edits live (#305).

`isolation="container"` was applied to the *editing* half of a cycle and not to
the *validating* half. The builders agent wrote inside a container, its edits
were synced back to the host worktree, and then the loop ran the test vector on
the host with `subprocess.run(argv, cwd=cycle_dir)`.

An argument vector is not an isolation boundary. `shell=False` decides how the
first command is parsed; it says nothing about whose code runs afterwards, and
a validation profile such as `python -m pytest` imports the candidate's test
modules, its `conftest.py`, and any pytest plugin its configuration declares.
So the candidate executed as the loop's own process, from an HTTP-initiated
run, under a setting whose whole purpose was to prevent that.

This module is the seam that fixes it, shared by `local_loop._run_tests` and
`candidate_fitness`, so the two halves of a cycle cannot drift back apart.

Fails closed, deliberately. Every branch that cannot establish containment
raises `ContainmentUnavailable` rather than returning a verdict:

  * no argument vector — there is no shell inside the sandbox to hand a command
    string to, and joining a vector into one would re-split any token holding a
    space, so the thing that ran would not be the thing policy named;
  * the container backend unavailable — a missing image or daemon is a reason
    to stop, not a reason to run candidate code on the host.

A refused run is a run that did not happen. A host-side fallback is a
containment failure that reports success, which is strictly worse.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# The interpreter a contained command invokes inside the sandbox (#614). The
# same name the Conductor's test profiles use ("python -m pytest"), for the
# same reason: the vector must name something the TARGET environment provides,
# and `sys.executable` here is a host path a container may not have.
CONTAINED_PYTHON = "python"

__all__ = [
    "CONTAINED_PYTHON",
    "ContainedEvaluation",
    "ContainmentUnavailable",
    "run_validation_in_container",
]


class ContainmentUnavailable(RuntimeError):
    """Containment was required and could not be established.

    Never caught here and turned into a failing verdict: "the tests failed" and
    "the tests could not be run safely" are different facts, and collapsing them
    would let a broken sandbox read as a candidate that did not pass.
    """


def run_validation_in_container(
    cycle_dir: Path,
    test_argv: Sequence[str],
    *,
    image: str,
    timeout: int,
) -> bool:
    """Run ``test_argv`` inside a container seeded from ``cycle_dir``.

    Returns whether the command exited zero. Raises `ContainmentUnavailable`
    rather than falling back to the host.
    """
    argv = list(test_argv)
    if not argv:
        raise ContainmentUnavailable(
            "container isolation requires an argument vector: there is no shell "
            "inside the sandbox to hand a command string to, and running the "
            "command on the host instead is the failure this exists to prevent"
        )
    try:
        from maistro_bootstrap.builders.container_sandbox import ContainerBuilderSandbox
    except ImportError as exc:  # pragma: no cover - exercised by the import test
        raise ContainmentUnavailable(
            f"container isolation needs maistro-bootstrap's container sandbox: {exc}"
        ) from exc

    try:
        with ContainerBuilderSandbox(cycle_dir, image=image) as sandbox:
            code, output = sandbox.run_argv_status(argv, timeout=timeout)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise ContainmentUnavailable(
            f"could not run the candidate's validation under container isolation: {exc}"
        ) from exc

    if code != 0:
        logger.info("rsi_contained_tests_failed", tail=output[-500:])
    return code == 0


class ContainedEvaluation:
    """One sandbox per evaluation; the fitness signals run inside it (#614).

    `evaluate_candidate` composes its Scorecard from signals that each execute
    the candidate's own code — the test vector, a coverage run, the red/green
    replay, the mutation probe's reruns and the static tools. Under container
    isolation each of those used to run on the host, which is why `LocalRsiLoop`
    had to REFUSE fitness entirely (#614). This is the session that removes the
    refusal instead of weakening it: the caller opens one sandbox seeded from
    the candidate directory, hands the object to `evaluate_candidate`, and every
    executing signal runs through `run_argv` here. One container per evaluation,
    not one per signal — a per-signal container would multiply a multi-cycle
    run's cost by the number of gates.

    Results cross the boundary as data. Exit statuses, stdout/stderr, and file
    contents read back through `read_file` are the only things that return; the
    host never re-executes anything the candidate wrote to obtain them.

    Fails closed like `run_validation_in_container`: an empty argument vector,
    an unimportable backend, or a sandbox that raises while establishing or
    executing raises `ContainmentUnavailable`. A signal that RUNS and exits
    non-zero is an ordinary verdict, not a refusal — "the tests failed" stays
    distinguishable from "the tests could not be run safely".
    """

    def __init__(
        self,
        cycle_dir: Path,
        *,
        image: str,
        timeout: int,
        sandbox_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._cycle_dir = Path(cycle_dir)
        self._image = image
        self._timeout = timeout
        self._sandbox_factory = sandbox_factory
        self._sandbox: Any = None

    def __enter__(self) -> ContainedEvaluation:
        if self._sandbox_factory is not None:
            factory = self._sandbox_factory
        else:

            def factory() -> Any:
                try:
                    from maistro_bootstrap.builders.container_sandbox import (
                        ContainerBuilderSandbox,
                    )
                except ImportError as exc:  # pragma: no cover - exercised by the import test
                    raise ContainmentUnavailable(
                        f"container isolation needs maistro-bootstrap's container sandbox: {exc}"
                    ) from exc
                return ContainerBuilderSandbox(self._cycle_dir, image=self._image)

        try:
            self._sandbox = factory().__enter__()
        except ContainmentUnavailable:
            raise
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            raise ContainmentUnavailable(
                f"could not open the evaluation sandbox seeded from the candidate directory: {exc}"
            ) from exc
        return self

    def __exit__(self, *exc: object) -> None:
        if self._sandbox is not None:
            try:
                self._sandbox.__exit__(*exc)
            finally:
                self._sandbox = None

    def _require_sandbox(self) -> Any:
        if self._sandbox is None:
            raise ContainmentUnavailable(
                "ContainedEvaluation used outside its context manager: there is no "
                "sandbox to run a signal in, and running it on the host instead is "
                "the failure this exists to prevent"
            )
        return self._sandbox

    def run_argv(self, argv: Sequence[str], *, timeout: int | None = None) -> tuple[int, str]:
        """Run one signal's command inside the sandbox; return (exit code, output).

        A non-zero exit is an ordinary result — the SIGNAL failed, not the
        containment. Only a sandbox that cannot establish or execute raises
        `ContainmentUnavailable`.
        """
        vector = list(argv)
        if not vector:
            raise ContainmentUnavailable(
                "container isolation requires an argument vector: there is no shell "
                "inside the sandbox to hand a command string to, and running the "
                "command on the host instead is the failure this exists to prevent"
            )
        sandbox = self._require_sandbox()
        try:
            return sandbox.run_argv_status(vector, timeout=timeout or self._timeout)
        except ContainmentUnavailable:
            raise
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            raise ContainmentUnavailable(
                f"could not run a fitness signal under container isolation: {exc}"
            ) from exc

    def run_argv_streams(
        self, argv: Sequence[str], *, timeout: int | None = None
    ) -> tuple[int, str, str]:
        """Like `run_argv` but with stdout/stderr separated, for callers that
        PARSE a stream (tool reports, collectors): a stray stderr line merged
        into stdout must not be able to turn a real finding into no finding."""
        vector = list(argv)
        if not vector:
            raise ContainmentUnavailable(
                "container isolation requires an argument vector: there is no shell "
                "inside the sandbox to hand a command string to, and running the "
                "command on the host instead is the failure this exists to prevent"
            )
        sandbox = self._require_sandbox()
        try:
            return sandbox.run_argv_streams(vector, timeout=timeout or self._timeout)
        except ContainmentUnavailable:
            raise
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            raise ContainmentUnavailable(
                f"could not run a fitness signal under container isolation: {exc}"
            ) from exc

    def read_file(self, path: str) -> str:
        """Read a file the sandbox run produced, as data.

        Raises `FileNotFoundError` when the file is absent — a missing artifact
        is a data-shaped answer (the run did not produce it), not a containment
        failure.
        """
        sandbox = self._require_sandbox()
        rel = PurePosixPath(path.replace("\\", "/"))
        if rel.is_absolute() or ".." in rel.parts:
            raise ContainmentUnavailable(f"path {path!r} escapes the sandbox workspace")
        try:
            return sandbox.read_file(str(rel))
        except FileNotFoundError:
            raise
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            raise ContainmentUnavailable(
                f"could not read a result back from the evaluation sandbox: {exc}"
            ) from exc

    def write_file(self, path: str, content: str) -> None:
        """Write content INTO the sandbox — how a mutation probe plants a mutant
        in the tree the tests will actually run against (#614)."""
        sandbox = self._require_sandbox()
        rel = PurePosixPath(path.replace("\\", "/"))
        if rel.is_absolute() or ".." in rel.parts:
            raise ContainmentUnavailable(f"path {path!r} escapes the sandbox workspace")
        try:
            sandbox.write_file(str(rel), content)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            raise ContainmentUnavailable(
                f"could not write into the evaluation sandbox: {exc}"
            ) from exc

    # -- MutationRunner protocol (maistro_evolve.mutation_probe) -------------
    # Aliases so this object can be handed to `probe_diff_mutations` directly:
    # the probe reads/writes the tree it tests, so under containment those
    # reads and writes land in the sandbox, never on the host worktree.

    def read_text(self, rel: str) -> str:
        return self.read_file(rel)

    def write_text(self, rel: str, content: str) -> None:
        self.write_file(rel, content)

    def run_tests(self, selectors: list[str], *, timeout: int) -> tuple[int, str]:
        # The same selection shape run_test_selection composes on the host —
        # one builder, so a contained run cannot drift from the host one.
        return self.run_argv(
            [
                CONTAINED_PYTHON,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                *selectors,
            ],
            timeout=timeout,
        )

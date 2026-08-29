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
from collections.abc import Sequence
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["ContainmentUnavailable", "run_validation_in_container"]


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

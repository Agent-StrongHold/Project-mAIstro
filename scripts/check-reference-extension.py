#!/usr/bin/env python3
"""Fixture: an extension builds and tests in a clean environment (M9-A3, #951).

What this proves
----------------
`check-extension-imports.py` reads imports statically; this fixture makes the
same claim physically. For every extension package under the policy's
``extension_trees`` it:

1. **builds** the extension as a wheel with ``uv build``;
2. **creates a fresh venv** and installs exactly two things into it: that
   wheel and pytest (the wheel's own declared dependencies resolve normally,
   which is the point — declare a dependency and a clean environment fetches
   it; import one you did not declare and the tests fail with ImportError);
3. **asserts the venv is clean**: every product-private import root from the
   namespace policy, plus the repo-relative sentinels ``packages`` and
   ``extensions``, must be UNIMPORTABLE from that venv;
4. **verifies the required artifacts from the installed distribution**: the
   discovery manifest (``extension.json``) must be present in what the wheel
   actually installed, read back via ``importlib.metadata`` — packaging that
   drops it fails here instead of at a host's discovery time;
5. **runs a staged copy of the extension's tests** (copied into the sandbox,
   so no test can read a resource that lives only in the checkout — a
   checkout-run suite would stay green even if the wheel omitted the files
   it reads) with that venv's interpreter from a neutral working directory,
   with pytest's conftest discovery cut off at the sandbox.

A fresh venv contains no part of this repository. So if the suite passes
there, the extension needed no repo-relative import, no ``sys.path`` repair,
and no product-private module to build or test — the CI-level acceptance the
issue asks for ("an extension can build/test without repo-relative imports"),
executed rather than asserted.

Why static + physical
---------------------
The static gate catches the import the author wrote; the fixture catches the
environment the author secretly needs — an undeclared dev tool used by a test,
a resource read from the checkout, a conftest fixture that only exists in
this tree. Either half alone can be green while the extension still cannot be
built by a third party.

Usage
-----
    python3 scripts/check-reference-extension.py
    python3 scripts/check-reference-extension.py --policy extensions/namespace-policy.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = REPO_ROOT / "extensions" / "namespace-policy.json"

#: Repo-relative sentinels probed alongside the policy's private roots: if a
#: venv can import ``packages`` or ``extensions``, the checkout leaked in.
_REPO_RELATIVE_SENTINELS = ("packages", "extensions")

#: Placeholder in the plan for the distribution name of the wheel the run
#: builds; ``isolate`` substitutes the real name from the built wheel's
#: filename so the artifact check reads back that exact distribution.
_WHEEL_DIST_NAME_ARG = "@WHEEL_DIST_NAME@"

_SUBPROCESS_TIMEOUT_S = 900


class FixtureError(RuntimeError):
    """A configuration or execution failure of the fixture itself."""


@dataclass(frozen=True)
class Step:
    """One executed command and what it was for (printed on failure)."""

    description: str
    argv: tuple[str, ...]
    expect_failure: bool = False
    """Negative controls: the command succeeding is the violation."""


def load_policy(path: Path) -> dict[str, object]:
    """Read the namespace policy (the same file the import gate enforces)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FixtureError(f"policy file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FixtureError(f"policy file is not valid JSON: {path}: {exc}") from exc
    if not raw.get("extension_trees"):
        raise FixtureError("policy declares no extension_trees; nothing to isolate")
    return raw


def discover_extension_projects(repo_root: Path, policy: dict[str, object]) -> list[Path]:
    """Extension directories (with a pyproject.toml) per the policy's trees."""
    projects: list[Path] = []
    for pattern in policy["extension_trees"]:
        dirs = [m for m in sorted(repo_root.glob(str(pattern))) if m.is_dir()]
        if not dirs:
            raise FixtureError(f"extension_trees pattern {pattern!r} matched no directory")
        for directory in dirs:
            if not (directory / "pyproject.toml").is_file():
                raise FixtureError(
                    f"extension {directory.name} has no pyproject.toml; an extension must "
                    "be its own buildable project"
                )
            projects.append(directory)
    return projects


def clean_env() -> dict[str, str]:
    """The environment subprocesses run under: no inherited interpreter state.

    ``PYTHONPATH``/``PYTHONHOME`` are exactly the levers that could smuggle the
    repository into the fresh venv; removing them is what makes the negative
    control meaningful on a developer machine as well as in CI.
    """
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    return env


def _run(step: Step, cwd: Path | None) -> str:
    result = subprocess.run(
        step.argv,
        cwd=cwd,
        env=clean_env(),
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
        check=False,
    )
    expected = step.expect_failure
    if (result.returncode != 0) == expected:
        return result.stdout
    verdict = "failed" if not expected else "succeeded where it must not"
    raise FixtureError(
        f"{step.description} {verdict} (exit {result.returncode}):\n"
        f"  command: {' '.join(step.argv)}\n"
        f"  stdout:\n{result.stdout}\n  stderr:\n{result.stderr}"
    )


def isolation_plan(extension_dir: Path, policy: dict[str, object], workdir: Path) -> list[Step]:
    """The exact commands that prove one extension builds and tests cleanly.

    Exposed as a function (and executed stepwise by ``isolate``) so the plan
    is inspectable — and testable — without running any of it.
    """
    dist = workdir / "dist"
    venv = workdir / "venv"
    venv_python = venv / "bin" / "python"
    # The tests the isolated run executes are the staged copy under the
    # sandbox, never the checkout's tests/ directory (``isolate`` copies
    # them in before any step executes).
    tests = workdir / "sandbox" / "tests"
    declared = policy.get("required_artifacts", ["extension.json"])
    if not isinstance(declared, list) or not all(isinstance(a, str) for a in declared):
        raise FixtureError("policy required_artifacts must be a list of file names")
    required_artifacts = tuple(declared)
    return (
        [
            Step("build wheel", ("uv", "build", "--wheel", "--out-dir", str(dist))),
            Step("create fresh venv", ("uv", "venv", str(venv), "--python", sys.executable)),
            Step(
                "install wheel + pytest into the fresh venv",
                ("uv", "pip", "install", "--python", str(venv_python), f"{dist}/*.whl", "pytest"),
            ),
        ]
        + [
            Step(
                f"product-private root {root!r} is unimportable from the fresh venv",
                (str(venv_python), "-c", f"import {root}"),
                expect_failure=True,
            )
            for root in (
                *policy["product_private_namespaces"],
                *_REPO_RELATIVE_SENTINELS,
            )
        ]
        + [
            Step(
                "installed distribution carries the extension's required artifacts",
                (
                    str(venv_python),
                    "-c",
                    "import importlib.metadata, sys; "
                    "installed = {f.name for f in (importlib.metadata.files(sys.argv[1]) or [])}; "
                    "missing = sorted(set(sys.argv[2:]) - installed); "
                    "sys.exit(f'installed {sys.argv[1]} lacks required artifacts: {missing}' "
                    "if missing else 0)",
                    _WHEEL_DIST_NAME_ARG,
                    *required_artifacts,
                ),
            )
        ]
        + [
            Step(
                "run the staged copy of the extension's tests with the fresh venv's interpreter",
                (
                    str(venv_python),
                    "-m",
                    "pytest",
                    str(tests),
                    "-q",
                    # The staged copy has no pyproject.toml above it, so the
                    # extension's pytest options are pinned here: importlib
                    # mode keeps pytest from inserting the tests dir on
                    # sys.path, and conftest discovery is cut off at the
                    # sandbox so neither the repository's nor the checkout's
                    # conftest.py can participate.
                    "--import-mode=importlib",
                    "--strict-markers",
                    "--rootdir",
                    str(tests.parent),
                    "--confcutdir",
                    str(tests.parent),
                    "-p",
                    "no:cacheprovider",
                ),
            )
        ]
    )


def isolate(extension_dir: Path, policy: dict[str, object], workdir: Path) -> None:
    """Execute the plan for one extension, failing on the first broken step."""
    dist = workdir / "dist"
    # Neutral working directory for every step after the build: nothing that
    # runs inside the venv may resolve the checkout by accident of cwd.
    sandbox = workdir / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    # Stage a copy of the tests inside the sandbox: a suite executed straight
    # out of the checkout could still read sibling checkout resources
    # (``extension.json``, fixture files) the installed wheel does not carry,
    # and pass for the wrong reason. From here on, only venv-visible files
    # exist.
    staged_tests = sandbox / "tests"
    shutil.rmtree(staged_tests, ignore_errors=True)
    shutil.copytree(
        extension_dir / "tests",
        staged_tests,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )

    steps = isolation_plan(extension_dir, policy, workdir)
    build = steps[0]
    _run(build, cwd=extension_dir)

    wheels = list(dist.glob("*.whl"))
    if len(wheels) != 1:
        raise FixtureError(f"expected exactly one wheel for {extension_dir.name}, got {wheels}")

    _run(steps[1], cwd=sandbox)
    # The plan spells the wheel as a glob and the artifact check's target
    # distribution as a placeholder; substitute both from the wheel this run
    # just built so the install pins — and the artifact check reads back —
    # that distribution, not whatever a stale cache holds.
    install = steps[2]
    glob_arg = f"{dist}/*.whl"
    dist_name = wheels[0].name.split("-")[0]

    def pin(arg: str) -> str:
        if arg == glob_arg:
            return str(wheels[0])
        return dist_name if arg == _WHEEL_DIST_NAME_ARG else arg

    install_argv = tuple(pin(arg) for arg in install.argv)
    _run(Step(install.description, install_argv, install.expect_failure), cwd=sandbox)

    for step in steps[3:-1]:
        pinned = Step(step.description, tuple(pin(arg) for arg in step.argv), step.expect_failure)
        _run(pinned, cwd=sandbox)

    _run(steps[-1], cwd=sandbox)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args(argv)

    policy = load_policy(args.policy)
    projects = discover_extension_projects(REPO_ROOT, policy)

    failures = 0
    with tempfile.TemporaryDirectory(prefix="extension-isolation-") as tmp:
        workdir = Path(tmp)
        for extension_dir in projects:
            print(f"isolation fixture: {extension_dir.name}")
            try:
                isolate(extension_dir, policy, workdir / extension_dir.name)
                print(f"ok: {extension_dir.name} builds and tests in a clean environment")
            except FixtureError as exc:
                failures += 1
                print(f"FAIL: {extension_dir.name}: {exc}", file=sys.stderr)

    if failures:
        print(
            f"FAIL: {failures} extension(s) failed the clean-environment fixture", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

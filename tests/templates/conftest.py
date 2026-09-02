"""Shared render and update harness for Copier template contracts."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from pathlib import Path

import pytest
import yaml
from copier import run_copy, run_update

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_ENGINE_SRC = "https://github.com/Agent-StrongHold/Project-mAIstro.git"


# SECURITY-REVIEW: Git is invoked with a fixed executable and argument vector;
# paths are pytest-owned temporary directories and never pass through a shell.
def _git(repository: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@dataclass(frozen=True)
class RenderedProject:
    source: Path
    template: Path
    destination: Path

    def update(self, data: dict[str, object]) -> None:
        """Commit the destination, advance the template, and apply an update."""
        _git(self.destination, "init")
        _git(self.destination, "config", "user.email", "template-tests@example.invalid")
        _git(self.destination, "config", "user.name", "Template Tests")
        _git(self.destination, "add", ".")
        _git(self.destination, "commit", "-m", "render v1")

        (self.template / "round-trip.txt.jinja").write_text(
            "updated {{ project_slug }}\n",
            encoding="utf-8",
        )
        _git(self.source, "add", ".")
        _git(self.source, "commit", "-m", "template v1.1")
        _git(self.source, "tag", "v1.1.0")

        run_update(
            self.destination,
            data=data,
            defaults=True,
            overwrite=True,
            quiet=True,
            unsafe=False,
        )


@pytest.fixture
def render_template(tmp_path: Path) -> Callable[[str, dict[str, object]], RenderedProject]:
    sequence = count()

    def render(name: str, data: dict[str, object]) -> RenderedProject:
        suffix = next(sequence)
        source = tmp_path / f"{name}-source-{suffix}"
        destination = tmp_path / f"{name}-output-{suffix}"
        source.mkdir()
        shutil.copy2(ROOT / "copier.yml", source / "copier.yml")
        template = source / "templates" / name
        shutil.copytree(ROOT / "templates" / name, template)
        _git(source, "init")
        _git(source, "config", "user.email", "template-tests@example.invalid")
        _git(source, "config", "user.name", "Template Tests")
        _git(source, "add", ".")
        _git(source, "commit", "-m", "template v1")
        _git(source, "tag", "v1.0.0")

        run_copy(
            str(source),
            destination,
            data={"product_template": name, **data},
            defaults=True,
            quiet=True,
            unsafe=False,
        )
        return RenderedProject(source=source, template=template, destination=destination)

    return render


# SECURITY-REVIEW: The generated tests run with a fixed Python argv and a
# pytest-owned cwd; no rendered value is interpolated into a shell command.
def _pin_canonical_template_origin(project: Path) -> None:
    """Local Copier renders record a temp _src_path; pin the canonical URL for contract tests."""
    answers_path = project / ".copier-answers.yml"
    answers = yaml.safe_load(answers_path.read_text(encoding="utf-8"))
    assert isinstance(answers, dict)
    answers["_src_path"] = CANONICAL_ENGINE_SRC
    answers_path.write_text(yaml.safe_dump(answers, sort_keys=False), encoding="utf-8")


def assert_generated_tests_pass(project: Path) -> None:
    _pin_canonical_template_origin(project)
    environment = os.environ.copy()
    pythonpath = str(project / "src")
    if existing := environment.get("PYTHONPATH"):
        pythonpath = os.pathsep.join((pythonpath, existing))
    environment["PYTHONPATH"] = pythonpath
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q"],
        cwd=project,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    lint = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "src", "tests"],
        cwd=project,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert lint.returncode == 0, lint.stdout + lint.stderr


@pytest.fixture
def generated_tests() -> Callable[[Path], None]:
    return assert_generated_tests_pass

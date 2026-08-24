"""The pre-pull step covers what is actually built (#204).

`docker-build` used to fail on a transient registry reset — the base-image
fetch, not the build. `scripts/prepull-base-images.sh` retries that fetch, which
is only worth anything if the images it pulls are the images the Dockerfiles
name. A hand-written list would rot the first time a Dockerfile gained a stage,
and rot *silently*: the missing image would just be fetched by `docker build`
instead, so nothing fails until the next blip.

So the list is parsed, and these tests hold the parse: the forms a Dockerfile
can legally use, the three things that are not pullable images, and — the one
that actually guards CI — that the shipped Dockerfiles' `FROM` lines are fully
accounted for.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepull-base-images.sh"

#: The Dockerfiles `docker-build` actually builds, and so the ones the pre-pull
#: step is given. Kept beside the assertion that they are covered, rather than
#: only in the workflow, so a change to one without the other fails here.
BUILT_DOCKERFILES = ("Dockerfile", "packages/hive-conductor/Dockerfile")

_FROM_RE = re.compile(r"^\s*FROM\s+(?P<rest>.+?)\s*$", re.IGNORECASE)


def _list(*dockerfiles: Path | str) -> list[str]:
    result = subprocess.run(
        [str(SCRIPT), "--list", *[str(d) for d in dockerfiles]],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "Dockerfile"
    path.write_text(body)
    return path


# --- the shipped Dockerfiles, which is the claim that guards CI -------------


def test_every_shipped_from_line_is_accounted_for() -> None:
    """No `FROM` in a built Dockerfile is missed by the pre-pull step.

    Missing one is not a loud failure — `docker build` would fetch it anyway —
    so nothing but this test would notice that the retry had stopped covering it.
    """
    pulled = set(_list(*BUILT_DOCKERFILES))

    for name in BUILT_DOCKERFILES:
        text = (ROOT / name).read_text()
        aliases: set[str] = set()
        for line in text.splitlines():
            match = _FROM_RE.match(line)
            if match is None:
                continue
            tokens = [t for t in match["rest"].split() if not t.startswith("--")]
            image = tokens[0]
            if "as" in [t.lower() for t in tokens]:
                idx = [t.lower() for t in tokens].index("as")
                if idx + 1 < len(tokens):
                    aliases.add(tokens[idx + 1].lower())
            if image.lower() == "scratch" or image.lower() in aliases:
                continue
            assert image in pulled, (
                f"{name} builds on {image!r}, which the pre-pull step does not "
                f"cover. It pulls: {sorted(pulled)}"
            )


def test_the_built_dockerfiles_are_the_ones_the_workflow_builds() -> None:
    """`BUILT_DOCKERFILES` above must match `ci.yml`, or this test guards nothing."""
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    job = workflow.split("docker-build:", 1)[1].split("\n  workflow-lint:", 1)[0]

    for name in BUILT_DOCKERFILES:
        assert name in job, f"{name} is not built by ci.yml's docker-build job"


# --- the forms a Dockerfile may legally use --------------------------------


def test_a_plain_from_is_pulled(tmp_path: Path) -> None:
    assert _list(_write(tmp_path, "FROM python:3.12-slim\nRUN true\n")) == ["python:3.12-slim"]


def test_a_named_stage_is_pulled_by_its_image(tmp_path: Path) -> None:
    assert _list(_write(tmp_path, "FROM node:22-alpine AS frontend\n")) == ["node:22-alpine"]


def test_a_platform_flag_is_not_mistaken_for_the_image(tmp_path: Path) -> None:
    body = "FROM --platform=$BUILDPLATFORM golang:1.25-alpine AS build\n"

    assert _list(_write(tmp_path, body)) == ["golang:1.25-alpine"]


def test_lowercase_from_is_recognised(tmp_path: Path) -> None:
    """Dockerfile keywords are case-insensitive; a missed one is a missed image."""
    assert _list(_write(tmp_path, "from python:3.12-slim as base\n")) == ["python:3.12-slim"]


def test_the_same_image_twice_is_pulled_once(tmp_path: Path) -> None:
    body = "FROM cgr.dev/chainguard/python:latest-dev AS builder\nFROM cgr.dev/chainguard/python:latest-dev\n"

    assert _list(_write(tmp_path, body)) == ["cgr.dev/chainguard/python:latest-dev"]


def test_images_from_several_dockerfiles_are_merged(tmp_path: Path) -> None:
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    (one / "Dockerfile").write_text("FROM node:22-alpine\n")
    (two / "Dockerfile").write_text("FROM python:3.12-slim\n")

    assert _list(one / "Dockerfile", two / "Dockerfile") == [
        "node:22-alpine",
        "python:3.12-slim",
    ]


# --- the three things that are not pullable images -------------------------


def test_a_stage_reference_is_not_pulled(tmp_path: Path) -> None:
    """`FROM builder` names an earlier stage; pulling it would 404."""
    body = "FROM node:22-alpine AS builder\nFROM builder\nRUN true\n"

    assert _list(_write(tmp_path, body)) == ["node:22-alpine"]


def test_a_stage_reference_is_matched_case_insensitively(tmp_path: Path) -> None:
    body = "FROM node:22-alpine AS Builder\nFROM builder\n"

    assert _list(_write(tmp_path, body)) == ["node:22-alpine"]


def test_scratch_is_not_pulled(tmp_path: Path) -> None:
    body = "FROM golang:1.25-alpine AS build\nFROM scratch\nCOPY --from=build /app /app\n"

    assert _list(_write(tmp_path, body)) == ["golang:1.25-alpine"]


def test_an_image_that_shares_a_name_with_a_later_stage_is_still_pulled(
    tmp_path: Path,
) -> None:
    """Aliases are registered *after* the image on their own line is judged.

    Registering first would make `FROM x AS builder` skip `x`, on the grounds
    that `builder` is a stage — silently dropping the one image that line names.
    """
    body = "FROM python:3.12-slim AS python\nFROM python\n"

    assert _list(_write(tmp_path, body)) == ["python:3.12-slim"]


def test_an_unresolved_build_arg_is_reported_not_silently_dropped(tmp_path: Path) -> None:
    """It cannot be pulled without build args, so it must not vanish quietly."""
    path = _write(tmp_path, "ARG BASE=python:3.12-slim\nFROM ${BASE}\nFROM node:22-alpine\n")

    result = subprocess.run(
        [str(SCRIPT), "--list", str(path)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    )

    assert result.stdout.splitlines() == ["node:22-alpine"]
    assert "cannot resolve" in result.stderr


# --- failure modes ---------------------------------------------------------


def test_a_missing_dockerfile_is_an_error(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(SCRIPT), "--list", str(tmp_path / "nope")],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 1
    assert "no such Dockerfile" in result.stderr


def test_a_dockerfile_with_no_from_is_an_error(tmp_path: Path) -> None:
    """Silently pulling nothing would look exactly like success."""
    result = subprocess.run(
        [str(SCRIPT), "--list", str(_write(tmp_path, "RUN true\n"))],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 1
    assert "no base images found" in result.stderr


def test_no_arguments_is_a_usage_error() -> None:
    result = subprocess.run([str(SCRIPT)], capture_output=True, text=True, cwd=ROOT, check=False)

    assert result.returncode == 2
    assert "usage:" in result.stderr


@pytest.mark.parametrize("mode", ["--list", ""])
def test_the_script_is_executable(mode: str) -> None:
    """It is invoked directly by the workflow, not via `bash script`."""
    assert SCRIPT.stat().st_mode & 0o111, f"{SCRIPT} is not executable ({mode})"

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
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepull-base-images.sh"
COMPOSE_FILE = ROOT / "packages" / "hive-conductor" / "docker-compose.test.yml"

#: The Dockerfiles `docker-build` actually builds, and so the ones the pre-pull
#: step is given. Kept beside the assertion that they are covered, rather than
#: only in the workflow, so a change to one without the other fails here.
BUILT_DOCKERFILES = ("Dockerfile", "packages/hive-conductor/Dockerfile")

#: The Dockerfiles `packages/hive-conductor/docker-compose.test.yml` builds
#: (the `hive`, `api-tests` and `e2e-tests` services). This is the coverage a
#: live develop protected push found missing: `hive-conductor-e2e` and
#: `hive-conductor-e2e-ui` run `docker compose --build` directly, never call
#: this script, and one failed outright on the exact registry-reset signature
#: #204 exists to survive -- `cgr.dev/chainguard/python:latest: ... connection
#: reset by peer`.
COMPOSE_DOCKERFILES = (
    "packages/hive-conductor/Dockerfile",
    "packages/hive-conductor/tests/Dockerfile",
    "packages/hive-conductor/tests/Dockerfile.playwright",
)

#: What each e2e job actually builds, and so what each must pre-pull -- not
#: all of `COMPOSE_DOCKERFILES`. `hive-conductor-e2e`'s `up ... api-tests`
#: builds api-tests and its `depends_on: hive`, never e2e-tests;
#: `hive-conductor-e2e-ui`'s `up ... e2e-tests` builds e2e-tests and hive,
#: never api-tests. Pre-pulling the Dockerfile the job never builds was
#: Codex's #713 review finding: it cost time against the job's 20-minute
#: budget and opened a registry-failure path for an image compose was never
#: going to touch.
JOB_DOCKERFILES = {
    "hive-conductor-e2e": (
        "packages/hive-conductor/Dockerfile",
        "packages/hive-conductor/tests/Dockerfile",
    ),
    "hive-conductor-e2e-ui": (
        "packages/hive-conductor/Dockerfile",
        "packages/hive-conductor/tests/Dockerfile.playwright",
    ),
}

#: The compose service each job's `--exit-code-from` targets. Kept beside the
#: assertion that ties it back to `ci.yml`'s literal text (below), so this map
#: cannot silently name a service the job no longer runs.
JOB_TARGET_SERVICE = {
    "hive-conductor-e2e": "api-tests",
    "hive-conductor-e2e-ui": "e2e-tests",
}

_FROM_RE = re.compile(r"^\s*FROM\s+(?P<rest>.+?)\s*$", re.IGNORECASE)


def _compose_services() -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load(COMPOSE_FILE.read_text())
    services: dict[str, Any] = document["services"]
    return services


def _compose_dockerfiles_for(service: str) -> set[str]:
    """The repo-relative Dockerfiles `service` and its `depends_on` closure build.

    Derived from `docker-compose.test.yml` itself, not hand-copied, so a
    service later gaining a dependency (e.g. `e2e-tests` depending on
    `api-tests`) changes what this returns automatically -- closing the gap
    Codex flagged on #715: `JOB_DOCKERFILES` compared only against itself,
    so a drift between it and the compose file's real dependency graph would
    have passed silently, reopening exactly the registry-failure exposure
    this whole pre-pull step exists to close.
    """
    services = _compose_services()
    seen: set[str] = set()
    queue = [service]
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        queue.extend(services[name].get("depends_on", {}))

    dockerfiles: set[str] = set()
    for name in seen:
        build = services[name]["build"]
        context = (COMPOSE_FILE.parent / build["context"]).resolve()
        dockerfile = (context / build["dockerfile"]).resolve()
        dockerfiles.add(dockerfile.relative_to(ROOT).as_posix())
    return dockerfiles


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


def test_every_compose_from_line_is_accounted_for() -> None:
    """No `FROM` in a compose-built Dockerfile is missed by the pre-pull step.

    `docker compose --build` resolves every one of these images itself if the
    pre-pull step falls behind, so a gap here fails silently right up until
    the next registry blip -- which is exactly what happened live (#204).
    """
    pulled = set(_list(*COMPOSE_DOCKERFILES))

    for name in COMPOSE_DOCKERFILES:
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


@pytest.mark.parametrize("job", sorted(JOB_DOCKERFILES))
def test_each_e2e_job_pre_pulls_exactly_what_it_builds(job: str) -> None:
    """`JOB_DOCKERFILES[job]` above must match `ci.yml`, or this test guards nothing.

    Both directions matter: missing one repeats #204 for that job: silent
    right up until the next registry blip. Pre-pulling one the job never
    builds repeats Codex's #713 finding: dead weight against the job's
    timeout, and a registry failure path the job has no reason to be
    sensitive to.
    """
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    body = workflow.split(f"\n  {job}:", 1)[1]
    body = re.split(r"\n  \S", body, maxsplit=1)[0]

    def _pulls(name: str) -> bool:
        # A whole-token match: `tests/Dockerfile` is a substring of
        # `tests/Dockerfile.playwright`, so plain `in` would count the latter
        # as pre-pulling the former too.
        return re.search(rf"(?<!\S){re.escape(name)}(?!\S)", body) is not None

    assert "prepull-base-images.sh" in body, f"{job} does not pre-pull base images"
    for name in JOB_DOCKERFILES[job]:
        assert _pulls(name), f"{job} does not pre-pull {name}"
    for name in COMPOSE_DOCKERFILES:
        if name not in JOB_DOCKERFILES[job]:
            assert not _pulls(name), (
                f"{job} pre-pulls {name}, which it never builds — see JOB_DOCKERFILES"
            )


@pytest.mark.parametrize("job", sorted(JOB_TARGET_SERVICE))
def test_the_job_targets_the_service_job_target_service_names(job: str) -> None:
    """`JOB_TARGET_SERVICE[job]` must match the `--exit-code-from` `ci.yml` runs.

    Without this, `JOB_TARGET_SERVICE` could name a service the job stopped
    running and `test_job_dockerfiles_match_the_compose_dependency_closure`
    below would keep validating against the wrong target, silently.
    """
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    body = workflow.split(f"\n  {job}:", 1)[1]
    body = re.split(r"\n  \S", body, maxsplit=1)[0]

    # Whole-token match: plain `in` would let `--exit-code-from api-tests`
    # match a renamed `--exit-code-from api-tests-v2` too (Codex, #720), so a
    # renamed service would validate against the old dependency graph while
    # the job silently builds a different one.
    service = re.escape(JOB_TARGET_SERVICE[job])
    assert re.search(rf"--exit-code-from {service}(?!\S)", body), (
        f"{job} does not run `--exit-code-from {JOB_TARGET_SERVICE[job]}`"
    )


@pytest.mark.parametrize("job", sorted(JOB_DOCKERFILES))
def test_job_dockerfiles_match_the_compose_dependency_closure(job: str) -> None:
    """`JOB_DOCKERFILES[job]` must equal what the compose file's own graph builds.

    `test_each_e2e_job_pre_pulls_exactly_what_it_builds` only checks
    `JOB_DOCKERFILES` against `ci.yml`'s text -- both sides written by hand,
    so a hand-copied mistake in one could match a hand-copied mistake in the
    other and this suite would never notice (Codex, #715). This checks the
    map against the one thing neither side is free to get wrong: what
    `docker-compose.test.yml` actually builds for the target service and its
    `depends_on` closure. If that service later gains a new dependency, this
    fails until `JOB_DOCKERFILES` is updated to match -- rather than the job
    quietly missing a pre-pull for an image it has started building.
    """
    assert _compose_dockerfiles_for(JOB_TARGET_SERVICE[job]) == set(JOB_DOCKERFILES[job])


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

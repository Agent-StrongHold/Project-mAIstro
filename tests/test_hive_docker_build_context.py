"""The documented Hive Docker build must use a context the Dockerfile can read.

The verifier for #1134 found the shipped README instructing

    docker build -f packages/hive-conductor/Dockerfile packages/hive-conductor ...

while every ``COPY`` in that Dockerfile names paths from the *monorepo root*
(``packages/maistro-core``, ``packages/hive-conductor/frontend/...``). With the
package directory as context the build fails on the first COPY. The Dockerfile
header and ``docker-compose.yml`` (``context: ../..``) already agree on the
root; this test keeps the README from drifting away from them again.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "packages/hive-conductor/Dockerfile"
README = REPO_ROOT / "packages/hive-conductor/README.md"
COMPOSE = REPO_ROOT / "packages/hive-conductor/docker-compose.yml"

# COPY <src>... <dest> / ADD <src>... <dest> — keep the src words that are
# filesystem paths (drop --from=stage refs, flags, and the final destination).
_COPY_LINE = re.compile(r"^(?:COPY|ADD)\s+(?P<flags>(?:--\w+(?:=\S+)?\s+)*)(?P<src>.+)$")


def _copy_sources() -> list[str]:
    sources: list[str] = []
    for line in DOCKERFILE.read_text().splitlines():
        match = _COPY_LINE.match(line.strip())
        if not match:
            continue
        if "--from=" in match.group("flags"):
            # Sources come from a previous build stage, not the build context.
            continue
        words = match.group("src").split()
        # Last word is the destination; earlier words are sources.
        for word in words[:-1]:
            if word.startswith("--") or "://" in word:
                continue  # build flags or remote URLs, not context paths
            sources.append(word)
    assert sources, "expected the Dockerfile to COPY at least one context path"
    return sources


def test_dockerfile_copy_sources_resolve_from_the_monorepo_root() -> None:
    """Every COPY source must exist relative to the repo root context."""
    for src in _copy_sources():
        assert (REPO_ROOT / src).exists(), f"COPY source {src!r} is missing from repo root"


def test_dockerfile_copy_sources_do_not_resolve_from_the_package_directory() -> None:
    """The package dir cannot be the context: root-relative paths would break.

    This is the failure mode the #1134 verifier hit — the documented build
    command used ``packages/hive-conductor`` as context, so the first
    ``COPY packages/maistro-core ...`` could never resolve.
    """
    package_dir = REPO_ROOT / "packages/hive-conductor"
    root_only = [src for src in _copy_sources() if src.startswith("packages/")]
    assert root_only, "expected root-only COPY sources that pin the context"
    for src in root_only:
        assert not (package_dir / src).exists(), (
            f"COPY source {src!r} unexpectedly exists inside the package dir; "
            "the context assumption of this test no longer holds"
        )


def test_readme_docker_build_command_uses_the_monorepo_root_context() -> None:
    """The README's docker build command must match the Dockerfile's context."""
    text = README.read_text()
    commands = re.findall(r"^docker build .*$", text, flags=re.MULTILINE)
    assert commands, "README no longer documents a docker build command"
    for command in commands:
        # -f path first, then the context word (must be '.' = repo root).
        match = re.match(r"^docker build\s+(?:-\S+\s+\S+\s+)*(?P<context>\S+)", command)
        assert match is not None
        context = match.group("context")
        assert context == ".", (
            f"README docker build context {context!r} is not the monorepo root; "
            "the Dockerfile COPY paths require building from '.'"
        )


def test_compose_build_context_is_the_monorepo_root() -> None:
    """compose must keep building with the same root context as the README."""
    text = COMPOSE.read_text()
    match = re.search(r"context:\s*(\S+)", text)
    assert match is not None, "docker-compose.yml no longer declares a build context"
    assert match.group(1) == "../..", (
        f"compose build context {match.group(1)!r} is not the monorepo root"
    )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])

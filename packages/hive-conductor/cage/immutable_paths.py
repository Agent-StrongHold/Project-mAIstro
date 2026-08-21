"""Immutable paths — files/directories Turing can never read, write, or delete."""

from __future__ import annotations

import fnmatch
from pathlib import Path

# Frozen paths: Turing cannot touch these under any circumstances.
IMMUTABLE_PATHS: frozenset[str] = frozenset(
    [
        "cage/",
        "eval/",
        ".env",
        ".env.*",
        "*.pem",
        "*.key",
        "**/secrets/**",
        "**/credentials/**",
        "docker-compose*.yml",
        "Dockerfile*",
        "Makefile",
        "CI/",
        ".github/",
        ".gitlab-ci.yml",
    ]
)


def is_immutable(path: str | Path) -> bool:
    """Return True if the given path matches any immutable pattern."""
    p = str(path)
    for pattern in IMMUTABLE_PATHS:
        if pattern.endswith("/"):
            if p.startswith(pattern) or f"/{pattern}" in f"/{p}":
                return True
        elif fnmatch.fnmatch(p, pattern) or fnmatch.fnmatch(Path(p).name, pattern):
            return True
    return False

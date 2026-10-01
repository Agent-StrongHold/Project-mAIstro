"""A PATH with named executables hidden, and everything beside them kept.

Dropping a whole directory to hide one binary works on a Mac, where Docker
Desktop puts `docker` in /usr/local/bin, and fails on a Linux runner, where
`docker` sits in /usr/bin beside `bash`: the harness could no longer start a
shell at all. Each directory holding a hidden name is replaced by a mirror of
symlinks to all its other entries, so `command -v docker` fails while `bash`,
`sed` and `python3` resolve exactly as before, on either platform.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path


def path_hiding(tmp_path: Path, hidden: Callable[[str], bool]) -> str:
    """`$PATH` with every entry for which `hidden(name)` is true removed."""
    mirrors = tmp_path / "path-mirrors"
    parts: list[str] = []
    for index, directory in enumerate(os.environ.get("PATH", "").split(os.pathsep)):
        if not directory or not os.path.isdir(directory):
            continue
        names = os.listdir(directory)
        if not any(hidden(n) for n in names):
            parts.append(directory)
            continue
        mirror = mirrors / str(index)
        mirror.mkdir(parents=True, exist_ok=True)
        for name in names:
            if not hidden(name):
                link = mirror / name
                if not link.exists():
                    link.symlink_to(os.path.join(directory, name))
        parts.append(str(mirror))
    return os.pathsep.join(parts)


def is_docker_binary(name: str) -> bool:
    return name == "docker" or name.startswith("docker-credential-")

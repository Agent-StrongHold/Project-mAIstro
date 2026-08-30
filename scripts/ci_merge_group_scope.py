#!/usr/bin/env python3
"""Classify which expensive CI legs a merge-group candidate can affect."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import PurePosixPath

LEGS = (
    "postgres",
    "object_storage",
    "durable_events",
    "strike_ladder",
    "hive_e2e",
    "wheel_imports",
    "docker_build",
)

_GLOBAL = {
    "pyproject.toml",
    "uv.lock",
    "conftest.py",
    ".github/workflows/ci.yml",
    ".github/actions/setup-uv/action.yml",
}


def _under(path: str, *prefixes: str) -> bool:
    return any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in prefixes)


def _classify_path(path: str, out: dict[str, bool]) -> None:
    core = _under(path, "packages/maistro-core")
    server = _under(path, "packages/maistro-server")
    hive = _under(path, "packages/hive-conductor")
    if _under(
        path,
        "alembic",
        "tests/migrations",
        "packages/maistro-core/tests/persistence",
        "packages/maistro-core/tests/workspaces",
    ) or (
        core
        and any(
            token in path
            for token in ("persistence", "workspace", "container", "storage", "run_store")
        )
    ):
        out["postgres"] = True
    if _under(path, "packages/maistro-core/tests/archive") or (core and "archive" in path):
        out["object_storage"] = True
    if (core and any(token in path for token in ("event", "durable"))) or _under(
        path, "tests/events", "tests/durable_events"
    ):
        out["durable_events"] = True
    if core and any(token in path for token in ("strike", "attempt", "execution", "run")):
        out["strike_ladder"] = True
    if hive or server or _under(path, "docker-compose.yml", "docker-compose", "tests/e2e"):
        out["hive_e2e"] = True
    if _under(path, "packages") and (
        path.endswith("pyproject.toml") or "/src/" in path or path.endswith("/__init__.py") or hive
    ):
        out["wheel_imports"] = True
    if (
        path.startswith("Dockerfile")
        or path.startswith(".dockerignore")
        or path == "README.md"
        or _under(
            path,
            "packages",
            "alembic",
            "scripts",
            "tests",
            "formal",
            "tools",
            "quality",
            "agents",
            "templates",
            "docs",
            "sbx",
            ".github",
        )
    ):
        out["docker_build"] = True


def classify(paths: Iterable[str]) -> dict[str, bool]:
    """Return a run/skip decision for each expensive specialized CI leg."""
    changed = {PurePosixPath(p).as_posix().removeprefix("./") for p in paths if p.strip()}
    if not changed or changed & _GLOBAL:
        return dict.fromkeys(LEGS, True)
    out = dict.fromkeys(LEGS, False)
    for path in changed:
        _classify_path(path, out)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = classify(args.paths)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        for leg in LEGS:
            print(f"{leg}={'true' if result[leg] else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Classify which expensive CI legs a merge-group candidate can affect.

This is deliberately conservative. Shared dependency/configuration surfaces
force every specialized leg to run. Otherwise a leg runs when the candidate
changes code, tests, or deployment inputs owned by that leg.

The classifier is pure: callers provide the changed paths. Workflow plumbing
is responsible for deriving those paths from the immutable merge-group base
revision resolved by :mod:`ci_base_revision`.
"""

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

# Any of these can change dependency resolution, test collection, or the CI
# contract itself. Guessing narrower here would turn optimization into a hole.
_GLOBAL = {
    "pyproject.toml",
    "uv.lock",
    "conftest.py",
    ".github/workflows/ci.yml",
    ".github/actions/setup-uv/action.yml",
}


def _under(path: str, *prefixes: str) -> bool:
    return any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in prefixes)


def classify(paths: Iterable[str]) -> dict[str, bool]:
    """Return a run/skip decision for each expensive specialized CI leg."""
    changed = {PurePosixPath(p).as_posix().lstrip("./") for p in paths if p.strip()}
    if not changed:
        # Missing diff evidence is not permission to skip anything.
        return {leg: True for leg in LEGS}
    if changed & _GLOBAL:
        return {leg: True for leg in LEGS}

    out = {leg: False for leg in LEGS}
    for path in changed:
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
            path.endswith("pyproject.toml") or "/src/" in path or path.endswith("/__init__.py")
        ):
            out["wheel_imports"] = True

        # Every shipped image copies package sources; the RSI image additionally
        # copies tests, scripts, docs, quality data, tools, templates, agents,
        # formal assets, sbx and .github. Keep this list equal to Dockerfile
        # COPY inputs rather than pretending a Dockerfile is the only input.
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

    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", help="changed repository-relative paths")
    parser.add_argument("--json", action="store_true", help="emit one JSON object")
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

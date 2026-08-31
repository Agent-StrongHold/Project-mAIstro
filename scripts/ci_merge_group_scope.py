#!/usr/bin/env python3
"""Classify which expensive CI legs a merge-group candidate can affect."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import PurePosixPath

try:
    from scripts.ci_base_revision import BaseRevisionError, resolve_base_revision_from_env
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from ci_base_revision import BaseRevisionError, resolve_base_revision_from_env

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
    "scripts/ci_base_revision.py",
    "scripts/ci_merge_group_scope.py",
}


def _under(path: str, *prefixes: str) -> bool:
    return any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in prefixes)


def _classify_path(path: str, out: dict[str, bool]) -> None:
    core = _under(path, "packages/maistro-core")
    server = _under(path, "packages/maistro-server")
    hive = _under(path, "packages/hive-conductor")
    alembic = _under(path, "alembic") or path == "alembic.ini"
    core_test_conftest = path == "packages/maistro-core/tests/conftest.py"
    if (
        alembic
        or core_test_conftest
        or _under(
            path,
            "tests/migrations",
            "packages/maistro-core/tests/persistence",
            "packages/maistro-core/tests/workspaces",
        )
        or (
            core
            and any(
                token in path
                for token in ("persistence", "workspace", "container", "storage", "run_store")
            )
        )
    ):
        out["postgres"] = True
    if _under(path, "packages/maistro-core/tests/archive") or (core and "archive" in path):
        out["object_storage"] = True
    if (
        core_test_conftest
        or (core and any(token in path for token in ("event", "durable")))
        or _under(path, "tests/events", "tests/durable_events")
        or (alembic and any(token in path for token in ("event", "durable")))
    ):
        out["durable_events"] = True
    if core_test_conftest or (
        core and any(token in path for token in ("strike", "attempt", "execution", "run"))
    ):
        out["strike_ladder"] = True
    if hive or server or core or _under(path, "docker-compose.yml", "docker-compose", "tests/e2e"):
        out["hive_e2e"] = True
    if _under(path, "packages") and (
        path.endswith("pyproject.toml") or "/src/" in path or path.endswith("/__init__.py") or hive
    ):
        out["wheel_imports"] = True
    if (
        path.startswith("Dockerfile")
        or path.startswith(".dockerignore")
        or path == "README.md"
        or alembic
        or _under(
            path,
            "packages",
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


def all_enabled() -> dict[str, bool]:
    return dict.fromkeys(LEGS, True)


def scope_for_event(event_name: str, changed_paths: Iterable[str] | None = None) -> dict[str, bool]:
    """Preserve PR evidence; classify only measured merge-group candidates."""
    if event_name != "merge_group" or changed_paths is None:
        return all_enabled()
    return classify(changed_paths)


def changed_paths_from_git(base_sha: str) -> list[str]:
    """Diff without rename folding so moved source paths remain visible."""
    proc = subprocess.run(
        ["git", "diff", "--no-renames", "--name-only", f"{base_sha}...HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in proc.stdout.splitlines() if line.strip()]


def render_outputs(scope: dict[str, bool]) -> str:
    """Render values suitable for appending directly to GITHUB_OUTPUT."""
    lines = [f"{leg}={'true' if scope[leg] else 'false'}" for leg in LEGS]
    lines.append(f"scope_json={json.dumps(scope, sort_keys=True)}")
    return "\n".join(lines)


def scope_from_environment(event_name: str) -> dict[str, bool]:
    """Measure a merge-group candidate, failing closed when evidence is unavailable."""
    if event_name != "merge_group":
        return all_enabled()
    try:
        base_sha = resolve_base_revision_from_env()
        return scope_for_event(event_name, changed_paths_from_git(base_sha))
    except (BaseRevisionError, OSError, subprocess.SubprocessError) as exc:
        print(
            f"WARN: merge-group scope is unmeasured; enabling every specialized leg: {exc}",
            file=sys.stderr,
        )
        return all_enabled()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--github-outputs", action="store_true")
    args = parser.parse_args()

    if args.github_outputs:
        if args.paths or args.json:
            parser.error("--github-outputs cannot be combined with paths or --json")
        event_name = os.environ.get("GITHUB_EVENT_NAME", "").strip()
        if not event_name:
            print(
                "WARN: GITHUB_EVENT_NAME is missing; enabling every specialized leg",
                file=sys.stderr,
            )
        print(render_outputs(scope_from_environment(event_name)))
        return 0

    result = classify(args.paths)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        for leg in LEGS:
            print(f"{leg}={'true' if result[leg] else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Write a resolved maistro-install plan to an install target directory."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import yaml


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_yaml(path: Path, data: Any) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _write_tutorial(path: Path, todos: list[str]) -> None:
    lines = ["# Maistro first-run setup", ""]
    lines.extend(f"- [ ] {todo}" for todo in todos)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _next_compose_command(base_compose_path: str | None) -> str:
    if base_compose_path is None:
        return "docker compose -f <path-to-docker-compose.yml> -f compose.override.yml config"
    return f"docker compose -f {base_compose_path} -f compose.override.yml config"


def _write_entrypoint(path: Path, base_compose_path: str | None) -> None:
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'cd "$(dirname "$0")"\n'
        "echo 'Maistro install artifacts are materialized in:' \"$PWD\"\n"
        "echo 'Review install-answers.yaml and compose.override.yml before starting services.'\n"
        f"echo 'Next: {_next_compose_command(base_compose_path)}'\n",
        encoding="utf-8",
    )
    if os.name != "nt":
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_powershell_entrypoint(path: Path, base_compose_path: str | None) -> None:
    path.write_text(
        "Set-StrictMode -Version Latest\n"
        '$ErrorActionPreference = "Stop"\n'
        "Set-Location $PSScriptRoot\n"
        'Write-Host "Maistro install artifacts are materialized in: $PWD"\n'
        'Write-Host "Review install-answers.yaml and compose.override.yml before starting services."\n'
        f'Write-Host "Next: {_next_compose_command(base_compose_path)}"\n',
        encoding="utf-8",
    )


def materialize_install_artifacts(plan: dict[str, Any], target_dir: Path) -> list[Path]:
    """Materialize generated installer artifacts and return written paths.

    This is intentionally file-only: it never starts containers, installs packages, or writes secrets.
    """
    artifacts = plan.get("generated_artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("plan is missing generated_artifacts")

    target_dir.mkdir(parents=True, exist_ok=True)
    answers = plan.get("answers", {})
    compose = artifacts.get("compose_override_preview", {})
    todos = artifacts.get("tutorial_todo", [])
    if not isinstance(todos, list):
        todos = []

    files: list[tuple[str, str, Any]] = [
        ("install-plan.json", "json", plan),
        ("install-answers.yaml", "yaml", answers),
        ("compose.override.yml", "yaml", compose),
        ("sandbox-policy.json", "json", artifacts.get("sandbox_policy", {})),
        ("bootstrap-users.json", "json", artifacts.get("bootstrap_users", [])),
        ("delivery.json", "json", artifacts.get("delivery", {})),
        ("first-agents.json", "json", artifacts.get("reactor", {}).get("first_agents", [])),
        ("identity-root.json", "json", artifacts.get("identity_root", {})),
        ("unsupported-options.json", "json", artifacts.get("unsupported_options", {})),
    ]

    written: list[Path] = []
    for name, kind, data in files:
        path = target_dir / name
        if kind == "json":
            _write_json(path, data)
        else:
            _write_yaml(path, data)
        written.append(path)

    tutorial = target_dir / "tutorial-todo.md"
    _write_tutorial(tutorial, [str(todo) for todo in todos])
    written.append(tutorial)

    base_compose_path = _relative_base_compose_path(plan.get("repo_root"), target_dir)

    written.extend(_materialize_delivery(plan, target_dir, base_compose_path))

    entrypoint = target_dir / "install.sh"
    _write_entrypoint(entrypoint, base_compose_path)
    written.append(entrypoint)

    powershell_entrypoint = target_dir / "install.ps1"
    _write_powershell_entrypoint(powershell_entrypoint, base_compose_path)
    written.append(powershell_entrypoint)

    return written


def _materialize_delivery(
    plan: dict[str, Any], target_dir: Path, base_compose_path: str | None
) -> list[Path]:
    """Render the delivery-mode artifacts: Makefile always, and for
    image_pull a standalone compose file with every build: replaced by a
    pinned image: (an override cannot remove base build: keys — Compose
    merges mappings)."""
    from maistro_bootstrap.delivery import (
        git_revision,
        render_image_pull_compose,
        render_makefile,
    )

    answers = plan.get("answers", {})
    mode = str(answers.get("delivery_mode", "image_pull"))
    repo_root = plan.get("repo_root")
    revision = git_revision(Path(str(repo_root))) if repo_root else None

    written: list[Path] = []
    makefile = target_dir / "Makefile"
    makefile.write_text(
        render_makefile(mode, base_compose_path=base_compose_path, revision=revision),
        encoding="utf-8",
    )
    written.append(makefile)

    if mode == "image_pull" and repo_root:
        base_file = Path(str(repo_root)) / "docker-compose.yml"
        if base_file.exists():
            base = yaml.safe_load(base_file.read_text(encoding="utf-8"))
            doc = render_image_pull_compose(base)
            out = target_dir / "compose.install.yml"
            header = (
                "# Generated by maistro-install — standalone image_pull compose.\n"
                "# No build: keys: services arrive as pinned images. Run with\n"
                "# --project-directory at the repo root (see Makefile) so .env\n"
                "# interpolation and relative bind mounts resolve correctly.\n"
            )
            out.write_text(header + yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
            written.append(out)
    return written


def _relative_base_compose_path(repo_root: Any, target_dir: Path) -> str | None:
    if not repo_root:
        return None
    compose_path = Path(repo_root) / "docker-compose.yml"
    if not compose_path.exists():
        return None
    try:
        rel = os.path.relpath(compose_path.resolve(), target_dir.resolve())
    except ValueError:
        return compose_path.as_posix()
    return rel.replace(os.sep, "/")

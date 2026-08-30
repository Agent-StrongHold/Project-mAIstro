"""Regression test for the formal suite's live Hypothesis modes."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FORMAL_MODELS = REPO_ROOT / "formal" / "models"
MODE_OWNED_SETTINGS = frozenset(
    {
        "max_examples",
        "phases",
        "deadline",
        "database",
        "derandomize",
        "suppress_health_check",
    }
)


def _run_profile(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "formal/models/test_hypothesis_profile.py",
            "-q",
            *args,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _mode_owned_overrides() -> list[str]:
    violations: list[str] = []
    for path in sorted(FORMAL_MODELS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                is_settings = isinstance(func, ast.Name) and func.id == "settings"
                is_settings = is_settings or (
                    isinstance(func, ast.Attribute) and func.attr == "settings"
                )
                if not is_settings:
                    continue
                owned = sorted(
                    keyword.arg
                    for keyword in decorator.keywords
                    if keyword.arg in MODE_OWNED_SETTINGS
                )
                if owned:
                    rel = path.relative_to(REPO_ROOT)
                    violations.append(f"{rel}:{node.lineno}: {', '.join(owned)}")
    return violations


def test_formal_hypothesis_modes_are_live_and_suite_owned() -> None:
    nightly_env = os.environ.copy()
    nightly_env["MAISTRO_FORMAL_NIGHTLY_EXAMPLES"] = "321"
    nightly = _run_profile(
        "--nightly",
        "--hypothesis-seed=12345",
        env=nightly_env,
    )
    assert nightly.returncode == 0, nightly.stdout + nightly.stderr

    replay_env = os.environ.copy()
    replay_env["MAISTRO_FORMAL_CI_EXAMPLES"] = "17"
    replay = _run_profile("--hypothesis-seed=0", env=replay_env)
    assert replay.returncode == 0, replay.stdout + replay.stderr

    violations = _mode_owned_overrides()
    assert not violations, (
        "formal tests must inherit mode-owned Hypothesis exploration settings; "
        "move these overrides into formal/conftest.py:\n" + "\n".join(violations)
    )

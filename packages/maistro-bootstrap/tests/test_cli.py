"""CLI output tests for maistro-install."""

from __future__ import annotations

import pytest

from maistro_bootstrap.cli import _print_human_plan
from maistro_bootstrap.schema import parse_answers_dict


def test_human_plan_prints_copier_command_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printed: list[str] = []

    def capture(value: object, **kwargs: object) -> None:
        printed.append(str(value))

    monkeypatch.setattr("maistro_bootstrap.cli.console.print", capture)

    answers = parse_answers_dict(
        {"schema_version": "1", "product": "autonoetic", "stack_bringup": "none"}
    )
    plan = {
        "shell_commands": ["# === maistro-install plan (default: print only) ==="],
        "copier_command": (
            "uv run copier copy --data product_template=autonoetic . '../my product'"
        ),
    }

    _print_human_plan(plan, answers, repo="/tmp/maistro-root")

    joined = "\n".join(printed)
    assert "# Copier (available after `uv sync`)" in joined
    assert "uv run copier copy --data product_template=autonoetic" in joined

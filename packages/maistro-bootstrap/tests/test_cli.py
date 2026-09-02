"""CLI output tests for maistro-install."""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro_bootstrap.cli import _maybe_stage_bootstrap_credentials, _print_human_plan
from maistro_bootstrap.credentials import (
    BOOTSTRAP_CREDENTIALS_FILENAME,
    ENV_CREDENTIALS_FILE,
    build_bootstrap_credentials,
    write_bootstrap_credentials,
)
from maistro_bootstrap.schema import InstallAnswersV1, parse_answers_dict


def _answers() -> InstallAnswersV1:
    return InstallAnswersV1.model_validate(
        {"admin_user": "root-admin", "daily_driver_user": "alice"}
    )


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
            "uv run copier copy --data product_template=autonoetic "
            "https://github.com/Agent-StrongHold/Project-mAIstro.git '../my product'"
        ),
    }

    _print_human_plan(plan, answers, repo="/tmp/maistro-root")

    joined = "\n".join(printed)
    assert "# Copier (available after `uv sync`)" in joined
    assert "uv run copier copy --data product_template=autonoetic" in joined


def _capture_cli_prints(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture `console.print` calls from the CLI module under test."""
    printed: list[str] = []

    def capture(value: object, **kwargs: object) -> None:
        printed.append(str(value))

    monkeypatch.setattr("maistro_bootstrap.cli.console.print", capture)
    monkeypatch.delenv(ENV_CREDENTIALS_FILE, raising=False)
    return printed


def test_a_valid_staging_skips_the_prompt_without_rewriting_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The "already staged" skip keys on validated staging, not bare
    existence (#809 AC-3): a parse-valid private file short-circuits the
    prompts and is reused, not re-staged."""
    printed = _capture_cli_prints(monkeypatch)
    write_bootstrap_credentials(
        tmp_path, build_bootstrap_credentials(_answers(), admin_password="a", user_password="u")
    )
    staged = tmp_path / BOOTSTRAP_CREDENTIALS_FILENAME
    before = staged.stat()

    _maybe_stage_bootstrap_credentials(_answers(), tmp_path)

    assert any("already staged" in text for text in printed)
    after = staged.stat()
    assert after.st_ino == before.st_ino  # reused, not overwritten
    assert not any("passwords now" in text for text in printed)  # never prompted


def test_without_a_staging_or_a_tty_credentials_defer_to_the_setup_wizard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Nothing validly staged and no interactive stdin: the run defers
    account creation to the UI Setup wizard instead of staging a file."""
    printed = _capture_cli_prints(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    _maybe_stage_bootstrap_credentials(_answers(), tmp_path)

    joined = "\n".join(printed)
    assert "No TTY" in joined
    assert not (tmp_path / BOOTSTRAP_CREDENTIALS_FILENAME).exists()

"""`maistro-install --answers-file` — unknown answer keys are named errors (#810).

The CLI must surface a pydantic `extra_forbidden` failure as a BadParameter
that names the offending key, never as a traceback, and never continue with
silently substituted defaults.
"""

from __future__ import annotations

from pathlib import Path

import typer
from typer.testing import CliRunner

from maistro_bootstrap.cli import main

runner = CliRunner()

_app = typer.Typer()
_app.command()(main)


_ANSI = __import__("re").compile(r"\x1b\\[[0-9;]*m")


def _combined(result) -> str:
    """stdout + stderr across click's CliRunner variants, ANSI-stripped.

    Rich colorizes flags mid-word in CI (non-TTY included), so raw
    substring assertions on flag names must run on stripped text.
    """
    try:
        raw = result.output + result.stderr
    except ValueError:
        raw = result.output
    return _ANSI.sub("", raw)


def _write_answers(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "answers.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_valid_answers_file_plans(tmp_path: Path) -> None:
    answers = _write_answers(tmp_path, 'schema_version: "1"\nfeatures: [core_lib]\n')
    result = runner.invoke(_app, ["--answers-file", str(answers)])
    assert result.exit_code == 0, result.output


def test_misspelled_security_key_is_named_error(tmp_path: Path) -> None:
    answers = _write_answers(
        tmp_path,
        'schema_version: "1"\nfeatures: [core_lib]\nsandbox_profle: developer\n',
    )
    result = runner.invoke(_app, ["--answers-file", str(answers)])
    out = _combined(result)
    # typer.BadParameter exits 2 (usage error) — a SystemExit, not a traceback.
    assert result.exit_code == 2
    assert isinstance(result.exception, SystemExit)
    assert "sandbox_profle" in out
    assert "--answers-file" in out
    # No silently-substituted plan ran after the failure.
    assert "Resolved plan" not in result.output


def test_password_field_in_answers_is_named_error(tmp_path: Path) -> None:
    """Secrets are forbidden answers keys by policy (SPEC-180) — explicitly."""
    answers = _write_answers(tmp_path, 'schema_version: "1"\nadmin_password: hunter2\n')
    result = runner.invoke(_app, ["--answers-file", str(answers)])
    assert result.exit_code == 2
    assert "admin_password" in _combined(result)
    assert "Resolved plan" not in result.output

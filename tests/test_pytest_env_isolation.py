"""Regression coverage for repository-root dotenv isolation (#300)."""

from __future__ import annotations

from pathlib import Path

from maistro.config.settings import Settings


_AMBIENT_SETTING_VARS = (
    "API_KEYS",
    "DEFAULT_MODEL",
    "DB_HOST",
    "REQUIRE_AUTH",
)


def test_general_test_settings_ignore_repository_root_dotenv(tmp_path: Path, monkeypatch) -> None:
    """A hostile cwd .env must not change ordinary test configuration."""
    for name in _AMBIENT_SETTING_VARS:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "REQUIRE_AUTH=true\n"
        'API_KEYS=["hostile-token"]\n'
        "DEFAULT_MODEL=hostile/model\n"
        "DB_HOST=hostile-db\n",
        encoding="utf-8",
    )

    settings = Settings()

    assert settings.api_keys == []
    assert settings.default_model == "anthropic/claude-sonnet-4-20250514"
    assert settings.db.host == "localhost"


def test_explicit_dotenv_fixture_still_works(tmp_path: Path, monkeypatch) -> None:
    """Tests that intentionally exercise dotenv can opt in with an isolated file."""
    monkeypatch.delenv("DEFAULT_MODEL", raising=False)
    env_file = tmp_path / "fixture.env"
    env_file.write_text("DEFAULT_MODEL=fixture/model\n", encoding="utf-8")

    settings = Settings(_env_file=env_file)

    assert settings.default_model == "fixture/model"

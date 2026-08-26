"""Regression coverage for repository-root dotenv isolation (#300)."""

from __future__ import annotations

from pathlib import Path

from maistro.config.settings import Settings


def test_general_test_settings_ignore_repository_root_dotenv(tmp_path: Path, monkeypatch) -> None:
    """A hostile cwd .env must not change ordinary test configuration."""
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

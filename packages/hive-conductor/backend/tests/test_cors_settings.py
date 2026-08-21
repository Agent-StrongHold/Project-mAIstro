"""hive-conductor's CORS allow-list, validated on the class the app reads.

This backend does not use `maistro.config.settings.Settings` — it has its own
`config.Settings`, and `main.py` hands *that* `cors_origins` to CORSMiddleware
together with `allow_credentials=True` and `allow_methods=["*"]`. Validating
only the engine's settings class left this, the more exposed of the two live
paths, unguarded. These tests exist so that gap cannot reopen silently.
"""

from __future__ import annotations

import pytest
from config import Settings


class TestHiveCorsValidation:
    def test_wildcard_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CORS_ORIGINS", '["*"]')
        with pytest.raises(ValueError, match="must not contain"):
            Settings()

    def test_opaque_null_origin_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CORS_ORIGINS", '["null"]')
        with pytest.raises(ValueError, match="must not contain 'null'"):
            Settings()

    def test_script_scheme_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CORS_ORIGINS", '["javascript:alert(1)"]')
        with pytest.raises(ValueError, match="unsafe origin"):
            Settings()

    def test_real_origins_are_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CORS_ORIGINS", '["https://hive.example","http://localhost:5173"]')
        assert Settings().cors_origins == ["https://hive.example", "http://localhost:5173"]

    def test_shipped_dev_defaults_still_construct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The validator must not reject the localhost defaults the documented
        dev loop depends on."""
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        assert "http://localhost:5173" in Settings().cors_origins

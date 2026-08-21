"""CORS origin validation, asserted on the path the servers actually read.

The bug this covers: validation existed and was correct, but lived on
`load_yaml_config` -> `MaistroYamlConfig.cors.allowed_origins`, which no
application reads. The apps pass `Settings.cors_origins` to CORSMiddleware,
and that field had no validation at all. The guard was on the wrong door.

So these tests assert the *effect* on `Settings`, not merely that a validator
function exists somewhere.
"""

from __future__ import annotations

import pytest

from maistro.config.settings import Settings, validate_cors_origins


class TestLivePath:
    """`Settings.cors_origins` is what maistro-server and hive-conductor hand
    to CORSMiddleware, paired with allow_credentials=True."""

    def test_wildcard_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CORS_ORIGINS", '["*"]')
        with pytest.raises(ValueError, match=r"must not contain"):
            Settings()

    def test_wildcard_mixed_with_real_origins_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One bad entry poisons the list — CORSMiddleware treats any '*' in
        allow_origins as allow-all, so a partial list is not partial safety."""
        monkeypatch.setenv("CORS_ORIGINS", '["https://app.example","*"]')
        with pytest.raises(ValueError, match=r"must not contain"):
            Settings()

    @pytest.mark.parametrize("scheme", ["javascript:alert(1)", "data:text/html,<script>"])
    def test_script_bearing_schemes_are_refused(
        self, scheme: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CORS_ORIGINS", f'["{scheme}"]')
        with pytest.raises(ValueError, match="unsafe origin"):
            Settings()

    def test_https_and_localhost_are_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CORS_ORIGINS", '["https://app.example","http://localhost:3000"]')
        assert Settings().cors_origins == ["https://app.example", "http://localhost:3000"]

    def test_default_is_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The validator must not reject the shipped default."""
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        assert Settings().cors_origins == ["http://localhost:3080"]


class TestSharedImplementation:
    def test_whitespace_is_stripped_and_blanks_dropped(self) -> None:
        """`MAISTRO_CORS_ORIGINS` arrives comma-separated, so entries carry
        surrounding whitespace and a trailing comma yields an empty entry."""
        assert validate_cors_origins([" https://a.example ", "", "  "]) == ["https://a.example"]

    def test_plain_http_non_localhost_warns_but_is_allowed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A warning, not a refusal — plenty of internal deployments terminate
        TLS at a proxy and legitimately register an http:// origin."""
        with caplog.at_level("WARNING"):
            assert validate_cors_origins(["http://internal.corp"]) == ["http://internal.corp"]
        assert "not HTTPS" in caplog.text


class TestOpaqueOrigin:
    """Browsers serialize opaque origins as the literal string `null`:
    sandboxed iframes, `file:` pages, `data:` documents, some redirect chains.
    They are mutually indistinguishable, so there is no such thing as trusting
    one of them — paired with credentials, allowing `null` grants them all
    credentialed access."""

    @pytest.mark.parametrize("value", ["null", "NULL", "Null"])
    def test_null_origin_is_refused(self, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CORS_ORIGINS", f'["{value}"]')
        with pytest.raises(ValueError, match="must not contain 'null'"):
            Settings()

    def test_null_mixed_with_real_origins_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CORS_ORIGINS", '["https://app.example","null"]')
        with pytest.raises(ValueError, match="must not contain 'null'"):
            Settings()

    def test_hostname_containing_null_is_still_allowed(self) -> None:
        """Only the exact opaque-origin token is refused, not any host that
        happens to contain those letters."""
        assert validate_cors_origins(["https://nullable.example"]) == ["https://nullable.example"]

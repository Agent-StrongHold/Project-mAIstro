"""Tests for maistro.config.loader — YAML config + env overrides."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from maistro.config.loader import load_yaml_config
from maistro.config.settings import set_yaml_config


@pytest.fixture(autouse=True)
def _reset_yaml_config() -> None:
    set_yaml_config(None)
    yield
    set_yaml_config(None)


@pytest.fixture
def _no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in [
        "DATABASE_URL",
        "LITELLM_URL",
        "LITELLM_MASTER_KEY",
        "ROUTER_API_KEY",
        "JWT_SECRET",
        "PHOENIX_COLLECTOR_ENDPOINT",
        "MAISTRO_WEBHOOK_SECRET",
        "MAISTRO_CORS_ORIGINS",
        "MAISTRO_RATE_LIMIT_RPM",
        "MAISTRO_MAX_REQUEST_BODY_BYTES",
        "MAISTRO_JWKS_URL",
        "MAISTRO_AUTH_ISSUER",
        "MAISTRO_AUTH_AUDIENCE",
        "MAISTRO_AUTH_CLIENT_ID",
        "MAISTRO_AUTH_AUTHORIZATION_URL",
        "MAISTRO_AUTH_TOKEN_URL",
        "MAISTRO_AUTH_CLIENT_SECRET",
        "MAISTRO_CONFIG",
    ]:
        monkeypatch.delenv(var, raising=False)


class TestLoadRawYaml:
    def test_missing_file_returns_defaults(self, _no_env: None, tmp_path: Path) -> None:
        config = load_yaml_config(tmp_path / "missing.yaml")
        assert config.database_url == ""

    def test_valid_yaml_loaded(self, _no_env: None, tmp_path: Path) -> None:
        path = tmp_path / "cfg.yaml"
        path.write_text(yaml.dump({"database_url": "postgres://x"}))
        config = load_yaml_config(path)
        assert config.database_url == "postgres://x"

    def test_invalid_yaml_raises(self, _no_env: None, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("key: [unbalanced")
        with pytest.raises(ValueError, match="Invalid YAML"):
            load_yaml_config(path)

    def test_path_defaults_from_env_var(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "envcfg.yaml"
        path.write_text(yaml.dump({"database_url": "from-env-path"}))
        monkeypatch.setenv("MAISTRO_CONFIG", str(path))
        config = load_yaml_config()
        assert config.database_url == "from-env-path"


class TestEnvOverrides:
    def test_database_url_overridden(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgres://override")
        config = load_yaml_config(tmp_path / "missing.yaml")
        assert config.database_url == "postgres://override"

    def test_all_env_vars_applied(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LITELLM_URL", "http://litellm-override")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key123")
        monkeypatch.setenv("ROUTER_API_KEY", "x" * 32)
        monkeypatch.setenv("JWT_SECRET", "y" * 32)
        monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix")
        monkeypatch.setenv("MAISTRO_WEBHOOK_SECRET", "z" * 16)
        config = load_yaml_config(tmp_path / "missing.yaml")
        assert config.litellm_url == "http://litellm-override"
        assert config.litellm_key == "key123"
        assert config.router_api_key == "x" * 32
        assert config.jwt_secret == "y" * 32
        assert config.phoenix_endpoint == "http://phoenix"
        assert config.webhook_secret == "z" * 16


class TestValidateSecrets:
    def test_short_router_key_warns_but_does_not_raise(
        self,
        _no_env: None,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("ROUTER_API_KEY", "short")
        config = load_yaml_config(tmp_path / "missing.yaml")
        assert config.router_api_key == "short"

    def test_short_jwt_secret_raises(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JWT_SECRET", "short")
        with pytest.raises(ValueError, match="JWT_SECRET must be at least 32"):
            load_yaml_config(tmp_path / "missing.yaml")

    def test_short_webhook_secret_raises(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_WEBHOOK_SECRET", "short")
        with pytest.raises(ValueError, match="MAISTRO_WEBHOOK_SECRET must be at least 16"):
            load_yaml_config(tmp_path / "missing.yaml")


class TestCorsAndLimits:
    def test_wildcard_cors_origin_raises(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_CORS_ORIGINS", "*")
        with pytest.raises(ValueError, match="must not contain"):
            load_yaml_config(tmp_path / "missing.yaml")

    def test_javascript_scheme_cors_origin_raises(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_CORS_ORIGINS", "javascript:alert(1)")
        with pytest.raises(ValueError, match="unsafe origin"):
            load_yaml_config(tmp_path / "missing.yaml")

    def test_data_scheme_cors_origin_raises(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_CORS_ORIGINS", "data:text/html,x")
        with pytest.raises(ValueError, match="unsafe origin"):
            load_yaml_config(tmp_path / "missing.yaml")

    def test_non_https_non_localhost_origin_warns(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_CORS_ORIGINS", "http://example.com")
        config = load_yaml_config(tmp_path / "missing.yaml")
        assert config.cors.allowed_origins == ["http://example.com"]

    def test_localhost_origin_does_not_warn(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_CORS_ORIGINS", "http://localhost:3000")
        config = load_yaml_config(tmp_path / "missing.yaml")
        assert config.cors.allowed_origins == ["http://localhost:3000"]

    def test_https_origin_accepted(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_CORS_ORIGINS", "https://example.com,https://other.com")
        config = load_yaml_config(tmp_path / "missing.yaml")
        assert config.cors.allowed_origins == ["https://example.com", "https://other.com"]

    def test_rate_limit_rpm_applied(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_RATE_LIMIT_RPM", "42")
        config = load_yaml_config(tmp_path / "missing.yaml")
        assert config.rate_limit.requests_per_minute == 42

    def test_max_body_bytes_applied(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_MAX_REQUEST_BODY_BYTES", "2048")
        config = load_yaml_config(tmp_path / "missing.yaml")
        assert config.max_request_body_bytes == 2048


class TestAuthEnv:
    def test_no_auth_vars_leaves_defaults(self, _no_env: None, tmp_path: Path) -> None:
        config = load_yaml_config(tmp_path / "missing.yaml")
        assert config.auth.audience == "" or config.auth.audience is not None

    def test_non_public_audience_applied_without_validation(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_AUTH_AUDIENCE", "my-audience")
        config = load_yaml_config(tmp_path / "missing.yaml")
        assert config.auth.audience == "my-audience"

    def test_public_url_var_with_private_host_raises(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_JWKS_URL", "https://localhost/.well-known/jwks.json")
        with pytest.raises(ValueError, match="resolves to private"):
            load_yaml_config(tmp_path / "missing.yaml")

    def test_public_url_var_with_public_host_applied(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_AUTH_ISSUER", "https://example.com/issuer")
        config = load_yaml_config(tmp_path / "missing.yaml")
        assert config.auth.issuer == "https://example.com/issuer"


class TestValidateUrlNotPrivate:
    def test_non_https_scheme_raises(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_AUTH_ISSUER", "http://example.com/issuer")
        with pytest.raises(ValueError, match="must use HTTPS scheme"):
            load_yaml_config(tmp_path / "missing.yaml")

    def test_no_hostname_raises(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_AUTH_ISSUER", "https:///path-only")
        with pytest.raises(ValueError, match="has no hostname"):
            load_yaml_config(tmp_path / "missing.yaml")

    def test_unresolvable_hostname_logs_and_skips(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_AUTH_ISSUER", "https://this-host-does-not-exist.invalid/issuer")
        config = load_yaml_config(tmp_path / "missing.yaml")
        assert config.auth.issuer == "https://this-host-does-not-exist.invalid/issuer"

    def test_loopback_address_raises(
        self, _no_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_AUTH_ISSUER", "https://127.0.0.1/issuer")
        with pytest.raises(ValueError, match="resolves to private"):
            load_yaml_config(tmp_path / "missing.yaml")

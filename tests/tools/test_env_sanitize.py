"""Tests for environment variable sanitization.

Updated for allowlist-based approach (MAJ-07). The sanitizer now only passes
through explicitly allowed env var names, with defense-in-depth value checks.
"""

from __future__ import annotations

import pytest

from maistro.tools.sandbox.env_sanitize import (
    is_allowed_name,
    is_blocked_name,
    looks_like_secret,
    sanitize_env,
)


class TestAllowlistNames:
    """MAJ-07: Only allowlisted env vars pass through to sandbox."""

    @pytest.mark.parametrize(
        "name",
        [
            "PATH",
            "LANG",
            "LANGUAGE",
            "TZ",
            "TERM",
            "SHELL",
            "EDITOR",
            "PYTHONDONTWRITEBYTECODE",
            "PIP_NO_CACHE_DIR",
            "VIRTUAL_ENV",
            "GOPATH",
            "CI",
            "DEBIAN_FRONTEND",
        ],
    )
    def test_allowed_exact_names(self, name: str) -> None:
        assert is_allowed_name(name), f"{name} should be allowed"

    @pytest.mark.parametrize(
        "name",
        [
            "LC_ALL",
            "LC_CTYPE",
            "NPM_CONFIG_REGISTRY",
            "CONDA_PREFIX",
            "CARGO_HOME",
            "RUSTUP_HOME",
            "PYTHONPATH",
        ],
    )
    def test_allowed_prefix_names(self, name: str) -> None:
        assert is_allowed_name(name), f"{name} should be allowed by prefix"

    @pytest.mark.parametrize(
        "name",
        [
            "AWS_SECRET_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "DATABASE_URL",
            "GITHUB_TOKEN",
            "MY_CUSTOM_VAR",
            "STRIPE_API_KEY",
            "COMPANY_INTERNAL_TOKEN",
        ],
    )
    def test_non_allowlisted_blocked(self, name: str) -> None:
        assert not is_allowed_name(name), f"{name} should NOT be allowed"


class TestBlockedNames:
    """Legacy blocklist still available for other uses."""

    @pytest.mark.parametrize(
        "name",
        [
            "API_KEY",
            "SECRET_TOKEN",
            "PASSWORD",
            "AWS_ACCESS_KEY_ID",
            "OPENAI_API_KEY",
            "GITHUB_TOKEN",
            "DB_PASSWORD",
            "DATABASE_URL",
        ],
    )
    def test_blocked_prefixes(self, name: str) -> None:
        assert is_blocked_name(name), f"{name} should be blocked"

    def test_case_insensitive(self) -> None:
        assert is_blocked_name("api_key")
        assert is_blocked_name("Api_Key")


class TestLooksLikeSecret:
    @pytest.mark.parametrize(
        "value",
        [
            "sk-1234567890abcdef1234567890abcdef",
            "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
            "ghs_abcdefghijklmnopqrstuvwxyz1234567890",
            "a" * 64,
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        ],
    )
    def test_secret_patterns_detected(self, value: str) -> None:
        assert looks_like_secret(value), f"Should detect as secret: {value[:20]}..."

    @pytest.mark.parametrize(
        "value",
        ["hello", "true", "8080", "/usr/local/bin", "production", "INFO", "utf-8", "en_US.UTF-8"],
    )
    def test_normal_values_not_flagged(self, value: str) -> None:
        assert not looks_like_secret(value)


class TestSanitizeEnv:
    """Integration: sanitize_env uses allowlist for names + secret check for values."""

    def test_allows_safe_vars(self) -> None:
        env = {
            "PATH": "/usr/bin",
            "LANG": "en_US.UTF-8",
            "TZ": "UTC",
        }
        result = sanitize_env(env)
        assert result == env

    def test_blocks_non_allowlisted_vars(self) -> None:
        env = {
            "PATH": "/usr/bin",
            "AWS_SECRET_KEY": "mysecret",
            "OPENAI_API_KEY": "sk-test",
            "MY_CUSTOM_VAR": "hello",
        }
        result = sanitize_env(env)
        assert "PATH" in result
        assert "AWS_SECRET_KEY" not in result
        assert "OPENAI_API_KEY" not in result
        assert "MY_CUSTOM_VAR" not in result

    def test_blocks_secret_values_even_on_allowed_names(self) -> None:
        env = {"PATH": "sk-1234567890abcdef1234567890abcdef"}
        result = sanitize_env(env)
        assert "PATH" not in result

    def test_empty_env(self) -> None:
        assert sanitize_env({}) == {}

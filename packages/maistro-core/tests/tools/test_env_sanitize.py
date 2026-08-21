"""Tests for environment variable sanitization.

Updated for allowlist-based approach (MAJ-07). The sanitizer now only passes
through explicitly allowed env var names, with defense-in-depth value checks.
"""

from __future__ import annotations

import time

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

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

    def test_unblocked_name_returns_false(self) -> None:
        assert is_blocked_name("PATH") is False

    def test_exact_blocked_name(self) -> None:
        assert is_blocked_name("HOME") is True


class TestLooksLikeSecret:
    @pytest.mark.parametrize(
        "value",
        [
            "sk-1234567890abcdef1234567890abcdef",
            "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
            "ghs_abcdefghijklmnopqrstuvwxyz1234567890",
            "a" * 64,
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            + "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            + "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
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


class TestSecretPatternBoundaries:
    """_SECRET_PATTERN's alternatives each have a hard length threshold
    (sk-/Bearer/eyJ need >=20 trailing chars, ghp_/ghs_ need exactly 36,
    hex keys need exactly 64). Off-by-one at each boundary must not flip
    the verdict in the wrong direction."""

    def test_hex_key_63_chars_not_flagged(self) -> None:
        assert not looks_like_secret("a" * 63)

    def test_hex_key_64_chars_flagged(self) -> None:
        assert looks_like_secret("a" * 64)

    def test_hex_key_65_chars_not_flagged(self) -> None:
        # exact {64} with trailing $ means one extra char breaks the match
        assert not looks_like_secret("a" * 65)

    def test_hex_key_uppercase_flagged(self) -> None:
        # regression: [a-f0-9] alone would miss uppercase-hex secrets
        assert looks_like_secret("A" * 64)

    def test_hex_key_mixed_case_flagged(self) -> None:
        assert looks_like_secret("aB" * 32)

    def test_github_pat_35_chars_not_flagged(self) -> None:
        assert not looks_like_secret("ghp_" + "a" * 35)

    def test_github_pat_36_chars_flagged(self) -> None:
        assert looks_like_secret("ghp_" + "a" * 36)

    def test_github_pat_37_chars_not_flagged(self) -> None:
        assert not looks_like_secret("ghp_" + "a" * 37)

    def test_github_app_token_36_chars_flagged(self) -> None:
        assert looks_like_secret("ghs_" + "a" * 36)

    def test_openai_key_19_chars_not_flagged(self) -> None:
        assert not looks_like_secret("sk-" + "a" * 19)

    def test_openai_key_20_chars_flagged(self) -> None:
        assert looks_like_secret("sk-" + "a" * 20)

    def test_bearer_token_19_chars_not_flagged(self) -> None:
        assert not looks_like_secret("Bearer " + "a" * 19)

    def test_bearer_token_20_chars_flagged(self) -> None:
        assert looks_like_secret("Bearer " + "a" * 20)

    def test_jwt_19_chars_not_flagged(self) -> None:
        assert not looks_like_secret("eyJ" + "a" * 19)

    def test_jwt_20_chars_flagged(self) -> None:
        assert looks_like_secret("eyJ" + "a" * 20)

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("property")
    @given(n=st.integers(min_value=0, max_value=80))
    @settings(max_examples=100)
    def test_hex_length_boundary_is_exactly_64(self, n: int) -> None:
        value = "a" * n
        assert looks_like_secret(value) == (n == 64)

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("property")
    @given(n=st.integers(min_value=0, max_value=60))
    @settings(max_examples=100)
    def test_github_pat_length_boundary_is_exactly_36(self, n: int) -> None:
        value = "ghp_" + "a" * n
        assert looks_like_secret(value) == (n == 36)

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("property")
    @given(n=st.integers(min_value=0, max_value=40))
    @settings(max_examples=100)
    def test_openai_key_length_boundary_is_at_least_20(self, n: int) -> None:
        value = "sk-" + "a" * n
        assert looks_like_secret(value) == (n >= 20)


class TestSecretPatternReDoSSafety:
    """The pattern's alternation has no nested ambiguous quantifiers, so it
    must stay linear-time even on long adversarial near-miss inputs. A
    regression here would mean someone introduced backtracking risk."""

    @pytest.mark.parametrize(
        "near_miss",
        [
            "a" * 50_000,  # almost a hex key, never terminates the run
            "sk-" + "a" * 50_000,
            "ghp_" + "a" * 50_000,
            "Bearer " + "a" * 50_000,
            "eyJ" + "a" * 50_000,
            ("a" * 49_999) + "!",  # one disqualifying char near the end
        ],
        ids=["bare_hex", "openai", "github_pat", "bearer", "jwt", "hex_with_bad_tail"],
    )
    def test_long_near_miss_inputs_stay_fast(self, near_miss: str) -> None:
        start = time.monotonic()
        looks_like_secret(near_miss)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"looks_like_secret took {elapsed:.2f}s — possible ReDoS regression"

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("property")
    @given(garbage=st.text(alphabet=st.characters(whitelist_categories=("L", "N")), max_size=2000))
    @settings(max_examples=50, deadline=None)
    def test_arbitrary_alnum_text_stays_fast(self, garbage: str) -> None:
        start = time.monotonic()
        looks_like_secret(garbage)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"looks_like_secret took {elapsed:.2f}s on len={len(garbage)} input"

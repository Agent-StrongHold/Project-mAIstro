"""Tests for constant-time secret comparison.

Evidence source: The reference implementation's secret-equal.ts uses HMAC-SHA256 before
timingSafeEqual to prevent timing attacks via length leakage.
"""

from __future__ import annotations

import inspect

from maistro.security.secret_equal import secret_equal


class TestSecretEqual:
    """Evidence: The reference implementation hashes both inputs with HMAC-SHA256
    before comparison, producing fixed-length 32-byte digests regardless of
    input length. This prevents timing attacks that could leak length info."""

    def test_equal_strings(self) -> None:
        assert secret_equal("abc123", "abc123") is True

    def test_unequal_strings(self) -> None:
        assert secret_equal("abc123", "abc124") is False

    def test_different_lengths(self) -> None:
        """Evidence: Different-length strings should be handled safely
        without leaking length information through timing."""
        assert secret_equal("short", "a-much-longer-string") is False

    def test_empty_strings(self) -> None:
        assert secret_equal("", "") is True

    def test_empty_vs_nonempty(self) -> None:
        assert secret_equal("", "notempty") is False

    def test_unicode_strings(self) -> None:
        assert secret_equal("héllo", "héllo") is True
        assert secret_equal("héllo", "hello") is False

    def test_type_confusion_int(self) -> None:
        """Evidence: The reference implementation defends against type confusion by performing
        a dummy comparison for non-string inputs."""
        assert secret_equal(123, "123") is False  # type: ignore[arg-type]

    def test_type_confusion_none(self) -> None:
        assert secret_equal(None, "test") is False  # type: ignore[arg-type]

    def test_type_confusion_both_nonstring(self) -> None:
        assert secret_equal(123, 456) is False  # type: ignore[arg-type]

    def test_long_tokens(self) -> None:
        """Evidence: Real API tokens are typically 40-100+ characters."""
        token = "sk-ant-api03-" + "a" * 80
        assert secret_equal(token, token) is True
        assert secret_equal(token, token[:-1] + "b") is False

    def test_uses_hmac_compare_digest(self) -> None:
        """Evidence: The implementation must use hmac.compare_digest, not ==.
        A mutation replacing compare_digest with == must be caught."""
        source = inspect.getsource(secret_equal)
        assert "compare_digest" in source, (
            "secret_equal must use hmac.compare_digest for constant-time comparison"
        )

    def test_uses_hmac_hashing(self) -> None:
        """Evidence: Inputs are HMAC-hashed before comparison to prevent
        length leakage via early-exit."""
        source = inspect.getsource(secret_equal)
        assert "hmac.new" in source or "hmac.HMAC" in source, (
            "secret_equal must HMAC-hash inputs before comparison"
        )

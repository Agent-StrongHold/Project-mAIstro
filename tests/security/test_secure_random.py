"""Tests for secure random utilities.

Evidence source: The reference implementation's secure-random.ts provides CSPRNG-based ID
generation, replacing all Math.random() usage in security contexts.
"""

from __future__ import annotations

import re

from maistro.security.secure_random import secure_base36, secure_id, secure_int, secure_urlsafe


class TestSecureId:
    """Evidence: The reference implementation's secureId generates hex strings from crypto.randomBytes."""

    def test_default_length(self) -> None:
        """Default 16 bytes = 32 hex chars."""
        result = secure_id()
        assert len(result) == 32
        assert re.match(r"^[0-9a-f]+$", result)

    def test_custom_length(self) -> None:
        result = secure_id(8)
        assert len(result) == 16

    def test_uniqueness(self) -> None:
        ids = {secure_id() for _ in range(100)}
        assert len(ids) == 100, "IDs should be unique"


class TestSecureUrlsafe:
    def test_produces_urlsafe_string(self) -> None:
        result = secure_urlsafe()
        assert re.match(r"^[A-Za-z0-9_-]+$", result)


class TestSecureInt:
    def test_range(self) -> None:
        for _ in range(100):
            val = secure_int(0, 10)
            assert 0 <= val < 10

    def test_distribution(self) -> None:
        """Values should spread across the range (not stuck at one value)."""
        values = {secure_int(0, 100) for _ in range(200)}
        assert len(values) > 20


class TestSecureBase36:
    """Evidence: The reference implementation's secureBase36 generates base36 tokens as
    drop-in replacements for Math.random().toString(36)."""

    def test_default_length(self) -> None:
        result = secure_base36()
        assert len(result) == 8

    def test_custom_length(self) -> None:
        result = secure_base36(16)
        assert len(result) == 16

    def test_charset(self) -> None:
        result = secure_base36(100)
        assert re.match(r"^[0-9a-z]+$", result)

    def test_uniqueness(self) -> None:
        tokens = {secure_base36() for _ in range(100)}
        assert len(tokens) == 100

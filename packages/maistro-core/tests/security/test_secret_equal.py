"""Tests for constant-time secret comparison.

Evidence source: the live primitive must HMAC-normalize both string inputs and
route the final decision through hmac.compare_digest. Tests observe those calls
rather than searching source text, so comments or dead code cannot satisfy them.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import call

import maistro.security.secret_equal as secret_equal_module
from maistro.security.secret_equal import secret_equal


class TestSecretEqual:
    def test_equal_strings(self) -> None:
        assert secret_equal("abc123", "abc123") is True

    def test_unequal_strings(self) -> None:
        assert secret_equal("abc123", "abc124") is False

    def test_different_lengths(self) -> None:
        assert secret_equal("short", "a-much-longer-string") is False

    def test_empty_strings(self) -> None:
        assert secret_equal("", "") is True

    def test_empty_vs_nonempty(self) -> None:
        assert secret_equal("", "notempty") is False

    def test_unicode_strings(self) -> None:
        assert secret_equal("héllo", "héllo") is True
        assert secret_equal("héllo", "hello") is False

    def test_type_confusion_int(self) -> None:
        assert secret_equal(123, "123") is False  # type: ignore[arg-type]

    def test_type_confusion_none(self) -> None:
        assert secret_equal(None, "test") is False  # type: ignore[arg-type]

    def test_type_confusion_both_nonstring(self) -> None:
        assert secret_equal(123, 456) is False  # type: ignore[arg-type]

    def test_long_tokens(self) -> None:
        token = "sk-ant-api03-" + "a" * 80
        assert secret_equal(token, token) is True
        assert secret_equal(token, token[:-1] + "b") is False

    def test_live_decision_uses_compare_digest(self, monkeypatch) -> None:
        """The exact compare_digest -> == mutant must fail this test."""
        seen: list[tuple[bytes, bytes]] = []

        def deny_even_equal(left: bytes, right: bytes) -> bool:
            seen.append((left, right))
            return False

        monkeypatch.setattr(secret_equal_module.hmac, "compare_digest", deny_even_equal)

        assert secret_equal("same-secret", "same-secret") is False
        assert len(seen) == 1
        left, right = seen[0]
        assert isinstance(left, bytes) and isinstance(right, bytes)
        assert len(left) == len(right) == 32

    def test_string_inputs_are_hmac_normalized_before_comparison(self, monkeypatch) -> None:
        """Both inputs must flow through HMAC before the comparison boundary."""

        @dataclass
        class _Digest:
            value: bytes

            def digest(self) -> bytes:
                return self.value

        calls: list[tuple[bytes, bytes, object]] = []

        def fake_new(key: bytes, message: bytes, digestmod: object) -> _Digest:
            calls.append((key, message, digestmod))
            return _Digest((message + b"\0" * 32)[:32])

        compared: list[tuple[bytes, bytes]] = []

        def fake_compare(left: bytes, right: bytes) -> bool:
            compared.append((left, right))
            return left == right

        monkeypatch.setattr(secret_equal_module.hmac, "new", fake_new)
        monkeypatch.setattr(secret_equal_module.hmac, "compare_digest", fake_compare)

        assert secret_equal("alpha", "beta") is False
        assert [entry[1] for entry in calls] == [b"alpha", b"beta"]
        assert all(entry[0] == secret_equal_module._HMAC_KEY for entry in calls)
        assert len(compared) == 1
        assert all(len(value) == 32 for value in compared[0])

    def test_nonstring_path_still_consumes_compare_digest(self, monkeypatch) -> None:
        """Type-confusion rejection must retain the dummy constant-cost comparison."""
        seen: list[tuple[bytes, bytes]] = []

        def fake_compare(left: bytes, right: bytes) -> bool:
            seen.append((left, right))
            return True

        monkeypatch.setattr(secret_equal_module.hmac, "compare_digest", fake_compare)

        assert secret_equal(1, "1") is False  # type: ignore[arg-type]
        assert seen == [(b"dummy-a", b"dummy-b")]

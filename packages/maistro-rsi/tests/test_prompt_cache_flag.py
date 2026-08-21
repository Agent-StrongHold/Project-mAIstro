"""The builders prompt-cache opt-in flag: off unless MAISTRO_BUILDERS_PROMPT_CACHE
is explicitly truthy, so the cache path never turns on by accident."""

from __future__ import annotations

import pytest

from maistro_rsi.local_loop import _prompt_cache_enabled


@pytest.mark.parametrize("value", ["1", "on", "true", "yes", "TRUE", "On", " yes "])
def test_enabled_for_truthy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("MAISTRO_BUILDERS_PROMPT_CACHE", value)
    assert _prompt_cache_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "off", "false", "no", "nope"])
def test_disabled_for_falsy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("MAISTRO_BUILDERS_PROMPT_CACHE", value)
    assert _prompt_cache_enabled() is False


def test_disabled_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAISTRO_BUILDERS_PROMPT_CACHE", raising=False)
    assert _prompt_cache_enabled() is False

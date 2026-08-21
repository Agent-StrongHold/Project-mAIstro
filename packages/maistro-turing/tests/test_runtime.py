"""Tests for runtime.py: TuringConfig, env loading, TuringActor, TuringChatSession."""

from __future__ import annotations

import os
from typing import Any

import pytest

from maistro_turing.bridge import (
    TuringProviderBridge,
)
from maistro_turing.runtime import (
    TuringActor,
    TuringChatSession,
    TuringConfig,
    load_turing_config,
)

_ENV_VARS = (
    "TURING_TICK_RATE_HZ",
    "TURING_DB_PATH",
    "TURING_LOG_LEVEL",
    "TURING_USE_FAKE_PROVIDER",
    "LITELLM_BASE_URL",
    "LITELLM_VIRTUAL_KEY",
    "TURING_POOLS_CONFIG",
    "TURING_CHAT_PORT",
    "TURING_CHAT_BIND",
    "TURING_BASE_PROMPT_PATH",
)


@pytest.fixture(autouse=True)
def _clean_env() -> Any:
    saved = {name: os.environ.pop(name, None) for name in _ENV_VARS}
    yield
    for name, value in saved.items():
        if value is not None:
            os.environ[name] = value
        else:
            os.environ.pop(name, None)


# ---------------------------------------------------------------- config -----


class TestTuringConfig:
    def test_defaults(self) -> None:
        cfg = TuringConfig()
        assert cfg.tick_rate_hz == 100
        assert cfg.db_path == ":memory:"
        assert cfg.log_level == "INFO"
        assert cfg.use_fake_provider is True
        assert cfg.litellm_base_url is None
        assert cfg.litellm_virtual_key is None
        assert cfg.pools_config_path is None
        assert cfg.chat_port is None
        assert cfg.chat_bind == "127.0.0.1"
        assert cfg.base_prompt is None
        assert cfg.voice_self_edit_enabled is True

    def test_validate_passes_for_positive_tick_rate(self) -> None:
        TuringConfig(tick_rate_hz=1).validate()

    def test_validate_raises_for_zero_tick_rate(self) -> None:
        with pytest.raises(ValueError, match="tick_rate_hz must be positive"):
            TuringConfig(tick_rate_hz=0).validate()

    def test_validate_raises_for_negative_tick_rate(self) -> None:
        with pytest.raises(ValueError, match="tick_rate_hz must be positive"):
            TuringConfig(tick_rate_hz=-5).validate()


class TestLoadTuringConfig:
    def test_defaults_with_no_env_no_overrides(self) -> None:
        cfg = load_turing_config()
        assert cfg == TuringConfig()

    def test_env_vars_override_defaults(self) -> None:
        os.environ["TURING_TICK_RATE_HZ"] = "50"
        os.environ["TURING_DB_PATH"] = "/tmp/turing.db"
        os.environ["TURING_LOG_LEVEL"] = "debug"
        os.environ["TURING_USE_FAKE_PROVIDER"] = "false"
        os.environ["LITELLM_BASE_URL"] = "http://localhost:4000"
        os.environ["LITELLM_VIRTUAL_KEY"] = "sk-virtual"
        os.environ["TURING_POOLS_CONFIG"] = "/etc/pools.yaml"
        os.environ["TURING_CHAT_PORT"] = "8080"
        os.environ["TURING_CHAT_BIND"] = "0.0.0.0"
        os.environ["TURING_BASE_PROMPT_PATH"] = "/etc/prompt.txt"

        cfg = load_turing_config()

        assert cfg.tick_rate_hz == 50
        assert cfg.db_path == "/tmp/turing.db"
        assert cfg.log_level == "DEBUG"
        assert cfg.use_fake_provider is False
        assert cfg.litellm_base_url == "http://localhost:4000"
        assert cfg.litellm_virtual_key == "sk-virtual"
        assert cfg.pools_config_path == "/etc/pools.yaml"
        assert cfg.chat_port == 8080
        assert cfg.chat_bind == "0.0.0.0"
        assert cfg.base_prompt == "/etc/prompt.txt"

    @pytest.mark.parametrize("truthy", ["1", "true", "TRUE", "True", "yes", "YES"])
    def test_use_fake_provider_truthy_values(self, truthy: str) -> None:
        os.environ["TURING_USE_FAKE_PROVIDER"] = truthy
        cfg = load_turing_config()
        assert cfg.use_fake_provider is True

    @pytest.mark.parametrize("falsy", ["0", "false", "no", "garbage"])
    def test_use_fake_provider_falsy_values(self, falsy: str) -> None:
        os.environ["TURING_USE_FAKE_PROVIDER"] = falsy
        cfg = load_turing_config()
        assert cfg.use_fake_provider is False

    def test_chat_port_zero_becomes_none(self) -> None:
        # _positive_int_or_none uses `int(value) or None`, so "0" -> 0 -> None.
        os.environ["TURING_CHAT_PORT"] = "0"
        cfg = load_turing_config()
        assert cfg.chat_port is None

    def test_overrides_take_precedence_over_env(self) -> None:
        os.environ["TURING_TICK_RATE_HZ"] = "50"
        cfg = load_turing_config(overrides={"tick_rate_hz": 200})
        assert cfg.tick_rate_hz == 200

    def test_overrides_alone_without_env(self) -> None:
        cfg = load_turing_config(overrides={"db_path": "/custom.db"})
        assert cfg.db_path == "/custom.db"
        assert cfg.tick_rate_hz == 100

    def test_invalid_tick_rate_raises_after_load(self) -> None:
        with pytest.raises(ValueError, match="tick_rate_hz must be positive"):
            load_turing_config(overrides={"tick_rate_hz": 0})


# ---------------------------------------------------------------- actor ------


class FakeMemoryBridge:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def store_episode(self, *, content: str, tier: str, **kwargs: Any) -> str:
        self.calls.append({"content": content, "tier": tier, **kwargs})
        return "mem-id"


class FakeSecurityBridge:
    def __init__(self, verdict: str = "allowed") -> None:
        self._verdict = verdict
        self.self_write_calls: list[tuple[str, str]] = []
        self.tool_result_calls: list[tuple[str, str]] = []

    async def scan_self_write(self, content: str, *, kind: str = "") -> dict[str, Any]:
        self.self_write_calls.append((content, kind))
        return {"verdict": self._verdict, "flags": []}

    async def scan_tool_result(self, content: str, *, tool_name: str = "") -> dict[str, Any]:
        self.tool_result_calls.append((content, tool_name))
        return {"verdict": self._verdict, "flags": ["x"] if self._verdict == "blocked" else []}


class TestTuringActor:
    async def test_handle_memory_event_stores_when_allowed(self) -> None:
        memory = FakeMemoryBridge()
        security = FakeSecurityBridge(verdict="allowed")
        actor = TuringActor(
            memory=memory,  # type: ignore[arg-type]
            security=security,  # type: ignore[arg-type]
            provider=TuringProviderBridge(),
            self_id="self-1",
        )
        result = await actor.handle_memory_event("I learned something", "observation", weight=0.4)
        assert result == "mem-id"
        assert memory.calls == [
            {"content": "I learned something", "tier": "observation", "weight": 0.4}
        ]
        assert security.self_write_calls == [("I learned something", "observation")]

    async def test_handle_memory_event_blocked_returns_empty_and_skips_store(self) -> None:
        memory = FakeMemoryBridge()
        security = FakeSecurityBridge(verdict="blocked")
        actor = TuringActor(
            memory=memory,  # type: ignore[arg-type]
            security=security,  # type: ignore[arg-type]
            provider=TuringProviderBridge(),
            self_id="self-1",
        )
        result = await actor.handle_memory_event("bad content", "observation")
        assert result == ""
        assert memory.calls == []

    async def test_handle_tool_result_returns_scan(self) -> None:
        security = FakeSecurityBridge(verdict="blocked")
        actor = TuringActor(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            security=security,  # type: ignore[arg-type]
            provider=TuringProviderBridge(),
            self_id="self-1",
        )
        result = await actor.handle_tool_result("grep", "some output")
        assert result == {"verdict": "blocked", "flags": ["x"]}
        assert security.tool_result_calls == [("some output", "grep")]


# ---------------------------------------------------------------- chat -------


class FakeChatProvider:
    def __init__(self, reply: str = "a reply") -> None:
        self._reply = reply
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, max_tokens: int | None = None, pool: str = "") -> str:
        self.prompts.append(prompt)
        return self._reply


class FakeClassifierBridge:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def classify_message(
        self, message: str, *, task_types: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.messages.append(message)
        return {"task_type": "general", "complexity": 0.5, "priority": "normal"}


class FailingMemoryBridge:
    async def store_episode(self, *, content: str, tier: str, **kwargs: Any) -> str:
        raise RuntimeError("store failed")


class TestTuringChatSession:
    async def test_handle_message_returns_reply_and_records_history(self) -> None:
        memory = FakeMemoryBridge()
        provider = FakeChatProvider(reply="Hello there!")
        classifier = FakeClassifierBridge()
        security = FakeSecurityBridge()
        session = TuringChatSession(
            memory=memory,  # type: ignore[arg-type]
            provider=provider,  # type: ignore[arg-type]
            classifier=classifier,  # type: ignore[arg-type]
            security=security,  # type: ignore[arg-type]
            self_id="self-1",
        )
        reply = await session.handle_message("Hi")
        assert reply == "Hello there!"
        assert session._history == [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello there!"},
        ]
        assert classifier.messages == ["Hi"]
        assert "User: Hi" in provider.prompts[0]
        assert memory.calls[0]["tier"] == "observation"

    async def test_handle_message_includes_previous_context_on_second_turn(self) -> None:
        provider = FakeChatProvider(reply="ok")
        session = TuringChatSession(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=provider,  # type: ignore[arg-type]
            classifier=FakeClassifierBridge(),  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
        )
        await session.handle_message("first message")
        await session.handle_message("second message")
        second_prompt = provider.prompts[1]
        assert "Previous context:" in second_prompt
        assert "user: first message" in second_prompt
        assert "User: second message" in second_prompt

    async def test_handle_message_swallows_memory_store_failure(self) -> None:
        session = TuringChatSession(
            memory=FailingMemoryBridge(),  # type: ignore[arg-type]
            provider=FakeChatProvider(reply="fine"),  # type: ignore[arg-type]
            classifier=FakeClassifierBridge(),  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
        )
        # Must not raise even though the memory bridge always fails.
        reply = await session.handle_message("hi")
        assert reply == "fine"

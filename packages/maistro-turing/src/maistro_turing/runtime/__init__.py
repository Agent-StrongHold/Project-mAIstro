"""Turing runtime: config, chat, actor — wired to maistro-core through the bridge.

Ported from project-turing/sketches/turing/runtime/.
Simplified to use maistro-core subsystems via the bridge layer.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from maistro_turing.bridge import (
    TuringClassifierBridge,
    TuringMemoryBridge,
    TuringProviderBridge,
    TuringSecurityBridge,
)

logger = logging.getLogger("maistro_turing.runtime")


# ---------------------------------------------------------------- config -----


@dataclass(frozen=True)
class TuringConfig:
    tick_rate_hz: int = 100
    db_path: str = ":memory:"
    log_level: str = "INFO"
    use_fake_provider: bool = True
    litellm_base_url: str | None = None
    litellm_virtual_key: str | None = None
    pools_config_path: str | None = None
    chat_port: int | None = None
    chat_bind: str = "127.0.0.1"
    base_prompt: str | None = None
    voice_self_edit_enabled: bool = True

    def validate(self) -> None:
        if self.tick_rate_hz <= 0:
            raise ValueError("tick_rate_hz must be positive")


def _env_truthy(value: str) -> bool:
    return value.lower() in {"1", "true", "yes"}


def _positive_int_or_none(value: str) -> int | None:
    return int(value) or None


# Maps an env var name to (config field, parser). The parser converts the raw
# string into the typed config value.
_ENV_FIELD_MAP: dict[str, tuple[str, Callable[[str], Any]]] = {
    "TURING_TICK_RATE_HZ": ("tick_rate_hz", int),
    "TURING_DB_PATH": ("db_path", str),
    "TURING_LOG_LEVEL": ("log_level", str.upper),
    "TURING_USE_FAKE_PROVIDER": ("use_fake_provider", _env_truthy),
    "LITELLM_BASE_URL": ("litellm_base_url", str),
    "LITELLM_VIRTUAL_KEY": ("litellm_virtual_key", str),
    "TURING_POOLS_CONFIG": ("pools_config_path", str),
    "TURING_CHAT_PORT": ("chat_port", _positive_int_or_none),
    "TURING_CHAT_BIND": ("chat_bind", str),
    "TURING_BASE_PROMPT_PATH": ("base_prompt", str),
}


def load_turing_config(
    overrides: dict[str, Any] | None = None,
) -> TuringConfig:
    """Load config: overrides -> env vars -> defaults."""
    env = os.environ
    kwargs: dict[str, Any] = {}

    for env_name, (field, parser) in _ENV_FIELD_MAP.items():
        if env_name in env:
            kwargs[field] = parser(env[env_name])

    cfg = TuringConfig(**kwargs)
    if overrides:
        cfg = replace(cfg, **overrides)
    cfg.validate()
    return cfg


# ---------------------------------------------------------------- actor ------


class TuringActor:
    """Bridges internal durable-memory events to outward-facing actions.

    Uses the bridge to write memories, scan outputs, and dispatch tool calls.
    """

    def __init__(
        self,
        *,
        memory: TuringMemoryBridge,
        security: TuringSecurityBridge,
        provider: TuringProviderBridge,
        self_id: str,
    ) -> None:
        self._memory = memory
        self._security = security
        self._provider = provider
        self._self_id = self_id

    async def handle_memory_event(self, content: str, tier: str, **kwargs: Any) -> str:
        """Store a memory and scan it for security issues."""
        scan = await self._security.scan_self_write(content, kind=tier)
        if scan.get("verdict") == "blocked":
            logger.warning("self-write blocked by warden: %s", scan.get("flags"))
            return ""
        return await self._memory.store_episode(
            content=content,
            tier=tier,
            **kwargs,
        )

    async def handle_tool_result(self, tool_name: str, content: str) -> dict[str, Any]:
        """Scan a tool result and optionally store an observation."""
        scan = await self._security.scan_tool_result(content, tool_name=tool_name)
        return scan


# ---------------------------------------------------------------- chat -------


class TuringChatSession:
    """A single chat session wired through the bridge."""

    def __init__(
        self,
        *,
        memory: TuringMemoryBridge,
        provider: TuringProviderBridge,
        classifier: TuringClassifierBridge,
        security: TuringSecurityBridge,
        self_id: str,
    ) -> None:
        self._memory = memory
        self._provider = provider
        self._classifier = classifier
        self._security = security
        self._self_id = self_id
        self._history: list[dict[str, str]] = []

    async def handle_message(self, message: str) -> str:
        """Process a user message and return a response."""
        self._history.append({"role": "user", "content": message})

        await self._classifier.classify_message(message)

        prompt_parts = [f"User: {message}"]
        if self._history[:-1]:
            prompt_parts.insert(0, "Previous context:")
            for turn in self._history[-6:]:
                prompt_parts.insert(
                    len(prompt_parts) - 1, f"  {turn['role']}: {turn['content'][:200]}"
                )
        prompt_parts.append("Respond naturally as yourself.")

        reply = self._provider.complete(
            "\n".join(prompt_parts),
            max_tokens=1000,
        )

        self._history.append({"role": "assistant", "content": reply})

        try:
            await self._memory.store_episode(
                content=f"User said: {message[:200]}; I replied: {reply[:200]}",
                tier="observation",
                source="i_did",
                weight=0.1,
                intent="chat-capture",
            )
        except Exception:
            logger.debug("chat capture failed", exc_info=True)

        return reply

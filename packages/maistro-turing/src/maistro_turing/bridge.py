"""Bridge adapters: connect Turing's needs to maistro-core subsystems.

Turing needs:
1. Memory — episodic store for self-model, working memory, conversations
2. Security — warden scans on all self-writes and tool results
3. Classifier — for understanding chat messages
4. Router/Providers — pool-based model access (PoolConfig, not ModelConfig)

Each bridge wraps a maistro-core protocol implementation and exposes
the interface Turing expects.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    # maistro-core does not ship a py.typed marker yet, so these imports are
    # untyped from mypy's perspective. Owned by another package.
    from maistro.protocols.classifier import IntentClassifier
    from maistro.protocols.llm import LLMClient
    from maistro.protocols.memory import (
        EpisodicStore,
        LearningStore,
    )

logger = logging.getLogger("maistro_turing.bridge")


# ---------------------------------------------------------------- protocols ---
# Turing's internal interfaces — the bridge adapts maistro-core to these.


@runtime_checkable
class TuringMemory(Protocol):
    """What Turing needs from a memory system."""

    async def store_episode(
        self,
        *,
        content: str,
        tier: str,
        source: str = "i_did",
        weight: float = 0.3,
        intent: str = "",
        context: dict[str, Any] | None = None,
    ) -> str: ...

    async def retrieve_episodes(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]: ...

    async def store_learning(
        self,
        *,
        category: str,
        trigger_keys: list[str],
        learning: str,
        tool_name: str = "",
    ) -> int: ...


@runtime_checkable
class TuringSecurity(Protocol):
    """What Turing needs from the security system."""

    async def scan_self_write(self, content: str, *, kind: str = "") -> dict[str, Any]: ...

    async def scan_tool_result(self, content: str, *, tool_name: str = "") -> dict[str, Any]: ...


@runtime_checkable
class TuringProvider(Protocol):
    """What Turing needs from the provider system.

    Turing uses pools (PoolConfig with window/quota) NOT ModelConfig/RouterEngine.
    The bridge translates between the two abstractions.
    """

    def complete(self, prompt: str, *, max_tokens: int | None = None, pool: str = "") -> str: ...

    async def acomplete(
        self, prompt: str, *, max_tokens: int | None = None, pool: str = ""
    ) -> str: ...


@dataclass(frozen=True)
class PoolConfig:
    """A single provider pool with its own quota window and quality weight.

    Translates Turing's pool concept to maistro-core's model selection.
    """

    pool_name: str
    model: str
    window_kind: str
    window_duration_seconds: int
    tokens_allowed: int
    quality_weight: float = 1.0
    role: str = "chat"


@runtime_checkable
class TuringClassifier(Protocol):
    """What Turing needs from the intent classifier."""

    async def classify_message(
        self,
        message: str,
        *,
        task_types: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


# ------------------------------------------------------------ bridges --------


class TuringMemoryBridge:
    """Wraps maistro-core EpisodicStore + LearningStore for Turing's memory needs."""

    def __init__(
        self,
        episodic_store: EpisodicStore | None = None,
        learning_store: LearningStore | None = None,
    ) -> None:
        self._episodic = episodic_store
        self._learnings = learning_store

    async def store_episode(
        self,
        *,
        content: str,
        tier: str,
        source: str = "i_did",
        weight: float = 0.3,
        intent: str = "",
        context: dict[str, Any] | None = None,
    ) -> str:
        if self._episodic is None:
            logger.warning("no episodic store configured; memory write dropped")
            return ""
        from maistro.types.memory import (
            EpisodicMemory,
            MemoryTier,
        )

        mem = EpisodicMemory(
            content=content,
            tier=MemoryTier(tier),
            source=source,
            weight=weight,
            context=context or {},
        )
        return str(await self._episodic.store(mem))

    async def retrieve_episodes(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if self._episodic is None:
            return []
        results = await self._episodic.retrieve(query, limit=limit)
        return [
            {
                "memory_id": m.memory_id,
                "content": m.content,
                "tier": m.tier.value,
                "weight": m.weight,
                "created_at": m.created_at.isoformat(),
            }
            for m in results
        ]

    async def store_learning(
        self,
        *,
        category: str,
        trigger_keys: list[str],
        learning: str,
        tool_name: str = "",
    ) -> int:
        if self._learnings is None:
            logger.warning("no learning store configured; learning write dropped")
            return 0
        from maistro.types.memory import Learning

        lrn = Learning(
            category=category,
            trigger_keys=trigger_keys,
            learning=learning,
            tool_name=tool_name,
        )
        return int(await self._learnings.store(lrn))


class TuringSecurityBridge:
    """Wraps maistro-core warden for Turing's self-write and tool-result scans."""

    def __init__(self, warden: Any = None) -> None:
        self._warden = warden

    async def scan_self_write(self, content: str, *, kind: str = "") -> dict[str, Any]:
        if self._warden is None:
            return {"verdict": "allowed", "flags": []}
        try:
            result = self._warden.scan(content, "user_input")
            if inspect.isawaitable(result):
                result = await result
            return {
                "verdict": "blocked" if not result.clean else "allowed",
                "flags": list(getattr(result, "flags", [])),
            }
        except Exception:
            logger.exception("warden scan failed for self-write")
            return {"verdict": "allowed", "flags": []}

    async def scan_tool_result(self, content: str, *, tool_name: str = "") -> dict[str, Any]:
        if self._warden is None:
            return {"verdict": "allowed", "flags": []}
        try:
            result = self._warden.scan(content, "tool_result")
            if inspect.isawaitable(result):
                result = await result
            return {
                "verdict": "blocked" if not result.clean else "allowed",
                "flags": list(getattr(result, "flags", [])),
            }
        except Exception:
            logger.exception("warden scan failed for tool result")
            return {"verdict": "allowed", "flags": []}


class TuringProviderBridge:
    """Wraps maistro-core's LLMClient for Turing's pool-based model access.

    Turing uses PoolConfig (model + window/quota) NOT ModelConfig/RouterEngine.
    The bridge maps pool_name → model string and delegates to LLMClient.complete().
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        pools: list[PoolConfig] | None = None,
    ) -> None:
        self._client = llm_client
        self._pools: dict[str, PoolConfig] = {}
        if pools:
            for p in pools:
                self._pools[p.pool_name] = p
        self._default_pool = pools[0] if pools else None

    def register_pool(self, pool: PoolConfig) -> None:
        self._pools[pool.pool_name] = pool
        if self._default_pool is None:
            self._default_pool = pool

    def complete(self, prompt: str, *, max_tokens: int | None = None, pool: str = "") -> str:
        if self._client is None:
            raise RuntimeError("no LLM client configured")
        pool_cfg = self._pools.get(pool) if pool else self._default_pool
        model = pool_cfg.model if pool_cfg else ""
        import asyncio

        coro = self._client.complete(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            max_tokens=max_tokens,
        )
        try:
            asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                result = future.result()
        except RuntimeError:
            result = asyncio.run(coro)
        choices = result.get("choices", [])
        if choices:
            return str(choices[0].get("message", {}).get("content", ""))
        return ""

    async def acomplete(self, prompt: str, *, max_tokens: int | None = None, pool: str = "") -> str:
        if self._client is None:
            raise RuntimeError("no LLM client configured")
        pool_cfg = self._pools.get(pool) if pool else self._default_pool
        model = pool_cfg.model if pool_cfg else ""
        result = await self._client.complete(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            max_tokens=max_tokens,
        )
        choices = result.get("choices", [])
        if choices:
            return str(choices[0].get("message", {}).get("content", ""))
        return ""

    def pool_names(self) -> list[str]:
        return list(self._pools.keys())

    def quality_weights(self) -> dict[str, float]:
        return {name: p.quality_weight for name, p in self._pools.items()}


class TuringClassifierBridge:
    """Wraps maistro-core's IntentClassifier for Turing's chat understanding."""

    def __init__(self, classifier: IntentClassifier | None = None) -> None:
        self._classifier = classifier

    async def classify_message(
        self,
        message: str,
        *,
        task_types: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._classifier is None:
            return {"task_type": "general", "complexity": 0.5, "priority": "normal"}
        try:
            intent = await self._classifier.classify(
                messages=[{"role": "user", "content": message}],
                task_types=task_types or {},
            )
            return {
                "task_type": getattr(intent, "task_type", "general"),
                "complexity": getattr(intent, "complexity", 0.5),
                "priority": getattr(intent, "priority", "normal"),
            }
        except Exception:
            logger.exception("classifier failed")
            return {"task_type": "general", "complexity": 0.5, "priority": "normal"}

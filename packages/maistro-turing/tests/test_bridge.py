"""Tests for bridge.py: adapters between Turing and maistro-core subsystems."""

from __future__ import annotations

from typing import Any

import pytest

from maistro_turing.bridge import (
    PoolConfig,
    TuringClassifierBridge,
    TuringMemoryBridge,
    TuringProviderBridge,
    TuringSecurityBridge,
)

# ---------------------------------------------------------------- fakes ------


class FakeEpisodicStore:
    def __init__(self) -> None:
        self.stored: list[Any] = []

    async def store(self, memory: Any) -> str:
        self.stored.append(memory)
        return "mem-1"

    async def retrieve(self, query: str, *, limit: int = 5) -> list[Any]:
        from maistro.types.memory import EpisodicMemory, MemoryTier

        return [
            EpisodicMemory(
                memory_id=f"mem-{i}",
                tier=MemoryTier.OBSERVATION,
                content=f"{query}-{i}",
                weight=0.3,
            )
            for i in range(min(limit, 2))
        ]


class FakeLearningStore:
    def __init__(self) -> None:
        self.stored: list[Any] = []

    async def store(self, learning: Any) -> int:
        self.stored.append(learning)
        return 42


class FakeWardenResult:
    def __init__(self, clean: bool, blocked: bool, flags: list[str]) -> None:
        self.clean = clean
        self.blocked = blocked
        self.flags = flags


class FakeWarden:
    """Quacks like ``Warden.scan(content, boundary) -> WardenVerdict``."""

    def __init__(self, verdict: str = "allowed", flags: list[str] | None = None) -> None:
        self._clean = verdict == "allowed"
        self._blocked = verdict == "blocked"
        self._flags = flags or []
        self.scan_calls: list[tuple[str, str]] = []

    async def scan(self, content: str, boundary: str = "") -> FakeWardenResult:
        self.scan_calls.append((content, boundary))
        return FakeWardenResult(self._clean, self._blocked, self._flags)


class RaisingWarden:
    async def scan(self, content: str, boundary: str = "") -> FakeWardenResult:
        raise RuntimeError("warden exploded")


class FakeLLMClient:
    def __init__(self, content: str = "hello") -> None:
        self._content = content
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self, messages: list[dict[str, Any]], model: str = "", max_tokens: int | None = None
    ) -> dict[str, Any]:
        self.calls.append({"messages": messages, "model": model, "max_tokens": max_tokens})
        return {"choices": [{"message": {"content": self._content}}]}


class EmptyChoicesLLMClient:
    async def complete(
        self, messages: list[dict[str, Any]], model: str = "", max_tokens: int | None = None
    ) -> dict[str, Any]:
        return {"choices": []}


class FakeIntent:
    def __init__(self, task_type: str, complexity: float, priority: str) -> None:
        self.task_type = task_type
        self.complexity = complexity
        self.priority = priority


class FakeClassifier:
    def __init__(self, intent: FakeIntent) -> None:
        self._intent = intent

    async def classify(
        self, messages: list[dict[str, Any]], task_types: dict[str, Any]
    ) -> FakeIntent:
        return self._intent


class RaisingClassifier:
    async def classify(
        self, messages: list[dict[str, Any]], task_types: dict[str, Any]
    ) -> FakeIntent:
        raise RuntimeError("classifier exploded")


# --------------------------------------------------------- TuringMemoryBridge


class TestTuringMemoryBridge:
    async def test_store_episode_with_no_store_returns_empty_string(self) -> None:
        bridge = TuringMemoryBridge()
        result = await bridge.store_episode(content="x", tier="observation")
        assert result == ""

    async def test_store_episode_delegates_to_episodic_store(self) -> None:
        store = FakeEpisodicStore()
        bridge = TuringMemoryBridge(episodic_store=store)
        result = await bridge.store_episode(
            content="I did a thing",
            tier="observation",
            source="i_did",
            weight=0.4,
            intent="testing",
            context={"k": "v"},
        )
        assert result == "mem-1"
        assert len(store.stored) == 1
        mem = store.stored[0]
        assert mem.content == "I did a thing"
        assert mem.weight == 0.4
        assert mem.context == {"k": "v"}

    async def test_retrieve_episodes_with_no_store_returns_empty_list(self) -> None:
        bridge = TuringMemoryBridge()
        result = await bridge.retrieve_episodes("query")
        assert result == []

    async def test_retrieve_episodes_delegates_and_shapes_output(self) -> None:
        store = FakeEpisodicStore()
        bridge = TuringMemoryBridge(episodic_store=store)
        result = await bridge.retrieve_episodes("query", limit=2)
        assert len(result) == 2
        assert result[0]["memory_id"] == "mem-0"
        assert result[0]["content"] == "query-0"
        assert result[0]["tier"] == "observation"
        assert result[0]["weight"] == 0.3
        assert isinstance(result[0]["created_at"], str)

    async def test_store_learning_with_no_store_returns_zero(self) -> None:
        bridge = TuringMemoryBridge()
        result = await bridge.store_learning(
            category="general", trigger_keys=["k"], learning="learned"
        )
        assert result == 0

    async def test_store_learning_delegates_to_learning_store(self) -> None:
        store = FakeLearningStore()
        bridge = TuringMemoryBridge(learning_store=store)
        result = await bridge.store_learning(
            category="general",
            trigger_keys=["a", "b"],
            learning="learned something",
            tool_name="grep",
        )
        assert result == 42
        assert len(store.stored) == 1
        lrn = store.stored[0]
        assert lrn.category == "general"
        assert lrn.trigger_keys == ["a", "b"]
        assert lrn.learning == "learned something"
        assert lrn.tool_name == "grep"


# ------------------------------------------------------- TuringSecurityBridge


class TestTuringSecurityBridge:
    async def test_scan_self_write_with_no_warden_allows(self) -> None:
        bridge = TuringSecurityBridge()
        result = await bridge.scan_self_write("content", kind="blog")
        assert result == {"verdict": "allowed", "flags": []}

    async def test_scan_self_write_delegates_to_warden(self) -> None:
        warden = FakeWarden(verdict="blocked", flags=["pii"])
        bridge = TuringSecurityBridge(warden=warden)
        result = await bridge.scan_self_write("content", kind="blog")
        assert result == {"verdict": "blocked", "flags": ["pii"]}
        assert warden.scan_calls == [("content", "user_input")]

    async def test_scan_self_write_swallows_warden_exception(self) -> None:
        bridge = TuringSecurityBridge(warden=RaisingWarden())
        result = await bridge.scan_self_write("content", kind="blog")
        assert result == {"verdict": "allowed", "flags": []}

    async def test_scan_tool_result_with_no_warden_allows(self) -> None:
        bridge = TuringSecurityBridge()
        result = await bridge.scan_tool_result("content", tool_name="grep")
        assert result == {"verdict": "allowed", "flags": []}

    async def test_scan_tool_result_delegates_to_warden(self) -> None:
        warden = FakeWarden(verdict="allowed", flags=[])
        bridge = TuringSecurityBridge(warden=warden)
        result = await bridge.scan_tool_result("content", tool_name="grep")
        assert result == {"verdict": "allowed", "flags": []}
        assert warden.scan_calls == [("content", "tool_result")]

    async def test_scan_tool_result_blocks_on_unclean_verdict(self) -> None:
        """Real ``Warden.scan`` returns clean=False/blocked=False for a single-flag
        (suspicious-but-not-hard-blocked) verdict; the bridge must still report it
        as blocked rather than assuming allowed."""
        warden = FakeWarden(verdict="suspicious", flags=["injection"])
        bridge = TuringSecurityBridge(warden=warden)
        result = await bridge.scan_tool_result("content", tool_name="grep")
        assert result == {"verdict": "blocked", "flags": ["injection"]}

    async def test_scan_tool_result_swallows_warden_exception(self) -> None:
        bridge = TuringSecurityBridge(warden=RaisingWarden())
        result = await bridge.scan_tool_result("content", tool_name="grep")
        assert result == {"verdict": "allowed", "flags": []}


# ------------------------------------------------------- TuringProviderBridge


class TestTuringProviderBridge:
    def test_complete_raises_without_client(self) -> None:
        bridge = TuringProviderBridge()
        with pytest.raises(RuntimeError, match="no LLM client configured"):
            bridge.complete("prompt")

    async def test_acomplete_raises_without_client(self) -> None:
        bridge = TuringProviderBridge()
        with pytest.raises(RuntimeError, match="no LLM client configured"):
            await bridge.acomplete("prompt")

    async def test_acomplete_uses_default_pool_when_no_pool_named(self) -> None:
        client = FakeLLMClient(content="reply text")
        pool = PoolConfig(
            pool_name="primary",
            model="gpt-test",
            window_kind="rolling",
            window_duration_seconds=60,
            tokens_allowed=1000,
        )
        bridge = TuringProviderBridge(llm_client=client, pools=[pool])
        result = await bridge.acomplete("hello", max_tokens=50)
        assert result == "reply text"
        assert client.calls[0]["model"] == "gpt-test"
        assert client.calls[0]["max_tokens"] == 50

    async def test_acomplete_selects_named_pool(self) -> None:
        client = FakeLLMClient(content="reply")
        pool_a = PoolConfig(
            pool_name="a",
            model="model-a",
            window_kind="rolling",
            window_duration_seconds=60,
            tokens_allowed=100,
        )
        pool_b = PoolConfig(
            pool_name="b",
            model="model-b",
            window_kind="rolling",
            window_duration_seconds=60,
            tokens_allowed=100,
        )
        bridge = TuringProviderBridge(llm_client=client, pools=[pool_a, pool_b])
        await bridge.acomplete("hi", pool="b")
        assert client.calls[0]["model"] == "model-b"

    async def test_acomplete_unknown_pool_name_falls_back_to_empty_model(self) -> None:
        client = FakeLLMClient(content="reply")
        pool_a = PoolConfig(
            pool_name="a",
            model="model-a",
            window_kind="rolling",
            window_duration_seconds=60,
            tokens_allowed=100,
        )
        bridge = TuringProviderBridge(llm_client=client, pools=[pool_a])
        await bridge.acomplete("hi", pool="nonexistent")
        # pool name not found -> pools.get returns None -> model falls back to ""
        assert client.calls[0]["model"] == ""

    async def test_acomplete_empty_choices_returns_empty_string(self) -> None:
        bridge = TuringProviderBridge(llm_client=EmptyChoicesLLMClient())
        result = await bridge.acomplete("hi")
        assert result == ""

    def test_complete_runs_coro_when_no_running_loop(self) -> None:
        client = FakeLLMClient(content="sync reply")
        bridge = TuringProviderBridge(llm_client=client)
        result = bridge.complete("prompt", max_tokens=10)
        assert result == "sync reply"

    def test_complete_empty_choices_returns_empty_string(self) -> None:
        bridge = TuringProviderBridge(llm_client=EmptyChoicesLLMClient())
        result = bridge.complete("prompt")
        assert result == ""

    async def test_complete_runs_in_thread_pool_when_loop_is_running(self) -> None:
        # complete() is sync, but when called from inside a running event loop
        # (e.g. from sync code invoked by an async caller) it must offload the
        # coroutine to a thread pool rather than raising "asyncio.run() cannot
        # be called from a running event loop". This test runs inside pytest's
        # event loop (asyncio_mode=auto), so calling complete() directly here
        # exercises the get_running_loop()-succeeds branch.
        client = FakeLLMClient(content="threaded reply")
        bridge = TuringProviderBridge(llm_client=client)
        result = bridge.complete("prompt", max_tokens=5)
        assert result == "threaded reply"
        assert client.calls[0]["max_tokens"] == 5

    def test_register_pool_adds_and_sets_default_when_empty(self) -> None:
        bridge = TuringProviderBridge()
        assert bridge.pool_names() == []
        pool = PoolConfig(
            pool_name="p1",
            model="m1",
            window_kind="rolling",
            window_duration_seconds=60,
            tokens_allowed=100,
            quality_weight=0.8,
        )
        bridge.register_pool(pool)
        assert bridge.pool_names() == ["p1"]
        assert bridge.quality_weights() == {"p1": 0.8}

    def test_register_pool_does_not_override_existing_default(self) -> None:
        pool_a = PoolConfig(
            pool_name="a",
            model="model-a",
            window_kind="rolling",
            window_duration_seconds=60,
            tokens_allowed=100,
        )
        bridge = TuringProviderBridge(pools=[pool_a])
        client = FakeLLMClient(content="from default")
        bridge._client = client  # type: ignore[attr-defined]
        pool_b = PoolConfig(
            pool_name="b",
            model="model-b",
            window_kind="rolling",
            window_duration_seconds=60,
            tokens_allowed=100,
        )
        bridge.register_pool(pool_b)
        result = bridge.complete("prompt")
        assert result == "from default"
        assert client.calls[0]["model"] == "model-a"

    def test_quality_weights_multiple_pools(self) -> None:
        pool_a = PoolConfig(
            pool_name="a",
            model="model-a",
            window_kind="rolling",
            window_duration_seconds=60,
            tokens_allowed=100,
            quality_weight=1.5,
        )
        pool_b = PoolConfig(
            pool_name="b",
            model="model-b",
            window_kind="rolling",
            window_duration_seconds=60,
            tokens_allowed=100,
            quality_weight=0.5,
        )
        bridge = TuringProviderBridge(pools=[pool_a, pool_b])
        assert bridge.quality_weights() == {"a": 1.5, "b": 0.5}


# --------------------------------------------------- TuringClassifierBridge


class TestTuringClassifierBridge:
    async def test_classify_message_with_no_classifier_returns_default(self) -> None:
        bridge = TuringClassifierBridge()
        result = await bridge.classify_message("hello")
        assert result == {"task_type": "general", "complexity": 0.5, "priority": "normal"}

    async def test_classify_message_delegates_to_classifier(self) -> None:
        intent = FakeIntent(task_type="code_review", complexity=0.9, priority="high")
        bridge = TuringClassifierBridge(classifier=FakeClassifier(intent))
        result = await bridge.classify_message("review this", task_types={"code_review": {}})
        assert result == {"task_type": "code_review", "complexity": 0.9, "priority": "high"}

    async def test_classify_message_swallows_classifier_exception(self) -> None:
        bridge = TuringClassifierBridge(classifier=RaisingClassifier())
        result = await bridge.classify_message("hello")
        assert result == {"task_type": "general", "complexity": 0.5, "priority": "normal"}

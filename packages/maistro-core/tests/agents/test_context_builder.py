"""Tests for ContextBuilder: soul + learnings + episodic assembly with token budgeting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from maistro.agents.context_builder import (
    ContextBuilder,
    _estimate_tokens,
    inject_cache_breakpoints,
)
from maistro.types.agent import AgentIdentity


def test_estimate_tokens_divides_chars_by_four() -> None:
    assert _estimate_tokens("x" * 40) == 10


class _FakePromptManager:
    def __init__(self, prompts: dict[str, str] | None = None) -> None:
        self._prompts = prompts or {}
        self.calls: list[str] = []

    async def get(self, name: str) -> str:
        self.calls.append(name)
        return self._prompts.get(name, "")


@dataclass
class _Learning:
    learning: str
    id: int | None = None
    rca_category: str | None = None


@dataclass
class _FakeLearningStore:
    promoted: list[_Learning] = field(default_factory=list)
    relevant: list[_Learning] = field(default_factory=list)
    promoted_calls: list[dict[str, Any]] = field(default_factory=list)
    relevant_calls: list[dict[str, Any]] = field(default_factory=list)

    async def get_promoted(self, *, org_id: str) -> list[_Learning]:
        self.promoted_calls.append({"org_id": org_id})
        return self.promoted

    async def find_relevant(self, text: str, *, agent_id: str, org_id: str) -> list[_Learning]:
        self.relevant_calls.append({"text": text, "agent_id": agent_id, "org_id": org_id})
        return self.relevant


def _identity(**overrides: Any) -> AgentIdentity:
    base: dict[str, Any] = {"name": "tester"}
    base.update(overrides)
    return AgentIdentity(**base)


@pytest.fixture
def builder() -> ContextBuilder:
    return ContextBuilder()


async def test_build_with_no_soul_no_learnings_returns_messages_unchanged(
    builder: ContextBuilder,
) -> None:
    messages = [{"role": "user", "content": "hi"}]
    pm = _FakePromptManager()

    result_messages, kept_ids = await builder.build(messages, _identity(), prompt_manager=pm)

    assert result_messages == messages
    assert kept_ids == []


async def test_build_with_soul_prepends_system_message(builder: ContextBuilder) -> None:
    messages = [{"role": "user", "content": "hi"}]
    pm = _FakePromptManager({"agent.tester.soul": "You are tester."})

    result_messages, _ = await builder.build(messages, _identity(), prompt_manager=pm)

    assert result_messages[0] == {"role": "system", "content": "You are tester."}
    assert result_messages[1] == messages[0]


async def test_build_uses_custom_soul_prompt_name(builder: ContextBuilder) -> None:
    messages = [{"role": "user", "content": "hi"}]
    pm = _FakePromptManager({"custom.soul": "Custom soul."})

    result_messages, _ = await builder.build(
        messages, _identity(soul_prompt_name="custom.soul"), prompt_manager=pm
    )

    assert result_messages[0]["content"] == "Custom soul."


async def test_build_soul_exceeding_budget_logs_warning_and_continues(
    builder: ContextBuilder, caplog: pytest.LogCaptureFixture
) -> None:
    messages = [{"role": "user", "content": "hi"}]
    pm = _FakePromptManager({"agent.tester.soul": "x" * 100})

    with caplog.at_level("WARNING"):
        result_messages, _ = await builder.build(
            messages, _identity(), prompt_manager=pm, system_token_budget=1
        )

    assert "exceeds token budget" in caplog.text
    assert result_messages[0]["content"] == "x" * 100


async def test_build_merges_into_existing_system_message(builder: ContextBuilder) -> None:
    messages = [
        {"role": "system", "content": "existing"},
        {"role": "user", "content": "hi"},
    ]
    pm = _FakePromptManager({"agent.tester.soul": "soul text"})

    result_messages, _ = await builder.build(messages, _identity(), prompt_manager=pm)

    assert result_messages[0] == {"role": "system", "content": "soul text\n\nexisting"}
    assert len(result_messages) == 2


async def test_build_promoted_learnings_included_when_enabled(builder: ContextBuilder) -> None:
    messages = [{"role": "user", "content": "hi"}]
    pm = _FakePromptManager()
    store = _FakeLearningStore(promoted=[_Learning(learning="be nice", id=1, rca_category="tone")])

    result_messages, kept_ids = await builder.build(
        messages,
        _identity(memory_config={"learnings": True}),
        prompt_manager=pm,
        learning_store=store,
        org_id="org-1",
    )

    assert kept_ids == [1]
    content = result_messages[0]["content"]
    assert '<maistro:corrections type="promoted">' in content
    assert "[tone] be nice" in content
    assert store.promoted_calls == [{"org_id": "org-1"}]


async def test_build_skips_promoted_learnings_when_memory_config_disabled(
    builder: ContextBuilder,
) -> None:
    messages = [{"role": "user", "content": "hi"}]
    pm = _FakePromptManager()
    store = _FakeLearningStore(promoted=[_Learning(learning="be nice", id=1)])

    result_messages, kept_ids = await builder.build(
        messages, _identity(), prompt_manager=pm, learning_store=store
    )

    assert result_messages == messages
    assert kept_ids == []
    assert store.promoted_calls == []


async def test_build_matched_learnings_use_latest_user_message(builder: ContextBuilder) -> None:
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "second"},
    ]
    pm = _FakePromptManager()
    store = _FakeLearningStore(relevant=[_Learning(learning="matched fact", id=2)])

    result_messages, kept_ids = await builder.build(
        messages,
        _identity(memory_config={"learnings": True}),
        prompt_manager=pm,
        learning_store=store,
        agent_id="agent-1",
        org_id="org-1",
    )

    assert kept_ids == [2]
    assert store.relevant_calls == [{"text": "second", "agent_id": "agent-1", "org_id": "org-1"}]
    content = result_messages[0]["content"]
    assert '<maistro:corrections type="matched">' in content
    assert "- matched fact" in content


async def test_build_no_matched_learnings_when_no_user_message(builder: ContextBuilder) -> None:
    messages = [{"role": "assistant", "content": "hi"}]
    pm = _FakePromptManager()
    store = _FakeLearningStore(relevant=[_Learning(learning="matched fact", id=2)])

    result_messages, kept_ids = await builder.build(
        messages,
        _identity(memory_config={"learnings": True}),
        prompt_manager=pm,
        learning_store=store,
    )

    assert result_messages == messages
    assert kept_ids == []
    assert store.relevant_calls == []


async def test_build_drops_learnings_exceeding_budget(builder: ContextBuilder) -> None:
    messages = [{"role": "user", "content": "hi"}]
    pm = _FakePromptManager()
    store = _FakeLearningStore(
        promoted=[
            _Learning(learning="a" * 10, id=1),
            _Learning(learning="b" * 10, id=2),
        ]
    )

    result_messages, kept_ids = await builder.build(
        messages,
        _identity(memory_config={"learnings": True}),
        prompt_manager=pm,
        learning_store=store,
        system_token_budget=20,
    )

    assert kept_ids == [1]
    content = result_messages[0]["content"]
    assert "aaaaaaaaaa" in content
    assert "bbbbbbbbbb" not in content


async def test_build_learnings_none_fit_budget_renders_no_block(builder: ContextBuilder) -> None:
    messages = [{"role": "user", "content": "hi"}]
    pm = _FakePromptManager()
    store = _FakeLearningStore(promoted=[_Learning(learning="a" * 100, id=1)])

    result_messages, kept_ids = await builder.build(
        messages,
        _identity(memory_config={"learnings": True}),
        prompt_manager=pm,
        learning_store=store,
        system_token_budget=10,
    )

    assert result_messages == messages
    assert kept_ids == []


async def test_build_no_learnings_at_all_skips_block(builder: ContextBuilder) -> None:
    messages = [{"role": "user", "content": "hi"}]
    pm = _FakePromptManager()
    store = _FakeLearningStore(promoted=[])

    result_messages, kept_ids = await builder.build(
        messages,
        _identity(memory_config={"learnings": True}),
        prompt_manager=pm,
        learning_store=store,
    )

    assert result_messages == messages
    assert kept_ids == []


async def test_build_zero_remaining_budget_skips_matched_learnings(
    builder: ContextBuilder,
) -> None:
    messages = [{"role": "user", "content": "hi"}]
    pm = _FakePromptManager({"agent.tester.soul": "x" * 40})
    store = _FakeLearningStore(relevant=[_Learning(learning="matched", id=3)])

    result_messages, kept_ids = await builder.build(
        messages,
        _identity(memory_config={"learnings": True}),
        prompt_manager=pm,
        learning_store=store,
        system_token_budget=10,
    )

    assert kept_ids == []
    assert store.relevant_calls == []
    assert result_messages[0]["content"] == "x" * 40


async def test_build_enable_cache_breakpoints_injects_blocks(builder: ContextBuilder) -> None:
    messages = [{"role": "user", "content": "hi"}]
    pm = _FakePromptManager({"agent.tester.soul": "soul text"})

    result_messages, _ = await builder.build(
        messages, _identity(), prompt_manager=pm, enable_cache_breakpoints=True
    )

    content = result_messages[0]["content"]
    assert isinstance(content, list)
    assert content[0]["cache_control"] == {"type": "ephemeral"}


def test_inject_cache_breakpoints_no_messages_returns_empty() -> None:
    assert inject_cache_breakpoints([]) == []


def test_inject_cache_breakpoints_no_system_message_returns_unchanged() -> None:
    messages = [{"role": "user", "content": "hi"}]
    assert inject_cache_breakpoints(messages) == messages


def test_inject_cache_breakpoints_splits_on_learnings_boundary() -> None:
    content = 'stable part\n\n<maistro:corrections type="promoted">stuff</maistro:corrections>'
    messages = [{"role": "system", "content": content}, {"role": "user", "content": "hi"}]

    result = inject_cache_breakpoints(messages)

    blocks = result[0]["content"]
    assert len(blocks) == 2
    assert blocks[0]["text"] == "stable part"
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[1]["text"].startswith("<maistro:corrections")
    assert "cache_control" not in blocks[1]


def test_inject_cache_breakpoints_no_boundary_marks_whole_text() -> None:
    messages = [{"role": "system", "content": "just soul text"}, {"role": "user", "content": "hi"}]

    result = inject_cache_breakpoints(messages)

    blocks = result[0]["content"]
    assert len(blocks) == 1
    assert blocks[0]["text"] == "just soul text"
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_inject_cache_breakpoints_boundary_at_start_marks_whole_text() -> None:
    content = '<maistro:corrections type="promoted">stuff</maistro:corrections>'
    messages = [{"role": "system", "content": content}, {"role": "user", "content": "hi"}]

    result = inject_cache_breakpoints(messages)

    blocks = result[0]["content"]
    assert len(blocks) == 1
    assert blocks[0]["text"] == content


def test_inject_cache_breakpoints_list_content_marks_first_block() -> None:
    messages = [
        {
            "role": "system",
            "content": [{"type": "text", "text": "part1"}, {"type": "text", "text": "part2"}],
        },
        {"role": "user", "content": "hi"},
    ]

    result = inject_cache_breakpoints(messages)

    blocks = result[0]["content"]
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in blocks[1]


def test_inject_cache_breakpoints_list_content_preserves_existing_cache_control() -> None:
    messages = [
        {
            "role": "system",
            "content": [
                {"type": "text", "text": "part1", "cache_control": {"type": "persistent"}},
            ],
        },
        {"role": "user", "content": "hi"},
    ]

    result = inject_cache_breakpoints(messages)

    blocks = result[0]["content"]
    assert blocks[0]["cache_control"] == {"type": "persistent"}

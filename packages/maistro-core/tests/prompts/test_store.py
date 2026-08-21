"""Tests for maistro.prompts.store — InMemoryPromptManager."""

from __future__ import annotations

import pytest

from maistro.prompts.store import InMemoryPromptManager


class TestScopedName:
    def test_agent_prefix_is_shared(self) -> None:
        assert InMemoryPromptManager._scoped_name("agent.foo", "u1") == "agent.foo"

    def test_system_prefix_is_shared(self) -> None:
        assert InMemoryPromptManager._scoped_name("system.foo", "u1") == "system.foo"

    def test_no_user_id_is_unscoped(self) -> None:
        assert InMemoryPromptManager._scoped_name("custom", "") == "custom"

    def test_user_scoped_name(self) -> None:
        assert InMemoryPromptManager._scoped_name("custom", "u1") == "u1:custom"


class TestUpsertAndGet:
    @pytest.mark.asyncio
    async def test_first_upsert_sets_production_and_latest_labels(self) -> None:
        manager = InMemoryPromptManager()
        await manager.upsert("p", "v1")
        content = await manager.get("p")
        assert content == "v1"
        content_latest = await manager.get("p", label="latest")
        assert content_latest == "v1"

    @pytest.mark.asyncio
    async def test_explicit_label_applied(self) -> None:
        manager = InMemoryPromptManager()
        await manager.upsert("p", "v1", label="staging")
        content = await manager.get("p", label="staging")
        assert content == "v1"

    @pytest.mark.asyncio
    async def test_second_upsert_does_not_overwrite_production_label(self) -> None:
        manager = InMemoryPromptManager()
        await manager.upsert("p", "v1")
        await manager.upsert("p", "v2")
        content_prod = await manager.get("p", label="production")
        content_latest = await manager.get("p", label="latest")
        assert content_prod == "v1"
        assert content_latest == "v2"

    @pytest.mark.asyncio
    async def test_get_with_config_returns_config(self) -> None:
        manager = InMemoryPromptManager()
        await manager.upsert("p", "v1", config={"temp": 0.5})
        content, config = await manager.get_with_config("p")
        assert content == "v1"
        assert config == {"temp": 0.5}

    @pytest.mark.asyncio
    async def test_get_with_config_no_config_defaults_to_empty_dict(self) -> None:
        manager = InMemoryPromptManager()
        await manager.upsert("p", "v1")
        _, config = await manager.get_with_config("p")
        assert config == {}

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_empty(self) -> None:
        manager = InMemoryPromptManager()
        content, config = await manager.get_with_config("missing")
        assert content == ""
        assert config == {}

    @pytest.mark.asyncio
    async def test_get_missing_label_falls_back_to_latest_version(self) -> None:
        manager = InMemoryPromptManager()
        await manager.upsert("p", "v1")
        content = await manager.get("p", label="nope")
        assert content == "v1"

    @pytest.mark.asyncio
    async def test_get_with_label_pointing_to_missing_version_returns_empty(self) -> None:
        manager = InMemoryPromptManager()
        await manager.upsert("p", "v1")
        manager._labels["p"]["dangling"] = 999
        content, config = await manager.get_with_config("p", label="dangling")
        assert content == ""
        assert config == {}

    @pytest.mark.asyncio
    async def test_user_scoped_prompt_isolated_from_system(self) -> None:
        manager = InMemoryPromptManager()
        await manager.upsert("custom", "shared-default")
        await manager.upsert("custom", "user-specific", user_id="u1")
        shared = await manager.get("custom")
        scoped = await manager.get("custom", user_id="u1")
        assert shared == "shared-default"
        assert scoped == "user-specific"

    @pytest.mark.asyncio
    async def test_agent_prompt_ignores_user_id_scoping(self) -> None:
        manager = InMemoryPromptManager()
        await manager.upsert("agent.foo", "v1", user_id="u1")
        content = await manager.get("agent.foo")
        assert content == "v1"

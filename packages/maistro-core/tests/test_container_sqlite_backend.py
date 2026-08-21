"""Container wires a real SQLite backend end-to-end when configured (Phase 3.5)."""

from __future__ import annotations

from maistro.container import create_container
from maistro.types.config import AgentConfig


async def test_create_container_selects_sqlite_backend_when_configured() -> None:
    container = await create_container(
        AgentConfig(router_api_key="test-key", database_url="sqlite://")
    )
    assert container.db_pool is not None


async def test_create_container_defaults_to_in_memory_backend() -> None:
    container = await create_container(AgentConfig(router_api_key="test-key"))
    assert container.db_pool is None


async def test_sqlite_backend_quota_tracker_write_then_read_back() -> None:
    container = await create_container(
        AgentConfig(router_api_key="test-key", database_url="sqlite://")
    )
    totals = await container.quota_tracker.record_usage("openai", "2026-06", 100, 50)
    assert totals["input_tokens"] == 100
    assert totals["output_tokens"] == 50

    all_usage = await container.quota_tracker.get_all_usage()
    assert len(all_usage) == 1
    assert all_usage[0]["provider"] == "openai"


async def test_sqlite_backend_session_store_write_then_read_back() -> None:
    container = await create_container(
        AgentConfig(router_api_key="test-key", database_url="sqlite://")
    )
    await container.session_store.append_messages(
        "session-1", [{"role": "user", "content": "hello"}]
    )
    history = await container.session_store.get_history("session-1")
    assert history == [{"role": "user", "content": "hello"}]

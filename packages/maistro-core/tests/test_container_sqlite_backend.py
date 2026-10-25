"""Container wires a real SQLite backend end-to-end when configured (Phase 3.5)."""

from __future__ import annotations

import time

from maistro.container import create_container
from maistro.types.config import AgentConfig


async def test_create_container_selects_sqlite_backend_when_configured() -> None:
    container = await create_container(
        AgentConfig(router_api_key="test-key", database_url="sqlite://")
    )
    assert container.db_pool is not None
    assert type(container.prompt_manager).__name__ == "SqlitePromptManager"
    assert type(container.audit_log).__name__ == "SqliteAuditLog"


async def test_create_container_defaults_to_in_memory_backend() -> None:
    container = await create_container(AgentConfig(router_api_key="test-key"))
    assert container.db_pool is None
    assert type(container.prompt_manager).__name__ == "InMemoryPromptManager"


async def test_sqlite_usage_log_flushes_and_restores_with_container(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'usage.db'}"
    first = await create_container(
        AgentConfig(router_api_key="test-key", database_url=database_url)
    )
    first.usage_log.record("openai:gpt-5", input_tokens=7, output_tokens=5)
    await first.aclose()

    second = await create_container(
        AgentConfig(router_api_key="test-key", database_url=database_url)
    )
    assert second.usage_log.count_since("openai:gpt-5", 60, now=time.time()) == 1.0
    await second.aclose()


async def test_shutdown_flush_failure_does_not_block_aclose(tmp_path) -> None:
    """A failing shutdown flush (#1204) is swallowed, not raised.

    The shutdown flush must never block the rest of the teardown: a snapshot
    that fails (say, a commit whose result was lost) is logged and the
    container still closes. The durable event identity makes the next
    process's retry harmless, so dropping this one flush is safe.
    """

    class _ExplodingSnapshot:
        async def snapshot(self, log: object) -> None:
            raise RuntimeError("commit result lost")

    container = await create_container(
        AgentConfig(
            router_api_key="test-key",
            database_url=f"sqlite:///{tmp_path / 'usage.db'}",
        )
    )
    container.usage_log.record("openai:gpt-5", input_tokens=1, output_tokens=1)
    assert container.usage_log_persistence is not None
    container.usage_log_persistence = _ExplodingSnapshot()

    await container.aclose()  # must not raise

    assert container.closed


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

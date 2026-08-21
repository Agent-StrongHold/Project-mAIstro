"""Tests for shared chat/widget tool-call primitives."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "packages" / "hive-conductor" / "backend")
)

from services.tool_primitives import ToolCallContext, ToolCredentialResolver


class _Store:
    def __init__(self, secrets: dict[tuple[str, str], str]) -> None:
        self.secrets = secrets
        self.calls: list[tuple[str, str]] = []

    def has_secret(self, user_id: str, provider_id: str) -> bool:
        self.calls.append((user_id, provider_id))
        return (user_id, provider_id) in self.secrets

    def use_secret(
        self, user_id: str, provider_id: str, callback: Callable[[str], str | None]
    ) -> str | None:
        return callback(self.secrets[(user_id, provider_id)])


def test_context_from_request_state_prefers_id() -> None:
    context = ToolCallContext.from_request_state({"id": "u-123", "username": "fallback"})

    assert context.user_id == "u-123"


def test_context_from_request_state_falls_back_to_username() -> None:
    context = ToolCallContext.from_request_state({"username": "pm"})

    assert context.user_id == "pm"


def test_context_candidate_user_ids_adds_dev_fallback_once() -> None:
    context = ToolCallContext("u-123")

    assert context.candidate_user_ids(include_dev_fallback=True) == ("u-123", "user")
    assert ToolCallContext("user").candidate_user_ids(include_dev_fallback=True) == ("user",)


def test_resolver_returns_first_provider_secret_for_context_user() -> None:
    store = _Store({("u-123", "jira"): "pat"})
    resolver = ToolCredentialResolver(store)

    secret = resolver.first_secret(ToolCallContext("u-123"), ("missing", "jira"))

    assert secret == "pat"
    assert store.calls == [("u-123", "missing"), ("u-123", "jira")]


def test_resolver_uses_dev_fallback_when_requested() -> None:
    store = _Store({("user", "airtable"): "token"})
    resolver = ToolCredentialResolver(store)

    secret = resolver.first_secret(
        ToolCallContext("u-123"), ("airtable",), include_dev_fallback=True
    )

    assert secret == "token"
    assert store.calls == [("u-123", "airtable"), ("user", "airtable")]


def test_ttl_cache_reuses_copy_until_expiry() -> None:
    import asyncio

    from services.tool_primitives import ToolCallTTLCache

    now = 10.0
    loads = 0
    cache = ToolCallTTLCache(clock=lambda: now)

    async def run() -> None:
        nonlocal loads, now

        async def loader() -> object:
            nonlocal loads
            loads += 1
            return {"records": [{"id": "rec1"}]}

        first = await cache.get_or_load("k", ttl_seconds=5, loader=loader)
        assert first == {"records": [{"id": "rec1"}]}
        assert loads == 1
        assert isinstance(first, dict)
        records = first["records"]
        assert isinstance(records, list)
        records.append({"id": "mutated"})

        second = await cache.get_or_load("k", ttl_seconds=5, loader=loader)
        assert second == {"records": [{"id": "rec1"}]}
        assert loads == 1

        now = 16.0
        third = await cache.get_or_load("k", ttl_seconds=5, loader=loader)
        assert third == {"records": [{"id": "rec1"}]}
        assert loads == 2

    asyncio.run(run())


def test_ttl_cache_coalesces_concurrent_misses() -> None:
    import asyncio

    from services.tool_primitives import ToolCallTTLCache

    loads = 0
    release = asyncio.Event()
    cache = ToolCallTTLCache(clock=lambda: 10.0)

    async def run() -> None:
        nonlocal loads

        async def loader() -> object:
            nonlocal loads
            loads += 1
            await release.wait()
            return {"records": [{"id": "rec1"}]}

        first = asyncio.create_task(cache.get_or_load("k", ttl_seconds=5, loader=loader))
        second = asyncio.create_task(cache.get_or_load("k", ttl_seconds=5, loader=loader))
        await asyncio.sleep(0)
        release.set()

        assert await first == {"records": [{"id": "rec1"}]}
        assert await second == {"records": [{"id": "rec1"}]}
        assert loads == 1

    asyncio.run(run())

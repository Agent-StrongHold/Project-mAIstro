"""Shared tool-call primitives for chat tools and deterministic widgets.

The chat assistant and dashboard widgets both call the same product systems
(Jira, Airtable, credentials, and dashboard data), but they enter through
different transports. This module holds small protocol-level primitives that
keep those transports from duplicating credential lookup and request-context
logic.
"""

from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import Awaitable, Callable, Hashable, Iterable
from dataclasses import dataclass
from typing import Protocol

JIRA_PROVIDER_IDS: tuple[str, ...] = (
    "atlassian_server_jira",
    "jira",
    "atlassian_rovo_mcp",
)
AIRTABLE_PROVIDER_IDS: tuple[str, ...] = ("airtable",)
CONFLUENCE_PROVIDER_IDS: tuple[str, ...] = ("atlassian_server_confluence", "confluence")
DEV_FALLBACK_USER_ID = "user"


class CredentialStore(Protocol):
    """Minimal credential-store protocol used by tool call surfaces."""

    def has_secret(self, user_id: str, provider_id: str) -> bool:
        """Return whether a provider secret exists for the user."""

    def use_secret(
        self,
        user_id: str,
        provider_id: str,
        callback: Callable[[str], str | None],
    ) -> str | None:
        """Use a provider secret inside the credential-store callback."""


@dataclass(frozen=True)
class ToolCallContext:
    """Transport-independent context for a chat or widget tool call."""

    user_id: str

    @classmethod
    def from_request_state(cls, state_user: object) -> ToolCallContext:
        """Build context from FastAPI request state user data."""
        user = state_user if isinstance(state_user, dict) else {}
        return cls(str(user.get("id") or user.get("username") or "dev"))

    def candidate_user_ids(self, *, include_dev_fallback: bool = False) -> tuple[str, ...]:
        """Return user IDs to try for single-user dev fallback aware lookups."""
        if include_dev_fallback and self.user_id != DEV_FALLBACK_USER_ID:
            return (self.user_id, DEV_FALLBACK_USER_ID)
        return (self.user_id,)


def use_secret(store: CredentialStore, user_id: str, provider_id: str) -> str | None:
    """Single allowlisted secret callback for chat and widget tool primitives."""
    try:
        return store.use_secret(user_id, provider_id, lambda s: s)
    except Exception:
        return None


@dataclass(frozen=True)
class ToolCredentialResolver:
    """Shared provider-secret resolver for chat tools and widget routes."""

    store: CredentialStore

    def first_secret(
        self,
        context: ToolCallContext,
        provider_ids: Iterable[str],
        *,
        include_dev_fallback: bool = False,
    ) -> str | None:
        """Return the first matching provider secret for the context."""
        for user_id in context.candidate_user_ids(include_dev_fallback=include_dev_fallback):
            for provider_id in provider_ids:
                try:
                    if self.store.has_secret(user_id, provider_id):
                        secret = use_secret(self.store, user_id, provider_id)
                        if secret:
                            return secret
                except Exception:
                    continue
        return None


@dataclass
class _CacheEntry:
    expires_at: float
    value: object


class ToolCallTTLCache:
    """Async in-memory TTL cache with per-key request coalescing for tool calls."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._entries: dict[Hashable, _CacheEntry] = {}
        self._locks: dict[Hashable, asyncio.Lock] = {}

    def clear(self) -> None:
        """Drop every cached value and in-flight lock."""
        self._entries.clear()
        self._locks.clear()

    async def get_or_load(
        self,
        key: Hashable,
        *,
        ttl_seconds: float,
        loader: Callable[[], Awaitable[object]],
        force_refresh: bool = False,
    ) -> object:
        """Return a cached copy, or coalesce concurrent misses behind one loader."""
        if ttl_seconds <= 0:
            return copy.deepcopy(await loader())

        now = self._clock()
        if not force_refresh:
            entry = self._entries.get(key)
            if entry and entry.expires_at > now:
                return copy.deepcopy(entry.value)

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            now = self._clock()
            if not force_refresh:
                entry = self._entries.get(key)
                if entry and entry.expires_at > now:
                    return copy.deepcopy(entry.value)

            value = await loader()
            self._entries[key] = _CacheEntry(
                expires_at=now + ttl_seconds, value=copy.deepcopy(value)
            )
            return copy.deepcopy(value)

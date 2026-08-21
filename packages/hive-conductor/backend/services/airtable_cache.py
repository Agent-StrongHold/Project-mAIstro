"""TTL-cached Airtable API calls shared by chat tools and widgets."""

from __future__ import annotations

import hashlib
import os
from typing import Any

from maistro.http import shared_client
from services.tool_primitives import ToolCallTTLCache

_AIRTABLE_CACHE = ToolCallTTLCache()


def airtable_cache_ttl_seconds() -> float:
    """Return Airtable cache TTL in seconds, defaulting to one minute."""
    raw = os.environ.get("AIRTABLE_TOOL_CACHE_TTL_SECONDS", "60")
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return 60.0


def clear_airtable_cache() -> None:
    """Clear Airtable cached responses for tests or explicit refresh workflows."""
    _AIRTABLE_CACHE.clear()


def _token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def _params_key(params: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(params.items()))


async def get_airtable_records_json(
    *,
    token: str,
    base_id: str,
    table: str,
    params: dict[str, str],
    force_refresh: bool = False,
    ttl_seconds: float | None = None,
) -> dict[str, Any]:
    """Fetch Airtable records JSON with TTL caching and concurrent miss coalescing."""
    ttl = airtable_cache_ttl_seconds() if ttl_seconds is None else ttl_seconds
    key = ("records", _token_fingerprint(token), base_id, table, _params_key(params))

    async def load() -> object:
        async with shared_client(timeout=15) as client:
            response = await client.get(
                f"https://api.airtable.com/v0/{base_id}/{table}",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            response.raise_for_status()
            return response.json()

    value = await _AIRTABLE_CACHE.get_or_load(
        key, ttl_seconds=ttl, loader=load, force_refresh=force_refresh
    )
    return value if isinstance(value, dict) else {}


async def get_airtable_base_tables_json(
    *,
    token: str,
    base_id: str,
    force_refresh: bool = False,
    ttl_seconds: float | None = None,
) -> dict[str, Any]:
    """Fetch Airtable base metadata with TTL caching and concurrent miss coalescing."""
    ttl = airtable_cache_ttl_seconds() if ttl_seconds is None else ttl_seconds
    key = ("base_tables", _token_fingerprint(token), base_id)

    async def load() -> object:
        async with shared_client(timeout=15) as client:
            response = await client.get(
                f"https://api.airtable.com/v0/meta/bases/{base_id}/tables",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            return response.json()

    value = await _AIRTABLE_CACHE.get_or_load(
        key, ttl_seconds=ttl, loader=load, force_refresh=force_refresh
    )
    return value if isinstance(value, dict) else {}


async def get_airtable_bases_json(
    *,
    token: str,
    force_refresh: bool = False,
    ttl_seconds: float | None = None,
) -> dict[str, Any]:
    """Fetch Airtable base list with TTL caching and concurrent miss coalescing."""
    ttl = airtable_cache_ttl_seconds() if ttl_seconds is None else ttl_seconds
    key = ("bases", _token_fingerprint(token))

    async def load() -> object:
        async with shared_client(timeout=10) as client:
            response = await client.get(
                "https://api.airtable.com/v0/meta/bases",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            return response.json()

    value = await _AIRTABLE_CACHE.get_or_load(
        key, ttl_seconds=ttl, loader=load, force_refresh=force_refresh
    )
    return value if isinstance(value, dict) else {}

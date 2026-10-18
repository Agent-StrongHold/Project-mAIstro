"""Isolated real PostgreSQL pools for durable capability conformance tests."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest

from maistro.persistence import _register_json_codecs


@asynccontextmanager
async def isolated_capability_pools(
    *, production_codecs: bool, peer_production_codecs: bool | None = None
) -> AsyncIterator[tuple[Any, Any]]:
    """Use a test-owned schema and two independent pools, never fake SQL."""
    dsn = os.getenv("MAISTRO_TEST_PG_DSN", "").strip()
    if not dsn:
        if os.getenv("MAISTRO_REQUIRE_PG_LEGS") == "1":
            pytest.fail("required PostgreSQL capability conformance has no MAISTRO_TEST_PG_DSN")
        pytest.skip("set MAISTRO_TEST_PG_DSN for real PostgreSQL capability conformance")
    import asyncpg

    # A generated identifier, never a caller-supplied schema or an existing one.
    schema = f"capability_test_{uuid4().hex}"
    admin = await asyncpg.connect(dsn)
    first = second = None
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        options = {
            "min_size": 1,
            "max_size": 4,
            "server_settings": {"search_path": schema},
            "init": _register_json_codecs if production_codecs else None,
        }
        first = await asyncpg.create_pool(dsn, **options)
        if peer_production_codecs is not None:
            options["init"] = _register_json_codecs if peer_production_codecs else None
        second = await asyncpg.create_pool(dsn, **options)
        yield first, second
    finally:
        try:
            try:
                if first is not None:
                    await first.close()
            finally:
                if second is not None:
                    await second.close()
        finally:
            try:
                await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            finally:
                await admin.close()

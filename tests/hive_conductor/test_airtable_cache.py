"""Tests for shared Airtable TTL cache wrappers."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "packages" / "hive-conductor" / "backend")
)

from services import airtable_cache


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _Client:
    def __init__(self, calls: list[dict[str, Any]], timeout: int) -> None:
        self._calls = calls
        self._timeout = timeout

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def get(
        self, url: str, *, headers: dict[str, str], params: dict[str, str] | None = None
    ) -> _Response:
        self._calls.append(
            {"url": url, "headers": headers, "params": params or {}, "timeout": self._timeout}
        )
        return _Response({"records": [{"id": "rec1", "fields": {"Name": "Roadmap"}}]})


def test_airtable_records_reuse_cached_response_until_refresh(monkeypatch: MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def handler(request: Any) -> Any:
        import httpx

        calls.append(
            {
                "url": str(request.url).split("?")[0],
                "headers": request.headers,
                "params": dict(request.url.params),
            }
        )
        return httpx.Response(
            200, json={"records": [{"id": "rec1", "fields": {"Name": "Roadmap"}}]}
        )

    # The shared client is real; only the transport is swapped, so this asserts
    # on the request httpx actually built rather than on what the call site passed.
    import httpx as _httpx

    from maistro.http import set_test_transport

    set_test_transport(_httpx.MockTransport(handler))
    monkeypatch.setattr(
        "maistro.http._test_transport", _httpx.MockTransport(handler), raising=False
    )
    airtable_cache.clear_airtable_cache()

    async def run() -> None:
        first = await airtable_cache.get_airtable_records_json(
            token="tok",
            base_id="base",
            table="Roadmap",
            params={"maxRecords": "20"},
            ttl_seconds=60,
        )
        second = await airtable_cache.get_airtable_records_json(
            token="tok",
            base_id="base",
            table="Roadmap",
            params={"maxRecords": "20"},
            ttl_seconds=60,
        )
        forced = await airtable_cache.get_airtable_records_json(
            token="tok",
            base_id="base",
            table="Roadmap",
            params={"maxRecords": "20"},
            ttl_seconds=60,
            force_refresh=True,
        )

        assert first == second == forced
        assert len(calls) == 2
        assert calls[0]["url"] == "https://api.airtable.com/v0/base/Roadmap"
        assert calls[0]["params"] == {"maxRecords": "20"}

    asyncio.run(run())

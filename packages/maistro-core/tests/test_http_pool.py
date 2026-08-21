"""The shared HTTP pool: identity, isolation, and the properties that make it
safe to share something that used to be built per request.

The per-request construction this replaces was not arbitrary — it sidestepped
a real constraint, that an `httpx.AsyncClient` binds to the event loop that
created it. Most of these tests exist to prove the cache preserves that.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from maistro.http import (
    aclose_shared_clients,
    configure_shared_http,
    get_shared_client,
    override_transport,
    set_test_transport,
    shared_client,
    shared_client_stats,
)


@pytest.fixture(autouse=True)
async def _clean_pool():
    await aclose_shared_clients()
    yield
    set_test_transport(None)
    await aclose_shared_clients()


class TestSharing:
    async def test_same_configuration_returns_the_same_client(self):
        a = get_shared_client(timeout=5.0)
        b = get_shared_client(timeout=5.0)
        assert a is b

    async def test_different_timeouts_do_not_share_a_client(self):
        """Timeout is a per-client default the call sites rely on; sharing one
        client across timeouts would silently change their semantics."""
        assert get_shared_client(timeout=5.0) is not get_shared_client(timeout=30.0)

    async def test_different_base_urls_do_not_share_a_client(self):
        a = get_shared_client(base_url="https://a.example")
        b = get_shared_client(base_url="https://b.example")
        assert a is not b

    async def test_limits_are_applied(self):
        client = get_shared_client(timeout=1.0)
        limits = client._transport._pool._max_connections  # type: ignore[attr-defined]
        assert limits == shared_client_stats()["max_connections"]


class TestEventLoopIsolation:
    """The property that made per-request construction look necessary."""

    def test_each_loop_gets_its_own_client(self):
        seen: list[int] = []

        async def grab() -> None:
            seen.append(id(get_shared_client(timeout=5.0)))

        asyncio.run(grab())
        asyncio.run(grab())
        assert seen[0] != seen[1], "a client leaked across event loops"

    def test_a_client_from_a_dead_loop_is_never_handed_out(self):
        """Reusing one would raise deep inside httpx on first request."""
        first: list[httpx.AsyncClient] = []

        async def make() -> None:
            first.append(get_shared_client(timeout=5.0))

        asyncio.run(make())

        async def check() -> None:
            assert get_shared_client(timeout=5.0) is not first[0]

        asyncio.run(check())


class TestCloseSafety:
    async def test_exiting_the_context_manager_does_not_close_the_client(self):
        """`shared_client` is a drop-in for `async with httpx.AsyncClient(...)`,
        and the whole point is that the exit does *not* close it."""
        async with shared_client(timeout=5.0) as client:
            pass
        assert not client.is_closed
        async with shared_client(timeout=5.0) as again:
            assert again is client

    async def test_aclose_is_idempotent(self):
        get_shared_client(timeout=5.0)
        await aclose_shared_clients()
        await aclose_shared_clients()
        assert shared_client_stats()["clients_this_loop"] == 0

    async def test_a_closed_client_is_replaced_rather_than_reused(self):
        client = get_shared_client(timeout=5.0)
        await client.aclose()
        assert get_shared_client(timeout=5.0) is not client


class TestConfiguration:
    def test_keepalive_above_max_connections_is_refused(self):
        with pytest.raises(ValueError, match="exceeds"):
            configure_shared_http(max_connections=10, max_keepalive_connections=20)

    def test_zero_connections_is_refused(self):
        with pytest.raises(ValueError, match="must be >= 1"):
            configure_shared_http(max_connections=0)


class TestTransportOverride:
    async def test_override_routes_every_call_site(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"seen": str(request.url)})

        with override_transport(httpx.MockTransport(handler)):
            async with shared_client(timeout=5.0) as client:
                resp = await client.get("https://never.contacted.example/x")
            assert resp.json()["seen"].endswith("/x")

    async def test_override_is_restored_on_exit(self):
        def handler(_r: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        with override_transport(httpx.MockTransport(handler)):
            pass
        # No override left behind; a fresh client has no mock transport.
        client = get_shared_client(timeout=5.0)
        assert not isinstance(client._transport, httpx.MockTransport)

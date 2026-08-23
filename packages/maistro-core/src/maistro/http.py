"""Process-wide pooled `httpx.AsyncClient`s, keyed by their configuration.

Why this exists
---------------
Every HTTP call site in the engine used to build its own client per request::

    async with httpx.AsyncClient(timeout=30) as client:
        ...

There were 124 such sites and zero shared clients. Constructing a client is not
cheap — it builds a TLS context, a connection pool and a transport, then throws
all three away — and it guarantees a fresh TCP+TLS handshake on every single
call because there is no pool left to reuse.

Measured, one request:

    per-request client   56.685 ms CPU
    shared client         1.241 ms CPU     46x

The pooling win is separate and larger under load: keep-alive removes the
handshake from the critical path entirely.

Why a keyed cache rather than one module-level client
-----------------------------------------------------
`HttpxAsyncHttp` documented the constraint that made per-request construction
look necessary: an `AsyncClient` binds to the event loop that created it, so a
single module-level client breaks the moment a second loop touches it (tests,
`asyncio.run` in a CLI, a worker with its own loop). The cache is therefore
keyed by the running loop as well as by configuration, so each loop gets its
own pool and the original safety property still holds.

Keying by timeout (rather than sharing one client and overriding per call) keeps
call-site semantics exactly as they were: `timeout=` on an `AsyncClient` is a
*default* for requests that do not specify one, and the call sites rely on that.
Distinct timeouts get distinct pools; connections are reused within each.

Pool size is not admission control
----------------------------------
Do not shrink `max_connections` to throttle load. That was measured directly on
a 300-node DAG competing with 20 interactive requests:

    shared budget, no admission control    chat p50  4.06s
    global cap (max_connections=25)        chat p50 24.14s   <- worst
    priority ordering, no reservation      chat p50  3.51s
    priority + reserved floor for LIVE     chat p50  2.03s

A small global connection cap is the *worst* of the four, because it throttles
everything into one queue and interactive requests wait behind batch work. The
pool's job is connection reuse; admission is `tasks.lanes.LaneGate`'s job.

Size the pool from Little's Law instead: concurrency = throughput x latency. At
50 req/s against 2s calls you need ~100 connections in flight, so a limit below
that turns into an invisible queue.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager

import httpx

from maistro.security.outbound import guarded

# Generous by design — see "Pool size is not admission control" above. These are
# ceilings that stop a runaway fan-out exhausting file descriptors, not a
# throttle. Overridable per call site and via `configure_shared_http`.
DEFAULT_MAX_CONNECTIONS = 100
DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 50
# Long enough that a bursty caller reuses connections between bursts, short
# enough that idle sockets are not held against a server's own idle timeout.
DEFAULT_KEEPALIVE_EXPIRY_S = 30.0

_limits = httpx.Limits(
    max_connections=DEFAULT_MAX_CONNECTIONS,
    max_keepalive_connections=DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
    keepalive_expiry=DEFAULT_KEEPALIVE_EXPIRY_S,
)

# (loop, timeout, base_url, headers, transport_id, follow_redirects, verify)
#
# The first element is the loop *object*, not `id(loop)`. CPython recycles
# addresses: after `asyncio.run()` tears a loop down, the next one is very
# likely allocated at the same address, so an id-keyed entry would hand a
# client bound to the dead loop straight to the new one — the exact failure
# the loop-keying exists to prevent, and it raises deep inside httpx on first
# use. Holding the loop keeps its identity stable; closed ones are pruned
# below, so this does not accumulate.
_CacheKey = tuple[
    asyncio.AbstractEventLoop | None, object, str, tuple[tuple[str, str], ...], int, bool, bool
]

_clients: dict[_CacheKey, httpx.AsyncClient] = {}
# Transports are held so `id()` keys cannot be recycled onto a different object
# while the cached client is still alive.
_transports: dict[int, httpx.AsyncBaseTransport] = {}
_lock = threading.Lock()

# Set only by `set_test_transport`. When present it overrides every call
# site's transport, which is how tests get "no network, everything else real".
_test_transport: httpx.AsyncBaseTransport | None = None


def configure_shared_http(
    *,
    max_connections: int = DEFAULT_MAX_CONNECTIONS,
    max_keepalive_connections: int = DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
    keepalive_expiry: float = DEFAULT_KEEPALIVE_EXPIRY_S,
) -> None:
    """Set the limits applied to clients created from now on.

    Existing cached clients keep the limits they were built with, so call this
    during startup, before the first request. Raising the ceiling at runtime
    would otherwise appear to work while the hot pools stayed small.
    """
    global _limits
    if max_connections < 1:
        raise ValueError(f"max_connections must be >= 1, got {max_connections}")
    if max_keepalive_connections < 0:
        raise ValueError(f"max_keepalive_connections must be >= 0, got {max_keepalive_connections}")
    if max_keepalive_connections > max_connections:
        raise ValueError(
            f"max_keepalive_connections ({max_keepalive_connections}) exceeds "
            f"max_connections ({max_connections}) — the pool could never reach it."
        )
    _limits = httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=max_keepalive_connections,
        keepalive_expiry=keepalive_expiry,
    )


def set_test_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Route every shared client through ``transport`` (tests only).

    The seam this replaces was ``monkeypatch.setattr(
    "some.module.httpx.AsyncClient", lambda timeout: ...)``, which pins the
    test to the exact keyword arguments the call site happens to pass — so
    adding `limits=` to a client broke a hundred tests that cared about none
    of it. Overriding the transport instead expresses what those tests
    actually want: no network, everything else real.

    Clears the cache on the way in and out so a client built before the
    override is never reused after it.
    """
    global _test_transport
    _test_transport = transport
    with _lock:
        _clients.clear()


@contextmanager
def override_transport(transport: httpx.AsyncBaseTransport) -> Iterator[None]:
    """Scoped form of `set_test_transport` — ``with override_transport(t): ...``.

    Deliberately not named `test_transport`: pytest collects any importable
    callable whose name starts with `test_`, so that name turns every module
    importing it into a spurious failing test.

    Restores the previous override on exit, so nested and sequential uses do
    not leak into unrelated tests.
    """
    previous = _test_transport
    set_test_transport(transport)
    try:
        yield
    finally:
        set_test_transport(previous)


def _guarded_transport(
    transport: httpx.AsyncBaseTransport | None,
    *,
    verify: bool,
) -> httpx.AsyncBaseTransport:
    """The transport this client will use, with the outbound policy in front.

    Every module that reaches the network through this pool is guarded here at
    once (#155) — which is the point, because the same control as a function
    each call site had to remember reached three sites out of twenty-five.
    Redirect hops are covered for free: httpx re-enters the transport per hop.

    When the caller passed no transport, the real one is built here rather than
    left to httpx, because it has to exist before it can be wrapped. It is
    built with the same `verify` and pool limits httpx would have used, so the
    only difference is the guard.
    """
    inner = transport
    if inner is None:
        inner = httpx.AsyncHTTPTransport(verify=verify, limits=_limits)
    return guarded(inner)


def _current_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        # No running loop: the caller is about to build a client outside async
        # context. Give it its own bucket rather than colliding with a loop's.
        return None


def _prune_dead_loops() -> None:
    """Drop entries for loops that have been closed. Caller holds `_lock`.

    Their sockets went with the loop, so there is nothing to close here — and
    trying to `aclose()` from a different loop would raise.
    """
    dead = [k for k in _clients if k[0] is not None and k[0].is_closed()]
    for k in dead:
        del _clients[k]


def get_shared_client(
    *,
    timeout: httpx.Timeout | float | None = None,
    base_url: str = "",
    headers: Mapping[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    follow_redirects: bool = False,
    verify: bool = True,
) -> httpx.AsyncClient:
    """A pooled client for this configuration on this event loop.

    The returned client is shared. Do **not** close it or use it as a context
    manager — use `shared_client()`, which is close-safe, or call
    `aclose_shared_clients()` at shutdown.
    """
    if _test_transport is not None:
        transport = _test_transport
    header_key = tuple(sorted((headers or {}).items()))
    key: _CacheKey = (
        _current_loop(),
        timeout,
        base_url,
        header_key,
        id(transport),
        follow_redirects,
        verify,
    )
    with _lock:
        _prune_dead_loops()
        client = _clients.get(key)
        if client is not None and not client.is_closed:
            return client
        client = httpx.AsyncClient(
            base_url=base_url,
            headers=dict(headers or {}),
            timeout=timeout,
            transport=_guarded_transport(transport, verify=verify),
            follow_redirects=follow_redirects,
            verify=verify,
            limits=_limits,
        )
        _clients[key] = client
        if transport is not None:
            _transports[id(transport)] = transport
        return client


@asynccontextmanager
async def shared_client(
    *,
    timeout: httpx.Timeout | float | None = None,
    base_url: str = "",
    headers: Mapping[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    follow_redirects: bool = False,
    verify: bool = True,
) -> AsyncIterator[httpx.AsyncClient]:
    """Drop-in for `async with httpx.AsyncClient(...) as client:` that pools.

    Exiting the block does **not** close the client — that is the whole point.
    The shape is kept identical to the call it replaces so the migration is a
    one-line change per site and reads the same afterwards.
    """
    yield get_shared_client(
        timeout=timeout,
        base_url=base_url,
        headers=headers,
        transport=transport,
        follow_redirects=follow_redirects,
        verify=verify,
    )


async def aclose_shared_clients() -> None:
    """Close every pooled client. Call on application shutdown.

    Safe to call more than once, and safe to call with requests never having
    been made. Clients belonging to other event loops are dropped from the
    cache without being closed — closing them from this loop would raise, and
    their sockets are released when that loop is torn down.
    """
    with _lock:
        current = _current_loop()
        mine = [(k, c) for k, c in _clients.items() if k[0] is current]
        for k, _ in mine:
            del _clients[k]
        stale = [k for k in _clients if k[0] is not current]
        for k in stale:
            del _clients[k]
        _transports.clear()
    for _, client in mine:
        if not client.is_closed:
            await client.aclose()


def shared_client_stats() -> dict[str, int]:
    """Pool counts, for tests and health endpoints."""
    with _lock:
        return {
            "cached_clients": len(_clients),
            "clients_this_loop": sum(1 for k in _clients if k[0] is _current_loop()),
            "max_connections": _limits.max_connections or 0,
            "max_keepalive_connections": _limits.max_keepalive_connections or 0,
        }

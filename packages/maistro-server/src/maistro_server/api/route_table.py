"""Route-table iteration that stays correct across fastapi versions.

fastapi >= 0.141 no longer flattens ``include_router`` targets into the
parent application eagerly: ``app.routes`` holds a private ``_IncludedRouter``
sentinel per inclusion (lazy inclusion, so routes added to a router after it
is mounted are still served), and the effective sub-routes -- the table
Starlette actually matches requests against -- are reachable only through
the sentinel's ``effective_route_contexts()``. Older fastapi versions
flattened eagerly and need no recursion.

Anything that introspects the app must iterate through :func:`iter_effective_routes`
instead of reading ``app.routes`` directly. Reading it directly is not merely
incomplete under lazy inclusion: a ``getattr(route, "path", None)`` guard
silently drops every router-mounted route, which turned the frontend-route
gate and the security enumeration gate into false witnesses (the gate saw a
near-empty table; the ratchet saw a gap disappear and called the baseline
stale).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any, cast


def iter_effective_routes(routes: Iterable[Any]) -> Iterator[Any]:
    """Yield route objects exposing ``.path``/``.methods`` across versions.

    Lazy inclusions (fastapi >= 0.141 ``_IncludedRouter`` sentinels) are
    flattened via ``effective_route_contexts()``; plain routes -- ``APIRoute``,
    Starlette ``Route``/``Mount``, anything else -- pass through unchanged.
    The attribute probe is defensive on purpose: it keeps working on both
    sides of the fastapi lazy-inclusion change and on non-fastapi routers.
    """
    for route in routes:
        flatten = getattr(route, "effective_route_contexts", None)
        if callable(flatten):
            yield from cast("Iterable[Any]", flatten())
        else:
            yield route

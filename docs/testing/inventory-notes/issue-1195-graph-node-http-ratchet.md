---
inventory-delta:
  tests/: +8
---

# Issue 1195 graph-node direct-HTTP ratchet (AC7 repair round)

Prior verification found `scripts/check_direct_effects.py` only classified
PM HTTP when URL literal fragments matched, so a graph-node
`shared_client().get(url)` with a dynamic URL produced zero sites and the
architecture ratchet was bypassable.

The repair makes graph-node egress fail closed: any effect-method call
(`get`/`post`/`stream`/`send`/`request`) whose receiver is a tracked shared
HTTP client (`maistro.http.shared_client` / `get_shared_client` /
`sync_client`, `httpx.AsyncClient` / `httpx.Client`, `aiohttp.ClientSession`)
in a `/graph/nodes/` path is inventoried as `DIRECT_HTTP_EFFECT:
graph-node-http` and must carry a reviewed disposition to pass the gate.
Receivers are tracked through assignment, `with`/`async with` bindings and
the chained `shared_client().get(...)` form; plain `dict.get` lookups stay
unclassified, and the fail-closed rule is scoped to graph nodes so curated
boundaries elsewhere are unchanged.

Adds 8 collected cases in `tests/test_check_direct_effects.py` covering the
dynamic-URL assign/chained/async-with/literal forms, alternative client
factories, PM-literal precedence, dict.get immunity, and the graph-node scope
guard.

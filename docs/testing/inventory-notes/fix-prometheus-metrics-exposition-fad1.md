---
inventory-delta:
  packages/maistro-core/tests: +12
  packages/maistro-server/tests: +3
---
# fix-prometheus-metrics-exposition-fad1

**+12 `packages/maistro-core/tests`** — nine new cases in `test_metrics.py` for
Prometheus text exposition (`render_prometheus`): full counter/gauge/histogram
rendering with deterministic sort order, HELP/label escaping, name/label policy,
special float values (+Inf/−Inf/NaN), empty-help formatting, bool gauges as
`0.0`/`1.0`, and an empty registry that exposes only uptime. Three more come
from parametrizing non-finite counter increments (`inf`, `-inf`, `nan`).

**+3 `packages/maistro-server/tests`** — one contract test for the `/metrics`
route (`test_metrics.py`), plus two in `test_rate_limit.py`'s
`TestBoundedRouteLabels`: legacy HTTP metrics must label by route template, not
raw path, and many unknown paths must collapse to a single unrouted series so
cardinality stays bounded.

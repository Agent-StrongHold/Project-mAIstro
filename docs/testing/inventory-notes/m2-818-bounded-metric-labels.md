---
inventory-delta:
  packages/maistro-core/tests: +7
  packages/maistro-server/tests: +2
---
# m2-818-bounded-metric-labels

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

**+7 `packages/maistro-core/tests`** — seven new cases in `test_metrics.py`
for the #818 AC-3 registry backstop: a counter fed ten distinct label values
holds exactly `max_series_per_metric` series with the rest counted in
`metrics_series_overflow_total`; a capped metric still updates its admitted
series without counting those updates as overflow; the cap applies to gauges
and histograms; the cap is per metric, not per registry;
`max_series_per_metric=None` restores uncapped behaviour and renders no
overflow counter; a cap below one is rejected; and the text exposition
surfaces the overflow counter for alerting.

**+2 `packages/maistro-server/tests`** — two new cases in `test_rate_limit.py`
`TestBoundedRouteLabels` for #818 AC-2/AC-4: sixty distinct unmatched UUID
paths plus thirty distinct item ids create at most two new series per
middleware-emitted metric (the `unrouted` fallback class and the
`/items/{item_id}` template) instead of one series per URL, and two real
routes stay distinguishable as separate series while no label value carries
a request-controlled identifier.

The middleware-side bounding (route templates at every emission site, the
existing `TestBoundedRouteLabels` cases) landed earlier via #831; this
change adds the registry-level backstop the issue's AC-3 asks for, so a
future caller that reintroduces a raw-path label degrades into a bounded
overflow bucket instead of unbounded memory.

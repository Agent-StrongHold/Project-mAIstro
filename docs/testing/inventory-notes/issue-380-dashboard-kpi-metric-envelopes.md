---
inventory-delta:
  packages/hive-conductor/backend/tests: +24
---

# issue-380-dashboard-kpi-metric-envelopes

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Inventory correction: this note originally claimed
`packages/hive-conductor/tests/e2e: +7`, but the suite inventory counts pytest
node IDs and the e2e recipe collects only the directory's Python tests — the
7 Playwright tests added in `dashboard-metrics-states.spec.ts` never become
collected nodes, so the gate read the claim as −7 drift. The same correction
was made for the same reason in `design-studio-visual-artifact-768.md` and
`issue-817-design-trust-active-markup.md`. The browser coverage itself is real
and documented below; the delta line is removed, not the coverage.

`packages/hive-conductor/backend/tests/test_dashboard_metrics.py` — 21 tests
for the KPI envelope contract (#380), plus 3 in `test_quotas.py` (the envelope
rewrite plus two malformed-response tests: a spend report whose body cannot
be aggregated and a `/model/info` body that is not a model list must both
answer the `error` envelope rather than an unhandled 500 — the aggregation-
and mapping-phase guards the first repair round left uncovered, which the
diff-coverage gate flagged), plus 7
Playwright tests in `packages/hive-conductor/tests/e2e/
dashboard-metrics-states.spec.ts`.

The service tests drive `services.dashboard_metrics.build_dashboard_metrics`
and the route over the TestClient. The interesting assertions are the ones the
old hard-coded payload could never fail: an unmeasured average is
`no_data`/`None`, not 0; an in-memory run history that restarted after local
midnight is `stale` with the boot time in the reason; a ring at its bound
reports its count as a floor; `ttft` and `approval_rate` say `unavailable`
with the reason instead of a plausible value; one failing source becomes one
`error` envelope without blanking the rest; and every chat-derived number is
scoped to the requesting principal (two users' observations never pool). The
envelope schema test pins the #380 acceptance fields — query, scope, window,
unit, computed_at, last_update — on every KPI, since that provenance is what
the SPA renders.

`test_quotas.py` was rewritten where the shape contract changed rather than
added to: providers/models now answer with an outer envelope (state, source,
window_days, computed_at) and rows whose unmeasured fields are `None`
(`request_count` is summed from the report's `num_requests` when the proxy
provides one — the new test pins that — and `None` when it does not, because
a count nobody returned is not a count of 0). The outcomes test flipped from
asserting the zeroed fallback shape to asserting the zeroed fallback shape is
GONE: `unavailable` with a reason, no `total`/`succeeded`/`failed`/`rate`
keys. `test_platform.py`'s two quota smoke tests needed no change (status-code
only), and its metrics test still passes because the envelope map keeps
`active_agents` as a top-level key.

The Playwright spec bundles the shipped `Dashboard.tsx` the same way
`widget-capabilities.spec.ts` does and drives the harness server through the
states a real deployment produces: seeded non-zero envelopes render measured
values with their unit/window/freshness footer and query/scope tooltip; an
outage (HTTP 500) renders the error state and no zeros; a stale envelope
renders the STALE badge with the last-known value and the reason visible; a
measured zero renders the digit with its footer while `no_data` renders an
em-dash — distinct; and a 401 renders a sign-in state. It can run against a
worktree via `E2E_SRC_ROOT` + `E2E_NODE_PATHS` (':'-joined), the same escape
hatch the widget spec documents.

Nothing was removed. `services/dag_run_store.py` gained `count_since` (its
coverage lives in the new file), and the pre-existing chat-metrics and
run-history suites were run unchanged and green (2994 passed, 6 skipped).

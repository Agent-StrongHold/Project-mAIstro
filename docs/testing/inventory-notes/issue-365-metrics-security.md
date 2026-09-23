---
inventory-delta:
  packages/maistro-server/tests: +5
  packages/maistro-core/tests: +8
---

# Issue 365 metrics security

The metrics endpoint tests replace the former anonymous exposition-only test
with coverage for anonymous denial, the dedicated `admin:metrics` service
scope, wrong-scope denial, forwarded-header non-bypass, and a scoped scraper
behind proxy headers. Health tests retain readiness dependency coverage while
asserting that public probes return only status. SLO tests also verify that
credential-shaped service keys are represented by an opaque digest rather than
raw metric label text.

Repair follow-up (#365 registry backstop): the core registry tests now also
cover the family-level cardinality backstop — the overflow counter's `metric`
label is series-capped against dynamically minted metric names, brand-new
families past `DEFAULT_MAX_METRICS_PER_REGISTRY` are refused with a dropping
sink and counted in the unlabeled `metrics_registry_overflow_total`, the new
metric name is reserved, and a family cap below 1 is rejected.

## Verification record (repair lane, head b1ee27d7)

Executed against the full production app (`maistro_server.main.app`) via
TestClient, plus the focused suites:

- `uv run ruff check .` / `uv run ruff format --check .`: pass.
- Focused pytest (core metrics/SLO/resource-policy, server metrics/health/
  rate-limit/resource-policy-health/strike-tracker-health): 152 passed.
- Live probes: anonymous `/metrics` → 401 with no metric families in the
  body; valid service key without `admin:metrics` → 403, no families; scoped
  scraper (`X-Service-Key`) → 200 with Prometheus exposition.
- Adversarial cardinality: 300 distinct attacker-controlled URL paths (rate
  limiter raised via `ALLOW_UNSAFE_RESOURCE_OVERRIDES` in the probe only)
  produced exactly 2 `http_requests_total` series — `route="/metrics"` and a
  single collapsed `route="unrouted"` — proving no series-per-path growth.
- CI findings from the prior run (Alembic `KeyError: '033'`, durable-events
  integration, coincurve/Python 3.14) are not reproducible in-tree
  (`uv run alembic history` exits 0 with the 032→033 chain intact) and the
  branch diff touches no alembic, packaging, Dockerfile, or CI files; they
  are pre-existing infrastructure, out of scope for #365.

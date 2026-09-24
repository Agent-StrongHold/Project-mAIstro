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

## Re-verification record (repair lane, head ead29ac9c)

Independent re-run, not a restatement of the record above:

- `uv run ruff check .` / `ruff format --check .`: only the untracked
  prior-run scratch probe `repro_metrics.py` fails lint; all tracked files
  pass both (untracked files do not ship to CI; the scratch is preserved
  salvage, deliberately not committed).
- Focused pytest (core metrics/SLO/resource-policy, server metrics/health/
  rate-limit/resource-policy-health/strike-tracker-health): **152 passed**.
- Canonical mypy (`packages/maistro-core/src` + `packages/maistro-server/src`):
  only pre-existing `maistro_bootstrap` import-resolution notes in
  lane-untouched `cli/_*` files; `scripts/check-reachability.py` exits 0.
- Fresh TestClient probes against `maistro_server.main.app` (11/11 pass):
  anonymous `/metrics` → 401 with zero metric names in the body; non-service
  Bearer token → 401; valid service key without `admin:metrics` → 403, no
  families; scoped scraper → 200 (22 families); `/health`, `/health/live`
  return exactly `{"status":"ok"}`; `/health/ready` failure body is
  `{"status":"not_ready"}` with no dependency detail; `/health/startup`
  exposes only `{status, startup_complete}`.
- Adversarial cardinality, re-executed: 300 distinct random URL paths added
  exactly 2 `http_requests_total` series (`route="unrouted"` × status 404/429)
  and nothing else; a dedicated `MetricsRegistry(max_metrics_per_registry=50)`
  minted 200 dynamic families, rendered 50, and counted 150 refusals in the
  unlabeled `metrics_registry_overflow_total`.
- The Alembic CI finding was re-tested against a **real database**, not just
  `alembic history`: on a scratch pgvector/pg18 database this tree ran
  `alembic upgrade head` through the full 032→033→…→040 chain, exit 0. The
  `KeyError: '033'` CI job installs alembic via bare `pip` (formal-
  conformance.yml), so the failure is that job's environment/checkout, not
  the tree. The durable-events and coincurve/Python-3.14 findings trace to
  trunk commits merged into this branch (`git branch -r --contains` shows
  them on origin/develop), not lane-authored work.

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

## Re-verification record (repair lane, head fa1715866)

Third independent pass; all evidence re-executed fresh, not restated:

- `uv run ruff check .`: the only failures (5, all fixable) are in the
  untracked prior-run scratch probe `repro_metrics.py` (git-unknown, does
  not ship); `ruff check packages/ docs/ scripts/ tests/` and
  `ruff format --check` on tracked paths (2439 files) pass.
- Focused pytest (core metrics/SLO/resource-policy, server metrics/health/
  rate-limit/resource-policy-health/strike-tracker-health): **152 passed**.
- Canonical mypy (all six package srcs per AGENTS.md): **Success, 712 source
  files**. (Scoped core+server runs surface only the pre-existing
  `maistro_bootstrap` import-resolution notes in release-vintage `cli/_*`
  files, which the canonical all-srcs invocation resolves.)
- `scripts/check-reachability.py`: exit 0 (189 unreachable of 1115 modules,
  within ratchet).
- Live probes against the full production app (`maistro_server.main.app`),
  19/19 pass: anonymous `/metrics` 401 with zero metric names; arbitrary
  user Bearer 401; wrong-scope service key 403, no families; forwarded
  headers do not bypass auth; scoped scraper 200 Prometheus exposition,
  also through proxy headers; `/health` and `/health/live` exactly
  `{"status":"ok"}`; `/health/ready` failure body exactly
  `{"status":"not_ready"}` with no dependency detail; `/health/startup`
  only `{status, startup_complete}`.
- #818 adversarial cardinality re-proven on the full app: 300 distinct
  random attacker paths grew `http_requests_total` by exactly 2 series
  (`route="unrouted"` × status 404/429); no attacker URL appears in any
  label value; the unrouted fallback exists.
- Registry family backstop re-proven: `MetricsRegistry(max_metrics_per_registry=50)`
  minted 200 dynamic families, collected 51 (50 capped + unlabeled overflow
  counter), `metrics_registry_overflow_total == 150`.
- Runtime label audit over the live registry after exercising `/health`,
  `/health/ready`, an unrouted path, and `/metrics`: label keys are exactly
  `dependency`, `method`, `outcome`, `route`, `status` — no user/tenant/
  prompt/model/credential/path keys; `route` values are route templates and
  `unrouted`; SLO `service_key` labels are sha256 digests (slo.py
  `_service_key_label`). Static emission-site grep found no metric call
  carrying model/tenant/user identifiers.
- CI triage re-checked: `uv run alembic history` resolves the full chain
  through 032→033→…→040 (exit 0); the branch touches no alembic or
  formal-conformance files. The `quality.yml` credential-gate removal in
  this branch's diff arrives via merges of origin/develop commits
  (`8bb344e32`, `ba2f1f077`; both `git branch -r --contains` on
  origin/develop), not lane-authored edits.

## Re-verification record (repair lane, head ada7be0f)

Fourth independent pass; evidence re-executed fresh, over a transport path
the earlier records did not use — a real uvicorn server on 127.0.0.1
probed with curl over TCP, not TestClient:

- Focused pytest (core test_metrics.py + resilience/test_slo.py +
  security/test_resource_policy.py; server test_metrics.py, test_health.py,
  test_rate_limit.py, test_resource_policy_health.py,
  test_strike_tracker_health.py): **131 + 41 = 172 passed**.
- Live probes (uvicorn + curl, full `maistro_server.main.app`): anonymous
  `/metrics` → 401 `Metrics authentication required`, zero Prometheus text;
  arbitrary user Bearer → 401; valid service key without `admin:metrics`
  → 403 `Metrics scope required`, no families; `X-Forwarded-*` headers do
  not authenticate (401); scoped scraper → 200 exposition via both
  `Authorization: Bearer sk-svc-…` and `X-Service-Key`, and the scraped
  payload contains no key material.
- Runtime registry audit from the scraped payload: 22 families; observed
  label keys `dependency`, `method`, `outcome` (plus `route`/`status` on
  traffic series) — no tenant/user/prompt/model/credential/path keys.
- Public health over real HTTP: `/health` and `/health/live` exactly
  `{"status":"ok"}`; `/health/ready` (deps down in the probe env) exactly
  `{"status":"not_ready"}` with no dependency detail; `/health/startup`
  only `{"status":"ok","startup_complete":true}`.
- #818 adversarial cardinality on the live server: 300 distinct random
  attacker paths (with the per-IP rate limiter engaging mid-run) grew
  `http_requests_total` to exactly 4 series — `route="/metrics"` (200/429)
  plus collapsed `route="unrouted"` × status 404 (29) / 429 (271); zero
  attacker-controlled text in any label value.
- Registry family backstop re-proven first-hand:
  `MetricsRegistry(max_series_per_metric=10, max_metrics_per_registry=50)`
  minted 200 dynamic families, stored 50, `metrics_registry_overflow_total
  150.0`.
- Validation battery: `ruff check packages/ docs/ scripts/ tests/` and
  `ruff format --check .` pass (2527 files formatted; the only failures are
  in the untracked scratch probe `repro_metrics.py`, preserved uncommitted
  salvage that does not ship); canonical mypy all six package srcs:
  **Success, 712 source files**; `scripts/check-doc-links.py`,
  `check-security-inventory.py`, `check-suite-inventory.py` all exit 0;
  Alembic script directory resolves 43 revisions to the single head
  `036_audit_log_org_scope` with `033_project_membership_unique_per_principal.py`
  present (CI `KeyError: '033'` again not reproducible in-tree).

## Re-verification record (repair lane, head 501be3a92)

Fifth independent pass; all evidence re-executed fresh at the current head.
Environment note for future passes: `maistro-server` is a workspace member
but not a root dependency, so a fresh worktree venv needs
`uv run --package maistro-server python -m uvicorn maistro_server.main:app …`
(plus `ROUTER_API_KEY`, `API_KEYS=["principal:secret"]`,
`REQUIRE_WEBHOOK_SECRETS=false`) to boot the full app for live probing.

- Focused pytest: **103 + 49 = 152 passed** — core `test_metrics.py`,
  `resilience/test_slo.py`, `security/test_resource_policy.py`; server
  `test_metrics.py`, `test_health.py`, `test_rate_limit.py`,
  `test_resource_policy_health.py`, `test_strike_tracker_health.py`.
- Live TCP probe of the full `maistro_server.main.app` (uvicorn on
  127.0.0.1, urllib client): **16/16 checks passed**. Anonymous `/metrics`
  → 401 generic body, zero Prometheus text; user-format Bearer → 401;
  valid service key without `admin:metrics` → 403 with no metric
  families; `X-Forwarded-*` headers do not authenticate; scoped scraper →
  200 exposition via both `Authorization: Bearer sk-svc-…` and
  `X-Service-Key`, payload contains no key material. `/health` and
  `/health/live` return exactly `{"status":"ok"}`; `/health/ready` (deps
  down) returns exactly `{"status":"not_ready"}` with no dependency
  detail; `/health/startup` returns only `{status, startup_complete}`.
- #818 adversarial cardinality re-proven on the live server: 300 distinct
  random attacker paths grew `http_requests_total` route-labeled series
  from 3 to exactly 4 (the collapsed `route="unrouted"` fallback); no
  24-char attacker path appears in any label value; scraped label keys
  are only `dependency`, `method`, `outcome`, `route`, `status` — no
  tenant/user/prompt/model/credential/path keys.
- Registry family backstop re-proven first-hand:
  `MetricsRegistry(max_series_per_metric=10, max_metrics_per_registry=50)`
  minted 200 dynamic families → 50 stored, `metrics_registry_overflow_total
  == 150.0`.
- Canonical mypy all six package srcs: **Success, 712 source files**.
  `ruff check packages/ docs/ scripts/ tests/` clean; `ruff format --check .`
  formats 2527 files — the sole reformat candidate remains the untracked
  prior-run scratch probe `repro_metrics.py` (preserved salvage, untracked,
  invisible to CI).
- Gates: `scripts/check-doc-links.py`, `check-security-inventory.py`,
  `check-suite-inventory.py`, `check-adr-index.py` all exit 0.
- Alembic resolution re-proven programmatically via `ScriptDirectory`:
  43 revisions resolve, single head `036_audit_log_org_scope`, linear chain
  `001 → … → 033 → … → 040 → 036_audit_log_org_scope`; the branch diff vs
  base `03c8ba83` contains no alembic-version changes, so the required-CI
  `KeyError: '033'` is an origin/infra failure outside this lane's surfaces,
  as are the `durable-events` and coincurve/Python-3.14 gate failures
  (no lane-authored code touches those paths).

## Re-verification + salvage-resolution record (repair lane, head d5a3712f0)

Sixth independent run. The prior lane process died on a provider timeout and
executed **zero** deterministic checks (`checks: []` in the prior job's
result), so every claim below is freshly executed evidence, not a restatement.

### Salvage resolution (uncommitted work from the timed-out run)

The only uncommitted item was the untracked scratch probe
`repro_metrics.py` (repo root). Disposition: its full text is archived below;
its evidentiary purpose (pre-router `scope["route"]` is unset and
`_match_route_template` recovers the template or falls back to `unrouted`) is
permanently superseded by the CI-enforced regression tests
`test_rate_limit.py::_unrouted_request_uses_fallback_label`,
`_many_unknown_paths_collapse_to_one_fallback_series`, and
`_many_distinct_404_uuid_paths_create_no_series_per_url`. A copy is also
preserved in the job directory (`salvaged-repro_metrics.py`). The file was
then removed from the worktree so the tree is clean and `ruff check .` /
`ruff format --check .` pass repo-wide (the scratch was the sole offender:
5 auto-fixable lint errors, all unused/unsorted imports).

### CI-repair round: vulture per-identity ledger (exact-debt-ledger)

`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` exited **1** at this head:
the #365 health minimization (which removed the public
uptime/service/version exposure) eliminated two identities but the ledger
still recorded one of them, and orphaned the class behind the other:

- FIXED genuinely dead code: `maistro_server/api/schemas.py` `HealthResponse`
  (and its "Item 36" section) — on develop it was the response model of the
  detailed public health payload; the branch removed its last import/use, so
  it had zero references in maistro-server src and tests. Deleted.
- PRUNED the two identities the fix eliminated from
  `quality/vulture-baseline.json`: `health.py::unused variable
  'uptime_seconds'` (already stale) and `schemas.py::unused variable
  'uptime_seconds'` (stale after the class deletion). `health.py::startup_complete`
  and `schemas.py::ci_status` remain (their classes still exist).
- Re-run: exit **0**, ratchet clean — 1415 reviewed identities → 1413
  findings, no unauthorized debt.

### Acceptance validation (freshly executed)

- Focused pytest (core metrics/SLO/resource-policy; server
  metrics/health/rate-limit/resource-policy-health/strike-tracker-health):
  **152 passed**, re-run after the dead-code removal: **152 passed**.
- `uv run ruff check .` and `uv run ruff format --check .`: pass (tracked
  tree; the scratch was the only failure and is resolved above).
- Canonical mypy (`maistro-core/src` + `maistro-server/src`): only the 5
  pre-existing `maistro_bootstrap` import-resolution notes in lane-untouched
  `cli/_*` files; zero findings in any #365-touched module.
- Live TCP probes against `maistro_server.main:app` under uvicorn
  (19 checks in run 1; 16 passed, 3 investigated):
  anonymous `/metrics` → 401 generic body, no metric families, arbitrary
  bearer → 401, `X-Forwarded-*` → 401; wrong-scope service key → 403, no
  families; scoped scraper → 200 `text/plain; version=0.0.4` exposition with
  no key material; `/health` and `/health/live` exactly `{"status":"ok"}`;
  `/health/ready` (deps down) → 503 with body exactly
  `{"status":"not_ready"}`; `/health/startup` → `{status, startup_complete}`
  only. Two of the three "failures" were probe-script bugs: the header dump
  used a case-sensitive lookup, and the family-cap arithmetic forgot the
  exempt `metrics_registry_overflow_total` counter (50 dynamic + uptime +
  overflow = 52 HELP lines; overflow == 150 is the proof). Confirmed
  corrected outcomes: registry backstop holds (200 dynamic names into a
  cap-50 registry → 50 stored, 150 refusals counted, counter unlabeled).
- #818 cardinality re-proven over real TCP: 8 distinct random attacker
  paths produced exactly one new series
  (`http_requests_total{method="GET",route="unrouted",status="404"}`) plus
  `route="/metrics"` — distinct route labels: `['/metrics', 'unrouted']`.
  No attacker-controlled text appears in any label value. (A heavier
  140-request variant tripped the ip-bucket rate limiter before the scrape —
  the limiter working as designed — and produced a 429 instead of the
  exposition; lighter load was used for the proof.)
- Alembic resolution: `uv run alembic history` exit 0 with the full chain
  including `032 -> 033` and `033 -> 034`; branch diff vs origin/develop
  contains no alembic/CI/packaging files, so the required-CI `KeyError:
  '033'`, `durable-events`, and coincurve/Python-3.14 failures remain
  origin/infrastructure findings outside this lane's surfaces.

### Residual risk (recorded, not repaired this round)

`main.py::http_exception_handler` builds its JSON envelope without
`exc.headers`, so the `WWW-Authenticate: Bearer` header that
`require_metrics_scope` attaches is dropped on the wire. This is
app-wide pre-existing envelope behavior, leaks no operational detail, and no
#365 acceptance criterion requires the header (RFC 6750 SHOULD-level nit);
it affects every HTTPException, not just metrics, so fixing it belongs to a
dedicated change with its own tests.

### Archived salvage: `repro_metrics.py` (verbatim, prior run)

```python
from fastapi import FastAPI, Request
from starlette.routing import Match, Route
import asyncio
from starlette.datastructures import Headers

async def dummy_endpoint(request: Request):
    return {"hello": "world"}

app = FastAPI()
app.add_route("/users/{user_id}", dummy_endpoint)

def _match_route_template(request: Request) -> str:
    from starlette.routing import Match
    try:
        for candidate in app.routes:
            match, _ = candidate.matches(request.scope)
            if match is Match.FULL:
                path = getattr(candidate, "path", None)
                if isinstance(path, str):
                    return path
    except Exception:
        return "unrouted"
    return "unrouted"

def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str):
        return template
    return _match_route_template(request)

async def main():
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/users/123",
        "url": "/users/123",
        "headers": {"host": "localhost"},
        "client": ("127.0.0.1", 12345),
        "server": ("localhost", 8000),
    }

    print(f"Request path: {scope['path']}")

    req = Request(scope)

    # Test 1: Request where route is already in scope (simulating post-router)
    class MockRoute:
        def __init__(self, path):
            self.path = path

    mock_route = MockRoute("/users/{user_id}")
    req_with_route = Request({**scope, "route": mock_route})

    print(f"Test 1 (_route_template with scope['route']): {_route_template(req_with_route)}")

    # Test 2: Request where route is NOT in scope (simulating middleware pre-router)
    print(f"Test 2 (_match_route_template): {_route_template(req)}")

    # Test 3: Request to an unrouted path
    scope_unrouted = scope.copy()
    scope_unrouted["path"] = "/unknown"
    scope_unrouted["url"] = "/unknown"
    req_unrouted = Request(scope_unrouted)
    print(f"Test 3 (unrouted): {_route_template(req_unrouted)}")

if __name__ == "__main__":
    asyncio.run(main())
```

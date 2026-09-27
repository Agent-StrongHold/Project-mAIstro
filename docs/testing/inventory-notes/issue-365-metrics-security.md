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

## Independent verification record (verifier lane, head 7cf1052ad)

Seventh independent run — fresh evidence at the develop-merge head
`7cf1052ad` (merge of develop base `55c5ad892` into auto-365). The prior
"uncommitted work" block is resolved as a no-op: the worktree arrived clean at
that exact SHA and the develop sync had already been committed as the merge.

Locally re-executed (not restated):

- `uv sync --locked --extra dev`; `uv run ruff check .`: pass.
- Focused pytest (core metrics/SLO/resource-policy; server metrics/health/
  rate-limit/resource-policy-health/strike-tracker-health): **152 passed**.
- Canonical mypy (six package srcs): **Success, 713 source files**.
- Alembic: `ScriptDirectory` single head `036_audit_log_org_scope`, 43
  revisions walked, `033` resolvable — the historical `KeyError: '033'`
  CI finding is dead at this head.
- Live full-app probes against `maistro_server.main.app` (TestClient,
  rate limiter raised via `ALLOW_UNSAFE_RESOURCE_OVERRIDES` in the probe
  only): anonymous `/metrics` → 401, zero metric families; arbitrary user
  Bearer → 401; wrong-scope service key → 403, no families; forwarded
  headers do not bypass; scoped scraper → 200 with 22 families via both
  `X-Service-Key` and Bearer, also through proxy headers;
  `/health` and `/health/live` → exactly `{"status": "ok"}`;
  `/health/ready` → 503 `{"status": "not_ready"}` with no dependency detail;
  `/health/startup` → only `{status, startup_complete}`.
- #818 cardinality on the full app: 300 distinct attacker paths added
  exactly **1** new `http_requests_total` series (`route="unrouted"`); no
  attacker URL appears in any label; distinct routes remain bounded
  (`/metrics`, `unrouted`).
- Registry family backstop re-proven: `MetricsRegistry(max_metrics_per_registry=50)`
  minted 200 dynamic families, rendered 50, counted refusals in the
  unlabeled `metrics_registry_overflow_total`.
- Live label-key audit of the rendered registry: `dependency`, `le`,
  `method`, `outcome`, `route`, `status` only — no user/tenant/prompt/
  model/credential/path keys.

### NEW findings this round: two lane-caused required-CI reds at this head

Live `statusCheckRollup` for PR #1457 at `7cf1052ad`: the previously red
findings (PostgreSQL coverage KeyError '033', integration-scope
durable-events, Gate C coincurve/Python 3.14) are now **green** — those were
stale. Still red, both reproduced locally and both caused by this branch:

1. `formal-conformance` FAILURE — generated-artifact drift. The branch adds
   the 39th scope `Scope.METRICS_READ = "admin:metrics"`
   (`packages/maistro-core/src/maistro/auth/_types.py:67`, absent at the
   develop base) but never regenerated
   `formal/generated/security-constants.json` (still `scope_count: 38`).
   Reproduced: `uv run python -m formal.extractors.extract_security_constants`
   rewrites exactly that one line to 39, matching CI's diff. The branch diff
   touches no `formal/` file. Repair: regenerate + commit the artifact.
2. CI `test` FAILURE — stale root smoke tests. Repo-level
   `tests/api/test_health.py:21-36` still asserts `service`, `version`, and
   `uptime_seconds` on public `/health`, all deliberately removed by the #365
   minimization (server-side `tests/api/test_health.py` was updated, this
   twin was missed — incomplete cutover). Reproduced locally:
   `uv run pytest tests/api/test_health.py -q` → 2 failed
   (`KeyError: 'service'`, `KeyError: 'uptime_seconds'`); CI log shows
   "2 failed, 3551 passed" with exactly these two. Repair: cut the root
   smoke tests over to the minimal liveness contract (or retire the
   superseded assertions), keeping a real probe of the public surface.

These are functional-gate defects, not cosmetics: required CI cannot go green
until both are repaired. Functional #365 acceptance itself is fully proven
locally (all eight acceptance criteria executed this round).

### Process record

- PR #1457 body ("Refs #365" only, draft) and all 14 branch commit messages
  contain no premature closure keywords (`fixes/closes/resolves #N`: 0
  matches).
- The extractor drift induced as finding-1 evidence was restored to committed
  bytes before this note was written; this note is the only tree delta.

## Eighth verification (develop-sync repair round, head abc983810 + notes)

Started from the preserved merge-conflict state (3 unmerged files vs develop
`ca4caec7d`). Resolved in place and merged, then merged current `origin/develop`
(`031bd0746`) cleanly.

- Merge resolution `985c4f781`: #1567 readiness diagnostics reconciled with
  #365 — whole detailed payload admin-gated; minimal contract for everyone
  else (see `issue-365-health-readiness-reconciliation.md`).
- Prior finding-1 (formal constants drift) is resolved structurally by
  develop's oracle cutover: `formal/generated/security-constants.json` and the
  extractor no longer exist anywhere; `check-formal-oracle-independence.py
  --base 031bd0746` OK.
- Prior finding-2 (root `tests/api/test_health.py` stale smoke) fixed in
  `abc983810`; root `tests/api` 86 passed.
- Live full-app probes (18/18 PASS at this head): anonymous `/metrics` 401/no
  families; arbitrary bearer 401; wrong-scope service key 403/no families;
  forwarded headers alone 401; scoped scraper 200 with 23 families via
  X-Service-Key and Bearer, also through proxy headers; `/health`,
  `/health/live` exactly `{"status":"ok"}`; `/health/startup` only
  `{status, startup_complete}`; `/health/ready` anonymous/auth-disabled status
  only. Reconciliation probe with real keys: user-scope and wrong-token get
  `{"status":"ok"}`; admin gets the full payload including
  `effective_resource_policy`, `container_limits`, `strike_tracker`.
- #818 re-proven: 300 random attacker paths added exactly 1 new
  `http_requests_total` route label (`unrouted`); no attacker URL in any
  label; label-key audit: `dependency, le, method, outcome, route, status`.
- Registry backstop re-proven: `max_metrics_per_registry=50` rendered exactly
  50 of 200 minted dynamic families; refusals counted in
  `metrics_registry_overflow_total`.
- Alembic on live pg18 (container `auto-365-pg`, port 55445):
  `upgrade head` to `042` clean; ScriptDirectory single head `042`, 44
  revisions, `033` resolves — the historical KeyError '033' stays dead.
- Formal conformance models: 664 passed (`pytest formal/models/
  --timeout=300 --hypothesis-seed=0` with `MAISTRO_TEST_PG_DSN`), including
  the PostgreSQL-backed I29 lease/fence model.
- Gates at this head: `ruff check .`, `ruff format --check .` (2576 files),
  mypy six packages (721 files), `check-doc-links.py`,
  `check-m1-convergence-freeze.py --base 031bd0746`,
  `check-formal-oracle-independence.py --base 031bd0746`,
  `check_enumerations.py` (no new gaps), `check-ac-state.py`,
  `check-suite-inventory.py`, `check-vulture-baseline.py ...` all exit 0.
- Vulture CI-repair: `container_limits` finding eliminated at the source
  (local binding mirroring develop's shape) rather than banked;
  trusted-base-authorized `uptime_seconds` identity banked in the candidate
  ledger; gate exit 0 with no unbanked/unauthorized identities.
- maistro-server suite 395 passed; core targeted (metrics/SLO/resource-policy
  103, security 1309/1310).
- Pre-existing, NOT lane-caused:
  `packages/maistro-core/tests/security/test_log_redaction.py::test_install_is_idempotent`
  fails under pytest 9.1.1 whenever the logging plugin attaches its capture
  handlers (passes with `-p no:logging`); reproduced with a minimal fixture
  file importing only develop-identical code, so develop's own tree has the
  same failure in this environment. Neither the test nor
  `maistro/security/log_redaction.py` is changed by this branch.
- Prior stale findings (PostgreSQL coverage KeyError '033', integration-scope
  durable-events, Gate C coincurve/3.14) were already reported green at
  `7cf1052ad` by the seventh verification and are superseded by the live
  alembic/formal evidence above where re-checked.

## Ninth verification + ledger repair (repair lane, head 0f8f793d8)

Ninth independent run. The prior deterministic verifier run (job
`dfe355152de240aa80e8539a8e53ba11`) failed exactly one check:
`check-suite-inventory.py` exiting 2 with `recorded suites with no collection
recipe: tests`. The "develop sync conflict preserved in worktree" block from
that round resolved as a no-op: the worktree arrived clean at `0f8f793d8`,
which is itself the merge of the develop base `d2c74137d` into auto-365
(merge commit `0f8f793d8`, no unmerged paths).

### Root cause and repair of the ledger failure

`issue-365-health-readiness-reconciliation.md` recorded an
`inventory-delta` line `tests: +0`. `tests` (no trailing slash) is not a
`RECIPES` key in `check-suite-inventory.py` — the root suite is keyed
`tests/` — and the gate deliberately refuses any recorded suite it cannot
collect. The line also recorded nothing: the root `tests/api/test_health.py`
cutover it documented kept the same item count, and per the ledger's own
design a change that moves no count records no delta. Repair: delete the
`tests: +0` line (keeping the valid `packages/maistro-server/tests: +2`).
No count moved; no inventory-delta for this note edit.

### Freshly executed evidence at this head

- `uv run python scripts/check-suite-inventory.py`: **exit 0, all 14 suites
  match the recorded inventory** (full collection: core 11260, server 400,
  root tests/ 3995, formal/ 664, etc.); the verifier's exact scoped
  invocation `--suite packages/maistro-core/tests` also exits 0.
- `uv run ruff check .`: pass. `uv run ruff format --check .`: 2584 files,
  pass.
- Vulture exact-debt-ledger CI-repair gate
  (`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`): **exit 0** — 1403 reviewed identities →
  1402 findings, baseline base d2c74137df82 → candidate 0f8f793d83bd, no
  unbanked or unauthorized identities (the eighth round's ledger repair
  still holds; no further amendment needed).
- Focused pytest (core `test_metrics.py` + `resilience/test_slo.py` +
  `security/test_resource_policy.py`; server `test_metrics.py`,
  `test_health.py`, `test_rate_limit.py`,
  `test_resource_policy_health.py`, `test_strike_tracker_health.py`; root
  `tests/api/test_health.py`): **162 passed**.
- Independent full-app acceptance probe (`maistro_server.main.app` via
  TestClient, per-IP limiter raised probe-only via
  `RATE_LIMIT_PER_MINUTE`/`RATE_LIMIT_BURST` env so the adversarial flood
  is measured rather than throttled): **27/27 checks pass** —
  anonymous `/metrics` → 401 generic body, zero metric families; arbitrary
  user Bearer → 401; wrong-scope service key → 403, no families;
  `X-Forwarded-*` alone → 401; scoped scraper → 200 Prometheus exposition
  via `X-Service-Key`, `Authorization: Bearer sk-svc-…`, and through proxy
  headers, payload contains no key material; `/health` and `/health/live`
  exactly `{"status":"ok"}`; `/health/startup` only
  `{status, startup_complete}`; `/health/ready` anonymous → 503 exactly
  `{"status":"not_ready"}` with no dependency detail; user-scope →
  status-only; admin → full detailed payload (checks,
  effective_resource_policy, container_limits, strike_tracker).
- #818 re-proven on the full app: 300 distinct random 24-char attacker
  paths added exactly **1** new `http_requests_total` series
  (`route="unrouted"`, status 404); no attacker-controlled text appears in
  any label value; live label keys across the rendered registry are exactly
  `dependency`, `le`, `method`, `outcome`, `route`, `status`.
- Registry family backstop re-proven first-hand:
  `MetricsRegistry(max_series_per_metric=10, max_metrics_per_registry=50)`
  minted 200 dynamic families → 50 rendered, refusal count 150.0 in the
  unlabeled `metrics_registry_overflow_total` (read via `collect_all()`).

## Tenth verification (verifier lane, head 07957e3f5)

Prior block carried into this round — "develop sync conflict preserved in
worktree" — did not manifest: the worktree is clean at 07957e3f5, which is
exactly the merge of the develop base 8bfd35903 into auto-365 (committed by
the prior round). No conflict resolution was needed; verification ran at that
head unchanged.

Freshly executed evidence at this head (all commands run by this round, not
inherited):

- `uv run ruff check .`: pass. Driver's `uv sync --locked --extra dev`,
  `ruff format --check .` (2585 files), and both `scripts/check-suite-inventory.py`
  scoped gates (core 11287, server 400) re-run: all exit 0.
- Focused pytest (same eight suites as the driver plus root
  `tests/api/test_health.py`): **142 passed**.
- Independent rate-limit-mounted TestClient probes: anonymous `/metrics` →
  401 generic body, zero metric families; arbitrary user-format Bearer → 401
  (service-key provider only accepts `X-Service-Key` / `Bearer sk-svc-*`);
  wrong-scope service key → 403 with no families; `X-Forwarded-*` alone →
  401; scoped scraper → 200 via `X-Service-Key`, via `Bearer sk-svc-…`, and
  through proxy headers; `/health` and `/health/live` exactly
  `{"status":"ok"}`; `/health/startup` only `{status, startup_complete}`;
  `/health/ready` anonymous → status-only body.
- #818 adversarial flood re-proven with the default limiter left enabled:
  round 1 (400 distinct random paths) added only bounded `route="unrouted"`
  series (404 plus the flood's own 429); round 2 (400 brand-new random
  paths) added **zero** new series; no attacker-controlled text appears in
  any rendered label.
- Registry backstop re-proven on a fresh
  `MetricsRegistry(max_series_per_metric=10, max_metrics_per_registry=50)`:
  200 minted families → exactly 50 caller families rendered, refusal count
  150.0 in the unlabeled `metrics_registry_overflow_total`; series-cap
  overflow count matched slot arithmetic (9 free slots after the unlabeled
  series → 21 of 30 new label sets dropped, counted, existing series still
  updatable).
- SLO credential leakage closed: `ErrorBudget.publish` emits only a
  16-hex digest label; the raw service key never reaches the exposition.
- Closure-keyword review: PR #1457 body ("Draft auto-opened … Refs #365")
  and all branch commit messages contain no fixes/closes/resolves tokens.

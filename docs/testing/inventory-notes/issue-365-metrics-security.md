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

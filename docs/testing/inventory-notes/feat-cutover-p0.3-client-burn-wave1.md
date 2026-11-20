# Inventory note — P0.3 typed-client debt burn wave 1 (#1995)

Rebased onto current `develop` after organic burns past the original
wave-1 ledger (60→43 raw / 142→131 hand-typed). Those earlier page
migrations landed via other PRs; this branch keeps only remaining
wave-1 value without regressing the develop floor.

## Changes

- Add `packages/hive-conductor/frontend/src/api/entities.ts` (OpenAPI
  aliases from `types.gen.ts`, plus path-derived / loose demo+provider
  shapes).
- Route remaining bare `fetch(` sites through `lib/api` helpers:
  AccountBanner logout, TemplatePicker demos, Settings elevate,
  LlmProviders list/key/activate.
- Drop the local `Template` type and LlmProviders local interfaces in
  favor of `entities.ts`.
- Preserve develop's AuthorizationContext / AuthorizationNotice on
  LlmProviders and Settings (do not reintroduce #2283 debt).

## Ratchet

`quality/frontend-typed-client-baseline.json`: **42 → 40** raw fetch,
**120 → 119** hand-typed (net of develop's already-lower floor).
(An earlier draft of this note said 124 → 123 hand-typed; that figure
predated the final rebase and disagreed with the ledger JSON — the gate
run below is the authority.)

## Verification (repair round, head `6b8c0921ecab`)

The hosted run at this head shows no content-gate failure: every leaf job
was `cancelled` by a concurrency supersede at 11:07Z and only the
`if: always()` aggregators (`Quality gate (Pillars 1–4, 7, 8)`,
`SAST (bandit + semgrep + gitleaks)`) then failed on cancelled needs.
The change-bearing gates were re-run locally with CI's exact arguments,
all green:

- `uv run python scripts/check-frontend-typed-client.py` → exit 0
  ("40 raw fetch and 119 hand-typed declaration(s) tolerated, none new").
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0 (1253
  identities, exact ledger match, `unclassified: 0`).
- `uv run python scripts/check-ratchet-provenance.py` → exit 0.
- `uv run python scripts/check-shipped-surface-truth.py` → exit 0
  (matrix complete after dropping the 4 stale `mutating-api-call` rows).
- SAST legs: bandit Medium+ count 0; semgrep 1.182.1, 364 rules, 0
  findings with `--error`; gitleaks 8.30.1 over
  `78133c093..6b8c0921` — no leaks.
- `uv run python scripts/check-doc-links.py` → exit 0 (CHANGELOG fix).
- `npm run build` in `packages/hive-conductor/frontend` → exit 0.

The diff vs merge base `78133c093` touches no Python and no workflow
files, so the Python-only quality pillars measure trees identical to
protected `develop`. Settings/Skills/Profile smoke from the original
test plan remains UNVERIFIED here — it needs the live stack.

## Verification (develop-sync round, head `ff367f356`)

The preserved `origin/develop` sync conflict (CHANGELOG.md, three-way
diff3 on the CodeQL scope-test Unreleased line) was resolved by taking
develop's wording (`#2359; follow-up to #2357`, a superset of the
branch-side `#2359` edit), and `origin/develop` (`10f872fa7be3`) was
merged; merge head `ff367f356`. Every gate was re-run locally at the
new head, all green:

- `uv run python scripts/check-frontend-typed-client.py` → exit 0:
  base `10f872fa7be3` → candidate `ff367f356f69`, **42 → 40 raw fetch,
  120 → 119 hand-typed, none new**.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0: 1248
  identities, exact ledger match, `unclassified: 0`,
  `never_allowlist: 0` (count moved 1253 → 1248 with develop's own
  churn; the ledger needed no candidate-side amendment).
- `uv run python scripts/check-shipped-surface-truth.py` → exit 0
  ("matrix is complete"; the 4 stale `mutating-api-call` rows stay
  dropped).
- `uv run python scripts/check-ratchet-provenance.py` → exit 0.
- `uv run python scripts/check-doc-links.py` → exit 0 (covers the
  resolved CHANGELOG conflict).
- `uv run python scripts/check-release-consistency.py` → exit 0.
- `uv run python scripts/check-suite-inventory.py` → exit 0 (21
  suites match; the branch adds no tests, and a no-count note records
  no `inventory-delta` block by design).
- `uv run ruff check .` and `uv run ruff format --check .` → clean.
- `npm run build` in `packages/hive-conductor/frontend` → exit 0
  (tsc + vite, built in ~2s).

The wave-1 SSE waiver holds at this head: the Profile stream fetch
lives under `lib/profile.ts` (detector-exempt, per its own comment
about the 30s shared-client body budget). Live-stack smoke
(Settings load/save, Skills list, Profile stream, `hctl status`)
remains UNVERIFIED.

## Verification + supply-chain repair round, head `42d433c2c3c2`

Branch merged `origin/develop` (`f8a2df966a1d`, the then-tip) so the
merge base measures the tree the queue integrates into; `origin/develop`
still resolved to `f8a2df966a1d` at repair time (no newer sync needed).
All branch-content gates re-run green at the merge head:

- `uv run python scripts/check-frontend-typed-client.py` → exit 0:
  base `f8a2df966a1d` → candidate `42d433c2c3c2`, **42 → 40 raw fetch,
  120 → 119 hand-typed, none new**.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0: 1238
  identities, exact ledger match, `never_allowlist: 0` (no candidate
  ledger amendment needed).
- `uv run python scripts/check-shipped-surface-truth.py`,
  `check-ratchet-provenance.py`, `check-suite-inventory.py` (21
  suites), `check-doc-links.py`, `check-release-consistency.py` → all
  exit 0.
- `uv run ruff check .` and `uv run ruff format --check .` → clean.
- `npm run build` in `packages/hive-conductor/frontend` → exit 0
  (tsc ×2 + vite, ~4s).

### Supply chain (pip-audit) — reproduced and repaired

The hosted failure was reproduced locally against the frozen env:
four advisories outside the triaged allowlist — dnspython 2.9.0
CVE-2026-128089 (fix 2.9.2), graphql-core 3.3.0 CVE-2026-119286 (fix
3.3.1), joserfc 1.7.5 CVE-2026-119284 (fix 1.7.6), opentelemetry-api
1.45.1 CVE-2026-126360 (fix 1.45.2). The branch's diff touches no
Python dependency input (no `uv.lock`, no `pyproject.toml`), so the
advisories fail identically on the develop base — trunk drift, not a
regression — but they are concretely fixable, so this round fixed them
per the gate's own instruction ("Fix by upgrading the dependency") and
the documented `constraint-dependencies` precedent (#891/#2238, #1084,
CONNECT tip #2327 rounds):

- Dev transitive floors raised in `[tool.uv] constraint-dependencies`:
  `dnspython>=2.9.2` (was 2.9.0), `graphql-core>=3.3.1` (was 3.3.0),
  new `joserfc>=1.7.6` — each annotated with the advisory and round.
- Production floor raised where the package actually ships:
  `opentelemetry-api>=1.45.2` in the root `dependencies` and
  `>=1.45.2,<2` in `maistro-core`'s `observability` extra.
- `uv lock` moved exactly the 6-package security closure (the four
  targets plus opentelemetry-sdk and opentelemetry-semantic-conventions
  pulled by the sdk); `uv sync --locked` clean.
- CI-exact re-run (`uv sync --locked --all-extras` → freeze →
  `pip-audit --strict` → `scripts/pip_audit_gate.py`) → exit 0:
  "pip-audit OK (1 known, all triaged in ALLOWED)"; direct-dependency
  usage OK.
- The hive-conductor runtime export (`uv export --locked --package
  hive-conductor --no-dev`) contains exactly one of the four packages —
  opentelemetry-api, now 1.45.2 — so the image's Python closure clears
  the advisory set too. `maistro-core[observability]` (the image's
  second dependency contract) imports cleanly at 1.45.2 with the
  tracer resolvable.

### Container scan + SBOM + cosign — not branch-attributable, partially addressed

The hosted log excerpt carries no step-level finding (bare exit 1).
This branch cannot introduce HIGH/CRITICAL image findings: it changes
no Dockerfile, no npm dependency, and its only image-relevant input is
frontend TS source. The single image-visible Python advisory
(opentelemetry-api) is fixed by the lock bump above; an OS-package or
infrastructure verdict (the workflow documents the libexpat/cache
classes) would fail identically on develop and needs a hosted re-run —
UNVERIFIED locally by design (a 4-image Trivy/Grype pipeline does not
fit this repair round's budget).

`security` is the workflow-level aggregate: its SAST legs passed on
this head and its remaining children are the two jobs above.


### Repair round (job 5bd9c302, head 2da5e0f35)

- DevSkim scope test `tests/test_devskim_scan_scope.py` (the 30s timeout
  failure) now completes in 8.7s after the os.walk pruning; 21 passed.
- Container images built locally and scanned with Trivy 0.73.0 against
  `.trivyignore.yaml`: `cr1995-engine:test` and `cr1995-hive:test` both
  report 0 HIGH/CRITICAL (exit 0).
- Frontend typed-client gate: 40 raw fetch / 119 hand-typed, none new.
- ruff check/format, mypy, vulture, ratchet-provenance, shipped-surface-truth,
  frontend-api-routes, suite-inventory: all green.

## Verification + service-backed gate round, head `f4c1dedf4080`

Named-gate reproduction against real services (no test additions; counts
unchanged). All commands run with CI's exact arguments/env unless noted:

- `tests/test_devskim_scan_scope.py` → 21 passed in 10.09s (the CI 30s
  pytest-timeout kill is gone; the coverage `scripts` producer no longer
  dies on it).
- Full coverage `scripts` producer
  (`pytest tests/ tests/test_model_check_consumer_claim.py
  packages/maistro-core/tests/extensions/test_lifecycle_proof.py
  --timeout=30 -q`) → **5932 passed, 139 skipped** in 8m12s; no
  `Event loop is closed` errors. (First attempt under concurrent docker
  load showed one order-dependent failure in
  `test_check_connection_credentials` that passed in isolation, passed
  via `scripts/check-connection-credentials.py`, and did not recur in a
  clean re-run; it is absent from CI's own log at this head. Not
  branch-attributable; recorded as residual flake evidence.)
- `uv run mypy` over the ten package src trees (CI's exact argument
  list) → success, 1120 files.
- Compliance registry: `python scripts/check-compliance.py` → exit 0.
- `pytest tests/cross_product_parity` → 26 passed.
- Postgres matrix (pgvector pg17 + pg18 via docker, CI step order:
  chain test → alembic up/down/up → suites, `MAISTRO_REQUIRE_PG_LEGS=1`):
  migration chain 18 passed on both majors; persistence 854 passed on
  both; `test_container_postgres.py` 15 passed on both; workspaces 420,
  personas 133, goals 184, canvas supported path 7, design supported
  path 4, scheduler 327+32, workspace authority durable 24 — all
  passed. (First container-test failure was local sequence drift — the
  DB had not been `alembic upgrade head`-ed before the batch; CI order
  re-run green.)
- durable-events (plain postgres:17, `MAISTRO_REQUIRE_PG_LEGS=1`):
  `packages/maistro-core/tests/events` → 513 passed, 5 skipped;
  `tests/migrations/test_event_schema_agreement.py` → 5 passed.
- object storage: MinIO built from the pinned Go pseudo-version
  (`v0.0.0-20250422221226-0d7408fc9969`), archive conformance → 128
  passed.
- docker-build legs the branch touches: root `Dockerfile` (with the
  docker-CLI 29.9.3 stage — tag verified via `git ls-remote`:
  `v29.9.3^{}` = `5457199aa57c…`, matching the Dockerfile pin) → built
  exit 0; `packages/hive-conductor/Dockerfile` (frontend npm ci + build
  stage, locked venv) → built exit 0; shipped hive image carries
  opentelemetry-api 1.45.2 (the branch's security floor).
- hive-conductor-e2e: `docker compose --profile test up --build
  --exit-code-from api-tests` against the branch-built image → exit 0
  (10 passed, 13 env-conditional skips in PM mode, same class as CI).
- hive-conductor-compose-durability:
  `scripts/verify-compose-durability.sh` (isolated project, host port
  remapped only) → 34/34 checks passed, full create → write → recreate
  → read → backup → restore round trip holds.
- lint-and-type-check script legs: verify-monorepo-layout,
  check-merge-markers, check-cross-package-imports,
  check-extension-imports, check-compose-resources,
  check-durable-table-inventory, check-promotion-surface,
  check-connection-credentials, check-owned-store-access,
  check-public-routes, check-shell-execution, check-build-context,
  check-api-route-contracts, check-secret-field-labels,
  check-retired-guidance, check-compose-secrets → all exit 0.
- `scripts/check-vulture-baseline.py` (CI-exact args) → 1238 reviewed
  identities == 1238 findings, `unclassified: 0` (no ledger amendment
  needed this round).
- `npm run build` in the frontend → exit 0; typed-client ratchet → 40
  raw fetch / 119 hand-typed, none new; frontend-api-routes → 217 call
  sites resolve.

Not re-executed locally this round: `hive-conductor-e2e-ui` (Playwright
stack too heavy for this round's budget; the hive image serving the new
bundle is proven by the api e2e + durability rounds above) and
`docker-rebuild-compare` (two no-cache engine rebuilds; the build itself
is proven green and the compared manifests are hash-pinned by
`--require-hashes` lock install, so rebuild variance is bounded to
base-image digest drift, which the branch does not change).

## Verification (service-backed closure round, head `bf9b7196012e`)

Both items left open by the previous round were executed for real this
time, against services (local docker daemon, same compose files CI
uses), plus a first local trivy pass over the branch-touched images:

- `hive-conductor-e2e-ui`: `docker compose -f docker-compose.test.yml
  --profile test up --build --abort-on-container-exit --exit-code-from
  e2e-tests e2e-tests` → **246 passed** in 5.2m, compose exit 0. (A
  first attempt exited 1 from a stale orphaned `e2e-tests` container of
  a previous compose project hash dying with SIGTERM under
  `--abort-on-container-exit` — a state a fresh CI runner cannot have;
  `down -v --remove-orphans` then a clean re-run passed. The rebuilt
  hive image carries this branch's frontend bundle.) Settings page
  load, Skills list, and Profile `whoami` from the issue's smoke plan
  are covered inside that suite (`navigation-coverage.spec.ts` pins
  `/settings` and `/skills` headings; `app-shell-loading.spec.ts` and
  the workspace specs pin `whoami`); the Profile summary SSE stream and
  `hctl status` remain manual-only.
- `docker-rebuild-compare`: two independent no-cache engine rebuilds
  via `scripts/buildx-build-retry.sh -- -f Dockerfile -t
  maistro-engine:rebuild-{a,b} --no-cache --load .` → both exit 0, and
  the venv distribution manifests diff clean — "two independent
  rebuilds produced identical dependency manifests (126
  distributions)". The rebuilt image carries `opentelemetry-api
  ==1.45.2` (the branch's security floor).
- Trivy (CI-pinned v0.73.0, CI-exact flags `--severity HIGH,CRITICAL
  --exit-code 1 --ignore-unfixed --ignorefile .trivyignore.yaml`) over
  the two images the branch's Dockerfile changes actually feed:
  branch-built `hive-conductor` (frontend bundle from this tree) and
  branch-built `maistro-engine` (docker-CLI 29.9.3 stage, in-image
  `docker --version` = `v29.9.3, build 5457199`) → both exit 0. The
  research/rsi-runner images differ from develop only through the
  6-package lock closure (their Dockerfiles and CLI pins are untouched);
  cosign keyless signing and the SBOM attest step are hosted-OIDC only
  and stay with the hosted re-run.
- Branch-content gates re-confirmed at this head (docs-only since
  `2da5e0f35`): typed-client 40 raw / 119 hand-typed none-new, vulture
  1238 == 1238 unclassified 0, compliance registry, shipped-surface,
  suite inventory (21 suites), ruff pair, mypy 1120 files (CI arg
  list), devskim scope 21 passed in 8.72s, cross-product-parity 26
  passed, frontend `npm run build` exit 0, frontend-api-routes 217
  sites → 257 routes, `hive-conductor-e2e` re-run → exit 0 (10 passed),
  `verify-compose-durability.sh` re-run → exit 0.
- npm dependency manifests are byte-identical to the merge base
  (`git diff <base>..HEAD -- '**/package.json' '**/package-lock.json'`
  is empty), so the containers job's frontend license surface is
  unchanged by the branch.

## Container-gate repair + develop sync round, heads `19d7c26e74` → `de535c9945`

### Hosted evidence at `18c9263438` (the previously failing check)

The merge-queue evaluation of `18c9263438` had exactly one failing check:
`Container scan + SBOM + cosign` (run 43892977838, job 133388832382).
Reading the fetched job log pinpoints the failing step — **`Trivy scan
maistro-engine-research (HIGH/CRITICAL only)`** — every build and the
hive/engine Trivy scans passed; the rsi-runner scan, Grype, SBOM and
reconciliation legs never ran (skipped after the failure). The findings:
13 HIGH python-pkg advisories (oauthlib 4.0.0 CVE-2026-49272; pyasn1
0.6.4 CVE-2026-119194..119197; pypdf 6.21.2 CVE-2026-119203..119209;
soupsieve 3.0.3 CVE-2026-126190) plus go-jose v4.1.5 CVE-2026-116587
(HIGH) inside the image's `usr/local/bin/docker`. The `npm audit` excerpt
in earlier handoff notes was stale — no npm step failed in this job.

### Round one — branch-side fix (`19d7c26e74`, salvaged from the interrupted attempt)

- Raise the four constraint floors (oauthlib>=4.0.1, pyasn1>=0.6.5,
  pypdf>=6.21.4, soupsieve>=4.0.0) and pin `Dockerfile.research` to
  docker CLI v29.9.3 = 5457199. Lock moves exactly the four packages
  (oauthlib 4.0.1 / pyasn1 0.6.5 / pypdf 7.1.0 / soupsieve 4.1.1);
  verified the four ship **only** in the research export (hive, engine
  `--extra image` and rsi-runner exports carry none), so no other image
  changes. Tag verified via `git ls-remote --dereference`:
  `v29.9.3^{}` = `5457199aa57c…`, v29.9.3 vendors go-jose v4.1.7 ≥ the
  4.1.6 fix (v29.9.1 = dfc520d vendored vulnerable v4.1.5), both checked
  against upstream `vendor.mod`.
- Local `docker build -f Dockerfile.research` → exit 0 (`uv pip check`,
  browser-use/playwright assert, `maistro_server.main` import smoke ok;
  in-image `docker version` = v29.9.3).
- Trivy 0.73.0 (CI-pinned), CI-exact flags (`--severity HIGH,CRITICAL
  --exit-code 1 --ignore-unfixed --ignorefile .trivyignore.yaml`) →
  **exit 0**: debian 0, every python-pkg target 0, `usr/local/bin/docker`
  gobinary 0.
- `check-image-lock-reconciliation.py` (CI-exact) → exit 0: "ships
  exactly the locked set (147 distributions)".
- **Grype cross-check (local, fresh DB) → exit 2** on the r2 image:
  5 HIGH+ matches — node 24.21.0 (the binary patchright/playwright
  wheels bundle as their driver) CVE-2026-111497 (Critical, KEV) +
  CVE-2026-105482/105483/106069 (High) and python 3.12.15
  CVE-2026-115557 (Critical, CPE). This reproduced the gate's *next*
  failing leg before CI could.

### Round two — develop sync (`de535c9945`)

`origin/develop` (tip `f927334a2e`, two commits ahead: `157c3f61`,
`f927334a2e`) had landed a **superset repair of the same gate** (CR1373
CI-repair round, merge-queue run 43821935433): the same four python
floors, plus `patchright>=1.64.4` / `playwright>=1.65.2` for exactly the
node-binary findings reproduced above, `temporalio>=1.36.1` for the
wheel-shipped Cargo.lock zip CVEs, an x/net v0.62.0 patch onto the docker
CLI tag (CVE-2026-78661, previously only suppressible), and refreshed
base-image digests (python 3.12.16 / 3.13.18). Merged `origin/develop`
and resolved the three conflicts in place:

- `Dockerfile` / `Dockerfile.research`: develop's side taken wholesale
  (superset of the branch's committed CLI bump; the branch's version is
  recorded in `19d7c26e74` history).
- `pyproject.toml`: develop's constraint block taken (its entries are a
  superset of both the branch's `35c005ea4d` pip-audit floors and its
  `19d7c26e74` container floors; superseded comment blocks noted
  in-line). The branch keeps its two extras develop lacks: the root
  `opentelemetry-api>=1.45.2` production floor and the
  `maistro-core[observability]` `>=1.45.2,<2` floor.
- `uv.lock`: develop's lock re-generated with the pinned uv 0.12.21
  (`uvx uv@0.12.21 lock`; identical delta under 0.12.20, so not a
  resolver-version artifact). Delta vs develop's lock = the two
  opentelemetry floor specifiers above + completion of the darwin-only
  `pyobjc-framework-pubsub` closure (marker-gated; no Linux image
  surface).

### Post-merge validation (all CI-exact args, head `de535c9945`)

- `uvx uv@0.12.21 lock --check` → exit 0; `uv sync --locked --extra
  dev` and `uv sync --locked --all-extras` → exit 0 (temporalio
  1.34.0 → 1.36.1 in the dev env).
- Research image rebuilt from the merged tree (r3) → exit 0, smoke ok;
  in-image `docker version` = v29.9.3.
- Trivy 0.73.0 CI-exact over r3 → **exit 0** (debian 0, docker gobinary
  0).
- **Grype 0.116.0 CI-exact (`--fail-on high --only-fixed`) over r3 →
  exit 0** — the node-binary and python-3.12.15 Critical/High legs that
  failed on r2 are gone (patchright 1.64.4 bundles node 24.22.1, base
  python is 3.12.16); remaining rows are Medium/Low/Negligible or
  `*`-marked not-affected, below the high threshold.
- `check-image-lock-reconciliation.py` over r3 → exit 0 ("ships exactly
  the locked set (147 distributions)").
- `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → exit 0 (1236 identities, exact ledger
  match; develop's −2 rows merged in, no candidate amendment needed).
- `check-frontend-typed-client.py` → exit 0 (40 raw / 119 hand-typed,
  none new). `check-shipped-surface-truth.py` → exit 0 (matrix
  complete). `check-suite-inventory.py` → exit 0 (21 suites, 35459 node
  IDs — develop's new suites merged into the recorded inventory).
  `check-ratchet-provenance.py` → exit 0 (55 consumers, 0 expansions).
- Supply chain CI-exact (`uv sync --locked --all-extras` → freeze →
  `pip-audit --strict` → `pip_audit_gate.py`) → exit 0 ("1 known, all
  triaged in ALLOWED; direct-dependency usage OK").
- `uv run ruff check .` / `uv run ruff format --check .` → clean;
  frontend `npm run build` → exit 0.

### Residuals

- The other three images are not rebuilt locally post-merge: their
  Dockerfiles change only through develop's committed base-digest/CLI
  updates (green on develop's own CI at `f927334a2e`), and this branch's
  post-merge delta moves no package they ship except `temporalio`, whose
  1.36.1 floor is develop's own green-landed change. Hosted re-run will
  confirm.
- The SBOM/license/cosign legs are hosted-OIDC-only (unchanged from the
  previous round's note).
- `.trivyignore.yaml`'s CVE-2026-78661 entry (x/net in the docker CLI)
  is now arguably stale — both Dockerfiles patch x/net onto the tag —
  but develop kept the entry and removing a suppression is a
  maintainer-scoped re-scan decision, not this lane's.

## Verification (queue-evaluation audit round, head `bdd229822a18`)

Two more develop merges landed on top of `de535c9945` (lizard 1.25.0
via `3d10c5831e`, develop tip `d0e8e235a896` — node 22→26-alpine base
bump + refreshed image pins/package-locks — via `bdd229822a`); both
merges resolved conflict-free. This round audited the branch against
the merge queue's own evaluation of this exact head rather than the
stale "gates red" claims, which attach to older heads (`18c9263438`
and earlier).

Hosted evaluation at `bdd229822a18` (captured 2026-11-18T01:09Z):
**125 of 126 check runs `success`, 1 `skipped`** — the skip is the
duplicate `Container scan + SBOM + cosign` leg of the redundant SAST
workflow run (`44118631184`); the primary run (`44118647009`) ran the
same job to `success`. Every gate named in earlier block notes
(Compliance registry, cross-product-parity, docker-build,
docker-rebuild-compare, durable-events, compose-durability, e2e,
e2e-ui, lint-and-type-check, MinIO, pg17/pg18, Coverage, Quality,
exact-debt-ledger, `block`) is `success` at this head. The eight
`gates-ran` commit statuses stuck at `pending` are board-accounting
artifacts, not gate results.

Local re-validation at this head (writer round, 2026-11-18):

- `uv run python scripts/check-frontend-typed-client.py` → exit 0:
  base `d0e8e235a896` → candidate `bdd229822a18`, **42 → 40 raw
  fetch, 120 → 119 hand-typed, none new** (the PR body's 60 → 43 /
  142 → 131 figures describe the original pre-rebase base; the note's
  "Ratchet" section above is the current authority).
- `uv run python scripts/check-shipped-surface-truth.py` → exit 0
  ("matrix is complete"; the 4 stale `mutating-api-call` rows stay
  dropped).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0 (1236
  identities, exact ledger match, `unclassified: 0`); no ledger
  amendment needed this round.
- `uv run python scripts/check-suite-inventory.py` → exit 0 (21
  suites, 35490 unique node IDs, 0 duplicates).
- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- `uv run pytest tests/test_devskim_scan_scope.py -q` → 21 passed.
- `uv run pytest tests/test_prepull_base_images.py -q` → 28 passed
  (develop's node-bump pin/lock refreshes).
- `uv lock --check` → consistent (468 packages).
- `npm run build` in `packages/hive-conductor/frontend` → exit 0
  (tsc --noEmit on both configs + vite, ~3s).
- `npm run lint` → exit 0, 0 errors, 94 warnings against the 96
  budget.
- Zero raw `fetch(` remaining in the four migrated frontend files
  (AccountBanner, LlmProviders, Settings, TemplatePicker); the SSE
  waiver still lives under `lib/` (`lib/profile.ts`, `lib/chatSessions.ts`).

Residuals unchanged: live-stack smoke (Settings load/save, Skills
list, Profile stream, `hctl status`) remains UNVERIFIED locally — it
is covered by the hosted `hive-conductor-e2e` / `hive-conductor-e2e-ui`
jobs, both `success` at this head.

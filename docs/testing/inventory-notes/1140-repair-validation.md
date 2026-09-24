---
inventory-delta:
  packages/hive-conductor/backend/tests: +16
  tests/: +11
---

# Issue #1140 repair checkpoint

Frozen scope: issue #1140 only, starting head `146e2c25410f8d2babfffbc819defc6a592da97a`, base `ffd6fdb16da57abd0a51198016e44b878be470d5`. Inspect shared route policy/checker, both auth middleware and adjacent tests, CI, relevant ADRs, and inventory notes. Repair targets: Conductor existing authorization behavior and SPA fallback route declaration; tests and documentation confined to those concerns. No GitHub mutations.

Initial evidence: clean assigned worktree. Prior result reports remote merge-candidate fallback declaration failure and audit/settings 403 regressions. Current job has no check logs. Prior local successes are not assumed valid.

Reproduced architecture evidence: the current registry applies write scopes to GET settings/audit (unlike the trusted base middleware). SPA route registration depends on `STATIC_DIR.is_dir()`, explaining why local source-only discovery passes while built-frontend CI fails. Initial shared-gate tests: 45 passed, without built static assets. Repair will retain method-specific product policy and explicitly classify the static route identity without a catch-all public prefix.

Implementation checkpoint: restore method-specific reads for seven Conductor families with owned, expiring exemptions; preserve elevated writes. Always register the exact SPA handler (404 without assets), declare that identity, and restrict runtime static exemption to requests whose first matching route is that handler. No catch-all URL permission is added. Added live read/write parity and static-boundary tests (+16 Conductor cases), asset-present/absent discovery, real app route injection, and fatal-import tests (+4 root cases). Strengthened both applications' misleading-suffix fixtures with registered unrelated `/invoke` and `/feedback` routes (+4 root cases) and pinned new-bypass rejection/exemption-removal ratchet behavior (+3 root cases). ADR-068 retains Sentinel as tool authorization authority; ADR-081226-6b46 retains Binding permission ceilings. No execution, Goal, or authorization authority is replaced.

Validation checkpoint: `uv run pytest packages/hive-conductor/backend/tests -x -q` passed (2533 passed, 1 existing skip, 93 warnings); focused middleware/static tests passed (74); shared gate tests passed (49); Turing backend suite passed (48); core registry-location tests passed (4). Shared production-app gate against the exact assigned base passed: 20 declarations, unchanged 12 trusted Conductor public identities. Ruff lint passed; format initially identified one test file and was applied to that file only. No gate/baseline/grant weakening is used.

Validation checkpoint 2: repository-wide ruff lint/format and `git diff --check` passed. Inventory gates passed (Conductor 2534 collected; root tests 3531). Expanded root gate/policy/enumeration tests passed (71); provenance suite passed (47); live enumeration gate passed with no new gaps. Docker port 8101 is occupied by an unrelated existing service; do not touch it. Use an isolated compose project with no host port publishing for the foreground API e2e run.

Docker acceptance evidence: foreground `docker compose -p maistro-1140-repair ... up --build --abort-on-container-exit --exit-code-from api-tests hive api-tests`, with stdin override `ports: !reset []`, exited 0 (10 passed, 13 existing skips). Both previously failing cases now pass on the built production image: `TestAuditTrail.test_audit_log_has_entries` and `TestDashboardAPIs.test_settings`, with logged GET `/v1/audit` and `/v1/settings` both 200 for `pmuser`. Containers stopped automatically; unrelated running services untouched. API e2e's existing canonical-execution skips and absent external engine are not changed by this repair.

Ambiguity: prompt includes verifier-only no-edit instructions and writer repair instructions. Proceed as assigned implementation writer, with focused repair and required local commit.

## Final acceptance evidence

- Actual registered apps / complete classification: `RATCHET_BASE_REV=ffd6fdb16da57abd0a51198016e44b878be470d5 uv run python scripts/check-public-routes.py` passes for both production applications. Asset-present and asset-absent Conductor fixtures both include and classify the SPA identity.
- Newly registered routes fail: shared fixtures inject a new route into each actual production app and observe a missing-declaration error. Fatal import fixtures prove neither application is skipped.
- Default-deny / exact semantics: full Conductor backend suite and Turing backend suite pass; static anonymous access is limited to the first-dispatched exact SPA identity, not arbitrary non-API handlers. Unknown API routes cannot borrow it. Both shared fixtures reject unrelated routes ending in `/invoke` or `/feedback`.
- Canonical permission vocabulary / product policy retained: existing Turing canonical-scope and insufficient-scope tests pass, along with all 48 backend tests. Seven Conductor read families preserve session authentication; corresponding writes still reject users without elevated permission. Both reported Docker e2e regressions now return 200.
- Exemptions / provenance: expiry fixtures for both applications, new-public/exempt rejection, exemption removal, trusted authorization tests, and 47 provenance tests pass. No baseline, authorization ledger, or grant was edited. The new registry is still bootstrapped against the assigned base where it was absent; subsequent changes remain ratcheted.
- Required CI wiring: `.github/workflows/ci.yml:179` invokes the shared gate, which imports both applications; the exact command passes locally. Turing startup/enablement and execution authorities are unchanged.

Final combined root validation: `uv run pytest tests/test_check_public_routes.py tests/test_route_permission_gate.py tests/test_m1_542_policy_coverage.py tests/test_check_enumerations.py tests/test_ratchet_provenance.py -x -q` — 125 passed. `uv run ruff check .`, `uv run ruff format --check .`, both changed-suite inventory gates (Conductor 2534, root 3538), live enumeration gate, and `git diff --check` pass.

Residual limits: remote CI and browser/UI e2e were not rerun. The API e2e suite retains 13 existing skips (canonical execution requires services not supplied by that harness); the backend suite retains one existing skip and warnings. No claim is made that these deferred execution paths were validated. Docker validation containers are stopped under isolated project `maistro-1140-repair`; unrelated services were not modified.

Completion: checked 1 issue, done 1 repair, skipped 0 issues, errors 0 in final validation. Next: reviewer handoff of local commit only; no integration or GitHub actions.

## Independent re-validation at head 3100509c (repair-verification job 0100ad81)

Re-ran every gate from scratch against the exact lane base `8bb344e32` / candidate `3100509c39bb`; no code changes were needed, so this section records evidence only (inventory deltas above are unchanged).

- `scripts/check-public-routes.py` passed: both production apps imported (hive + turing service-registry log lines), public-routes ratchet 12 -> 12 identities, 20 unauthenticated paths declared, "both live route tables are declared and authorized".
- Focused suites: root gate/policy/enumeration/provenance 144 passed; `packages/maistro-turing/backend/tests` 52 passed; `packages/hive-conductor/backend/tests` 2671 passed, 1 existing skip; `packages/maistro-core/tests/security` 1301 passed with the single `test_log_redaction.py::test_install_is_idempotent` failure, which fails identically at base `8bb344e32` (pre-existing log-redaction test-isolation defect, untouched by this branch, out of #1140 scope).
- Reported-CI-failure gates re-run green at this head: radon ratchet 70 -> 70 C-blocks; formal `security-constants.json` regenerated with no drift; diff-coverage gate replicated with the CI producers (core, turing src, turing backend, hive backend, root `tests/` as the scripts producer — 10127+177+52+2671+3510 collected) reports all 9 measured changed files at or above the 90%/80% floors.
- Docker E2E re-run in isolated project `maistro-1140-e2e` with `ports: !reset []` (host 8101 is occupied by an unrelated service — the earlier failure was environmental, not a code failure): `up --build --abort-on-container-exit --exit-code-from api-tests` exited 0, 10 passed / 13 existing skips, including the two previously regressed cases (`GET /v1/audit`, `GET /v1/settings` -> 200 for `pmuser`). The built image also proves the packaged registry resolution (`/app/backend/middleware` -> `/app/quality/route-permissions.json`) boots.
- `uv run ruff check .` and `uv run ruff format --check .` clean; suite inventory gates match (Conductor 2672 collected); live enumeration gate reports no new gaps.

## Independent re-validation at head a06bfe875 (repair lane, no code changes)

Re-ran the acceptance battery from scratch at `a06bfe875f6a` against merge-base `8bb344e32b86`; no code or registry change was needed, so this section is evidence only.

- `scripts/check-public-routes.py`: both production apps imported live, 20 unauthenticated paths declared and base-authorized, public-routes ratchet 12 -> 12 identities, "both live route tables are declared and authorized".
- Focused suites: root gate `tests/test_route_permission_gate.py` 49 passed; `packages/maistro-core/tests/security/test_http_route_policy.py` + `test_route_registry_location.py` + `packages/maistro-turing/backend/tests/test_auth.py` 61 passed; `packages/maistro-turing/backend/tests` 52 passed; Conductor `test_auth_middleware.py` + `test_spa_fallback_containment.py` 74 passed.
- Repo gates: `ruff check` / `ruff format --check` clean; suite inventory gates pass for Conductor, core, and Turing suites; `check-ratchet-provenance.py` and `check_enumerations.py` pass; the AGENTS.md mypy set (713 files) reports Success.
- CI-failure findings re-proven green at this head: `check-radon-baseline.py` 70 -> 70 C-blocks; formal constants regenerated with no drift (`git diff --quiet -- formal/generated/`); the diff-coverage gate replicated with the four real producers for this branch's measured changed files (turing backend 52; hive backend 2671 passed / 1 existing skip; core 10127 passed / 654 skipped; root `tests/` 3510 passed / 100 skipped) — `check-diff-coverage.py --base 8bb344e32` reports all 9 measured changed files at or above the 90%/80% floors.
- Environmental, not branch-caused: `packages/maistro-core/tests/test_container_postgres.py::test_an_unreachable_server_is_an_error_not_a_fallback` fails only inside the full core run under the CI `--timeout=30` flag when a local listener makes the connect hang ~61s instead of fast-refusing as in CI; it passes in isolation and the module is untouched by this branch. The Docker E2E port-8101 conflict from the prior verify run is the documented unrelated host service; this pass used in-process suites instead of re-running compose.
- Acceptance spot-checks against live behavior: an undeclared route injected into each real app fails the gate; import failure of either backend raises rather than skips; expired exemptions and `/v1/unrelated/invoke`-style suffix lookalikes are rejected for both applications; Turing registry permissions resolve through `canonical_permission` (`turing:chat` -> `turing.chat`) against `Principal.scopes`; docker-compose.yml still declares no Turing service.

## Re-validation at head 99664046b after integrating develop 1dea30dfe (repair lane)

The lane arrived mid-merge (`git merge 1dea30dfe` in progress, one conflict in `packages/maistro-turing/backend/tests/test_auth.py`). Resolution kept both sides verbatim: the #1140 route-gate/default-deny fixtures (HEAD) and develop's `test_app_uses_injected_canonical_security_composition` (#1139 Warden composition). No test was authored or removed; the inventory deltas above are unchanged. The merge modified only 3 of the branch's 30 changed-vs-base files (this note, `test_auth.py`, `quality/branch-independence.json`); all 9 measured production files are byte-identical to the previously validated head.

Evidence at candidate `99664046bf2d`, base `1dea30dfe30c`:

- `scripts/check-public-routes.py` exit 0: both live apps imported, 20 unauthenticated paths declared and base-authorized, public-routes ratchet 12 -> 12 identities, "both live route tables are declared and authorized"; route-permissions trusted-base comparison rendered.
- Focused suites: `tests/test_route_permission_gate.py` + core `test_http_route_policy.py` + `test_route_registry_location.py` 95 passed; `packages/maistro-turing/backend/tests` 78 passed (both conflict sides included); `packages/hive-conductor/backend/tests` 2678 passed / 1 existing skip; core 10166 passed / 654 skipped with the single documented environmental `test_container_postgres.py::test_an_unreachable_server_is_an_error_not_a_fallback` failure (passes in isolation in 62s; module untouched by branch); root `tests/` 3567 passed / 100 skipped.
- Diff-coverage gate produced first-hand with the four CI producers (turing backend, hive backend, core, root `tests/` as scripts producer): `check-diff-coverage.py coverage.xml --base 1dea30dfe` exit 0, 9/9 measured changed files at or above the 90%/80% floors, 11 test files exempt by declaration.
- CI-failure gates re-proven green at this head: `check-radon-baseline.py` 70 -> 70 C-blocks exit 0; `check-ratchet-provenance.py` exit 0 (all ratchets, 36 quality-JSON consumers with provenance); `python -m formal.extractors.extract_security_constants` regenerated with `git diff --quiet -- formal/generated/` (no drift); AGENTS.md mypy set Success (714 source files).
- `uv run ruff check .` clean; `uv run ruff format --check .` 2537 files already formatted.
- Acceptance spot-checks re-confirmed against live behavior at this head: registry `turing` section 11 entries each public/permission/exempt with `turing.*` scope.verb permissions; suffix lookalikes (`/v1/invoke-history`, `/v1/unrelated/invoke`, `/v1/unrelated/feedback`) rejected for both applications; expired-exemption and missing-declaration fixtures fail closed for both apps; import failure of either backend raises; docker-compose.yml declares no Turing service and is unchanged vs base.

Residual: Docker E2E not re-run this pass (host port 8101 occupied by an unrelated service, as documented above); in-process suites cover the acceptance criteria. Remote CI/browser e2e not run from this lane.

## Writer validation at head 8d07c01c (repair lane, no code changes)

Head `8d07c01cdd03` differs from the validated `99664046bf2d` only by this documentation file (`git diff 99664046b..HEAD --name-only` returns `docs/testing/inventory-notes/1140-repair-validation.md`), so all production code is byte-identical to the previously proven head. Every acceptance criterion was re-proven first-hand here rather than trusted from earlier claims.

First-hand probes against production behavior (in-memory only; no tree edits):

- Live route discovery through the real `app.routes` trees (including FastAPI lazy `_IncludedRouter` contexts): conductor 265 (method, path) identities vs 72 declarations, turing 15 identities vs 11 declarations — `_route_entry_failures` reports zero unclassified live routes for both applications.
- Undeclared route: a `GET /v1/brand-new` route injected into the real Turing app yields `turing GET /v1/brand-new: registered route has no declaration`.
- Expired exemption: an `expires: 2026-09-01` turing fixture fails with `exemption expired on 2026-09-01`.
- Misleading suffix: `/v1/unrelated/invoke` matched against an exact `/v1/invoke` public declaration is rejected for both applications (`_route_matches` offers only exact/boundary-prefix/template kinds; no suffix rule exists).
- Runtime default-deny against the real Turing app via TestClient: unauthenticated `/v1/feed` -> 401; authenticated human on undeclared `/v1/undeclared-future-route` -> 403 `Route authorization declaration required`; authenticated human on declared `/v1/feed` -> 200; non-admin human on `/v1/admin` -> 403 `Permission 'turing.admin' required`; an absent declaration (policy `None`) denies — an unmapped route can never mean allow.
- Canonical vocabulary: registry permissions `turing.vault_read`/`turing.vault_write`/`turing.chat`/`turing.admin` equal `canonical_permission(Scope.TURING_*)` (`turing:vault_read` -> `turing.vault_read`); `_PERMISSION_RE` (`scope.verb`) is enforced identically by the gate and `maistro.security.http_routes`.

Commands re-run green at this head:

- `uv run python3 scripts/check-public-routes.py` (the exact CI command, `.github/workflows/ci.yml:187`): exit 0, both production apps imported, 20 unauthenticated paths declared and base-authorized, ratchet 12 -> 12 identities, "both live route tables are declared and authorized".
- `uv run ruff check .` and `uv run ruff format --check .`: clean (2537 files formatted).
- `uv run pytest tests/test_route_permission_gate.py packages/maistro-core/tests/security/test_http_route_policy.py packages/maistro-core/tests/security/test_route_registry_location.py packages/maistro-turing/backend/tests/test_auth.py -q`: 111 passed.
- `uv run pytest packages/maistro-turing/backend/tests -q`: 78 passed.
- `uv run pytest tests/test_check_public_routes.py tests/test_m1_542_policy_coverage.py tests/test_check_enumerations.py tests/test_ratchet_provenance.py tests/test_m1_542_diff_coverage_edges.py tests/test_m1_542_review_regressions.py -q`: 115 passed.
- `uv run pytest packages/hive-conductor/backend/tests -q`: 2678 passed, 1 existing skip.
- `uv run python scripts/check_enumerations.py`: no new enumeration gaps; suite inventory gates match for core, Conductor, and Turing suites.

Prior-findings disposition: (1) required Quality gate FAILURE at `6ebc7503` is remote CI state at an older head — the branch's later commits re-proved every CI-failure gate green at `99664046b` (radon 70 -> 70, ratchet provenance, formal constants no drift, diff-coverage 9/9, mypy) and `8d07c01c` is docs-only over it; re-running remote CI requires a push, which this lane is prohibited from performing. (2) The Docker E2E `Bind for 127.0.0.1:8101` failure is environmental (unrelated host service holds the port); compose e2e passed in an isolated project at earlier heads whose production files are byte-identical to this head, and #1140's acceptance criteria are covered by the in-process evidence above.

Stop-condition check: `scripts/check-public-routes.py` remains the one policy mechanism (loop over `("conductor", "turing")`) backed by the single shared `maistro.security.http_routes` matcher consumed by both runtime middlewares; no second Turing-only checker exists (`ls scripts/ | grep route` shows only `check-public-routes.py` and the pre-existing frontend API check). docker-compose.yml declares no Turing service; Turing enablement and product authorization dependencies (`require_admin`, `require_turing_scope`, `require_user_or_turing_scope`) are unchanged — the middleware only adds the declaration floor.

Residual for the integrator: push the branch so required CI re-runs at the final head; the local evidence above predicts green. Docker compose e2e was not re-run this pass (environmental port conflict, previously green at byte-identical production code).


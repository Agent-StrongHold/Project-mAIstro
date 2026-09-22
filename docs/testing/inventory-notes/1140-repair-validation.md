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


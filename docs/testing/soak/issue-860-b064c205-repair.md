# Issue #860 — bounded CI repair b064c205

## Frozen scope

- Issue: #860 only; branch `auto-860` in `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `042c6e106216f562f2a5f938f802917b22595ffe` (resolved, clean).
- Assigned base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Process only supplied dispatch snapshot and prior failure: schema fence test,
  exact vulture scan, and issue acceptance evidence. No remote mutations.
- Candidate edit files: this report, `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  its inventory note if necessary, and `quality/vulture-baseline.json` only if
  the prescribed scan demonstrates reviewed retained identities.
- Read-only acceptance surfaces: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, `docs/testing/soak/m3a-load-profile.md`,
  `docs/testing/soak/m3a-soak-evidence.md`, related ADRs and production call sites.

## Initial evidence / assumptions

No `check-*.log` files were present in the supplied job directory at initial
inspection. The supplied prior `98a113.../check-3.log` reports 24 schema DDL calls
versus 21 expected; this must be reproduced before changing tests.
The prior result is BLOCKED on exact-RC deployment/physical-work/rate evidence,
not a develop merge conflict. Do not assume those historical findings still hold.
This is a writer CI-repair lane; passing local checks is not promotion approval.

## Validation and acceptance

- Historical schema failure does not reproduce: `uv run pytest
  packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped** (1.74 s). No test weakening is justified.
- Exact required vulture scan passed: `uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`: **1323 findings / 1323 reviewed identities**,
  zero unclassified, zero never-allowlist. No ledger amendment is justified.
- Profile read: explicitly labels the driver a host-process preflight, not the
  exact Compose artifact; requires >=4 hours and documents missing successful
  model/tool workloads, multiple users/Workspaces, fan-out and reconciliation.
- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **66 passed** (2.29 s). Combined focused result: 103 passed, 6 skipped.
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed,
  3270 files already formatted. All validation calls used 1200-second timeouts.
- Current schema test independently expects all 24 DDL statements, including
  the three Gauntlet audit columns missing from the historical failure.
- Production `RateLimitMiddleware` constructs an `InMemoryRateLimiter` per
  instance (`api/rate_limit.py:93`). The executed two-identity regression at
  `tests/test_soak_promotion_gates.py:439` observes 200, 200, 429 on each
  instance for the same identity: local limits, not a shared replica budget.
- Read ADR-081 (Proposed), accepted ADR-081626-f383, ADR-082126-f69c,
  ADR-085. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt. Admission
  uniqueness is not physical-work fencing; no alternate runtime or policy
  waiver is justified. The issue's stronger replica-selection requirement
  remains unresolved rather than silently reinterpreted as local enforcement.
- No production soak executed; PostgreSQL-dependent skips prove no integration
  behavior. No tests changed, so no inventory delta is needed.
- `uv run python scripts/check-ratchet-provenance.py`: passed, 53 consumers
  have explicit provenance (two non-fatal AST invalid-escape warnings).
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `git diff --check`: passed.

## Reachable evidence and acceptance disposition

The driver writes `preflight_artifact_check()` into its live result at
`scripts/soak/run_soak.py:1552`; the check returns false at line 730 and the
CLI consumes failed checks at line 1733. All three executed four-hour CLI
regressions reject missing/null/preflight artifact evidence. This is a truthful
blocker, not a gate to relax. `phase_claim_probe` calls cleanup at line 1152;
`_terminalize_probe_run` (line 1044) cancels the queued Run without executing it.
The executed backpressure test reaches the production task router and real
canonical spine but deliberately starts no runner; it proves admission behavior,
not active-work recovery.

| Frozen issue criterion | Current evidence / result |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**: profile documents missing multi-user/Workspace, fan-out, successful tool/model, Design/Canvas and reconciliation coverage; applicability to a selected RC is not established. |
| At least two deployed replicas | **UNVERIFIED**: two production middleware instances tested, not two deployed RC replicas. |
| Sustained saturation, growth, reclaim, retries and leaks | **UNVERIFIED**: accounting/sampling regressions passed; no sustained operational run executed. |
| No duplicated physical work / Goal reconciliation | **UNVERIFIED**: admission gates tested; schedule probe cancels before physical execution. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED overall; counterexample reproduced**: same identity exhausts each independent middleware allowance separately. Process-local enforcement is not aggregate enforcement. |
| Complete telemetry and explicit thresholds | **UNVERIFIED**: documented thresholds and tested samplers are not an executed complete RC series; driver loop lag is not application loop lag. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**: cleanup and gate regressions pass but do not exercise active physical work. |
| Long unchanged exact-RC soak | **UNVERIFIED / BLOCKED**: no >=4-hour RC run; production driver correctly rejects preflight artifact evidence even at that duration. |
| Findings filed/reclassified before promotion | Local disposition recorded here; external milestone disposition **UNVERIFIED**. No GitHub mutations. |
| Machine/human evidence tied to exact artifact hashes | **UNVERIFIED at promotion grade**: this report identifies tested source HEAD, not a deployed image/configuration-bound soak. |

## Final handoff

**BLOCKED**. Only this report changes. Historical CI failure already fixed;
no unbanked vulture identities or demonstrated new CI defect. Do not dispatch
another identical scanner repair without new evidence. Required next inputs/work:
select the immutable RC and supported configuration, resolve the replica-rate
contract, execute representative canonical physical-work scenarios with complete
telemetry and active-work interruption/recovery, then perform the unchanged
>=4-hour RC soak. A longer run of the existing preflight cannot satisfy this.
No promotion or integration approval is claimed.

Progress: checked 1 issue; acceptance-complete 0; skipped issues 0;
validation errors 0; blocked 1. Commit this report locally; preserve all existing
implementation and evidence.

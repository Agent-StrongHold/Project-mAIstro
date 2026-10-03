# #860 CI repair validation

## Frozen scope

Assigned issue: #860 only. Worktree: `/home/dev/Git/wt/auto-860`, branch
`auto-860`; verified clean starting HEAD
`b107735856e4674bb6e9c7efdf5e58533ce11882`. Supplied develop base:
`4fd7801fb333611955dda962d11845aaf065277c`.

Files in scope: this validation record, `quality/vulture-baseline.json` (explicit
CI-repair exception), and only production identities reported by the prescribed
vulture scan if inspection proves them dead. Adjacent tests, soak evidence,
repository instructions, ADRs and CI scripts are read-only inputs. No new soak,
new scheduler, authorization path, or production deployment is assumed.

Initial results: starting worktree clean; prior result artifact read. The job
directory listing contains no `check-*.log` files, so driver checks are unavailable,
not presumed passing. Previous handoff explicitly reports BLOCKED. Current
profile/evidence already disclaims cluster-wide rate limiting, exact-RC execution,
and >=4-hour soak; historical evidence will not be relabelled.

Assumption: the explicit CI-repair request authorizes reviewing and amending only
the vulture identity ledger, not ratchet grants or promotion requirements. Missing
RC identity/configuration and long-running evidence cannot be repaired by banking
scanner rows. Validation and final acceptance disposition follow below.

## Initial gate result and ADR reconciliation

The exact requested vulture scan exited 0: 1360 findings, 1360 reviewed
identities, zero unclassified/never-allowlist findings, no candidate bookkeeping
delta. Its default trusted base resolved to `045cfdfbe3ea`, not the supplied lane
base; repeat with `RATCHET_BASE_REV` pinned to the verified supplied base before
claiming lane-base validation. No dead-code or ledger change is justified by this
scan. The explicit ledger exception is not a requirement to invent a diff.
The repeat with the supplied `RATCHET_BASE_REV` also passed; the resolver still
reports `045cfdfbe3ea` (the trusted merge base), not the tip of the supplied ref.

Fresh checks (1800-second timeout): `uv sync --locked --extra dev` passed;
`uv run ruff check .` passed; `uv run ruff format --check .` passed (2809 files).
`uv run pytest tests/test_soak_promotion_gates.py
packages/maistro-core/tests/persistence/test_pg_learnings.py
packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
packages/maistro-server/tests/api/test_rate_limit.py -x -q` passed: **102 passed,
5 skipped**. PostgreSQL integration cases were skipped; they are not live-DB
proof. Existing tests exercise real rate-limit middleware instances, the canonical
admission backpressure seam, gate failure paths, and a real uv child sampler.
No new tests were added, so no inventory delta is required.

Accepted ADR-081226-a66b keeps Run/NodeRun/Attempt lifecycle authority canonical;
accepted ADR-081626-f383 guarantees stale-writer fencing but explicitly does not
establish lease-expiry takeover. This lane must not implement an alternate
scheduler/reclaim authority to satisfy the soak request. ADR-081 (deployment) is
Proposed, not an accepted override of those contracts. Therefore admission-only
and process-restart evidence cannot be upgraded to physical-work/reclaim proof.

## Final validation

- `git merge-base HEAD 4fd7801fb333611955dda962d11845aaf065277c` confirmed
  `045cfdfbe3eaa0c84493eb02754d7410b0c69378`; both vulture invocations above
  therefore used the expected trusted merge base. No merge/sync conflict exists.
- `uv run pytest packages/maistro-server/tests -x -q`: **483 passed, 8 skipped,
  22 deprecation warnings** (40.72 seconds). Skips are not acceptance evidence.
- `RATCHET_BASE_REV=4fd7801fb333611955dda962d11845aaf065277c uv run python
  scripts/check-ratchet-provenance.py`: PASS, 46 consumers checked.
- Same environment prefix with `uv run python scripts/check-shipped-surface-truth.py`:
  PASS. `check-deployment-claims.py`: PASS (component existence only).
  `check-doc-links.py`: PASS, 1611 files / zero broken relative links.
  `check-merge-markers.py`: PASS.
- An executed Python probe imported the current `scripts/soak/run_soak.py`, loaded
  the three known historical packs (`m3a-soak-evidence.json`,
  `m3a-round5-final.json`, `m3a-round6-shakedown.json`), and asserted every one is
  rejected by `failed_promotion_checks` for both `sustain_duration` and
  `exact_rc_artifact`. All assertions passed. Round 5 records 90.17 seconds;
  round 6 records 90.43 seconds. Run 1 has no top-level `sustain_seconds`.
- Local raw command logs: `/tmp/auto-860-{sync,vulture-initial,vulture-base,ruff,format,tests,server}.log`
  and `/tmp/auto-860-check-*.log`. These are validation logs, not soak evidence.

## Every acceptance criterion

| Criterion | Current executed evidence and disposition |
| --- | --- |
| Representative RC profile | PARTIAL: inspected `m3a-load-profile.md`; it explicitly lacks a concurrent user/Workspace population, fan-out, successful tools/models, Design/Canvas, and Goal/background workloads. Applicability to the selected RC remains UNVERIFIED. |
| At least two application replicas | UNVERIFIED: `deploy/docker-compose.prod.yml` defines two services; no current exact-artifact deployment was executed. Two ASGI middleware instances do not count as a deployed soak. |
| Sustained saturation, growth, reclaim, retries, leaks and restart | UNVERIFIED: executed evaluator rejects all three inspected historical packs; round 6 is 90.43 seconds vs 14400 required. A passing live child-sampler regression is not a long-window measurement. |
| No duplicate physical work / Goal reconciliation | UNVERIFIED: admission-oracle/backpressure tests pass, but do not prove physical Attempt effects across deployed replicas. Historical schedule probe cancels its queued Run; accepted fencing ADR does not establish expiry takeover. |
| Rate-limit/security/degraded replica-selection non-bypass | NOT MET for a shared allowance: executed `test_replica_selection_has_an_independent_production_allowance` reproduces `[200,200,429]` independently on both production middleware instances, for authenticated and unauthenticated callers. Current RC security/degraded behavior remains UNVERIFIED. |
| Complete telemetry and explicit thresholds | UNVERIFIED: profile has partial thresholds and host process-group samples; driver-loop latency is not application-loop latency. No exact-RC worker/pool/lease/leak window was measured. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED: no deployed replica was killed/restarted this round; historical process rejoin alone cannot prove physical-effect recovery. |
| Long-running exact RC artifact/configuration soak | BLOCKED: no designated immutable RC image/configuration supplied, and the current runner always fails `exact_rc_artifact`. Executed CLI regressions reject even synthetic four-hour preflight evidence. No new soak was run. |
| Findings filed/reclassified before promotion | PARTIAL: inspected historical local classifications. External filing UNVERIFIED and prohibited in this lane; no GitHub mutation performed. No new runtime defect is claimed from a clean vulture scan. |
| Human/machine evidence bound to exact hashes | PARTIAL: inspected/re-evaluated historical packs, not re-signed. Current promotion-artifact image/package/configuration hash-bound soak evidence UNVERIFIED. |

## Handoff

**BLOCKED for #860.** The requested CI failure did not reproduce; amending an
already exact ledger or changing runtime code would be cosmetic/speculative.
Only this validation record changed. No production/test/ledger/grant edits or
new test counts. Historical raw evidence is untouched. This is a local writer
checkpoint, never integration approval.

Next owner actions: designate the exact RC artifact/configuration, resolve the
rate-limit acceptance mismatch through its owning lane, complete representative
production-path workloads and effect/telemetry oracles, then run and publish a
new >=4-hour exact-artifact soak. Do not substitute a longer host preflight.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites and sustained soak}`.
Validation completed; issue acceptance remains blocked. Commit this report
locally without pushing, opening a PR, merging, commenting, or closing an issue.

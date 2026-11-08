# Issue #860 — repair checkpoint (job 72bc86b6)

## Frozen scope

- Only issue #860; assigned worktree `/home/dev/Git/wt/auto-860`, branch
  `auto-860`, verified clean starting HEAD
  `f29deca19c666eed799d601e67c4aebe8f42796b`.
- Review the existing `docs/testing/soak/m3a-load-profile.md`,
  `m3a-soak-evidence.md`, their historical JSON evidence, the soak driver and
  adjacent tests, production rate limiter, applicable ADRs, and the exact
  vulture per-identity gate. Modify only this checkpoint unless executed
  validation identifies a concrete scoped defect requiring repair.
- The ledger exception applies only to reviewed actual scanner findings;
  no speculative ledger or runtime changes.
- No `check-*.log` files were present in the assigned job directory at initial
  inspection. The previous job's result is background, not validation proof.
- Ambiguity resolved conservatively: this is a writer repair, not authorization
  to select an RC artifact or change production rate-limit semantics. No exact
  RC image/configuration has been supplied. Historical preflight results do
  not meet promotion acceptance.

## Initial evidence

The profile explicitly labels the runner a host-process preflight, not the
production Compose artifact. The evidence pack already retracts the earlier
shared-limiter claim and explains process-local allowances. The previous
checkpoint changed documentation only. There is no unresolved work to discard
or sync conflict to resolve. No GitHub mutations will be performed.

## Executed validation

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1,360 reviewed identities / 1,360 findings; zero unclassified and never-allowlist findings. Actual gate merge base: `045cfdfbe3ea`. No debt repair or ledger amendment is justified.
- Inspected the production limiter and its real-middleware tests: state is per process (`api/rate_limit.py:25-30,72`); independent replica allowances contradict a cluster-wide non-bypass claim. The earlier erroneous H3 statement is already corrected in the evidence pack.
- Read accepted ADR-081226-69ee and ADR-081626-f383: Graph → Run → NodeRun → Attempt remains canonical; durable stale-writer fencing is not proof of lease-expiry takeover. ADR-081 is Proposed, not an acceptance waiver. No new runtime or authorization authority is introduced.
- `deploy/docker-compose.prod.yml:11-12,26-29` explicitly describes a reference artifact and uses a local image build. The assignment does not identify the immutable RC/configuration. The current driver always rejects exact-artifact equivalence (`scripts/soak/run_soak.py:635-646`). Running it longer cannot close the block.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (2,809 files already formatted).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs`: **80 passed, 5 skipped**, 3.01 seconds. Five live-PostgreSQL cases require `MAISTRO_TEST_PG_DSN`; no database validation is claimed. Passing cases include authenticated and unauthenticated independent-replica allowances, six-path limiter probes, rejected four-hour preflight evidence, invalid admission receipts, and the live child-process resource sampler.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-execution-lifecycles.py`: PASS (19 classified/discovered lifecycles).
- `uv run python scripts/check-merge-markers.py`: PASS.
- `git diff --check`: PASS.
- Production reachability confirmed: `packages/maistro-server/src/maistro_server/main.py:588` installs the tested `RateLimitMiddleware`.

- Executed `uv run python` importing the current `failed_promotion_checks`
  evaluator over the fixed historical packs `m3a-soak-evidence.json`,
  `m3a-repair-validation.json`, `m3a-round5-final.json` and
  `m3a-round6-shakedown.json`. All four fail both `sustain_duration` and
  `exact_rc_artifact`; assertions passed. Recorded durations are absent,
  absent, 90.17 and 90.43 seconds respectively. This is evaluation of old
  records, not new load evidence or verification of their other passing flags.

## Acceptance disposition

| #860 criterion | Evidence and disposition |
|---|---|
| Representative RC profile | PARTIAL: `m3a-load-profile.md` defines request mix and thresholds but explicitly lacks concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and Goal/background workloads. RC applicability UNVERIFIED. |
| Two application replicas | Reference Compose declares two; actual exact-RC deployment UNVERIFIED. ASGI middleware instances are not deployed replicas. |
| Sustained saturation, queue/reclaim/retry and leaks | UNVERIFIED: no long-running soak executed. Short historical packs fail the current evaluator. |
| Physical-work uniqueness and Goal reconciliation | UNVERIFIED: admission identities do not prove physical Attempt fencing/reclaim; schedule probe cancels its queued Run. Accepted fencing ADR does not authorize implicit takeover. |
| Rate/security/degraded behavior without replica bypass | NOT MET for aggregate allowance: executed production middleware cases show a second allowance on replica 2 for the same authenticated or pre-auth identity. Full RC security/degraded behavior UNVERIFIED. |
| Complete metrics and thresholds | PARTIAL: live child-process sampler regression passes, but full application event-loop/worker census and sustained RC telemetry UNVERIFIED. |
| Active-work kill/restart, drain/fencing/recovery | UNVERIFIED: historical process rejoin/terminal counts are not physical-work recovery proof; no restart run this round. |
| Long-running exact RC artifact/configuration soak | BLOCKED: no designated immutable RC/configuration and no qualifying ≥14,400-second run; host-process driver cannot certify it. |
| Findings filed/reclassified at earliest invariant | PARTIAL: existing F11/F12 classify evidence-validity defects at M3-A; external filing UNVERIFIED. GitHub mutations are prohibited. |
| Machine/human evidence with exact hashes | PARTIAL: historical evidence is preserved, but qualifying RC artifact/configuration hashes and soak evidence UNVERIFIED. |

## Handoff

**BLOCKED**. The requested vulture failure does not reproduce. No source deletion,
ledger amendment, extra test, or cosmetic runtime change is justified. This
checkpoint is the only changed file; no inventory note is needed because no test
or count changed. Historical logs/JSON, code, runtime configuration and all ledgers
remain untouched. No integration approval or issue closure is claimed.

Next: release owner must designate the immutable RC/configuration; establish the
representative production workload, application telemetry and physical-work
recovery oracle; resolve the aggregate-limit acceptance mismatch; then execute
≥4 hours against that unchanged exact artifact. A longer preflight cannot remove
these blockers. Do not repeat short runs or documentation-only repairs as if they
were progress toward production acceptance.

Progress: checked 1 assigned issue, done 0, skipped 0 issues, errors 0 validation
commands; 5 database tests skipped. Commit this checkpoint locally and leave the
worktree clean.

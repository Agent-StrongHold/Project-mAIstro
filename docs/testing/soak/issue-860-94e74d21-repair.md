# #860 repair checkpoint — job 94e74d21

## Frozen scope and initial results

- Assigned issue: #860 only; branch `auto-860`, starting head
  `6f3a452184e218123ebf7b39b4df4069a3156602`, supplied develop base
  `5765efce8c1f1f65c778dce5d30aa542279ab70d`. Initial worktree clean.
- Review scope: existing soak profile, evidence, runner and promotion tests;
  production rate limiter; adjacent pg-learnings and task-backpressure tests;
  deployment/lifecycle/fencing ADRs; applicable gate definitions.
- Write scope: this checkpoint; vulture ledger only if the requested scan
  identifies actual reviewed retained debt. No speculative runtime repair.
- Job-directory snapshot: `events.jsonl`, `manifest.json`, `prompt.txt`,
  `state.json`. No `check-*.log` files supplied. Prior result read but its
  validation is not treated as current evidence.
- Executed requested exact vulture command: exit 0. Log:
  `/tmp/860-94e74d21-vulture.log`. No failing debt reproduced.
- Executed `DOCKER_HOST=unix:///var/run/docker.sock timeout 60 docker info`:
  exit 1. Log: `/tmp/860-94e74d21-docker.log`. Exact-RC deployment prerequisite
  failed; no soak started.

Assumption: writer/CI-repair lane. A passing debt scan is not justification for
ledger edits. This checkpoint will record focused validation and remaining
acceptance gaps, not convert short historical preflights into promotion proof.

## Focused validation checkpoint

Commands executed with a 600-second timeout:

- `uv run ruff check .`: exit 0.
- `uv run ruff format --check .`: exit 0.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs`: exit 0; counts/skips reviewed below.
- `uv run python scripts/check-ratchet-provenance.py`: exit 0.
- `uv run python scripts/check-shipped-surface-truth.py`: exit 0.

Logs: `/tmp/860-94e74d21-{ruff-check,ruff-format,pytest,provenance,surface}.log`.
Vulture reports 1,359 findings matching 1,359 reviewed identities, zero
unclassified and zero never-allowlist entries. Its default trusted base resolves
to `83db0175dd94`, not the supplied historical develop base. No ledger change
is warranted by the actual scan. Docker output confirms no reachable daemon
at the specified socket (also reports plugin I/O warnings).

Read ADR-081 (Proposed, not accepted authority), accepted ADR-081226-a66b
(lifecycle) and accepted ADR-081626-f383 (lease fencing). Reconciliation:
admission uniqueness is not physical-work uniqueness; lease expiry alone does
not authorize takeover. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt;
no competing scheduler, store, authorization or execution authority introduced.

## Executed evidence and acceptance disposition

Pytest: **80 passed, 5 skipped in 2.65s**. The five live PostgreSQL cases
require `MAISTRO_TEST_PG_DSN`; they did not run. Ruff reports all checks passed
and 2,770 files already formatted. Provenance reports 45 classified quality
JSON consumers; shipped-surface truth passes. The executed vulture arguments
match `.github/workflows/vulture-ratchet.yml:82-85`.

An additional `uv run python -` check imported the real
`failed_promotion_checks` evaluator and asserted rejection of the frozen four
historical packs (`m3a-soak-evidence.json`, `m3a-repair-validation.json`,
`m3a-round5-final.json`, `m3a-round6-shakedown.json`). Exit 0; all four fail
both `sustain_duration` and `exact_rc_artifact`. Runs 5/6 record 90.17/90.43
seconds, not 14,400. Log: `/tmp/860-94e74d21-evidence.log`.

| Acceptance criterion | Current executed evidence / disposition |
|---|---|
| Representative RC workload | PARTIAL profile only; `m3a-load-profile.md` explicitly lacks concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and sustained reconciliation. Representativeness UNVERIFIED. |
| At least two application replicas | Historical host-process preflight, not current exact-RC validation. Live deployment UNVERIFIED; Docker prerequisite failed. |
| Sustained saturation/growth/reclaim/retries/leaks | UNVERIFIED. Process sampler regression observes child allocation/FD growth but is not long-window application evidence. |
| No duplicate physical work, admissions and Goal reconciliation | UNVERIFIED. Receipt-identity regressions test the admission oracle; a cancelled schedule-probe Run does not establish physical Attempt uniqueness/recovery. |
| Rate/security/degraded non-bypass | NOT MET as a cluster-wide allowance. Executed real-middleware tests reproduce `[200, 200, 429]` independently on each replica for the same authenticated or unauthenticated identity. Full RC security/degraded behavior UNVERIFIED. |
| Full telemetry and thresholds | PARTIAL profile/instrumentation. Application-loop latency, full worker/container census and long-window telemetry UNVERIFIED. |
| Active-work kill/restart and drain/fencing/recovery | UNVERIFIED. Historical exit/rejoin and terminal Run counts do not prove physical-work recovery. |
| Long-running exact RC artifact/configuration soak | NOT MET. All four historical packs rejected by current evaluator; host preflight always fails artifact gate. No new soak attempted. |
| Findings filed/reclassified before promotion | Local F-series classifications reviewed; external filing UNVERIFIED and prohibited in this lane. |
| Hash-bound machine/human promotion evidence | Historical preflight packs exist; exact-image/configuration promotion evidence UNVERIFIED. |

The old H3 shared-store statement is already retracted in
`m3a-soak-evidence.md:171`; it is not a new documentation repair opportunity.
Production `rate_limit.py:25-30` explicitly describes process-local budgets.
Neither relaxing #860 nor introducing a new rate-limit authority is justified
by this debt-repair assignment.

## Final handoff

**BLOCKED.** Only this checkpoint changed; no tests added/modified, hence no
inventory delta. No production code, runtime configuration, historical evidence,
ledger or grant changes. No GitHub mutations. Local commit required.

Next: provide a working exact-RC deployment environment, finish the representative
workload and physical-work/telemetry oracles, resolve the replica-budget contract,
then execute >=14,400 seconds on the immutable RC image/configuration. Another
identical CI-debt repair lane cannot supply that evidence. Docker availability
alone would not close the runner and workload gaps.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: exact-RC deployment
and workload/evidence prerequisites}. The requested scan completed successfully;
the issue remains incomplete, not integration-approved.

# Issue #860 — repair checkpoint db6e3522

## Frozen scope

- Assigned item: #860 only; branch `auto-860`, starting head
  `6c79b4e9e50581e5ee72c38669fc8cd69e65a4af` (verified); supplied comparison
  base `b683268ea2a2baef61ee65bd4be49d4f2e46444a` resolves.
- Initial working tree clean; no salvage required.
- Inspect existing soak driver, promotion tests, profile/evidence, task
  backpressure and learning-schema tests, relevant deployment/execution ADRs,
  and required vulture gate. Only planned edit is this validation/handoff file;
  change the ledger only if the required scanner identifies actual debt.
- Do not treat the supplied base-to-head diff as this lane's scope: it includes
  unrelated development divergence. No develop sync conflict was reported.
- Job directory contains no `check-*.log` files at initial inspection. Earlier
  job results are historical, not executed validation for this head.
- Ambiguity: no immutable RC image or normalized RC configuration was designated.
  Do not invent one or run a four-hour host emulator as a substitute.

## Recorded results

- Required command `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1402 reviewed identities,
  1402 findings, zero unclassified/never-allowlist findings. No debt amendment
  justified; no dead-code repair guessed.
- Existing profile explicitly states host-process preflight cannot sign a
  promotion soak. Existing evidence now states limiter state is process-local
  and replica selection increases aggregate allowance. These prior findings
  must not be presented as newly repaired in this round.

## Fresh validation (1200–1800-second command timeouts)

- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-core/tests/persistence/test_pg_learnings.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  packages/maistro-server/tests/api/test_rate_limit.py -x -q -rs`:
  **102 passed, 5 skipped in 10.93s**. Output is in the job directory's
  `repair-pytest.log`. All skips require `MAISTRO_TEST_PG_DSN`; no live database
  validation is claimed.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2624 files already formatted.
- `uv run python scripts/check-suite-inventory.py --suite tests/`: PASS, 4198.
- Inline `uv run python -` imported the current evaluator and asserted that
  all four fixed historical packs (`m3a-soak-evidence.json`,
  `m3a-repair-validation.json`, `m3a-round5-final.json`,
  `m3a-round6-shakedown.json`) fail both `sustain_duration` and
  `exact_rc_artifact`. Last two observed durations: 90.17 and 90.43 seconds.
  Also asserted `preflight_artifact_check()['ok'] is False`.

No source/configuration/test changes were warranted by this gate-repair run.
No tests were added; inventory delta is zero. This file is the only changed file.

## Architecture reconciliation

Read repository instructions and ADR-081 (proposed deployment topology), accepted
ADR-085 (principal-keyed rate policy), ADR-081626-f383 (Attempt fencing),
ADR-082526-b36a (renewal/reclaim), and ADR-082126-f69c (recurrence produces Runs).
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; neither admission counters
nor terminal Run counts prove physical-effect uniqueness or stale-worker fencing.
ADR-085 does not establish shared limiter state. Its policy is not a waiver of
#860's non-bypass requirement. Do not add an alternate scheduler or auth path to
make the harness pass.

Production reachability checked: `main.py:478` installs RateLimitMiddleware;
`api/tasks.py:117-131` maps RunConcurrencyExceeded to 429/Retry-After;
`container.py:2538` invokes learning schema initialization, whose advisory lock
is at `persistence/pg_learnings.py:141`. Passing unit seams do not prove sustained
multi-replica behavior.

## Acceptance disposition

| Issue criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC workload | PARTIAL: inspected profile; one key, no representative concurrent Workspaces, fan-out, successful model/tools, Design/Canvas or sustained Goal/background activity. Full criterion UNVERIFIED. |
| At least two deployed replicas | UNVERIFIED: Compose declares two; this run exercised independent ASGI middleware instances, not deployed RC replicas. |
| Sustained saturation/reclaim/retry/leaks | UNVERIFIED: all four historical packs fail duration; live child RSS/FD regression is not a long-running application soak. |
| No duplicate physical work and Goal reconciliation | UNVERIFIED: admission regression starts no worker; occurrence admission does not prove physical Attempt fencing. |
| Rate/security/degraded non-bypass | NOT MET for aggregate rate budget: executed production-middleware regression gets [200,200,429] independently on both replicas for the same identity. Exact-RC concurrent security/degraded behavior UNVERIFIED. |
| Required metrics and thresholds | PARTIAL: sampler regression passes, DB tests skip; application-loop latency, complete worker census and sustained RC series UNVERIFIED. |
| Kill/restart active work and recover safely | UNVERIFIED: no new deployed restart or physical-effect oracle. |
| Long-running exact RC/config soak | BLOCKED: immutable RC/config not designated; host driver rejects equivalence at run_soak.py:635. 90.43s historical evidence is below 14400s. |
| Findings filed/reclassified | PARTIAL: existing local F11/F12 classifications name M3-A evidence validity. No new load finding; external filing UNVERIFIED and prohibited here. |
| Human/machine hash-tied evidence | PARTIAL: historical packs preserved and rejected by current evaluator; qualifying exact-RC promotion evidence UNVERIFIED. |

## Handoff

**BLOCKED, not promotion or integration approval.** Required exact-debt-ledger
validation is green and supplies no actionable debt. Repeating that repair cannot
satisfy the missing release experiment. Release owner must designate the immutable
RC/configuration; owning work must resolve aggregate-rate acceptance and finish
production workloads, physical-effect/fencing oracles and metrics before running
and publishing >=4 hours. Any code/runtime-config change requires a new soak.
No GitHub mutations or historical evidence rewrites performed.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: designated RC and
production-path sustained evidence}`. Gate validation completed; issue remains
blocked. Checkpoint committed locally.

# Issue #860 — round 15 repair checkpoint

## Frozen scope

- Sole issue: #860; assigned writer worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `93e233bc6c7bc09afdf9677b28f1467c97e95260` (resolved; clean).
- Supplied develop base: `9fe61e216786b95748d36ba8d75751f875b925e1` (resolved).
- Inspect existing soak harness/profile/evidence, promotion-gate tests, related
  rate-limit/task/learning production code and tests, applicable ADRs, and the
  vulture checker/ledger. Edits limited to evidenced #860 repairs, explicitly
  authorized vulture ledger repair if needed, and this report/inventory notes.
- No sync conflict exists. The supplied base differs substantially from HEAD;
  this is not authority to change unrelated files or fetch/merge develop.
- Job directory contains no `check-*.log` files at initial inspection. Driver
  checks cannot be presumed green. Prior result was read only as a lead.
- Ambiguity: no immutable promotion RC image/configuration is specified. Do not
  designate a substitute or claim host uvicorn preflight as production evidence.

## Results

- Exact requested vulture gate: PASS, 1402 reviewed identities / 1402 findings,
  zero unclassified and zero never-allowlist findings. No ledger amendment is
  justified by this execution.
- Focused pytest (promotion gates, pg_learnings, task concurrency backpressure,
  rate_limit): 102 passed, 5 skipped in 10.83s. The five live PostgreSQL tests
  skipped because `MAISTRO_TEST_PG_DSN` is unset; no live DB claim.
- Current human evidence already corrects the historical H3 shared-store claim.
  Production middleware regression freshly confirms independent per-instance
  allowances for both authenticated and unauthenticated identities.
- Ruff lint and formatting: PASS (2624 files already formatted).
- Suite inventory: PASS (`tests/`: 4198).
- Fresh import/execution of `failed_promotion_checks` over the four frozen
  historical JSON documents rejects all four for `sustain_duration` and
  `exact_rc_artifact` (and earlier documents for additional failed gates).
  Round 5 records 90.17 seconds; round 6 records 90.43 seconds. The current
  `preflight_artifact_check()['ok']` is also asserted false.
- No new soak or promotion acceptance claim made.

## Commands executed

All validation commands used 600–1800 second timeouts. Output was observed
in the worker tool transcript; no driver check logs were supplied.

```sh
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q -rs
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check-suite-inventory.py --suite tests/
```

Also ran `uv run python -` to import `scripts/soak/run_soak.py`, load
`m3a-soak-evidence.json`, `m3a-repair-validation.json`, `m3a-round5-final.json`,
and `m3a-round6-shakedown.json`, assert each fails both duration and artifact
checks, and assert the current host-preflight artifact check is false. These
are fresh evaluator results on historical inputs, not fresh load observations.

## Architecture and reachable behavior

Read repository instructions plus accepted ADR-081426-1f7c (runtime mechanics),
ADR-081626-f383 (Attempt lease fencing), ADR-085 (principal rate policy),
ADR-083026-a91e (missing measurements), and proposed ADR-081 (deployment).
No change to `Goal -> Graph -> Run -> NodeRun -> Attempt` ownership. A unique
admission receipt does not establish physical-effect uniqueness, and a process
exit is not proof of fenced recovery. ADR-081626-f383 explicitly does not grant
implicit expiry takeover authority; a soak must not invent a recovery scheduler.
Unobserved application metrics remain absent, not zero. Proposed deployment
text does not waive exact-artifact validation. ADR-085's principal identity
requirement does not establish shared limiter state.

`maistro_server/main.py:478` installs `RateLimitMiddleware`; lines 544 and 559
mount the task router. The executed independent-allowance regression at
`tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` separately
on two instances for the same authenticated principal or connecting IP.
`rate_limit.py:25-30` documents that exact process-local behavior. This is a
reachable middleware counterexample, not a deployed two-replica soak.

The executed task-backpressure test mounts the real task router over a canonical
in-memory spine, observes the principal ceiling returning 429 + Retry-After,
another principal admitted, and re-admission after release. It does not start
an execution worker and cannot prove cross-replica physical-work uniqueness.
The sampler test observes real child memory/descriptors; its database seam is
mocked, so it cannot establish PostgreSQL load behavior.

## Acceptance disposition

| Criterion | Fresh evidence / remaining gap |
| --- | --- |
| Representative RC profile | PARTIAL: inspected `m3a-load-profile.md`; its remaining-gaps section acknowledges missing users/Workspaces, Graph fan-out, successful model/tool calls, Canvas/Design and Goal/background traffic. RC representativeness **UNVERIFIED**. |
| Two application replicas | Compose defines two services (`deploy/docker-compose.prod.yml:27-62`). Execution of two designated RC replicas **UNVERIFIED**. |
| Sustained pool/queue/reclaim/retry/leak/shutdown behavior | **UNVERIFIED**: historical duration rejected by freshly executed evaluator; no new sustained run. |
| No duplicate schedule/task/Run/Attempt physical work; Goal reconciliation | **UNVERIFIED**: admission and sampler regressions pass but do not run cross-replica physical executions or sustained Goal reconciliation. |
| Rate/security/degraded concurrency cannot be bypassed by replica selection | Aggregate principal non-bypass **NOT MET**: executed production-middleware counterexample proves independent allowances. Full RC security/degraded proof **UNVERIFIED**. |
| Required complete metrics and explicit thresholds | PARTIAL: profile thresholds and sampler regressions exist. Exact-RC application loop, database contention/saturation and long-window series **UNVERIFIED**. Five live PostgreSQL tests skipped. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED**: historical exit/rejoin does not correlate Attempts with physical effects; no new kill/restart execution. |
| Long-running exact-RC/configuration soak | **BLOCKED**: immutable RC/configuration not designated. Current harness always rejects host-artifact equivalence (`run_soak.py:635`); latest historical duration is 90.43 seconds, not 14400. |
| Findings filed/reclassified to earliest invariant | PARTIAL: preserved human pack classifies F11/F12 as M3-A evidence-validity defects. No new load findings claimed. External filing **UNVERIFIED** and prohibited in this lane. |
| Machine/human hash-tied soak evidence | PARTIAL: preserved four historical documents and human pack. Qualifying exact-image/configuration sustained evidence **UNVERIFIED**. |

## Final checkpoint

**BLOCKED, not integration approval.** Only this report changed. No runtime,
configuration, raw evidence, tests, ledger or grants changed; inventory delta
is zero. The requested CI gate has no debt delta to repair, and the historical
H3 claim has already been corrected. An invented code/ledger edit would not
resolve the evidence blockers.

Required next action: the release owner must designate the immutable promotion
artifact/configuration, resolve the aggregate rate-policy mismatch with its
owning lane, and establish representative production workloads plus physical
fencing/recovery oracles. Then execute and publish a new >=4-hour exact-artifact
soak; repeat after any code/runtime-configuration change. Do not repeat host
preflight as a substitute. No GitHub mutations performed.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: designated RC and
representative production-path sustained evidence}`. CI validation completed;
#860 acceptance remains incomplete. This report is the local commit checkpoint.

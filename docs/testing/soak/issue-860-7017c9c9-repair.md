# Issue #860 — repair checkpoint (7017c9c9)

## Frozen scope

Assigned item only: #860, branch `auto-860`, starting commit
`428ef8a23158b7ac466544769f685ede818b8692`, supplied develop base
`00aafef9b75a1057edc2b03f2d6a71732ec9d880`.
Worktree was clean. No sync conflict exists. No GitHub mutations permitted.

Read-only review scope: repository instructions, relevant execution/deployment
ADRs, existing soak profile/evidence/harness and adjacent promotion, persistence,
backpressure and rate-limit tests, exact vulture gate/ledger. Planned write scope:
this report only unless executed validation identifies an actionable defect.
No additional issues or historical repair reports will be processed.

## Initial executed evidence

- Exact required vulture command passed: 1342 reviewed identities, 1342 findings,
  zero unclassified. No ledger amendment is warranted by this scan.
- Job directory listing contains no `check-*.log` files. Driver checks therefore
  cannot be independently inspected; do not infer a green result.
- Supplied prior result exists and reports BLOCKED; its claims will not substitute
  for this round's validation.

## Ambiguity / assumption

The brief requests a CI ledger repair but the exact gate is already green.
Proceed with focused validation and report unmet soak acceptance rather than
invent scanner findings, change runtime semantics, or weaken promotion gates.
A host preflight is not an exact-RC deployment soak.

## Focused validation checkpoint

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (2876 files).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q`:
  **80 passed, 5 skipped**. These are regression tests, not a production soak.
- Inspected the production `RateLimitMiddleware`, preflight artifact check and
  promotion evaluator, alongside their tests. The test using two real middleware
  instances reproduces independent allowances for the same authenticated or
  unauthenticated identity. Six-path overload rejection is not non-bypass proof.
- The prior H3 prose contradiction is already corrected in the starting tree's
  `m3a-soak-evidence.md` run-6 table. No cosmetic re-repair is needed.

Architecture review: ADR-081 is Proposed, not an accepted deployment waiver;
ADR-046 is Superseded. Accepted ADR-081626-f383 assigns fencing to canonical
Attempt persistence; ADR-082826-d9f5 makes RunStore the sole execution authority.
No competing scheduler, store, authorization or execution authority is introduced.
Admission counts cannot stand in for physical-work/recovery evidence.
Accepted ADR-082126-f69c supersedes ADR-046: recurrence produces canonical Runs,
not a second runtime. This review preserves that decision.

## Final executed evidence

Re-ran the focused pytest command with `-rs`: **80 passed, 5 skipped**.
The five skips require `MAISTRO_TEST_PG_DSN` pointing at a migrated PostgreSQL
instance (test_pg_learnings.py:766,877,896,906,917). No live database or RC
load test is claimed. `git diff --check` passed.

Executed `failed_promotion_checks` from the current production preflight driver
against the frozen four historical evidence packs and asserted that every one
fails both `sustain_duration` and `exact_rc_artifact`:

| Evidence JSON | Recorded top-level sustained seconds | Failed checks |
|---|---:|---|
| m3a-soak-evidence | absent | rate_limit_enforced, lb_failover_bounded, nonterminal_runs_after_settle, task_admission_availability, sustain_duration, exact_rc_artifact, graceful_drain |
| m3a-round5-final | 90.17 | rate_limit_enforced, sustain_duration, exact_rc_artifact |
| m3a-round6-shakedown | 90.43 | sustain_duration, exact_rc_artifact |
| m3a-repair-validation | absent | exactly_once_task_admission, lb_failover_bounded, nonterminal_runs_after_settle, task_admission_availability, sustain_duration, exact_rc_artifact, graceful_drain |

Files are under `docs/testing/soak/evidence/`; raw records were not modified.
The evaluator consumes historical summary fields: acceptance of an old H3 field
would not prove the current six-path probe was run.

## Acceptance disposition

1. **Representative profile — PARTIAL.** `m3a-load-profile.md` defines mixes and
   thresholds but explicitly lacks multiple users/Workspaces, fan-out, successful
   tool/model calls, Canvas/Design and sustained Goal/background workloads.
2. **Two application replicas — UNVERIFIED for exact RC.** Production Compose
   declares two servers; historical host-process evidence is not that deployment.
3. **Sustained saturation/reclaim/retry/leaks — UNVERIFIED.** Executed duration
   evaluation rejects the reviewed packs; none establishes the required window.
4. **No duplicate physical work / Goal reconciliation — UNVERIFIED.** A single
   schedule-admission race and canceled queued probe do not exercise physical
   Attempts or sustained Goal reconciliation.
5. **Security/degraded behavior and replica-selection non-bypass — NOT MET.**
   The executed production-middleware regression gives the same identity
   `[200, 200, 429]` on each independent replica. Local overload enforcement does
   not supply the cross-replica guarantee. Full deployed security/degradation
   remains UNVERIFIED.
6. **Complete telemetry with thresholds — UNVERIFIED.** Profile admits driver
   loop lag is not application lag; historical wrapper-only RSS/FD measurements
   cannot prove application health. No new production telemetry was collected.
7. **Kill/restart with physical fencing/recovery — UNVERIFIED.** Historical
   process exit/rejoin is not correlated in-flight Attempt recovery evidence.
8. **Long soak of exact RC — NOT MET.** Executed evaluator rejects all four
   packs for both duration and artifact identity. `preflight_artifact_check`
   explicitly refuses host-process equivalence even at four hours.
9. **Findings filed/reclassified — PARTIAL.** Existing local F11/F12 evidence
   classifies earliest failure as M3-A evidence validity. External filing is
   UNVERIFIED and prohibited in this lane; no issue mutations were performed.
10. **Hash-bound machine/human evidence — PARTIAL.** Both formats exist for
    historical preflights, but exact promoted image/configuration evidence is
    UNVERIFIED. Supplied source refs alone do not identify an immutable RC image
    and its complete deployment configuration.

## Handoff

**BLOCKED**, not promotion-ready. No actual scanner defect was found; changing
`quality/vulture-baseline.json` would have no evidentiary basis. This round changes
only this report. No tests were added, so no inventory delta is needed.

Next owner must resolve the cross-replica rate-limit contract without waiving
#860, select immutable RC artifacts/configuration, complete the representative
production-path runner and telemetry, and execute at least 14400 sustained seconds
with active-work recovery proof. Any runtime/configuration change needs a new
soak. Extending the existing emulator cannot close these acceptance gaps.

Progress: checked 1 assigned item; done 0; skipped 0; errors 0; blocked 1.
Validation completed and this handoff is committed locally. No push, merge,
external filing, ledger/grant change or runtime change was performed.

# Issue #860 — repair checkpoint (job 404870ca)

## Frozen scope and initial state

Only issue #860 in `/home/dev/Git/wt/auto-860`, branch `auto-860`.
Starting HEAD verified as `ba74e7af2a15bf896a6eb0a0ffdcdbb71623267d`;
working tree clean, no incoming changes or sync conflict to salvage.

Fixed review scope: existing soak profile/evidence and four historical JSON
packs, `scripts/soak/`, `tests/test_soak_promotion_gates.py`, production rate
limiter and middleware wiring, learning-store and task-backpressure tests,
production Compose, relevant execution/fencing/deployment ADRs, exact vulture
checker and its ledger. Modify only this checkpoint unless executed validation
identifies a concrete scoped repair. No speculative ledger banking.

No `check-*.log` files exist in the supplied job directory at initial inspection;
the prior result has an empty checks array and is not validation evidence.
Assumption: writer repair assignment does not authorize choosing the release
owner's immutable RC or changing rate-limit semantics to reinterpret acceptance.
Prior block concerns missing production soak evidence, not a develop conflict.
The existing profile already disclaims exact-artifact equivalence and the old
shared-limiter claim has already been retracted. Revalidate rather than repeat
that repair. No GitHub actions, runtime changes or new soak are claimed.

## Validation

- Exact requested vulture command: PASS, 1,360 findings and 1,360 reviewed
  identities, zero unclassified/never-allowlist findings. Gate reports merge
  base `045cfdfbe3ea` and candidate `ba74e7af2a15`. No failing identity exists
  to repair or bank; ledger amendment is not justified by actual evidence.
- Read accepted canonical Graph/Node and execution-fencing ADRs, proposed
  deployment ADR, production limiter, production Compose and adjacent soak
  tests. `RateLimitMiddleware` constructs independent in-memory limiters;
  Compose is explicitly a reference build, not a designated immutable RC.
  The host-process artifact gate unconditionally returns false. No code or
  authorization change is warranted by these already-documented blockers.

- ADR reconciliation: accepted ADR-082526-b36a adds explicit TTL renewal and
  reclamation to ADR-081626-f383's original fencing boundary. Do not read the
  older ADR as prohibiting the now-defined reclaim path. This review does not
  prove that path under production load. Goal → Graph → Run → NodeRun → Attempt
  remains the only execution model; no parallel authority is introduced.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2,809 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs`:
  **80 passed, 5 skipped**, 3.08 seconds. Live PostgreSQL cases skip because
  `MAISTRO_TEST_PG_DSN` is unset; no database or deployed-replica proof claimed.
  Tests exercise the actual production limiter (including both authenticated
  and pre-auth independent replica allowances), real task router/spine
  backpressure, six-path probe failures, admission-receipt validation and a
  live uv child resource sampler. `main.py:588` installs that limiter in the
  application. Synthetic ASGI routing is not a deployed production soak.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-execution-lifecycles.py`: PASS, 19 classified
  and 19 discovered lifecycles.
- `uv run python scripts/check-merge-markers.py`: PASS.
- Executed current `failed_promotion_checks` through `uv run python` against
  the fixed historical packs `m3a-soak-evidence.json`,
  `m3a-repair-validation.json`, `m3a-round5-final.json` and
  `m3a-round6-shakedown.json`. Assertions confirm all four fail both
  `sustain_duration` and `exact_rc_artifact`. Their top-level observed
  sustain durations are absent, absent, 90.17 and 90.43 seconds. This tests
  rejection of old evidence, not the truth of other historical passing flags.
- `git diff --check`: PASS.

## Acceptance disposition

| #860 criterion | Executed evidence / remaining gap |
|---|---|
| Representative RC load profile | PARTIAL: read profile and explicit gaps; concurrent users/Workspaces, fan-out, successful tool/model, Design/Canvas and Goal/background workload applicability UNVERIFIED. |
| At least two application replicas | Compose defines two; deployed exact-RC replicas UNVERIFIED. Middleware-instance tests do not satisfy this criterion. |
| Sustained saturation, queue growth, reclaim, retries and leaks | UNVERIFIED: no sustained run this round; all four historical packs rejected by current duration/artifact gates. |
| No duplicated physical work / Goal reconciliation | UNVERIFIED: admission probes are not physical-work uniqueness or sustained reconciliation proof. Accepted TTL/reclaim semantics do not waive load validation. |
| Rate/security/degraded non-bypass | NOT MET for aggregate rate allowance: executed real-middleware tests reproduce a second allowance on replica 2 for the same identity. Full concurrent RC security/degraded validation UNVERIFIED. |
| All requested metrics and thresholds | PARTIAL: child-process sampler test passes; complete RC PostgreSQL, application-loop, queue, worker, error/timeout telemetry and threshold compliance UNVERIFIED. |
| Active-work kill/restart and drain/fencing/recovery | UNVERIFIED: no deployed replica killed/restarted this round; historical terminal counts cannot establish physical-work recovery. |
| Long-running exact RC artifact/configuration | BLOCKED: no designated immutable RC/configuration supplied, no qualifying ≥14,400-second evidence; host-process driver cannot certify it at any duration. |
| Findings filed/reclassified at earliest invariant | PARTIAL: local F11/F12 evidence-validity classification exists at M3-A; external filing UNVERIFIED and no GitHub mutation permitted. |
| Machine/human evidence tied to exact hashes | PARTIAL: historical packs preserved and rejected; qualifying exact-RC image/package/commit/config evidence UNVERIFIED. |

## Handoff

**BLOCKED**: actual vulture failure does not reproduce; no source or ledger
change is justified. The prior acceptance block remains unresolved, not hidden
by passing deterministic checks. This checkpoint is the sole changed file.
No tests added or counts changed, so no inventory delta is required. No code,
runtime configuration, ledger, or historical evidence changed.

Next owner action: designate the immutable promotion RC/configuration, settle
aggregate-limit acceptance versus the existing per-process contract, complete
the representative production workload and physical-work/telemetry oracles,
then execute ≥4 hours against that unchanged exact deployment. Do not schedule
another short host-process run or documentation-only repair to close #860.

Progress: checked 1 issue, done 0, skipped 0 issues, validation command errors 0;
5 database tests skipped. Local commit is handoff only, not integration approval.

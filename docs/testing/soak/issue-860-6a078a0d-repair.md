# Issue #860 — repair checkpoint (job 6a078a0d)

## Frozen scope

- Issue #860 only; branch `auto-860`, starting head
  `720e95bb83bde4917edff664c6d357c2e1051a89`, supplied base
  `cd5618223cbdd9ac55d40695987e09fd8b4ef184`.
- Starting worktree clean. No incoming work required salvage.
- Inputs: supplied dispatch-context.json and prior a8afdb65 result; no
  check-*.log files were present in the assigned job directory.
- Review scope: scripts/soak/run_soak.py, tests/test_soak_promotion_gates.py,
  production rate-limit/task middleware, adjacent tests, load profile,
  historical round6 evidence, relevant ADRs and exact vulture CI gate.
- Edit scope: this checkpoint and only reproduced issue-related repairs;
  quality/vulture-baseline.json is permitted only if the requested exact scan
  identifies reviewed retained identities. No speculative ledger changes.
- Assumption: writer lane, not verifier-only; local validation and commit are
  required. Historic shakedown evidence cannot certify the current RC.

## Progress

Snapshot and input inspection complete; read the captured issue body and all
28 comments. Prior BLOCKED was not a develop-sync conflict. No merge warranted.

The exact requested vulture command passed: 1,338 reviewed identities and
findings, zero unclassified / never-allowlist identities. No source or ledger
repair is justified by this scan. Read the load profile: its explicit production
workload and exact-artifact limitations remain blockers, not acceptance waivers.
Promotion is not claimed. No GitHub mutations or alternate execution/authorization
paths.

## Executed validation

- `git diff --check cd5618223cbdd9ac55d40695987e09fd8b4ef184...HEAD`:
  passed; previous whitespace findings do not reproduce.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 2,920 files.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests -x -q`:
  547 passed, 8 skipped, 22 deprecation warnings in 45.29 seconds.
  This executes real middleware replica-selection counterexamples for both
  identity classes and live child-process resource sampling, not a production
  deployment or long soak.

## Architecture reconciliation

Read ADR-081 (Proposed deployment), ADR-085 (Accepted principal rate limiting),
ADR-081226-a66b (Accepted lifecycle), and ADR-081626-f383 (Accepted fencing).
Retain `Goal -> Graph -> Run -> NodeRun -> Attempt`; execution authority stays
with canonical persistence and AttemptExecutionService. ADR-f383 explicitly
leaves expiry takeover/recovery supersession to a later contract: do not invent
soak-side reclaim authority to satisfy issue wording. ADR-085 does not establish
a cluster-wide implementation or waive the issue's replica-selection criterion.
The existing limiter documents process-local state, and the executed middleware
tests reproduce fresh allowance on the second instance. No runtime rewrite or
ledger edit is justified as a vulture repair.

## Additional executed gates

- `uv run python scripts/check-ratchet-provenance.py`: passed, 49 consumers;
  existing invalid-escape SyntaxWarning did not fail the gate.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `uv run python scripts/check-suite-inventory.py`: passed, 14 suites,
  26,020 unique identities, no copied-file duplicate evidence.
- `uv run python scripts/check-backlog-consistency.py`: passed, 168 items.
- Repeated the exact vulture scan with
  `RATCHET_BASE_REV=cd5618223cbdd9ac55d40695987e09fd8b4ef184`: passed, 1,338
  reviewed identities; reported trusted merge base `94781cf6b708`.
  Arguments match `.github/workflows/vulture-ratchet.yml:82-85`.
- Inline `uv run python` imported the current driver and evaluated historical
  `m3a-round6-shakedown.json`: asserted failures exactly `sustain_duration` and
  `exact_rc_artifact`, and asserted current preflight artifact check is false.
  This validates rejection, not the truth of the historical measurements.

No test additions or changes, so no inventory delta is required. No historical
measurements edited; no scanner failure was reproduced to repair.

## All ten acceptance criteria

| Criterion | Evidence / disposition |
|---|---|
| Representative RC profile | PARTIAL: profile exists, but `m3a-load-profile.md:152-166` omits concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background work. Production representativeness UNVERIFIED. |
| Two application replicas | `deploy/docker-compose.prod.yml:26-77` declares two replicas. Exact production topology execution UNVERIFIED; current driver explicitly boots host processes (`run_soak.py:635-647`). |
| Sustained saturation, reclaim, retry, leaks | UNVERIFIED. Historical evidence is 90.43 seconds versus 14,400 required (`m3a-round6-shakedown.json:221-224`); executed evaluator rejects it. |
| No duplicate physical work / Goal reconciliation | UNVERIFIED. Historical schedule admission probe cancels its queued Run (`m3a-round6-shakedown.json:12-15`), not physical Attempt execution. No new production race/reconciliation workload executed. |
| Replica-selection non-bypass / security / degraded behavior | NOT MET for a shared allowance. Executed real middleware test `tests/test_soak_promotion_gates.py:439-488` yields `[200, 200, 429]` independently on both instances for authenticated and unauthenticated identities. `main.py:593` installs this middleware in production; its process-local state is explicit at `api/rate_limit.py:25-30,72-76`. Sustained production security/degraded behavior UNVERIFIED. |
| Complete telemetry and thresholds | PARTIAL: live child-process sampling and missing-measurement tests passed. Application-loop latency, complete worker coverage and sustained database/queue/error/leak measurements UNVERIFIED (`m3a-load-profile.md:158-166`). |
| Kill/restart during active work, drain/fence/recover | UNVERIFIED. Historical process exit/rejoin does not correlate active physical work with fencing and recovery. No production fault injection performed this round. |
| Long exact-RC soak | NOT MET: current evaluator rejects historical duration and artifact; current runner cannot certify the production image/config even after four hours. |
| Findings classified to earliest broken invariant | PARTIAL: backlog consistency passed and existing F9 backpressure test passed against the canonical task admission spine. Completeness of filing/reclassification UNVERIFIED; no GitHub mutation permitted. |
| Machine/human evidence tied to exact hashes | PARTIAL: historical JSON/Markdown exist; JSON records `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not the assigned head. Current promoted image/package/config-bound evidence UNVERIFIED. |

## Handoff

**BLOCKED**, not merge-ready. Changed file: this validation/handoff report only.
Existing source and gates pass focused validation; no evidence justifies speculative
code changes or ledger amendments. The earlier whitespace failures no longer
reproduce. The unresolved blocker is production acceptance, not vulture CI.

Next prerequisites: select the immutable RC artifact/configuration; settle the
replica-wide allowance claim with the security owner; complete representative
production workloads and physical-work/application telemetry; execute at least
four hours on the exact supported topology with active-work kill/restart; publish
hash-bound results and classify any failures. Preserve the canonical authority
model and accepted fencing boundary. Another identical scanner-repair dispatch
cannot produce the missing soak evidence.

Checkpoint: checked 1 issue; done 0 acceptance completions; skipped 0 issues;
errors 0 validation-command failures. Local commit records blocked handoff only,
not integration approval.

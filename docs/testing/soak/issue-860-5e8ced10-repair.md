# Issue #860 — job 5e8ced10 repair checkpoint

## Frozen scope

- Only issue #860; no linked PR or issue mutations.
- Assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD `bbbcbb47beafc706ecbd0fedcd383485281f2e4b`; base `420d503d4156225907ec673b1e70caa19101241d`; clean at entry.
- Review targets: supplied dispatch snapshot and prior result; repository instructions; execution-runtime, lease-fencing, cost/quota and release ADRs; `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, server rate-limit middleware and adjacent tests; load profile and round30 evidence; vulture gate/ledger and suite-inventory gate/notes.
- Write targets: this report; ledger only if reproduced identities require correction; inventory notes only if a reproduced inventory discrepancy requires correction. No speculative production redesign.
- No driver `check-*.log` files were present in the supplied job-directory listing. Prior result says BLOCKED, but its claims are not treated as executed validation for this round.
- Assumption: this is the assigned writer/CI-repair lane, not the read-only verifier lane. A passing vulture scan does not justify ledger churn or establish soak acceptance.

## Progress

1. Requested exact vulture command PASS: 1322 findings, 1322 reviewed identities, zero unclassified/never-allowlist. No unbanked identities were reported; ledger amendment is not warranted. The gate reports merge base `2f56be40ad24`, not the supplied dispatch base; no authorization or ledger change is being inferred from either.
2. Read the issue's full acceptance body from the supplied snapshot. Current profile explicitly calls the runner a preflight emulator and retains representative-workload and long-window gaps. Accepted runtime/fencing ADRs require canonical Attempt execution authority; admission deduplication is not physical-work proof. ADR-085 requires per-principal enforcement and does not waive replica-selection acceptance.

3. `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS, 3306 files. `uv run python scripts/check-suite-inventory.py`: PASS, all 17 suites; tests/ = 5354; 31489 unique identities. The supplied inventory mismatch does not reproduce; no inventory amendment warranted. Logs: `/tmp/860-5e8ced10-{ruff,format,inventory}.log`.
4. Read actual production limiter, current promotion evaluator and adjacent tests. Limiter allocates an `InMemoryRateLimiter` per middleware instance. The existing regression explicitly compares fresh allowances for the same identity across two instances. Accepted lease-reclaim ADR adds renewal/reclaim to the earlier fencing boundary; no competing recovery mechanism is appropriate. Release ADR requires immutable RC provenance and re-soak after changes, not relabeling this branch as an RC.

5. `uv run pytest tests/test_soak_promotion_gates.py -x -q`: PASS, 84 tests in 1.36s. The executed tests at lines 477–526 reproduce `[200, 200, 429]` on each independent middleware instance for the same principal/IP. Switching replicas restores allowance. Production installs this middleware at `packages/maistro-server/src/maistro_server/main.py:648`; construction is at `api/rate_limit.py:93-100`. These tests exercise real middleware but are not a deployed multi-replica soak.
6. `uv run pytest packages/maistro-server/tests -x -q`: PASS, 566 passed, 8 skipped, 22 HTTP status deprecation warnings in 36.26s. Logs: `/tmp/860-5e8ced10-{soak-tests,server-tests}.log`.
7. `uv run python` imported the current driver, loaded `docs/testing/soak/evidence/m3a-round30-shakedown.json`, and asserted that `failed_promotion_checks` returns exactly `['sustain_duration', 'exact_rc_artifact']`. Also asserted `preflight_artifact_check()['ok'] is False`. Both assertions PASS. This is expected rejection, not a successful soak. Historical JSON records 420.08 seconds and commit `c4f45b309fd622f2e8a4b315dad35e721d81aad3`, not the assigned HEAD.
8. Confirmed requested scanner arguments match `.github/workflows/vulture-ratchet.yml:82-85`. No sync conflict exists; no remote fetch or merge was necessary.

## Acceptance audit

| Criterion from issue snapshot | Executed evidence / status |
| --- | --- |
| Representative RC workload profile | **UNVERIFIED as complete**. Profile exists, but `m3a-load-profile.md:167-183` explicitly lacks concurrent user/Workspace population, Graph fan-out, successful tool/model/Canvas work and Goal/background reconciliation. |
| At least two application replicas | **UNVERIFIED for current RC**. Middleware tests exercise independent instances, not two deployed RC replicas. Historical host-process preflight is not current RC proof. |
| Sustained saturation, queue growth, lease reclaim, retries, leaks and restart | **UNVERIFIED**. Evaluated historical run is 420.08s, below the 14400s profile requirement. Pool saturation, reclaim and long-window coverage remain absent from the documented profile evidence. |
| No duplicated physical schedule/task/Run/Attempt/Goal work | **UNVERIFIED**. Round30 JSON lines 11–15 cancel the schedule probe Run after admission; this cannot establish physical Attempt fencing or Goal reconciliation. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; no second scheduler/recovery authority introduced. |
| Rate/security/degraded enforcement cannot be bypassed by replica selection | **NOT PROVEN; counterexample reproduced** by the executed middleware tests. `api/rate_limit.py:32-37` deliberately documents independent N-times-limit budgets. This does not waive #860's stronger requirement. Sustained security/degraded behavior remains UNVERIFIED. |
| PostgreSQL/application/process/queue/error telemetry with thresholds | **UNVERIFIED as complete**. Profile contains partial thresholds; driver loop lag is not application event-loop lag and required worker/saturation/reclaim observations remain gaps (`m3a-load-profile.md:167-183`). No new production telemetry collected. |
| Active-work kill/restart proves drain/fencing/recovery | **UNVERIFIED**. Process exit/rejoin and terminal Run counts do not demonstrate physical-work recovery; no current RC active-work exercise performed. |
| Long-running exact RC artifact/configuration | **NOT MET by evaluated evidence**. Current driver always rejects exact artifact at `scripts/soak/run_soak.py:744-755`; historical evidence fails both duration and artifact. No selected immutable RC image/config identity was supplied. |
| Findings filed/reclassified before promotion | This local report preserves the canonical execution and security-budget blockers; external filing/reclassification is **UNVERIFIED**. No GitHub mutations permitted or performed. |
| Machine/human evidence tied to promoted hashes | **UNVERIFIED for current RC**. Historical JSON names an older host-process preflight. This report records local checks only, not promotion-grade evidence. |

## Outcome and handoff

**BLOCKED.** Requested CI failures do not reproduce, so no dead-code removal,
ledger amendment, inventory correction or cosmetic product change is justified.
Existing acceptance blockers are not a develop-sync conflict and cannot be
resolved by banking scanner identities. No new test was added; no inventory-delta
note is required. Changed file: this report only.

No new live soak was attempted: extending the current runner cannot satisfy its
explicitly false exact-artifact gate, nor supply missing representative workloads.
A selected immutable RC and runtime configuration, complete production-path workload
and telemetry coverage, replica-selection-resistant enforcement through the existing
canonical identity path, and a >=4-hour exact-artifact run with physical-work
fencing/reclaim/recovery evidence are still required. Do not re-dispatch unchanged
vulture-only repair as though it could resolve these acceptance prerequisites.

All validation commands above passed; acceptance remains blocked. Progress:
checked 1 issue, done 0 acceptance-complete issues, skipped 0 issues, errors 0
validation commands, blocked 1. Next: provide the RC/protocol prerequisites and
complete the production soak. No linked PR processing, gate weakening, ledger/grant
changes, background execution, push or GitHub mutation occurred.

This report is the local commit handoff, not integration approval.

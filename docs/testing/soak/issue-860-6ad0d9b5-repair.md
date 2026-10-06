# Issue #860 — repair checkpoint (6ad0d9b5)

## Scope and disposition

**BLOCKED: no evidence-based vulture repair is available at the assigned HEAD.**
The exact scanner passes; issue acceptance still requires a representative,
long-running, exact-RC production soak. This report is not promotion approval.

- Frozen item: #860 only; branch `auto-860`, `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `be75c95ebb3ac74df5a0d9643a6d2449311009c1`.
- Supplied base: `626683154ce9dbd521e6754cee494190c0fb29f0`.
- Initial tree was clean, both refs resolved, no salvage or merge conflict.
- Inputs: supplied dispatch and prior result, repository instructions, accepted
  execution-fencing/recurrence/rate/measurement ADRs, existing runner, profile,
  historical evidence, middleware, focused tests and CI workflow.
- Writer role assumed from the repair assignment. No driver `check-*.log` files
  were present initially; the checks below were executed afresh.
- Only this report changes. No source, tests, inventory counts, ledger, grant or
  historical evidence changes are justified by the observed CI results.

## Executed validation

Logs are in `/home/dev/maistro/jobs/6ad0d9b5e1924ded89ddae0afdda1481/`.
All commands completed with exit 0:

| Command | Result / log |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1,336 findings / 1,336 reviewed identities, zero unclassified or never-allowlist; `check-vulture.log` |
| Same scanner with `RATCHET_BASE_REV=626683154ce9dbd521e6754cee494190c0fb29f0` | Same result; resolver uses merge base `56332162cf63`; `check-vulture-explicit-base.log` |
| `uv run ruff check .` | PASS; `check-ruff.log` |
| `uv run ruff format --check .` | 3,003 files already formatted; `check-format.log` |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 61 passed in 3.14s; `check-pytest.log` |
| `uv run python scripts/check-ratchet-provenance.py` with supplied `RATCHET_BASE_REV` | PASS, 49 consumers; `check-provenance.log` (non-failing syntax/local-CORS warnings) |
| `uv run python scripts/check-shipped-surface-truth.py` with supplied `RATCHET_BASE_REV` | PASS; `check-shipped.log` |
| `uv run python -` loading the current runner with `runpy`, then evaluating historical round-6 JSON | Assertions confirm rejection of `sustain_duration` and `exact_rc_artifact`; `check-evidence.log` |
| `git diff --check 626683154ce9dbd521e6754cee494190c0fb29f0...HEAD` | PASS; prior whitespace finding no longer reproduces |

The focused tests exercise actual production limiter instances: both credential
classes receive `[200, 200, 429]` on replica 1 and then independently on replica
2 (`tests/test_soak_promotion_gates.py:439-488`). Production installs this
middleware at `packages/maistro-server/src/maistro_server/main.py:628`; it creates
an `InMemoryRateLimiter` per instance (`api/rate_limit.py:72-76`). This is a
reachable counterexample to a shared allowance, not a deployed concurrency soak.
Other passing tests cover fail-closed CLI gates, admission evidence handling,
backpressure HTTP behavior and real child-process resource sampling.

## Acceptance audit

| Criterion | Evidence / remaining requirement |
| --- | --- |
| Representative users/Workspaces and Graph, schedule, queue, tool/model, Canvas and worker mix | UNVERIFIED. Profile explicitly lists missing workloads at `m3a-load-profile.md:152-166`; its single-key degraded-model mix is insufficient. |
| At least two production application replicas | UNVERIFIED. Static topology and two middleware instances are not a live exact-RC deployment. |
| Sustained saturation, queues, reclaim, backoff, leaks and restart | UNVERIFIED. Re-evaluated historical evidence records 90.43 seconds versus required 14,400 (`evidence/m3a-round6-shakedown.json:165,221-224`). No long soak executed this round. |
| No duplicate physical work, including Goal reconciliation and Attempt fencing | UNVERIFIED. Admission assertions do not observe physical execution; profile says the schedule probe cancels its Run without execution (`m3a-load-profile.md:191-200`). |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Independent replica allowance counterexample reproduced by both identity-class tests above. Full deployed security/degraded behavior UNVERIFIED. |
| PostgreSQL, application-loop, worker/process, RSS/fd, queue and error metrics with thresholds | UNVERIFIED end to end. Sampler regression passes, but driver-loop timing is not application-loop timing; profile records remaining telemetry gaps. |
| Kill/restart during active work proves drain/fencing/recovery | UNVERIFIED. Gate tests reject incomplete evidence; no active-work exact-RC restart was executed. |
| Long soak of exact RC, rerun after code/config changes | UNVERIFIED. Current `preflight_artifact_check()` returns false (`scripts/soak/run_soak.py:635-646`); current evaluator rejects historical duration/artifact. Longer preflight cannot clear this gate. |
| Findings classified to earliest broken milestone before promotion | UNVERIFIED for the missing representative RC run. Existing historical triage is not fresh complete load evidence; no GitHub mutations permitted or performed. |
| Human/machine evidence tied to exact image/package/commit/config hashes | UNVERIFIED for current RC. Historical JSON and this validation report are not a current promoted-image/configuration soak. |

## Contract reconciliation and next action

Accepted ADR-082126-f69c requires schedules to produce canonical Runs, not a
second scheduler. ADR-081626-f383 requires physical Attempt fencing; admission
counts cannot substitute for it. ADR-085 requires principal-keyed limits but does
not establish cluster-wide enforcement. The process-local N-times allowance
explicitly documented for #842 does not prove #860's stronger non-bypass criterion.
ADR-083026-a91e forbids fabricating missing measurements as zero. The canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` path is unchanged.

No new scanner identity exists to amend under the CI-repair exception. Do not
repeat ledger-only repairs without a new actual failing scan. Next work requires
an immutable production RC image/configuration, representative production-path
workloads and missing telemetry/physical-work probes, reconciliation of the
cross-replica rate contract, then a fresh >=4-hour exact-RC soak and finding triage.
No test additions were made, so no inventory delta is required.

Checkpoint: checked 1 issue; done 0 acceptance-complete issues; skipped 1 absent
CI repair; 0 failed validation commands; 1 blocked acceptance item. Existing work
is preserved. This report is committed locally as the required handoff; no push,
PR, merge, issue comment or closure is authorized.

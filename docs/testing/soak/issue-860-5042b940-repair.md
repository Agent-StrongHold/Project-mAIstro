# Issue #860 — repair checkpoint (5042b940)

## Frozen scope

- One assigned item: issue #860, branch `auto-860` in `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `7735adaf39f491132757139dec7bf1a72103fed7`.
- Supplied develop base: `11376c7bef4ea7d17195b90bea8ca9a64a769bb1`.
- Inputs: supplied `dispatch-context.json`, optional prior result, existing soak
  implementation/tests/docs, repository instructions, relevant ADRs, CI workflow
  and vulture checker/baseline. No GitHub queries or mutations.
- Allowed repair targets: identities actually reported by the exact vulture
  command, their source/adjacent tests, `quality/vulture-baseline.json` under the
  explicit CI-repair exception, inventory note if tests change, and this report.
- Initial worktree was clean; HEAD matches assignment. No salvage needed.
- Job directory contains no `check-*.log` files; execute validation locally.

## Assumption

This is a writer CI-repair round, not permission to replace production execution
or authorization paths. Multi-hour representative release-candidate soak remains
an independent acceptance requirement; passing static checks cannot prove it.

## Progress

- Read the supplied issue acceptance and latest comments, prior result, repository
  instructions, vulture CI workflow, load profile, and accepted fencing/rate/
  recurrence ADRs. Prior result is evidence only, not reused validation.
- `uv sync --locked --extra dev`: PASS.
- `RATCHET_BASE_REV=11376c7bef4ea7d17195b90bea8ca9a64a769bb1 uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  PASS, 1,336 findings / 1,336 reviewed identities, zero unclassified or
  never-allowlist entries. Checker resolved merge base `56332162cf63`.
  No unbanked identity exists to repair or amend; changing the ledger would be
  unsupported. Output: `/tmp/issue-860-5042b940-vulture.log`.
- Current profile explicitly labels the host-process runner preflight only;
  canonical admission counters are not physical-work fencing proof. No alternate
  scheduler, authorization path or execution store will be introduced.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3,003 files).
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  PASS, 61 tests. Includes actual production middleware instances reproducing
  independent allowances for both authenticated and unauthenticated identities
  (`maistro_server/main.py:628` installs that same middleware in production),
  CLI rejection of four-hour preflight evidence, and real child-process resource
  sampling. These are bounded regressions, not deployed multi-replica soak proof.
- With the same resolved `RATCHET_BASE_REV`, both
  `uv run python scripts/check-ratchet-provenance.py` and
  `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `git diff --check 11376c7bef4ea7d17195b90bea8ca9a64a769bb1...HEAD`
  and `git diff --check`: PASS. Prior trailing-blank-line finding does not
  reproduce at the assigned HEAD.
- Executed the current runner's `failed_promotion_checks` against
  `evidence/m3a-round6-shakedown.json`: rejects `sustain_duration` and
  `exact_rc_artifact`. Actual duration is 90.43 seconds, required minimum 14,400;
  artifact HEAD is `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not assigned HEAD.
  `preflight_artifact_check()` returns `ok=False` for host-uvicorn-preflight.
- Local command outputs: `/tmp/issue-860-5042b940-{sync,vulture,ruff-check,ruff-format,pytest,provenance,shipped,evidence}.log`.

## Acceptance disposition

| Issue criterion | Executed evidence and limit |
| --- | --- |
| Representative users/Workspaces, request mix, Graph/node fan-out, schedules, queue, tool/model, Design/Canvas, workers | UNVERIFIED. `m3a-load-profile.md:152-166` explicitly lists missing production workloads; the existing single-key degraded-model profile is not representative proof. |
| At least two production application replicas | UNVERIFIED. Compose declares two, and middleware tests instantiate two; neither is an executed two-replica RC deployment. |
| Sustained saturation, queues, reclaim, retry/backoff, memory/descriptor/process leaks, restart | UNVERIFIED. Re-evaluated historical run lasts 90.43 seconds, not the required four hours. No long soak was run this round. |
| No duplicate physical work: schedule/task/Run/Attempt and Goal reconciliation | UNVERIFIED. Tests validate admission evidence handling, not physical work. Profile states the schedule probe cancels its Run without execution (`m3a-load-profile.md:191-200`). |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Counterexample reproduced: `test_replica_selection_has_an_independent_production_allowance` passes for both identity classes; exhausting one instance leaves another's allowance untouched. Complete deployed security/degraded behavior remains UNVERIFIED. |
| PostgreSQL/loop/worker/RSS/fd/queue/error metrics with thresholds | UNVERIFIED end to end. Child-process sampler regression passes, but driver loop lag is not application loop lag; required telemetry gaps remain explicit in the profile. |
| Kill/restart during active work proves drain/fencing/recovery | UNVERIFIED. No live RC restart or physical-work observation in this round; gate tests only prove evidence rejection. |
| Long soak of exact RC, repeated after code/config changes | UNVERIFIED and blocked by runner capability: current preflight artifact gate always rejects. Historical duration and artifact gates also reject on re-evaluation. |
| Classify findings at earliest broken milestone before promotion | UNVERIFIED for a representative RC soak not yet executed. Existing finding records are not proof of a complete fresh triage. No GitHub mutation authorized or performed. |
| Machine/human evidence bound to exact image/package/commit/config hashes | UNVERIFIED for current RC. Historical evidence carries a different commit and no exact promoted application image/config proof. This report is validation evidence only. |

## ADR reconciliation and handoff

Accepted ADR-082126-f69c requires schedule production of canonical Runs, not a
parallel scheduler; ADR-081626-f383 requires Attempt fencing, which admission
counts cannot prove. Accepted ADR-085 requires principal-keyed limiting but does
not itself establish a cluster-wide implementation. Existing #842 middleware
semantics explicitly allow N-times aggregate allowance; that is not a waiver of
#860's stronger non-bypass criterion. ADR-083026-a91e forbids representing missing
measurements as zero. ADR-081 is Proposed and cannot override accepted contracts.
The canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` model is unchanged.

**Outcome: BLOCKED, not merge-ready.** The requested vulture CI failure is not
present, so there is no evidence-based source or ledger repair to make. Only this
report changed; no tests or inventory counts changed, so no inventory delta is
needed. Existing artifacts and code were preserved. No gate was weakened.

Next: select an immutable production RC image/configuration with the required
reachable model gateway, complete the representative production-path workload
and missing telemetry/physical-work probes, reconcile the cross-replica rate
contract through the canonical path, then execute a fresh >=4-hour exact-RC soak
and classify its findings. A longer run of this preflight cannot clear the
artifact gate. Do not repeat ledger-only repair rounds without new failing
scanner evidence.

Checkpoint: checked 1 assigned issue; CI failure absent (repair skipped), 0
acceptance-complete issues, 1 blocked issue, 0 failed validation commands.
Final pre-commit status contains only this new report, with no unmerged paths.
The report is the sole file staged for the local handoff commit.

# Issue #860 — job 94cb1fe2 repair checkpoint

## Frozen scope

- Assigned issue: #860 only; writer in `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD verified: `51202c3bf143d04a201e4cf4e506dacca45d2f78`; worktree clean.
- Base: `430139cb729ec1bbf51a5e77ef602b8192f5d594`.
- Inspect existing soak profile/evidence, adjacent promotion tests, production limiter,
  relevant execution/deployment/rate/quality ADRs, and exact-debt gate/ledger.
- Planned edit surface: this checkpoint and `quality/vulture-baseline.json` only
  if the requested scanner supplies actual repairable debt evidence. No guessed
  source repairs, new scheduler, or changes to production authorization.
- The supplied prior result was read: it reports BLOCKED, not release approval.
- Job directory initially contains events, manifest, prompt, and state only;
  no driver `check-*.log` files are available to inspect.

## Assumptions and boundaries

This is a writer repair, not the read-only verifier lane. Existing historical
notes and evidence are preserved. Missing RC artifact/configuration identity
cannot be inferred from the branch head or host-uvicorn preflight. No GitHub
mutations or ledger-gate weakening are permitted. Run the requested scanner and
focused acceptance checks before deciding whether any ledger edit is justified.

## Validation

- Requested Vulture command executed with a 600-second timeout: FAIL (exit 1).
  `worker-vulture.log` in this job directory records 1377 findings, zero
  unclassified/unreachable findings, and **no candidate bookkeeping delta**.
  Nine identities are unauthorized against trusted base `430139cb729e` (six
  relocated crypto API identities, lazy import hook, two Principal adapters).
  The previous candidate-ledger repair is already present. Re-running update
  would not repair the trusted-base failure; no ledger/grant/gate change is made.
- Relevant ADRs read: accepted runtime 081426-1f7c, fencing 081626-f383,
  recurrence 082126-f69c, rate policy 085, and quality provenance 083126-5e62.
  Deployment ADR-081 is Proposed. Admission is not physical-work proof; no
  alternative execution authority is warranted. Candidate bookkeeping cannot
  authorize new debt against the protected base.
- Existing H3 prose at `m3a-soak-evidence.md:171` already disclaims shared state;
  the supplied stale shared-store finding is not reproduced at this head.
  The underlying acceptance mismatch remains: production `rate_limit.py:25-30`
  explicitly provides independent per-process budgets.

- `uv run ruff check .`: PASS (`worker-ruff.log`).
- `uv run ruff format --check .`: PASS, 2717 files (`worker-format.log`).
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **88 passed, 5 skipped** (`worker-pytest.log`). PostgreSQL integration skips
  are not live database evidence. The production limiter regression demonstrates
  independent allowances for the same authenticated/unauthenticated identity
  on two middleware instances. ASGI transport is not multi-replica deployment
  evidence. The sampler test runs a real child process; the admission test uses
  the actual router/queue/spine but does not start physical execution.
- `uv run python scripts/check-compose-secrets.py`: PASS, eight tracked Compose
  files (`worker-compose-secrets.log`).
- `uv run python scripts/check-suite-inventory.py --suite tests/`: PASS, 4326
  tests (`worker-inventory.log`). No tests added/removed; no inventory delta.
- Direct `uv run python` invocation of `failed_promotion_checks` on the frozen
  four packs (`m3a-soak-evidence.json`, `m3a-repair-validation.json`,
  `m3a-round5-final.json`, `m3a-round6-shakedown.json`): PASS rejection assertions;
  **all fail duration and exact-artifact checks** (`worker-evidence.log`). Last
  two sustained durations are 90.17 and 90.43 seconds, not 14400 seconds.
- Validation commands used 600/1200-second tool timeouts. No deployment was
  launched: the supplied head is not a selected immutable RC/configuration,
  and the available host-process harness cannot sign promotion at any duration.

## Acceptance disposition

| # | Criterion | Evidence / outstanding proof |
|---|---|---|
| 1 | Representative RC load profile | PARTIAL: inspected `m3a-load-profile.md` defines traffic and thresholds but explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and sustained Goal reconciliation. Representative coverage UNVERIFIED. |
| 2 | At least two production replicas | Compose declares two services; historical host processes are not that artifact. Actual RC replicas UNVERIFIED. |
| 3 | Sustained saturation, reclaim, retries, leaks, shutdown | Historical duration rejected; no sustained RC run. UNVERIFIED. |
| 4 | Admission and physical-work uniqueness, Goal reconciliation | Admission oracle regressions passed; they do not prove physical Attempt uniqueness under competing leases. UNVERIFIED. |
| 5 | Security/degraded behavior and replica-selection non-bypass | NOT MET: real production middleware grants two independent allowances in executed regression. Full concurrent security/degraded production proof UNVERIFIED. |
| 6 | Complete telemetry with explicit thresholds | Profile inspected, child-process sampler regression passed; application-loop, worker, pool and long-window observations still UNVERIFIED. |
| 7 | Active-work kill/restart with drain/fencing/recovery | Historical process-exit/rejoin is not physical-work recovery proof. UNVERIFIED. |
| 8 | Four-hour exact RC artifact/configuration soak | Four historical packs mechanically rejected; runner explicitly fails exact-artifact gate at `scripts/soak/run_soak.py:635-645`. UNVERIFIED. |
| 9 | Findings filed/reclassified at earliest invariant | Existing local classifications preserved; no new runtime defect found here. External filing UNVERIFIED; GitHub mutation prohibited. |
| 10 | Machine/human evidence tied to exact artifact hashes | Historical evidence preserved, current validation tied to starting head above. No qualifying RC soak evidence; UNVERIFIED. |

## Handoff and checkpoint

**BLOCKED, not integration or promotion approval.** Only this report changed.
No production code/configuration, evidence pack, gate, ledger or grant was
modified. The supplied old H3 wording complaint has already been repaired;
repeating that edit would be cosmetic. Candidate ledger banking has likewise
already been repaired. The actual remaining CI failure needs separately
reviewed trusted-base authorization, not another candidate update.

Next: authorized owner resolves the exact-debt trusted-base discrepancy and the
replica-selection rate-limit contract mismatch; release owner selects the RC
image/configuration and completes a representative production-topology runner,
then executes a new >=14400-second soak with physical-work and recovery oracles
and complete telemetry. Do not rerun the emulator merely to consume four hours.
Every runtime/configuration change requires fresh RC soak evidence.

Item checkpoint: checked 1, done 0 (acceptance blocked), skipped 0, errors 1
(trusted-base Vulture gate). Local report commit is a handoff only.

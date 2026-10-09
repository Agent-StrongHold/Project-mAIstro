# Issue 860 — repair checkpoint (8c1c10c6)

## Frozen scope

- Issue: #860 only; writer/CI-repair round, not integration approval.
- Worktree/branch: `/home/dev/Git/wt/auto-860`, `auto-860`.
- Starting HEAD: `17dc75e49dd09c756435681acc8957ae81b1fa23`.
- Assigned base: `626683154ce9dbd521e6754cee494190c0fb29f0`.
- Initial worktree clean; no salvage required. No merge conflict present.
- Inputs: supplied dispatch-context.json and prior result 6ad0d9b5;
  no check-*.log files present in this job directory at initial inspection.
- Repair target: exact vulture scan, with ledger changes only if actual scan
  findings justify them. Validation scope: existing soak promotion tests,
  production boot contract, adjacent task admission tests, lint/format and
  relevant CI gates. No expansion to other issues or GitHub mutations.
- Files eligible for changes: this checkpoint, quality/vulture-baseline.json
  only if justified by actual findings, and scanner-identified source identities
  only after review. No tests planned; inventory delta only if tests change.

## Initial evidence and assumption

The supplied prior result is BLOCKED and reports no vulture debt. This is a
claim to recheck, not authority. The issue's ten acceptance criteria require
production execution evidence, not merely harness unit tests. A passing static
scan will not establish the exact-artifact multi-replica soak requirement.

## Exact-debt checkpoint

Executed the assigned exact command:
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`.
Exit 0: 1,336 findings, 1,336 reviewed identities, zero unclassified and zero
never-allowlist findings. Output: job-local `check-vulture-worker.log`.
No genuinely dead or unbanked identity was reported; no source or ledger
amendment is justified. The scanner reports its own ratchet base as
`56332162cf63`; this is recorded rather than conflated with the assigned diff
base. Do not manufacture a ledger change just to produce a repair diff.

## Focused validation checkpoint

- `uv run ruff check .`: exit 0, all checks passed.
- `uv run ruff format --check .`: exit 0, 3,003 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  exit 0, **61 passed in 2.30s**.
- `uv run python scripts/check-suite-inventory.py`: exit 0; all 15 suites match,
  27,048 unique test identities, no duplicate evidence.
- `git diff --check 626683154ce9dbd521e6754cee494190c0fb29f0...HEAD`:
  exit 0, no output. The previously reported blank-EOF failures do not
  reproduce against the assigned base and starting HEAD.

Logs for the uv checks are in the supplied job directory as
`check-{ruff,format,pytest,inventory}-worker.log`. No tests changed, so no
inventory note/delta is needed. Passing synthetic gate tests are not a soak.
The real production middleware regression in the focused suite reproduces
independent allowances for the same identity on two middleware instances.

## Architecture reconciliation

Reviewed ADR-081626-f383 (Attempt fencing), ADR-082526-b36a (renewal/reclaim),
ADR-085 (per-principal rate limiting), and ADR-083026-a91e (absent metrics).
Preserve Goal -> Graph -> Run -> NodeRun -> Attempt and canonical store-owned
fences: one admission or a terminal Run count cannot prove physical work was
not duplicated. Missing application metrics cannot be inferred from driver
metrics. The documented #842 process-local enforcement scope is not proof of
#860's stronger replica-selection non-bypass criterion; retain that criterion
as blocked rather than silently redefining it.

## Final checks and acceptance disposition

- `uv run python scripts/check-ratchet-provenance.py`: exit 0, 49 quality
  JSON consumers have explicit provenance; warnings remain informational.
- `uv run python scripts/check-shipped-surface-truth.py`: exit 0, complete.
- Executed the current `failed_promotion_checks` evaluator against
  `evidence/m3a-round6-shakedown.json` via `uv run python`: confirmed failures
  are `sustain_duration` and `exact_rc_artifact`. Actual duration 90.43 seconds,
  required 14,400. `preflight_artifact_check()` returns `ok=false` and
  `topology=host-uvicorn-preflight`. Job-local `check-evidence-worker.log`
  records the result; assertions passed. This reevaluates old evidence,
  **not** a fresh execution of the workload or validation of its raw claims.
- Also inspected ADR-081: it is Proposed, not an accepted waiver of the
  supported reference Compose topology's two-application-replica claim.

| Issue acceptance criterion | Current executed evidence / limitation |
| --- | --- |
| Representative users/Workspaces, Graph fan-out, schedule/queue, tool/model, Design/Canvas, workers | **UNVERIFIED**. `m3a-load-profile.md:152-164` explicitly records missing production workloads; its one-key degraded-provider mix is incomplete. |
| At least two deployed application replicas | **UNVERIFIED** for the RC. Boot-contract tests pass but inspect configuration, not deployed execution. Middleware instances are not deployed replicas. |
| Sustained saturation, growth, reclaim, retries, leaks, shutdown | **UNVERIFIED**. Historical duration is only 90.43 seconds (`evidence/m3a-round6-shakedown.json:163-165,221-224`); no new long run performed. |
| Schedule/task/Run/Attempt and Goal physical-work uniqueness | **UNVERIFIED**. Admission probe tests pass; `m3a-load-profile.md:190-200` distinguishes the cancelled schedule probe from actual execution/reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **Counterexample reproduced** by both parameterizations of `test_replica_selection_has_an_independent_production_allowance` (`tests/test_soak_promotion_gates.py:439-488`): same identity gets `[200,200,429]` on each replica. Other production concurrency/security behavior remains UNVERIFIED. |
| Complete PostgreSQL/application-loop/worker/RSS/fd/queue/error telemetry with thresholds | **UNVERIFIED**. Sampler tests pass, including real child resource growth; driver-loop and historical wrapper measurements cannot establish application-loop/worker or long-window health. |
| Active-work kill/restart drain/fencing/recovery | **UNVERIFIED**. No new deployed active-work kill; historical rejoin and terminal counters do not prove physical fencing. |
| Long-running exact RC artifact/config soak | **UNVERIFIED / blocked**. Current evaluator rejects historical duration and artifact; current runner unconditionally rejects its own topology (`scripts/soak/run_soak.py:635-646`). |
| Findings filed/reclassified to earliest invariant | **UNVERIFIED** for complete disposition. Historical F-series is documented in `m3a-soak-evidence.md`; this round cannot infer filing/completion from prose. No GitHub mutations performed. |
| Machine/human evidence bound to exact image/package/commit/config | **UNVERIFIED** for the current RC. Historical packs exist, but neither a current image-bound evidence bundle nor a new production run was generated. |

## Handoff

**BLOCKED, not merge-ready.** CI debt repair itself needs no change: the exact
scan already passes. The previous block is not a develop merge conflict and
cannot be resolved with another ledger edit, short preflight run, or gate
waiver. No source, tests, runtime configuration, ledger or grant was changed.
Only this evidence-backed checkpoint is committed in this round.

Next work requires an explicitly selected immutable RC/configuration, an
exact-Compose workload runner covering the missing representative surfaces,
physical-work/fence instrumentation and application telemetry, resolution of
the observed rate-limit scope mismatch, and a fresh >=4-hour production soak
with active-work failure/recovery observations. Merely extending the existing
host runner's duration cannot satisfy the artifact requirement. No claim is
made that the available Docker environment is incapable of running that work;
it was not executed in this bounded CI-repair round.

Progress: checked 1 issue; done 0 (issue acceptance); skipped 0; errors 0
(validation commands); next: production RC soak and unresolved acceptance
work above. Existing work preserved; no push or integration action.

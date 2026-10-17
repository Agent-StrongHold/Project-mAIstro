# Issue #860 — repair validation, job 86cb034e

## Frozen scope

- Sole item: issue #860, branch `auto-860`, starting head
  `57ef6c444971c6acfdbe09185cb357e17b321eb4`, base
  `a586560170a9ce4d72ee7d750100d0178c1f69d0` (both resolved locally).
- Clean incoming worktree; no salvage needed. Preserve all inherited work.
- Review scope: repository instructions, relevant ADRs, `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, production rate limiter, existing soak
  profile/evidence, adjacent persistence/admission tests, and CI gate definitions.
- Edit scope: this validation/handoff note only unless executed validation finds
  an actionable defect in the above scope. No speculative ledger amendment.
- Prior result read: job `a30f3c5f1a7c4ebc976267bdb42e2280` was BLOCKED.
- Current job directory contains no `check-*.log` files. Driver results are
  therefore unavailable; validation below is performed directly, not inferred.

## Initial executed result

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
passed: 1,342 reviewed identities / 1,342 findings, zero unclassified identities.
The requested CI-repair failure is not reproduced; changing the ledger without
an observed identity delta would be unjustified.

## Interpretation

This is a writer repair lane. Exact-RC identity/configuration cannot be guessed;
existing host preflight evidence is not a substitute for the required long
production-topology soak. Acceptance remains open pending fresh validation.

## Validation checkpoint

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 2,883 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py tests/test_soak_promotion_gates.py -x -q -rs`:
  **102 passed, 5 skipped**. All skips require a migrated `MAISTRO_TEST_PG_DSN`;
  no live database concurrency proof is claimed for this run.
- Executed production-middleware regression demonstrates that the same identity
  gets `[200, 200, 429]` independently from both ASGI replica instances. This
  confirms process-local budgets; it is not a deployed multi-replica soak.
- Old H3 shared-store prose is already corrected in the starting tree
  (`m3a-soak-evidence.md:171`). No redundant cosmetic correction is warranted.
- Read accepted ADR-081626-f383 (canonical Attempt fencing), ADR-082126-f69c
  (recurrence produces Runs), ADR-082826-d9f5 (RunStore execution authority),
  and ADR-085 (per-principal rate policy). ADR-081 is Proposed, not an accepted
  override. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; no alternate
  scheduler/store/authorization is introduced. ADR-085 does not waive the
  issue's explicit replica-selection requirement. ADR-081626-f383's original
  boundary does not itself establish lease-expiry takeover proof.

## Additional executed evidence

- `uv run python scripts/check-ratchet-provenance.py`: passed (49 consumers
  with explicit provenance; delegated checks passed).
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `uv run pytest tests/test_prod_stack_boot_contract.py -x -q`: **8 passed**.
  Static deployment-contract tests do not demonstrate a running topology.
- Ran `uv run python` to import the current soak module and evaluate the exact
  four existing packs named below through `failed_promotion_checks`. Asserted
  both `sustain_duration` and `exact_rc_artifact` fail for each. All assertions
  passed. Executed `preflight_artifact_check()` returns `ok=false`, topology
  `host-uvicorn-preflight`.

| Historical pack under `docs/testing/soak/evidence/` | Recorded duration gate | Current failed checks |
| --- | --- | --- |
| `m3a-soak-evidence.json` | absent | rate, LB failover, settle, admission availability, duration, artifact, drain |
| `m3a-repair-validation.json` | absent | task admission, LB failover, settle, admission availability, duration, artifact, drain |
| `m3a-round5-final.json` | 90.17 / 14400 seconds, false | rate, duration, artifact |
| `m3a-round6-shakedown.json` | 90.43 / 14400 seconds, false | duration, artifact |

These are rejection checks on preserved historical evidence, not a fresh soak
or verification of the historical functional booleans. The evaluator trusts
recorded summaries; passing unit tests cannot sign deployment acceptance.

## Acceptance audit

| Issue criterion | Evidence and disposition |
| --- | --- |
| Representative RC load profile | PARTIAL: `m3a-load-profile.md:152` explicitly records missing multi-user/Workspace, Graph fan-out, successful tool/model, Design/Canvas and Goal/background-worker workloads. No selected RC configuration justifies those exclusions. |
| At least two production application replicas | UNVERIFIED: `deploy/docker-compose.prod.yml:16-81` defines two servers, and 8 static contract tests pass; neither establishes execution of this artifact. |
| Sustained saturation, queue growth, reclaim, retries, leaks | UNVERIFIED: executed duration rejection for all four historical packs; no fresh sustained load. |
| Schedule/task/Run/Attempt physical-work uniqueness and Goal reconciliation | UNVERIFIED: `scripts/soak/run_soak.py:948` cancels the schedule probe's queued Run without executing it. Admission identity tests and backpressure tests pass but do not prove physical work fencing under load. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET for aggregate allowance: production middleware regression passed for both identity classes, independently allowing two requests on each replica; implementation is explicitly process-local (`rate_limit.py:25-30,72`). Deployment-wide security/degradation proof remains UNVERIFIED. |
| Complete telemetry with thresholds | UNVERIFIED: profile acknowledges wrapper-only historical measurements, missing application-loop observations and worker/lease telemetry; `run_soak.py:1305` measures driver-loop lag, not application-loop lag. |
| Kill/restart during active work, drain/fencing/recovery | UNVERIFIED: process rejoin summaries do not correlate physical Attempts or stale-worker effects. No new active-work restart was executed. |
| Long soak of exact RC artifact/configuration | NOT MET: all four packs fail current artifact/duration evaluation. Host preflight cannot sign this requirement (`run_soak.py:635-646`). No immutable promotion image/configuration was supplied; guessing one would not establish #89 equivalence. |
| Findings filed/reclassified to earliest invariant | PARTIAL: existing F11/F12 classify evidence validity at M3-A in `m3a-soak-evidence.md:224-252`. No new load finding this round; external filing UNVERIFIED and prohibited in this lane. |
| Machine/human evidence bound to exact artifact/config hashes | UNVERIFIED for promotion: historical packs and narrative exist but do not sign the selected RC. This note is validation evidence only. |

## Handoff and changes

**BLOCKED.** The requested vulture failure is not reproduced and the earlier
schema assertion repair now passes. No actual new repair defect was established;
do not amend a matching ledger or substitute another short emulator run.

Only this note changed. No tests were added or changed, so no inventory delta
note is needed. Runtime, deployment, ledger/grants and historical evidence remain
untouched. No push, GitHub mutation, or external filing performed.

Required next inputs/work: identify immutable #89 promotion images and resolved
runtime configuration, resolve cluster-wide rate-limit acceptance, complete the
representative workloads and application telemetry, then execute at least four
hours on that exact topology with active physical Attempt interruption/recovery
correlation. Any subsequent runtime/config change requires a new soak. These are
substantive outstanding acceptance requirements, not CI repairs.

Progress: checked 1, done 0, skipped 0, errors 0, blocked 1; next: release owner
supplies the exact RC artifact/configuration and resolves the above blockers.
Local commit follows; clean worktree required at handoff.

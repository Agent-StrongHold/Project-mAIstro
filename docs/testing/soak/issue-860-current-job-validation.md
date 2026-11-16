# Issue #860 validation — current job

## Scope and evidence

The exact-Release-Candidate soak acceptance cannot be repaired by changing the host-process harness or relabeling historical observations. The frozen issue acceptance requires representative production workloads, multi-replica behavior, a four-hour sustained run, safe recovery/fencing, findings disposition, and evidence bound to the promoted artifact.

The current branch's `docs/testing/soak/m3a-load-profile.md` explicitly lists missing concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas, Goal/background reconciliation, pool saturation, lease reclaim, and physical Attempt fencing as blockers. Its duration contract requires 14,400 seconds and says host-process preflight cannot be promotion evidence. The committed round-8 production-stack record (`git show HEAD:docs/testing/soak/evidence/m3a-round8-prodstack-extended.json`) records 1,200 seconds, `sustain_duration.ok=false`, and `exact_rc_artifact.ok=false`; it also records failures in the promotion-gate replay. No promoted RC designation or exact RC configuration is available here.

The limiter's implementation documents process-local enforcement at `packages/maistro-server/src/maistro_server/api/rate_limit.py:32-36`; ADR-085 specifies per-principal semantics but does not establish a shared cluster-wide allowance. The soak profile explicitly describes the multi-replica aggregate allowance as N× the per-replica limit, so no contrary cluster-wide guarantee is inferred.

## Validation run

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — **143 passed**.
- `uv run ruff check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py` — **passed**.
- `uv run ruff format --check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py` — **passed**.
- The assigned job directory contains no `check-*.log` files; no driver checks were available to inspect. The prior supplied job's `check-4.log` failed with package-suite drift (`expected 18435, collected 18436`). Independently reran `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`; it reproduces the same +1. The added `test_ensure_schema_fences_ddl_behind_advisory_lock` is the collected node; `docs/testing/inventory-notes/860-pg-learnings-schema-fence.md` records the corresponding +1 delta. The first note draft used a trailing slash and the gate correctly rejected its unknown suite; after correcting the suite key, reran `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` — passed at 18436/18436.
- An initial incorrect package-scoped pytest path (`packages/maistro-server/tests/test_soak_promotion_gates.py`) failed because the test lives at repository-root `tests/test_soak_promotion_gates.py`; the correct command above passed.

## Disposition

**Not promotion-ready.** The executed tests validate local promotion-gate behavior, not an exact-RC soak. Acceptance items requiring production workload coverage, long-duration soak, RC identity, complete fencing/recovery proof, external findings filing/reclassification, and evidence tied to the promoted RC remain unmet or unverified. No gate was weakened and no evidence was represented as promotion proof.

That earlier round recorded 332 tracked documentation deletions at its own start; this is historical context, not the state of the current assigned head. The current worktree started clean.

## Current assigned-head revalidation

Starting head: `1fddbce2312385656e14aac4348c94890e088875`; develop base:
`157c3f615beee120f8088caf801ab3eb17b5fa12`. The prior driver result's server
inventory check failed (`expected 670, collected 671`). The branch contains the
added `test_tasks_concurrency_backpressure.py`; its missing +1 was not recorded
in the existing inventory delta. Updated
`docs/testing/inventory-notes/860-pg-learnings-schema-fence.md` to record +1 for
both the core and server suites.

Executed on this head:

- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-server/tests` — PASS, 671/671.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` — PASS, 18,501/18,501.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` — 38 passed, 6 skipped. The skips are not live-PG proof.
- `uv run ruff check .` — PASS; `uv run ruff format --check .` — PASS.

## Disposition and criterion audit

**NEEDS-DEEP-REVIEW / not promotion-ready.** The real inventory drift was fixed
as a missing inventory-note delta; no test or gate was weakened. The relevant
acceptance criteria remain incomplete:

| Issue criterion | Evidence at this head / disposition |
|---|---|
| Representative user/Workspace, Graph fan-out, schedule/task, model/tool, Design/Canvas, worker profile | `m3a-load-profile.md` explicitly says concurrent user/Workspace, Graph fan-out, successful tool/model, Design/Canvas, and sustained Goal/background reconciliation are missing. UNVERIFIED. |
| At least two production replicas | Existing host-process preflight is not the production Compose artifact; no exact-RC multi-replica run established. UNVERIFIED. |
| Sustained load with saturation, growth, reclaim, backoff and leak observations | Profile requires 14,400 seconds. Round-8 record was 1,200 seconds and failed duration/artifact gates; pool saturation, lease reclaim, and physical fencing remain gaps. UNVERIFIED. |
| Exactly-once/fenced operations across replicas | Targeted regression tests passed, but do not prove all physical work across replicas; ADR-081626-f383 explicitly leaves lease-expiry takeover/reclaim undefined. PARTIAL; production proof UNVERIFIED. |
| Security/rate limit cannot be bypassed by replica selection | Current limiter is process-local and the profile explicitly says aggregate allowance can scale with replica count. The acceptance's no-bypass assertion is not proven. UNVERIFIED. |
| Required telemetry and thresholds | The preflight captures specified observations, but no four-hour exact-RC measurement set exists. PARTIAL; promotion evidence UNVERIFIED. |
| Kill/restart with drain, fencing and recovery | Earlier drain probe recorded failure; no current exact-RC successful drain/fencing/recovery proof. UNVERIFIED. |
| Exact RC/config soak; re-soak on code/config change | No promoted RC identity/config is available and host preflight always fails `exact_rc_artifact`. UNVERIFIED. |
| Findings filed/reclassified to earliest invariant | No evidence in this job establishes complete disposition of findings discovered under qualifying load. UNVERIFIED. |
| Machine/human evidence tied to exact hashes | Existing evidence is host preflight / historical and does not bind a promoted artifact. UNVERIFIED. |

The targeted tests establish only their specific regression contracts. They are
not equivalent to the requested release soak. No source behavior or promotion
gate was changed, and no integration/promotion approval is implied.

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

At job start, the worktree already contained 332 tracked documentation deletions (including historical soak evidence and inventory notes) with no staged changes. They were not staged, restored, or discarded in this job; they remain preserved as an uncommitted diff and must be investigated by the owner before integration. This report is committed independently of those deletions.

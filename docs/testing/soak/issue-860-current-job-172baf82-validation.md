# Issue #860 — current job validation (blocked)

Starting HEAD: `2103718306e29331609eb3452b54185cd13fb00d` (assigned branch state is clean). The job directory contains no `check-*.log` files; validation was run directly. No qualifying production RC or soak evidence was supplied.

## Executed validation

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS: 1,321 reviewed identities equal 1,321 findings; zero unclassified and zero never-allowlist. No ledger change is warranted.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — PASS: 84 tests. This tests gate behavior, not a production deployment or long-running soak.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS: 3,413 files already formatted.
- Re-evaluated `docs/testing/soak/evidence/m3a-round109-shakedown.json` with the current `scripts/soak/run_soak.py` evaluator — failed promotion checks are exactly `sustain_duration` and `exact_rc_artifact`; recorded sustain is 420.05 seconds. `preflight_artifact_check()` returns `ok: false`, topology `host-uvicorn-preflight`, reason `not the exact production Compose image and configuration`.
- One initial evaluator invocation passed a `Path` rather than the required evidence dictionary and raised `AttributeError`; corrected invocation above passed the parsed JSON. This was a validation-command error, not a product failure.

## Production behavior and ADR reconciliation

The harness intentionally refuses to certify its host-process preflight as the exact production Compose RC (`scripts/soak/run_soak.py:744-754`), and promotion requires both sustained duration and exact artifact evidence (`:764-779`). The retained round-109 report records 420.05 seconds against 14,400 seconds and a failed exact-RC check (`docs/testing/soak/evidence/m3a-round109-shakedown.json:221-224,283-287`). The profile explicitly lists concurrent user/Workspace population, Graph fan-out, successful tool/model calls, Design/Canvas, and Goal/background reconciliation as gaps, and warns that process-exit/rejoin does not prove physical-work fencing (`docs/testing/soak/m3a-load-profile.md:165-207`).

Accepted ADR-081226-a66b keeps the canonical lifecycle `Run -> NodeRun -> Attempt`; ADR-081626-f383 assigns lease/fencing authority to canonical Attempt persistence and states expiry takeover/recovery is not yet defined. Nothing in this validation creates a competing scheduler, execution authority, Goal store, or authorization path. ADR-073126-c4e1 requires soaking the selected RC and a new RC after fixes; it does not waive exact artifact evidence.

## Acceptance disposition

| Criterion | Evidence / disposition |
|---|---|
| Representative RC profile | UNVERIFIED; material workload gaps remain in `m3a-load-profile.md:165-183`, and no selected RC/configuration establishes applicability. |
| At least two application replicas | UNVERIFIED for the selected RC; no selected exact-RC deployment was run. |
| Sustained load observing saturation, queues, reclaim/retry, resource leaks and restart | NOT MET: retained run is 420.05 seconds; required minimum is 14,400 seconds. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | UNVERIFIED; no qualifying physical execution and recovery evidence. |
| Rate/security/degraded behavior under concurrent replica selection | UNVERIFIED at exact-RC integrated load grade. |
| Required PostgreSQL, event-loop, worker/process, RSS, descriptor, queue and error telemetry with thresholds | UNVERIFIED for exact RC and the representative full profile. |
| Kill/restart during active work proves drain/fencing/recovery | UNVERIFIED at exact-RC promotion grade. |
| Long soak of exact RC artifact/configuration | NOT MET; current evidence fails duration and artifact checks, and no RC was supplied. |
| Findings reclassified to earliest broken invariant | UNVERIFIED for a qualifying representative production run. |
| Human/machine evidence tied to exact image/package/commit/config hashes | NOT MET for a selected exact-RC soak. |

No tests or production code were changed; the test inventory is unchanged and no inventory-delta note applies. Do not substitute a longer host-process preflight for the production RC soak. Required next input is a release-owner-designated immutable RC/configuration, applicable representative workload and cross-replica enforcement contract, followed by a >=14,400-second deployed soak with physical Attempt/recovery observations and hash-bound evidence. The issue remains blocked; this validation is not integration approval. No remote action was taken.

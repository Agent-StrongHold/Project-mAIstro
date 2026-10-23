# Issue #860 — round 157 validation and handoff

Snapshot: issue #860, branch `auto-860`, starting HEAD
`b8d1cd5ef65c32546d24d1fc5877c61482febc5a`. Only this issue was processed.
The supplied job directory contains no `check-*.log` files. Prior results were
leads only; current source and tests were rechecked. No immutable RC image,
normalized production configuration, or authorized production target was
provided. No production soak was attempted, no external actions were taken.

## Executed validation

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q` — **105 passed** (one Starlette deprecation warning).
- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — passed (3471 files).

These are focused local tests and quality checks, not deployed soak evidence.
No tests changed or were added; suite inventory delta is zero, so no inventory
note is required.

## Reachable behavior / architecture

`packages/maistro-server/src/maistro_server/api/rate_limit.py` constructs an
`InMemoryRateLimiter` inside each middleware instance. Its module documentation
explicitly states the aggregate allowance is N × the configured limit and not
cluster-wide; the profile likewise says replica-local enforcement cannot prove
that selection cannot increase a principal's aggregate allowance. A passing
component test is not proof of the issue's stronger non-bypass criterion. This
is an actual documented production behavior gap, not a speculative scanner
finding. Resolving it needs an agreed shared-budget contract/store at the
existing enforcement seam; this round does not invent a second authorization
path or coordination authority.

Read accepted ADR-085 (per-principal rate limiting) and
ADR-081626-f383 (durable canonical Attempt lease/fencing; stale-writer
rejection). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. Neither
admission tests nor process restart counts substitute for physical Attempt
fencing/recovery proof. No scheduler, Goal store, event authority or execution
authority was added.

`scripts/soak/run_soak.py:744-755` deliberately reports
`exact_rc_artifact.ok=false` for its host-process preflight. The checked-in
profile requires at least 14,400 seconds and states its representative-profile
gaps (one API key; no Graph fan-out, successful model/tool work, Design/Canvas,
or Goal/background-worker reconciliation) are blockers, not waivers. Lowering
the artifact gate or running the preflight longer cannot supply the missing RC
identity or production topology evidence.

## Acceptance disposition

1. Representative users/Workspaces and workload mix — **UNVERIFIED**; profile
   documents the missing user population and workload surfaces.
2. At least two supported production replicas — **UNVERIFIED**; local component
   tests are not a deployed topology.
3. Sustained saturation, queue, lease, retry, leak and restart behavior —
   **UNVERIFIED**; no qualifying long-run production telemetry.
4. No duplicate physical work across schedule/Run/Attempt admission and Goal
   reconciliation — **UNVERIFIED**; admission probes do not exercise physical
   work and recovery under load.
5. Rate/security/degraded behavior cannot be bypassed by replica selection —
   **NOT SATISFIED by current limiter contract**: the limiter is process-local
   and explicitly provides N × allowance. Focused test success does not cure
   this behavior.
6. Required PostgreSQL/application-loop/worker/RSS/fd/queue/error telemetry
   with thresholds — **UNVERIFIED**; no production measurements.
7. Kill/restart during active work with drain/fencing/recovery — **UNVERIFIED**;
   no active physical Attempt fault injection in a production topology.
8. Long soak of exact RC artifact/configuration, rerun after changes —
   **UNVERIFIED / BLOCKED**; no RC/config supplied and the preflight fails the
   artifact gate by design.
9. Load findings filed/reclassified to earliest broken invariant —
   **UNVERIFIED**; no new production-load findings were generated.
10. Machine- and human-readable hash-tied evidence — **UNVERIFIED**; no
    qualifying artifact/config hashes or evidence pack exist for this run.

## Handoff

**NEEDS-REPAIR** for the rate-limit acceptance gap and **BLOCKED** on the
production soak prerequisites. No source or test edit is claimed as a repair.
The supplied previous block is not resolved merely by a clean worktree; this
commit records fresh validation and the concrete behavior gap. Next work needs
a shared per-principal rate-budget contract implemented at the existing
middleware seam, an owner-selected immutable RC/config and production target,
then a representative >=4-hour multi-replica run with active-work failure and
hash-bound telemetry/evidence. Any runtime change requires a new soak.

Progress: checked 1 issue; acceptance-complete 0; skipped 0; validation command
errors 0. Local commit is a handoff only, not integration or promotion approval.

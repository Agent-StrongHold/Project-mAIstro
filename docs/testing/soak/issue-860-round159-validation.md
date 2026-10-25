# Issue #860 — round 159 validation

## Scope and evidence

Processed only issue #860 in the assigned `auto-860` worktree at starting
HEAD `10d78cea28956e3acd2095f16955e5708dbea001`. The job directory contains no
`check-*.log` files. No RC image/configuration or production soak target was
provided. The prior `BLOCKED` result identifies production acceptance blockers;
this round does not claim promotion evidence.

## Reproduced test mismatch and repair

Fresh targeted validation initially failed at
`tests/test_soak_promotion_gates.py::test_receipt_load_reads_admitted_tasks_through_production_router`:
it expected the peer replica to return 404, but both reads returned 200. This
is the current intended production contract: `packages/maistro-server/src/maistro_server/api/tasks.py:144-150`
uses `TaskQueue.get_shared`, which resolves a receipt through shared durable
Run truth (issue #1690), so a stale process-local-404 test expectation no longer
matches reachable behavior. Updated the existing test's expectation and
comment; no test was added and suite inventory is unchanged.

## Validation executed

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q` — **105 passed**, one existing Starlette deprecation warning.
- `uv run ruff check . && uv run ruff format --check .` — passed; 3504 files formatted.
- `uv run python scripts/check-suite-inventory.py` — passed; 21 suites, 34,461 collected identities match.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — passed; 1297/1297 reviewed identities, zero unclassified.

The initial targeted run before updating the outdated assertion was **73 passed,
1 failed**; it exposed the mismatch described above.

## Acceptance disposition

| Issue #860 criterion | Evidence / status |
|---|---|
| Representative supported release-candidate workload | **UNVERIFIED**; no production workload or RC inputs provided. |
| At least two production application replicas | **UNVERIFIED**; the passing test uses two in-process ASGI apps, not deployed replicas. |
| Sustained saturation, queue/lease/retry/leak and restart observation | **UNVERIFIED**; no qualifying long-running production soak was run. |
| No duplicate physical work across replicas | **UNVERIFIED**; execution-fencing component tests are not production-topology failure proof. |
| Rate limiting/security cannot be bypassed by replica selection | **NOT MET at production acceptance level**; existing limiter is process-local; no shared-budget contract or deployed ingress test was supplied. |
| Required telemetry with explicit thresholds | **UNVERIFIED**; no production telemetry pack supplied. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**; no production failure injection performed. |
| Exact-RC soak for required duration and configuration | **BLOCKED**; no selected artifact/configuration or authorized deployment target supplied. |
| Findings filed/reclassified to earliest invariant | **UNVERIFIED** for production-load findings; no external filing performed. |
| Machine/human hash-bound evidence pack | **UNVERIFIED**; no qualifying evidence pack supplied. |

Accepted ADRs preserve the canonical `Goal -> Graph -> Run -> NodeRun -> Attempt`
model and durable lease fencing/reclaim authority (ADR-081226-69ee,
ADR-081226-a66b, ADR-081626-f383, ADR-082526-b36a). The test correction aligns
the harness assertion with shared receipt reads and introduces no execution
authority. No soak gate was weakened and no soak evidence was fabricated.

**Disposition: NEEDS-DEEP-REVIEW / production acceptance remains blocked.** The
test mismatch is repaired and focused validation passes, but the issue's
promotion acceptance cannot be proven without an owner-selected immutable RC,
production topology/configuration, and a representative long soak including
active-work failure injection and hash-bound telemetry. A shared per-principal
rate-limit contract/decision is also needed to meet the replica-selection
non-bypass criterion; its scope is not solved by changing this stale test.

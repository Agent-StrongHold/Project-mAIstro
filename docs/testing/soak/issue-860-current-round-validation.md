# Issue #860 — current-round evidence review

## Scope and authority

Reviewed the assigned `auto-860` head `ec6bbaccfe3337f5f51124abc4b9aa12ec070878`, issue acceptance, soak profile/evidence, rate limiter, gate tests, and accepted ADR-085 plus ADR-081226-a66b. No production execution authority or alternate scheduler was introduced. The canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` lifecycle remains authoritative. No `check-*.log` files were present in this job directory, so driver check claims were not used as evidence.

## Executed validation

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — **84 passed**. These tests validate gate logic, not production workload behavior.
- `uv run ruff check . && uv run ruff format --check .` — clean; 3,366 files formatted.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — **passed**, 1,326 reviewed identities match 1,326 findings; no unclassified or never-allowlist findings.

## Verified blockers / acceptance disposition

- **Exact RC + sustained duration:** `docs/testing/soak/evidence/m3a-round109-shakedown.json` records `sustain_seconds=420.05`, versus the documented 14,400-second minimum, and `thresholds.checks.exact_rc_artifact.ok=false`. This is a short host-process preflight, not promotion evidence.
- **Replica-selection rate limit:** `packages/maistro-server/src/maistro_server/api/rate_limit.py` constructs an `InMemoryRateLimiter` per middleware instance and explicitly documents process-local state. `tests/test_soak_promotion_gates.py::test_replica_selection_has_an_independent_production_allowance` confirms that moving the same principal between two instances grants each a fresh allowance. This conflicts with issue acceptance that replica selection cannot bypass the allowance. The harness's direct replica probes only prove enforcement on each replica; they do not prove shared aggregate enforcement. ADR-085 requires per-principal rate limiting but does not settle cluster coordination; the current #842 contract explicitly permits N× aggregate budget. Resolve the contract and add coordinated state before claiming this criterion.
- **Physical-work fencing/recovery:** `scripts/soak/run_soak.py::phase_claim_probe` races schedule admission then calls `_terminalize_probe_run` on the queued Run. It does not execute a NodeRun/Attempt and therefore cannot prove physical-work uniqueness, fencing, lease reclaim, or recovery. ADR-081226-a66b requires lifecycle ownership and Attempt-level physical execution evidence.
- **Remaining workload/telemetry:** `docs/testing/soak/m3a-load-profile.md` lines 165–184 and 217–219 explicitly leave concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas, Goal reconciliation, worker counts, pool saturation, lease reclaim and application event-loop measurements unverified.
- **Promotion evidence:** No exact production Compose image/configuration, four-hour run, or machine+human evidence matching such an artifact was produced in this round. The prior evidence is not a waiver.

No production code change or gate relaxation is supported by available evidence. Issue acceptance remains unproven; the passing tests and quality gates are implementation checks only, not a promotion approval.

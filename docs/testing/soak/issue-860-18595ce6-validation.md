# Issue #860 validation — job 18595ce6

## Scope and provenance

- Assigned snapshot: issue #860 only. Worktree `auto-860`, starting HEAD `222c826c32dda020a36e453e314255708035eddd`; worktree was clean.
- Dispatch `check-*.log` files: none present. Inspected the supplied dispatch context and prior result; the prior result records a worker error and no checks, so it is not acceptance evidence.
- Read the repo instructions and accepted ADR-081626-f383 (Attempt lease/fencing) and ADR-082426-2192 (single server Container/spine). No competing scheduler/execution authority was added.

## Validation executed

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — PASS, 84 passed. This validates promotion-gate behavior, not deployed production behavior.
- `uv run ruff check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py packages/maistro-server/src/maistro_server/api/rate_limit.py` — PASS.
- `uv run ruff format --check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py packages/maistro-server/src/maistro_server/api/rate_limit.py` — PASS (3 files formatted).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS, 1324 reviewed identities / 1324 findings; 0 unclassified and 0 never-allowlist. No ledger amendment warranted.

## Acceptance audit

1. Representative release-candidate workload — **UNVERIFIED**. `docs/testing/soak/m3a-load-profile.md` still identifies missing concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background-worker workloads.
2. Two application replicas on supported production topology — **UNVERIFIED** by this round; no production Compose run was executed.
3. Sustained saturation, queue growth, lease recovery, retries, memory/fd leaks and restart behavior — **UNVERIFIED**. No sustained soak was run.
4. Exactly-once/fenced physical work and Goal reconciliation — **UNVERIFIED**. Admission/schedule deduplication is not evidence of physical Attempt fencing or recovery; the profile explicitly describes that limitation.
5. Security/rate limit cannot be bypassed by replica selection — **NOT PROVEN**. `packages/maistro-server/src/maistro_server/api/rate_limit.py` constructs an `InMemoryRateLimiter` per middleware instance and documents per-process budgets. The promotion-gate tests pass while modeling separate replica budgets; they do not establish cross-replica enforcement.
6. Required PostgreSQL, event-loop, worker/process, RSS/fd, queue and error telemetry with thresholds — **UNVERIFIED** at production scale. The profile distinguishes driver-loop lag from application-loop latency and records worker/pool/lease gaps.
7. Active-work kill/restart with graceful drain, fencing and recovery — **UNVERIFIED**. Not exercised in this round.
8. Long soak of exact RC artifact/configuration — **UNVERIFIED / BLOCKED**. `scripts/soak/run_soak.py` states the host-process preflight cannot sign promotion; `failed_promotion_checks` requires `sustain_duration` and `exact_rc_artifact`. Existing short/stale packs do not satisfy the assigned candidate's exact artifact requirement.
9. Load findings classified to earliest broken milestone invariant — **UNVERIFIED** for the required future RC soak.
10. Machine- and human-readable evidence bound to exact artifact/config hashes — **UNVERIFIED**; no valid exact-RC production evidence was generated.

No production or runtime changes were made because the evidence gap requires a real exact-RC deployment/soak, not a synthetic test or cosmetic adjustment. No tests were added; therefore no suite inventory delta is applicable. No GitHub actions were performed.

## Disposition

**NEEDS-REPAIR / promotion BLOCKED.** The focused harness tests and quality checks pass, but all acceptance criteria requiring production load/recovery evidence remain unproven, and the documented process-local limiter does not prove replica-selection non-bypass. A production-topology, ≥4-hour exact-RC soak plus cross-replica rate-limit proof is still required.

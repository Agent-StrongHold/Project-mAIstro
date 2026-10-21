# Issue #860 — bounded repair handoff

Scope: issue #860 only; branch `auto-860`; dispatched HEAD
`4342ccb89a77b6cadf9b855a574876df185a0b52`. The worktree was clean on
arrival. The job directory supplied no `check-*.log` files. Prior result
`ec68a820b1b143d69f3cb9962c0b9e60/result.json` was reviewed; it reports a
BLOCKED acceptance state, not a develop-sync conflict. No GitHub action or
branch sync was performed.

## Validation run here

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` — **111 passed**, one existing Starlette deprecation warning. These are regression tests, not production soak evidence.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS (3,413 files).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS, 1,321 reviewed identities / 1,321 findings; unclassified=0, never_allowlist=0. No ledger change warranted.
- `git diff --check` — PASS before this handoff was added.

No tests or runtime behavior were changed; no inventory delta is applicable.

## Acceptance review — production evidence

- Representative release-candidate workload — **UNVERIFIED**. The load profile's remaining gaps (`docs/testing/soak/m3a-load-profile.md`, “Remaining representative-profile gaps”) name concurrent users/Workspaces, graph fan-out, successful tools/models, Design/Canvas, and Goal/background reconciliation.
- Two replicas in the exact supported production topology — **UNVERIFIED**. The existing evidence is from `host-uvicorn-preflight`; `scripts/soak/run_soak.py`'s `preflight_artifact_check` always reports false for exact Compose artifact identity.
- Sustained saturation, queue/reclaim/retry and resource/leak observations — **NOT MET**. `docs/testing/soak/evidence/m3a-round109-shakedown.json` records 420.05 seconds; profile requires 14,400 seconds.
- Exactly-once schedule/task admission, Goal reconciliation and physical-work fencing/recovery — **PARTIAL/UNVERIFIED**. Round 109 has task-admission and occurrence-claim probes; the schedule probe creates and cancels its queued Run. It does not observe executing physical Attempts through restart/reclaim. Accepted ADR-081626-f383 explicitly leaves lease-expiry takeover/recovery undefined; ADR-082426-82c7's occurrence claim does not prove live scheduler convergence or physical execution uniqueness.
- Rate-limit and security behavior cannot be bypassed by replica selection — **NOT MET**. `packages/maistro-server/src/maistro_server/api/rate_limit.py` constructs an in-memory limiter per middleware and documents the resulting N× aggregate allowance across N replicas. Probe coverage of each replica does not establish a cluster-wide principal budget.
- Required telemetry and thresholds — **PARTIAL/UNVERIFIED**. The preflight includes several driver/process and PostgreSQL probes, but profile limitations still state driver loop lag is not application event-loop lag and require worker-count, pool-saturation, lease-reclaim, and long-window observations.
- Kill/restart during active work, graceful drain/fencing/recovery — **PARTIAL/UNVERIFIED**. The existing host preflight reports replica rejoin and drain observations, but exact RC execution and physical Attempt fencing/recovery are not proven.
- Exact RC artifact/config four-hour soak with hashes — **NOT MET**. No immutable RC image/config identity or qualifying run was supplied. `sustain_duration` and `exact_rc_artifact` are mechanically false for the preserved evidence.
- Findings filed/reclassified to earliest broken milestone — **UNVERIFIED**. This lane did not file/reclassify findings or mutate GitHub.
- Machine-readable and human-readable evidence tied to exact hashes — **PARTIAL**. Existing machine-readable/human-readable preflight artifacts exist, but are not tied to the promoted RC artifact/configuration.

## Disposition

**BLOCKED** for issue #860 acceptance. Focused local tests and CI quality checks pass, but they cannot substitute for a designated production RC and a qualifying multi-replica soak. No source defect is inferred or fixed by this evidence. The next step is owner selection of the exact RC/configuration and an authorized production-topology soak covering the unresolved acceptance surfaces. This handoff is not promotion or integration approval.

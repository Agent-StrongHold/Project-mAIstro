# Issue #860 repair-lane validation

- Issue #860 only; branch `auto-860`, starting HEAD `937fe43d55ebfaaec63d2edaeb8179d9ae67f40d`.
- Inspected the dispatch snapshot and prior result. The job directory contains no `check-*.log`; therefore there were no deterministic driver checks to inspect. No unrelated issue/PR was investigated.
- Read the accepted execution-lease contract (`docs/adr/ADR-081626-f383-execution-lease-fencing.md`), rate-limit policy (`docs/adr/ADR-085-cost-quota-rate-limiting.md`), and issue profile. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; no separate scheduler, execution authority, or Goal/event store introduced.

## Fresh validation

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — **84 passed**.
- The passing suite includes `test_replica_selection_has_an_independent_production_allowance` (lines 480 onward): for the same principal/client identity, each production `RateLimitMiddleware` instance allows `[200, 200, 429]` independently. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32-37,93-98` confirms and documents process-local budgets. This proves independent allowance behavior, not cluster-wide non-bypass.
- `scripts/soak/run_soak.py:1064-1088` confirms the schedule probe is cancelled without executing the admitted Run. This is admission evidence, not physical Attempt fencing/recovery.
- `docs/testing/soak/m3a-load-profile.md:167-183` explicitly records missing representative user/Workspace, Graph fan-out, successful model/tool and Canvas/Goal workloads, and missing application-loop/physical recovery proof. The profile requires a >=14,400-second exact-RC soak; host-process preflight evidence cannot satisfy that artifact gate.
- Re-ran `uv run pytest tests/test_soak_promotion_gates.py -x -q` at HEAD `af312c21d3628ec578d45dea1af4a67297bf2ce4`: **84 passed in 1.96s**. The assigned job directory has no `check-*.log` files to inspect. This test validates harness gate behavior only; it does not establish the missing RC/load evidence.

## Acceptance disposition

The strict replica-selection resistance criterion conflicts with the existing documented process-local limiter policy. ADR-085 requires per-principal limits but does not prescribe a shared storage mechanism; `rate_limit.py` explicitly states that cluster coordination is a separate change. Do not silently add a new cross-replica authorization/storage path without its policy and supported deployment decision.

All promotion-level acceptance remains **UNVERIFIED/BLOCKED**: no immutable RC image/configuration was supplied or deployed, no qualifying four-hour run was performed, workload/telemetry gaps remain, and no physical Attempt/recovery experiment ran. Historical packs are not treated as fresh proof. No code change can honestly satisfy those external prerequisites in this lane. No tests were added or modified, so no suite inventory delta is needed. No quality ledger, runtime configuration, or gate was changed.

Next: establish the immutable RC/configuration and decide the cluster rate-budget contract with its owner; extend the supported workload/telemetry and physical-work oracle; then execute the >=4-hour exact-RC multi-replica soak and repeat it after runtime/config changes. No GitHub mutation or issue closure was performed.

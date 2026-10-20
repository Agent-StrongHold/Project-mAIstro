# Issue #860 — bounded repair result (job `e61fa934`)

## Scope and validation

Processed only issue #860 in `/home/dev/Git/wt/auto-860`, branch `auto-860`, at dispatched HEAD `55b135911104b5147bf14c0ab553612df2a25618`. Worktree was clean at entry. The assigned job directory had no `check-*.log` files. The supplied prior result was read; it records blocked acceptance, not a develop-sync conflict. No GitHub queries or mutations were performed.

Read accepted ADR-081226-a66b (canonical Run/NodeRun/Attempt lifecycle), ADR-081626-f383 (durable Attempt execution leases/fencing), and ADR-085 (per-principal rate limits). The canonical execution authority remains `Goal -> Graph -> Run -> NodeRun -> Attempt`; no alternate scheduler, store, event authority, or authorization path was introduced.

Fresh focused validation on this HEAD:

- `uv run pytest tests/test_soak_promotion_gates.py -k replica_selection_has_an_independent_production_allowance -q -x` — PASS, 2 passed. This exercises real production middleware instances; the same identity receives independent replica allowances, so it confirms rather than resolves the anti-bypass gap.
- `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -q -x` — PASS, 26 passed. These establish local middleware behavior, not shared cross-replica limits.
- `git diff --check` — PASS; the assigned job directory had no `check-*.log` files.

## Acceptance assessment

| #860 criterion | Evidence / disposition |
|---|---|
| Define representative RC workload: concurrent users/Workspaces, fan-out, schedules, tool/model, Canvas and workers | **UNVERIFIED** — `docs/testing/soak/m3a-load-profile.md` explicitly lists these remaining profile gaps. |
| Exercise supported production multi-replica topology | **UNVERIFIED** — `scripts/soak/run_soak.py:19-21` says host preflight cannot sign promotion; no exact production Compose RC artifact/evidence was supplied. |
| Sustained soak long enough to observe saturation, reclaim, retries, leaks and shutdown/restart | **UNVERIFIED** — profile requires at least 14,400 seconds; no exact-RC soak was run in this attempt. |
| Prove exactly-once/fenced physical work and Goal reconciliation across replicas | **UNVERIFIED** — `scripts/soak/run_soak.py:1064-1067,1170-1174` terminalizes the schedule probe Run; it does not execute a physical Attempt. |
| Prove rate limits cannot be bypassed by replica selection | **NOT SATISFIED** — fresh targeted test passed by demonstrating independent per-replica allowances; `rate_limit.py:32-35,93-96` documents/constructs process-local limiter state. |
| Capture production PostgreSQL, app-loop, workers, RSS, descriptors, queue and error telemetry with thresholds | **UNVERIFIED** — no promotion-grade production soak/evidence supplied; profile calls out app-loop and worker/pool/lease measurement gaps. |
| Kill/restart active replica and prove drain/fencing/recovery | **UNVERIFIED** — no active physical Attempt recovery experiment against exact RC topology. |
| Long soak exact RC artifact/config and re-run after code/config changes | **NOT SATISFIED** — no exact RC artifact/config hash pack; host preflight's `exact_rc_artifact` is always false (`run_soak.py:19-21,1576`). |
| File/reclassify load findings to earliest broken invariant | **UNVERIFIED** — no representative RC soak findings to classify in this attempt. |
| Publish machine- and human-readable evidence tied to exact hashes | **UNVERIFIED** — no exact-image/config production evidence pack supplied. |

Disposition: **BLOCKED for acceptance**. The proven replica-selection weakness requires an actual shared/authoritative rate-limit design and production validation; changing the harness or relabeling the check would not repair it. The remaining criteria require an immutable RC deployment and multi-hour observation that cannot be truthfully fabricated from unit tests or historical host-process evidence. No test was added, so no test inventory delta applies. This handoff is not integration or promotion approval.

# Issue #860 validation checkpoint — 8d2d6f26

## Scope and disposition

Processed only issue #860 in `auto-860`, at dispatched HEAD `e11debfb234201b90c40c718cf81484a06f3cdf6`. The job directory contains no `check-*.log` files. The previous blocked result was reviewed: it identifies missing production soak prerequisites/evidence, not a develop-sync conflict. `origin/develop` resolves to `fe4332d8eb128e121e429b484354f23003e6baed`, the dispatched base; no merge was indicated or attempted. **Disposition: BLOCKED for acceptance; no integration approval.**

## Fresh validation

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` — **85 passed**. Component tests do not constitute deployed multi-replica soak evidence.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — **passed**; 1322 reviewed identities match 1322 findings, zero unclassified and zero never-allowlist.
- Evaluated `docs/testing/soak/evidence/m3a-round30-shakedown.json` with `failed_promotion_checks()` — duration **420.08 seconds**; rejected for `sustain_duration` and `exact_rc_artifact`.
- No tests were added or changed; no suite inventory delta is required. No production behavior, gate, or ledger was changed.

## Acceptance disposition

| Issue #860 criterion | Evidence/status |
|---|---|
| Representative workload across supported users/Workspaces, Graph/node fan-out, schedules, queue, tools/models, Canvas and applicable background work | **UNVERIFIED** — `docs/testing/soak/m3a-load-profile.md` explicitly lists remaining profile gaps; selected RC applicability was not supplied. |
| At least two deployed application replicas; sustained saturation, queue/reclaim/retry, leaks and shutdown/restart | **UNVERIFIED** — no deployed RC run. Component tests are not production topology or soak. |
| No duplicate physical schedule/Run/Attempt work, Goal reconciliation, and safe rate/security behavior against replica selection | **UNVERIFIED / NOT PROVEN** — tested rate limiting is per-process, and admission probes do not prove physical work, production reconciliation, or replica-resistant aggregate behavior. |
| Required PostgreSQL, latency, worker/process, RSS, descriptor, queue and error telemetry with thresholds | **UNVERIFIED** — no fresh production telemetry set. |
| Kill/restart during active work proves drain, fencing and recovery | **UNVERIFIED** — no production failure injection with active physical Attempts. |
| Long-running soak of exact RC artifact/config; any change requires a new soak | **NOT MET** — round-30 evidence is 420.08 seconds; evaluator rejects both `sustain_duration` and `exact_rc_artifact`. |
| Findings reclassified to earliest broken invariant | **UNVERIFIED** — no external mutation performed. |
| Machine- and human-readable evidence bound to exact image/package/commit/config hashes | **UNVERIFIED** — no selected immutable RC evidence pack supplied. |

The host-process runner explicitly fails its exact-artifact check (`scripts/soak/run_soak.py`, `preflight_artifact_check`); extending its duration cannot establish image/config equivalence. Governing accepted contracts reviewed: ADR-081626-f383 assigns canonical Attempt fencing to the Run store, ADR-082426-82c7 defines occurrence identity/uniqueness at canonical Run admission, and ADR-082826-b601 routes eligible admitted Runs through the canonical consumer. These do not authorize a parallel scheduler or execution authority and do not substitute for production failover evidence.

Required follow-up is an approved exact immutable RC deployment/configuration, representative workload and >=4-hour production run with specified telemetry, physical-work correlation, and active-work drain/fencing/recovery proof. This note records local validation only.

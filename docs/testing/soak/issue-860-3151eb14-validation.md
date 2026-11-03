# Issue #860 independent validation — job 3151eb14

**Assigned head:** `0f0d9c8017da7aef77c65e41ef05ef98a6cdb59c` (clean on entry)  
**Scope:** verify retained soak evidence and promotion gates; no production RC/configuration was provided. No tests or production code were changed.

## Executed checks

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — **84 passed**.
- `uv run ruff check .` — **PASS**.
- `uv run ruff format --check .` — **PASS**, 3,441 files already formatted.
- Re-evaluated `docs/testing/soak/evidence/m3a-round109-shakedown.json` with the current `scripts.soak.run_soak` evaluator. It records **420.05 s** against **14,400 s** and `exact_rc_artifact.ok=false`, topology `host-uvicorn-preflight`; evaluator returns failures `['sustain_duration', 'exact_rc_artifact']`. Current `preflight_artifact_check()` also returns `ok=false` for that topology.
- `DOCKER_HOST=unix:///var/run/docker.sock timeout 30 docker info` — **PASS**; Docker daemon is reachable. This does not supply a designated immutable promoted RC or its production configuration.

No current deployment was started and no four-hour soak was claimed. Re-running a longer host-process preflight would remain ineligible under the harness's artifact check and would not meet the exact-RC acceptance criterion.

## Acceptance disposition

| Criterion | Evidence / status |
|---|---|
| Define representative workload from supported claims | **PARTIAL.** `docs/testing/soak/m3a-load-profile.md` defines existing preflight coverage but its remaining-gaps section documents missing concurrent users/Workspaces, graph fan-out, successful tools/models, Design/Canvas, and sustained Goal/background-worker traffic. RC applicability is unverified. |
| At least two exact production replicas | **UNVERIFIED.** Historical host-uvicorn evidence is not production Compose artifact evidence. |
| Sustained saturation, reclaim/retry, leak and restart observations | **UNMET.** Retained run is 420.05 s vs 14,400 s; four-hour production run not executed. |
| Exactly-once/fenced physical work and Goal reconciliation | **UNVERIFIED.** Schedule/task admission probes are not proof of physical Attempt uniqueness or sustained Goal reconciliation. Accepted ADR-082126-f69c requires recurrence to produce canonical Runs; ADR-081626-f383 establishes Attempt fencing but does not grant lease-expiry takeover. |
| Security/degraded behavior under concurrency; replica-selection non-bypass | **PARTIAL/UNVERIFIED.** Historical probes show per-replica rate enforcement, explicitly process-local; they do not prove aggregate non-bypass or exact-RC behavior. |
| Required telemetry and explicit thresholds | **PARTIAL.** Profile/harness defines metrics, but retained preflight does not constitute exact-RC production telemetry evidence. |
| Kill/restart active work with drain/fencing/recovery | **UNVERIFIED** for promoted artifact and active canonical work. Historical host evidence cannot prove physical-work recovery. |
| Four-hour soak of exact RC/config | **UNMET.** Evaluator rejects both duration and artifact identity. No RC/config was supplied. |
| Findings reclassified to earliest invariant | **UNVERIFIED** outside local evidence; no external actions performed. |
| Hash-bound human and machine evidence | **PARTIAL.** Historical preflight is hash-bound; qualifying exact-RC human/machine evidence is absent. |

## Conclusion

The promotion gate behaves fail-closed and its regression tests pass. Available evidence does **not** satisfy issue #860's promotion acceptance; verdict is **NEEDS-REPAIR** pending a designated immutable RC/config, representative production workload, required duration/telemetry, and physical execution/recovery evidence. This report records evidence only; it does not waive acceptance criteria or authorize promotion.

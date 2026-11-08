# M3-A #860 round 147 — validation and blocker disposition

## Scope

Validated issue #860 at `64c164247593bddee504841d8a7b24a29aaa19ff` against its
acceptance criteria, the soak profile/driver/evidence, the rate-limit middleware,
and accepted ADR-085, ADR-081626-f383, and ADR-082126-f69c. The canonical
execution authority remains `Goal -> Graph -> Run -> NodeRun -> Attempt`;
this round does not introduce another scheduler, execution authority, or
authorization path. The assigned job directory had no `check-*.log` files.
No production RC image/configuration or deployment credentials were supplied.

## Executed validation

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — **84 passed**.
- `uv run pytest tests/test_soak_promotion_gates.py::test_replica_selection_has_an_independent_production_allowance -q` — **2 passed**. This regression confirms independent process-local allowances, not a shared cluster budget.
- `uv run ruff check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py packages/maistro-server/src/maistro_server/api/rate_limit.py` — **passed**.
- `uv run ruff format --check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py packages/maistro-server/src/maistro_server/api/rate_limit.py` — **passed**.
- `uv run python scripts/soak/run_soak.py --help` — **passed**; help explicitly says host-process preflight cannot sign promotion and `exact_rc_artifact` always fails.

## Evidence and acceptance disposition

The existing `docs/testing/soak/evidence/m3a-round109-shakedown.json` is a
host-uvicorn run tied to commit `5a59c724a20ef1241d57c048df90758f2c2e1e25`.
It records 420.05 seconds against the 14,400-second minimum and
`exact_rc_artifact.ok=false`; it is not evidence for the assigned head or the
promoted Compose artifact. The profile (`docs/testing/soak/m3a-load-profile.md`)
explicitly lists missing user/Workspace population, Graph fan-out, successful
tool/model calls, Design/Canvas and Goal/background reconciliation. Its
schedule probe cancels the admitted queued Run; it does not exercise a physical
Attempt. `rate_limit.py` documents process-local state and an aggregate
allowance proportional to replica count, so replica selection does not meet
the issue's stronger non-bypass criterion.

| Issue acceptance criterion | Evidence / disposition |
|---|---|
| Representative production RC load profile | **UNVERIFIED** — profile describes a preflight and lists workload gaps. |
| At least two exact-RC application replicas | **UNVERIFIED** — historical host processes are not the production Compose artifact. |
| Sustained saturation, queues, lease/retry, memory/descriptor leak, restart | **UNVERIFIED** — 420.05-second prior run is below the 4-hour minimum and is not exact RC. |
| Exactly-once schedule/task/Run/Attempt and Goal reconciliation | **PARTIAL / UNVERIFIED** — historical admission probes do not establish physical Attempt fencing/recovery or sustained Goal reconciliation. |
| Rate/security/degraded path cannot be bypassed via replica selection | **NOT MET** — process-local limiter permits independent replica budgets; targeted regression passed by reproducing this behavior. |
| Production telemetry and explicit thresholds | **UNVERIFIED** — host-process/driver measurements do not establish production PG, application event-loop, worker/container and queue health. |
| Kill/restart one replica during active physical work | **UNVERIFIED** — historical drain/rejoin does not demonstrate active physical-work fencing/recovery. |
| At least 4-hour exact-RC soak | **UNMET** — no exact-RC execution supplied; historical duration 420.05 s. |
| Findings reclassified before promotion | **UNVERIFIED** — no promotion finding disposition was independently evidenced in this round. |
| Machine/human evidence tied to exact image/config hashes | **UNMET** — historical evidence lacks promoted Compose image/config identity. |

No tests were added, so no suite inventory delta is required. A soak cannot be
manufactured from unit tests or this environment, and marking the host
preflight as exact-RC or relaxing its fail-closed gate would falsify evidence.
The issue remains **not promotion-ready**. Next required step is execution
against an immutable production RC/configuration, with the replica-budget
contract resolved and physical Attempt recovery observed. Any code/runtime
configuration change requires a new soak.

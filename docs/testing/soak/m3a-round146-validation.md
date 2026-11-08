# M3-A #860 round 146 — fresh validation and blocker disposition

## Scope and authority

Rechecked assigned head `ad1ccb5186b7447091c76850226f10dd489d9ce1` against the issue acceptance, `docs/testing/soak/m3a-load-profile.md`, `scripts/soak/run_soak.py`, the round-109 evidence, production rate-limit middleware and its regression test, and accepted ADR-085 plus ADR-081626-f383. The canonical execution authority remains `Goal -> Graph -> Run -> NodeRun -> Attempt`. No production or test code was changed. The assigned job directory contains no `check-*.log` files; results below are from direct commands run in this worktree.

## Fresh validation

- `uv run python scripts/check-reachability.py` — **failed**: 169 unreachable modules; newly unreachable `maistro.runs.admission_identity`.
- `uv run python scripts/check-ratchet-provenance.py` — **failed**: the reachability ratchet is incomplete; the same module is absent from the trusted disposition baseline. Other reported ratchets passed.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — **84 passed**. The suite includes the regression that verifies each replica grants an independent allowance; this is not evidence of a shared/non-bypassable cluster budget.
- `uv run ruff check scripts/soak/run_soak.py packages/maistro-server/src/maistro_server/api/rate_limit.py tests/test_soak_promotion_gates.py` — **passed**.
- Re-read `docs/testing/soak/evidence/m3a-round109-shakedown.json`: `sustain_seconds=420.05`; `thresholds.checks.exact_rc_artifact.ok=false` (`host-uvicorn-preflight`).

## Findings and acceptance

1. The reachability failure is confirmed on this head. `packages/maistro-core/src/maistro/runs/admission_identity.py` is an inactive contract module with no production importer; its test import does not make it reachable. Wiring an artificial caller or changing a quality disposition would be unrelated to this release-evidence repair, so no baseline or architecture workaround was made.
2. `packages/maistro-server/src/maistro_server/api/rate_limit.py` stores limiter state in process-local `InMemoryRateLimiter` instances. The passing test `tests/test_soak_promotion_gates.py::test_replica_selection_has_an_independent_production_allowance` reproduces fresh allowance after replica selection changes. ADR-085 specifies per-principal limiting, but the implementation and profile explicitly define per-process N× semantics; the issue's stronger anti-bypass criterion remains unproven and fails the observed test condition.
3. The shakedown evidence is about seven minutes and explicitly not the exact production Compose artifact. No 4-hour exact-RC run, production telemetry, or active physical-work kill/restart/fencing evidence was generated in this round.
4. The checked-in profile itself marks concurrent user/Workspace traffic, Graph fan-out, successful tool/model and Design/Canvas workloads, Goal reconciliation, and physical Attempt recovery as gaps. `phase_claim_probe` is schedule admission then cancellation, not physical execution.

| Criterion | Disposition |
|---|---|
| Representative profile / telemetry | **PARTIAL** — profile and emulator exist; production workload/scope gaps remain |
| Two exact-RC replicas and kill/restart during active work | **UNVERIFIED** |
| ≥4-hour soak of exact RC artifact/config | **UNMET** — 420.05 s, exact-artifact check false |
| Exactly-once/fenced physical execution and Goal reconciliation | **UNVERIFIED** — admission-only probe does not execute an Attempt |
| Rate limiting cannot be bypassed by replica selection | **FAIL / unresolved** — independent per-replica budgets reproduced |
| Production saturation, queue/lease/retry/leak and runtime telemetry thresholds | **UNVERIFIED** at promotion grade |
| Findings reclassified before final promotion | **UNVERIFIED** in this round |

Disposition: **NEEDS-REPAIR**. The passing unit suite does not establish the acceptance criteria, and the concrete rate-limit and soak evidence failures remain. No tests were added, so no suite inventory delta is required. No ledger change was authorized or made.

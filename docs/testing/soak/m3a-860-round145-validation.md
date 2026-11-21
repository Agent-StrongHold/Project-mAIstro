# M3-A #860 round 145 — validation and blocker disposition

## Scope and authority

Reviewed the assigned head `8e9b198c37ac4fd24054f32eea268ca3d5df29fd`, issue #860 acceptance, `docs/testing/soak/m3a-load-profile.md`, the round-109 evidence, `scripts/soak/run_soak.py`, the rate-limit middleware, relevant gate tests, and accepted ADR-085 plus ADR-081626-f383. No tests or production code were added. The execution authority remains `Goal -> Graph -> Run -> NodeRun -> Attempt`.

## Validation run in this round

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — passed: 1,326 findings match 1,326 reviewed identities; no unclassified or never-allowlist entries.
- `uv run python scripts/check-reachability.py` — failed: `maistro.runs.admission_identity` is newly unreachable.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — 84 passed. These are gate/harness tests and do not constitute production soak evidence.
- `uv run ruff check scripts/soak/run_soak.py packages/maistro-server/src/maistro_server/api/rate_limit.py tests/test_soak_promotion_gates.py` — passed.

No `check-*.log` files were present in the assigned job directory, so this round records only commands run directly here.

## Findings

1. `packages/maistro-core/src/maistro/runs/admission_identity.py` describes itself as an inactive contract leaf; production reference search finds no importer. Wiring an artificial runtime caller would change architecture rather than resolve an actual supported behavior defect. The reachability gate therefore remains failed. Its baseline is not changed: this round authorizes only the vulture-ledger repair, and unrelated quality-ledger edits are prohibited.
2. `packages/maistro-server/src/maistro_server/api/rate_limit.py` keeps limits in process-local memory. `tests/test_soak_promotion_gates.py::test_replica_selection_has_an_independent_production_allowance` demonstrates the same principal receiving a fresh allowance on another instance. ADR-085 requires per-principal limiting but does not establish cluster-coordinated state; current soak profile explicitly describes N× aggregate semantics. The stronger issue criterion remains unproven/failed, not fixed by asserting the probe passes.
3. `docs/testing/soak/evidence/m3a-round109-shakedown.json` records 420.05 seconds and `exact_rc_artifact.ok: false`, below the 14,400-second threshold and not the exact Compose release candidate. No production four-hour run was performed here.
4. The profile explicitly leaves concurrent users/Workspaces, Graph fan-out, successful tool/model and Design/Canvas workloads, and Goal reconciliation unverified. `phase_claim_probe` admits/cancels a queued Run and does not execute/fence physical Attempt work. No replica kill/restart during active physical work or exact-artifact recovery evidence is established.

## Acceptance disposition

- Representative profile and telemetry — **PARTIAL**; profile exists, with the listed workload and production telemetry gaps.
- Two replicas, active-work kill/restart, and exactly-once/fenced physical execution — **UNVERIFIED** for the exact production artifact.
- Non-bypassable rate limit under replica selection — **FAIL / unresolved contract**; per-instance allowance behavior is reproduced by tests.
- Sustained ≥4-hour exact-RC soak and hash-bound evidence — **UNMET**; available shakedown is 420.05 seconds and marks exact artifact false.
- Findings filed/reclassified before promotion — **UNVERIFIED** in this round.
- CI checks — vulture baseline passes; reachability fails on the intentionally inactive contract leaf. No unrelated ledger change or architecture workaround was made.

Disposition: **NEEDS-REPAIR**. A focused code change cannot honestly satisfy the outstanding release-evidence and cluster-rate-limit criteria. No test inventory delta is required because this round adds no tests.

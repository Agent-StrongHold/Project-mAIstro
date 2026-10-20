# Issue #860 validation — round 33

Validated from the clean assigned branch head `9d6326e209d78da28c8d2b34c9e353edc3d601d3`.

## Executed checks

- `uv run pytest tests/test_soak_promotion_gates.py tests/test_soak_compose_pressure.py -x -q` — **111 passed**.
- `uv run ruff check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py tests/test_soak_compose_pressure.py` — passed.
- `uv run ruff format --check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py tests/test_soak_compose_pressure.py` — passed (three files formatted).
- `uv run python scripts/check-suite-inventory.py` — **failed collection** for four reference-gallery package suites because their modules are not installed (`ModuleNotFoundError` for `gallery_weather_connector`, `gallery_unit_skill`, `gallery_model_adapter`, and `gallery_renderer_pack`). The gate reports 32,371 collected node IDs across 17 suites but explicitly says not to update inventory while collection fails.

## Acceptance status

The tests validate the preflight harness and fail-closed promotion gates, not a promotion soak. The current committed evidence remains host-process preflight evidence; the profile states that this cannot satisfy the exact production Compose artifact requirement, and the latest shakedown is far shorter than the four-hour minimum. It also does not establish production Graph/node fan-out, successful tool/model/Canvas workloads, sustained Goal reconciliation or physical Attempt fencing, long-window pool/queue/leak behavior, nor a shared cluster-wide rate-limit allowance. No acceptance waiver is inferred from unit tests or historical evidence. Promotion remains blocked pending a clean exact-RC production-topology soak and these uncovered correctness/telemetry proofs.

No tests were added in this validation-only note, so no inventory delta applies.

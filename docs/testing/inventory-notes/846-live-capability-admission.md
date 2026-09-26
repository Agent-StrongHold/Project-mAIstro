---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/hive-conductor/backend/tests: +2
---

# #846 live capability admission

Adds behavioral coverage for Binding revocation, shipped harness-route revocation,
and self-repair policy-provider failure. The tests assert that an already-built
actor performs no provider call after capability/binding withdrawal and that a
policy failure produces a failed/degraded repair rather than granting the effect.

## Revalidation pass 5 (2026-09-25, head 73c505708a4a)

Independent repair-lane revalidation at 73c505708a4a8abc1199e529866414f16b3157bd:

- `uv run pytest packages/maistro-core/tests/capabilities -q` -> 339 passed.
- `uv run pytest packages/hive-conductor/backend/tests/{test_harness_routes,test_capabilities_wiring,test_governed_model_consumers,test_canvas_model_egress,test_providers_routes,test_self_repair_routes}.py -q` -> 103 passed.
  Includes the formerly failing `test_model_chat_egress.py::test_setup_hook_runs_after_authorization_before_model_http` (fixed by the `_effects()` fixture opting into `binding_scope_policy`).
- `uv run ruff check .` / `uv run ruff format --check .` -> clean.
- `uv run mypy packages/maistro-core/src/maistro/capabilities` -> clean (38 files).
- CI gates: `check-model-egress.py`, `check-execution-lifecycles.py`, `check-security-inventory.py` -> OK.
- No code changes in this pass; tree already fail-closed at this head (explicit route policy, `_unconfigured_policy` deny default, Invocation-time binding/provider resolution in harness and self-repair wiring).

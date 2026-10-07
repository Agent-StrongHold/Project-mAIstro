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

## Independent verify pass 6 (2026-09-25, head 1fa049fa9)

Independent verifier revalidation at 1fa049fa9876f5c0e676f21e75455e63160b93ad
(auto-846 after merging develop@5eeac0734):

- Driver checks (job 469c3a75): `uv sync --locked --extra dev`, `ruff check .`,
  `ruff format --check .` (2545 files), core batch 161 passed, conductor batch
  103 passed, `check-suite-inventory.py` OK for both suites — all green.
- Verifier re-ran: `uv run pytest` on test_harness_manager, test_governed_invocation,
  test_self_repair_provider{,_gaps}, test_self_repair_integration,
  test_model_chat_egress -> 64 passed; `.venv/bin/python -m pytest` on
  test_harness_routes, test_self_repair_routes, test_capabilities_wiring,
  test_governed_model_consumers -> 49 passed.
- Verifier re-ran gates: `check-model-egress.py` (45 direct-effect sites, all
  dispositioned), `check-security-inventory.py`, `check-execution-lifecycles.py`,
  `ruff check .` -> all OK.
- Code re-read confirms: routes/harness.py builds an explicit
  `SequencePolicyEngine([BudgetRule(count=0)])` (no `policy=None` path);
  `HarnessSessionManager._admission_unavailable` refuses policy-less managers;
  `AllowAllGate` no longer exists in the repo; harness start/send/stream/stop and
  self-repair actions all admit through `GovernedInvocationExecutionService.invoke`
  with Invocation-time binding re-resolution; sessions store provider identity only;
  PR body contains no closure keywords ("Refs #846" only).

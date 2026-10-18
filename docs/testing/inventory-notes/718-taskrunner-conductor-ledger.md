---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
  packages/maistro-server/tests: +2
---

# #718 follow-up: the TaskRunner conductor class reaches the canonical quota ledger

Closes the unrecorded acceptance gap from
`718-verifier-followup-taskrunner-ledger-gap.md`: the `/tasks` queue worker
(maistro-server `main.py`) and hive demo mode's `LocalTaskBackend` both called
bare `run_task`, so a major production call class never touched the Invocation
quota ledger while per-provider rows presented as complete.

## What moved

- `packages/maistro-server/tests` +2 — `test_taskrunner_quota_ledger.py`
  drives the executor the real lifespan hands to `TaskRunner` (real Container,
  real governed egress, fake gateway) and observes quota ledger movement:
  reported usage lands with provider/token/Invocation identity, and a gateway
  that reports no usage surfaces as `unreported_count`/`usage_complete=False`
  evidence, never a measured zero.
- `packages/hive-conductor/backend/tests` +3 — the adapter tests pin that
  `MaistroCoreBridge.governed_egress` is built once over the Container's
  effect authorities and the same gateway endpoint the roster's model clients
  got (and is `None` before start); the engine test pins that demo mode's
  task backend executes through that egress with the deployment's Workspace,
  the same authority shape the maistro-server worker now uses.

## Production changes these tests pin

- `maistro_server/main.py`: `_build_container` returns
  `(container, governed_egress)`; the lifespan's `runner_executor` closure
  supplies that egress (plus `workspace_id`/`project_id`) to
  `conductor.run_task` — the canonical effect authority once, not a
  per-caller recording callback (the issue's stop condition).
- `hive-conductor` `adapters/maistro_core.py`: `EmbeddedRuntime` carries
  `governed_egress`; the bridge exposes it as a property.
- `hive-conductor` `services/engine.py`: demo mode's `LocalTaskBackend`
  executor is a governed closure over `run_task`; a stub port (no bridge)
  keeps the raw call because that process has no canonical authority to cross.

Two source-shape retirement tests (`test_pm_poc_catalog_retirement.py`,
`test_pm_poc_execution_retirement.py`) were updated in place to the new
truth: execution still routes through the canonical `conductor.run_task`,
now via the governed closure. No collected-count movement there.

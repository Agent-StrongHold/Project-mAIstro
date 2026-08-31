# M1 #129 PM-Fleet POC closeout inventory

Audited from `develop@93401f3485ebb815dedc1b0c6b7ad1d7e767fa32` on 2026-08-31.

## Ownership audit

- `chatgpt/m1-129-pm-fleet-closeout` was a pure ancestor of `develop` with no lane-specific commits before recovery.
- No open PR matched #129, #190, PM-Fleet, `pm_fleet`, or Workspace Persona ownership.
- #190 remains closed; its frontend `usePmPoc()` scope was already completed.
- #129 had been closed on current-state evidence, but the reachability audit below found residual executable POC authority, so #129 was reopened.

## Reachable POC authority found

1. Hive demo startup read `MAISTRO_POC_MODE` / `HIVE_POC_MODE` and selected `maistro.agents.pm_runner.run_pm_task` instead of the canonical conductor executor.
2. The same Hive path synthesized a private `_pm_catalog` through `register_pm_fleet()`.
3. maistro-server startup independently synthesized `app.state.pm_catalog` when `MAISTRO_POC_MODE=pm`.
4. Hive startup installed `install_pm_event_bridge()`, which imported `pm_runner`, created a private EventBus, and rebound the PM executor's event hook.
5. `maistro.agents.pm_fleet` remained an importable PM-specific roster/routing adapter beside the canonical Workspace Persona template.
6. `maistro.agents.pm_runner` remained an importable independent PM executor after the product had already moved reusable identity resolution to materialized Workspace agents.

## Disposition

### CONNECT / retain

- `personas/templates/pm_fleet.yaml` remains the reusable PM Fleet definition and retains migration provenance from the historical hardcoded roster.
- Generic `expand_persona` plus Hive `services/agent_materialization.py` owns Workspace-scoped materialization.
- Generic `services/agent_invocation.py` resolves a requested spawn against that Workspace's materialized roster and preserves PM task-description behavior.
- PM capabilities, work-item draft gates, program context, curated `pm_fleet` project domain, and the `daily-status`/PM seed behavior remain unchanged.

### RETIRE

- Environment-selected PM executor switch in Hive demo mode.
- Hive private PM catalog.
- maistro-server private PM catalog.
- PM-runner event bridge.
- `maistro.agents.pm_fleet` adapter module.
- `maistro.agents.pm_runner` executor module.

Deletion is intentional. Keeping either removed module as a compatibility import would let restart/import recreate a second reusable roster or execution authority.

## Acceptance evidence

- New core retirement tests assert the packaged `pm_fleet` template is a Workspace Persona with the six migrated spawns, retains legacy-definition provenance, and that the legacy authority modules do not exist.
- New Hive retirement tests assert demo startup contains no retired POC environment/executor/catalog switch and still uses the canonical conductor executor.
- New maistro-server retirement tests assert startup cannot seed a PM POC catalog and task execution remains on the canonical conductor executor.
- Existing `test_agent_invocation.py` continues to characterize Workspace-scoped resolution, capability refusal, description compatibility, and pulse-roster isolation without importing the retired executor.
- Generic DAG-run history remains; only the PM-runner-specific EventBus bridge is removed. Direct DAG route writes remain its live producer.

## Expected shared-ratchet decreases

This branch deliberately does **not** edit `quality/reachability-baseline.json`, `quality/reachability-dispositions.json`, or other shared ratchet authority while #721 owns that lane. Expected follow-up shrinkage includes symbols/files formerly attributable to:

- `packages/maistro-core/src/maistro/agents/pm_fleet.py`
- `packages/maistro-core/src/maistro/agents/pm_runner.py`
- `register_pm_fleet`
- `run_pm_task`
- `install_pm_event_bridge`
- the retired PM private EventBus hooks and PM executor helpers

The owning ratchet lane should reconcile those decreases from its then-current trusted base rather than this PR competing for the same shared files.

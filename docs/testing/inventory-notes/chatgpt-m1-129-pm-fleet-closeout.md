# M1 #129 PM-Fleet POC closeout inventory

Initial reachability audit from `develop@93401f3485ebb815dedc1b0c6b7ad1d7e767fa32` on 2026-08-31. The branch is brought forward to current `develop` before merge validation.

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
7. maistro-server still mounted the POC-only `/v1/maistro/agents` list/invoke API. That route imported the hardcoded fleet adapter and could queue those legacy agent IDs independently of Workspace Persona ownership whenever `MAISTRO_POC_MODE=pm` was set.
8. `maistro.tools.pm_stubs` remained as a fleet-POC-only fake execution layer. Repository search found its production consumer was the retired PM runner; its remaining consumers were its own dedicated tests.

## Disposition

### CONNECT / retain

- `personas/templates/pm_fleet.yaml` remains the reusable PM Fleet definition and retains migration provenance from the historical hardcoded roster.
- Generic `expand_persona` plus Hive `services/agent_materialization.py` owns Workspace-scoped materialization.
- Generic `services/agent_invocation.py` resolves a requested spawn against that Workspace's materialized roster and preserves PM task-description behavior.
- PM capabilities, work-item draft gates, program context, curated `pm_fleet` project domain, and the `daily-status`/PM seed behavior remain unchanged.
- Generic/public tool-client surfaces exposed after deleting the PM runner remain real APIs; they are classified in the Vulture debt ledger rather than deleted to make the ratchet green.

### RETIRE

- Environment-selected PM executor switch in Hive demo mode.
- Hive private PM catalog.
- maistro-server private PM catalog.
- PM-runner event bridge.
- `maistro.agents.pm_fleet` adapter module.
- `maistro.agents.pm_runner` executor module.
- maistro-server's POC-only `/v1/maistro/agents` list/invoke API and its dedicated test surface.
- `maistro.tools.pm_stubs` fleet-demo fake tool handlers and their dedicated tests.

Deletion is intentional. Keeping any removed module, route, or fake handler registry as a compatibility surface would let restart/import recreate a second reusable roster or execution authority.

## Acceptance evidence

- New core retirement tests assert the packaged `pm_fleet` template is a Workspace Persona with the six migrated spawns, retains legacy-definition provenance, and that the legacy authority modules do not exist.
- New Hive retirement tests assert demo startup contains no retired POC environment/executor/catalog switch and still uses the canonical conductor executor.
- New maistro-server retirement tests assert startup cannot seed a PM POC catalog, task execution remains on the canonical conductor executor, and no `/v1/maistro/agents` route is registered.
- Existing `test_agent_invocation.py` continues to characterize Workspace-scoped resolution, capability refusal, description compatibility, and pulse-roster isolation without importing the retired executor.
- Generic DAG-run history remains; only the PM-runner-specific EventBus bridge is removed. Direct DAG route writes remain its live producer.
- The full Python suite reached 8,488 passed / 493 skipped / 1 xfailed during convergence before the final POC-stub deletion; subsequent required CI is the merge authority.
- `ruff check` is clean. A pinned repository-format run established the remaining Ruff-format delta was EOF-newline-only and normalized the eight affected files without semantic edits.

## Vulture debt reconciliation

Deleting PM-Fleet authority removes stale debt entries for the retired route handlers, hardcoded fleet symbol, private server catalog, and PM-runner functions. It also exposes package-public/declarative surfaces that had previously been kept alive incidentally by the retired runner. The candidate ledger records those exact identities under the existing rules rather than deleting valid APIs or weakening the checker.

The final reconciliation merged `develop@80b0d82794f15db970c61f7f915a46001b251b88`, applied exactly the Vulture identities reported by the exact-debt gate, and self-removed its temporary workflow before pushing. The resulting PR file set contains no temporary workflow and no shared reachability ledger or disposition file.

The reconciliation does not modify #721's ratchet checker/workflow implementation. In particular, this lane does not edit `quality/reachability-baseline.json`, `quality/reachability-dispositions.json`, or the reachability/provenance enforcement scripts.

## Expected shared-reachability decreases

This branch deliberately does **not** edit `quality/reachability-baseline.json`, `quality/reachability-dispositions.json`, or other shared reachability authority while #721 owns that lane. Expected follow-up shrinkage includes symbols/files formerly attributable to:

- `packages/maistro-core/src/maistro/agents/pm_fleet.py`
- `packages/maistro-core/src/maistro/agents/pm_runner.py`
- `packages/maistro-core/src/maistro/tools/pm_stubs.py`
- `packages/maistro-server/src/maistro_server/api/agents.py`
- `register_pm_fleet`
- `run_pm_task`
- `install_pm_event_bridge`
- the retired PM private EventBus hooks and PM executor helpers
- the retired PM-specific `/v1/maistro/agents` route family
- the retired fleet-demo fake tool-handler registry

The owning reachability-ratchet lane should reconcile those decreases from its then-current trusted base rather than this PR competing for the same shared files.

---
inventory-delta:
  packages/hive-conductor/backend/tests: -2
  packages/maistro-core/tests: -170
  tests/: -1
---
# M1 #129 PM-Fleet POC closeout inventory

## Suite inventory delta (retirement deletions)

The retirement deletes executable POC surfaces and their dedicated tests; the
inventory-delta above records the net collected-node-ID movement against the
rebased base (`develop@ecf062b3`):

- `packages/maistro-core/tests`: **-170** — dedicated tests for the deleted
  `agents/pm_runner`, `agents/pm_fleet`, `tools/pm_stubs` modules, the retired
  PM POC executor edge cases, and the one-shot ledger-diagnostic module
  removed with its reconciler.
- `packages/hive-conductor/backend/tests`: **-2** — the Program Pulse
  queue-path tests that monkeypatched the deleted `get_engine` submission
  path (`run_program_pulse` is proposal-only after retirement).
- `tests/`: **-1** — the root-tree direct-effects test for the retired
  `maistro.agents.pm_llm_call` model-helper seam.

No suite stopped collecting: every suite still collects and the numbers above
are deletions of retired-behavior tests, verified against
`develop@ecf062b365bbd87aceea92efbc5ddaea42d18bad`.

Initial reachability audit from `develop@93401f3485ebb815dedc1b0c6b7ad1d7e767fa32` on 2026-08-31. The branch was merged forward to `develop@80b0d82794f15db970c61f7f915a46001b251b88` before final merge validation.

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
8. `maistro.tools.pm_stubs` exposed a broad fleet-demo fake-handler registry used by the retired PM runner. Merge validation also proved one narrow behavior inside that module was still independently supported: `agents.work_items.confirm_post_stub()` used `stub_create_work_item()` for the user-confirmed work-item simulation path.
9. A final review found a subtler execution seam: after deleting `pm_runner`, Hive still accepted PM `agent_id`/`capability` metadata and sent the request to generic `conductor.run_task()`. That conductor ignores `agent_id`, `capability`, and `program_context`, so `poll_jira`, `web_search_background`, and other PM capabilities would have returned generic engineering plans shaped like successful PM work. That was a false-success compatibility path, not convergence.

## Disposition

### CONNECT / retain

- `personas/templates/pm_fleet.yaml` remains the reusable PM Fleet definition and retains migration provenance from the historical hardcoded roster.
- Generic `expand_persona` plus Hive `services/agent_materialization.py` owns Workspace-scoped materialization.
- Generic `services/agent_invocation.py` resolves a requested spawn against that Workspace's materialized roster and preserves human-readable PM task-description behavior for proposal/validation surfaces.
- PM capability names and policy remain as proposal, validation, and gated-work-item metadata. They no longer imply a private PM execution engine.
- Program context, curated `pm_fleet` project domain, `daily-status` seed behavior, Workspace-scoped Program Pulse proposals, and work-item draft/clarify/edit/confirm UX remain.
- `confirm_post_stub()` remains supported. The single deterministic Jira-create simulation it needs now lives as private `_stub_create_work_item()` inside `agents/work_items.py`; it owns no roster, catalog, identity, executor, event bus, or reusable agent-definition authority.
- Generic/public tool-client surfaces exposed after deleting the PM runner remain real APIs; they are classified in the Vulture debt ledger rather than deleted to make the ratchet green.

### RETIRE

- Environment-selected PM executor switch in Hive demo mode.
- Hive private PM catalog.
- maistro-server private PM catalog.
- PM-runner event bridge.
- `maistro.agents.pm_fleet` adapter module.
- `maistro.agents.pm_runner` executor module.
- maistro-server's POC-only `/v1/maistro/agents` list/invoke API and its dedicated test surface.
- The broad `maistro.tools.pm_stubs` fleet-demo module, `PM_STUB_HANDLERS` registry, and dedicated broad stub tests. Only the independently supported work-item-create behavior was retained at its live consumer.
- Direct or autonomous PM-capability execution through the generic task queue. `EngineService.submit_task()` now refuses known PM capabilities before backend submission instead of allowing `conductor.run_task()` to produce an unrelated generic plan.
- Program Pulse task execution formerly owned by `pm_runner`. Pulse remains Workspace-roster-aware and returns proposals/suggestions, but `queued` is empty with an explicit retirement note until canonical Graph execution owns these capabilities.
- The post-confirm downstream PM task after the explicit Jira stub. Confirmation still validates the Workspace Persona agent, performs the existing stub Jira post, persists the posted draft, and returns `task_id: null` plus an explicit execution-retired note rather than fabricating follow-up execution.

This is deliberate fail-closed retirement, not a replacement dispatcher. Re-implementing Jira/browser/PM-role execution inside Hive would create the new adapter authority #129 forbids and collide with the canonical Graph/DAG convergence lane. Existing canonical Graph node work (including Jira/Airtable execution paths) is left untouched.

## Acceptance evidence

- New core retirement tests assert the packaged `pm_fleet` template is a Workspace Persona with the six migrated spawns, retains legacy-definition provenance, and that the legacy fleet/runner authority modules do not exist.
- New Hive retirement tests assert demo startup contains no retired POC environment/executor/catalog switch and still uses the canonical conductor executor for genuinely generic tasks.
- New maistro-server retirement tests assert startup cannot seed a PM POC catalog, task execution remains on the canonical generic executor, and no `/v1/maistro/agents` route is registered.
- `test_pm_poc_execution_truthfulness.py` proves known PM capabilities fail closed before the generic backend, Program Pulse preserves proposals without queueing PM work, and work-item confirmation preserves the Jira stub while returning no downstream task.
- Existing `test_agent_invocation.py` continues to characterize Workspace-scoped resolution, capability refusal, description compatibility, and pulse-roster isolation without importing the retired executor.
- Existing `packages/maistro-core/tests/agents/test_work_items.py::test_confirm_posts_stub` characterizes the retained user-confirmed work-item simulation; CI caught the over-deletion and the implementation was narrowed to the one live behavior instead of restoring the POC handler module.
- Updated Hive Program Pulse and work-item route tests preserve Workspace context/roster authorization while asserting proposal-only / no-false-execution semantics.
- Generic DAG-run history remains; only the PM-runner-specific EventBus bridge is removed. Direct DAG route writes remain its live producer.
- During convergence the full Python suite reached 8,488 passed / 493 skipped / 1 xfailed before final semantic retirement; final required CI is the merge authority for the proposal-only closeout.
- A pinned repository-format pass repaired earlier EOF-only formatting drift; final CI owns Ruff formatting for the last semantic patch.

## Quality-ledger reconciliation

Deleting PM-Fleet authority removes stale Vulture entries for retired route handlers, the hardcoded fleet symbol, private server catalog, and PM-runner functions. It also exposes package-public/declarative surfaces that had previously been kept alive incidentally by the retired runner. The Vulture ledger records those exact identities under the existing rules rather than deleting valid APIs or weakening the checker.

The branch also prunes exactly three stale Radon complexity identities corresponding to the deleted implementations:

- `packages/maistro-core/src/maistro/agents/pm_fleet.py::build_task_description`
- `packages/maistro-core/src/maistro/agents/pm_runner.py::_run_browser_driven`
- `packages/maistro-core/src/maistro/agents/pm_runner.py::run_pm_task`

No new Radon debt was added.

The convergence merge brought in `develop@80b0d82794f15db970c61f7f915a46001b251b88`. Temporary reconciliation/repair workflows self-removed before their result commits were treated as merge candidates. The resulting PR file set contains no temporary workflow and no shared reachability ledger or disposition file.

This lane does not modify #721's reachability ratchet checker/workflow implementation. In particular, it does not edit `quality/reachability-baseline.json`, `quality/reachability-dispositions.json`, or the reachability/provenance enforcement scripts.

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
- retired Program Pulse credential plumbing that existed only to feed `pm_runner`

The owning reachability-ratchet lane should reconcile those decreases from its then-current trusted base rather than this PR competing for the same shared files.

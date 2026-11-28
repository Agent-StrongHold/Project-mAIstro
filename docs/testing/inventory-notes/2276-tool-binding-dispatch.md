---
inventory-delta:
  packages/hive-conductor/backend/tests: +5
---

# 2276 — Apply Workspace tool_bindings at agent dispatch

Wires `services.tool_binding` into:

- `agent_invocation._capabilities_of` (pulse + `resolve_agent_task` gate)
- `agent_materialization._build_runtime_agent` (runtime tools + prompt fragment)

Adds presentation-store helpers `binding_tools_override` /
`binding_prompt_fragment`. Tests: four dispatch ACs in
`test_agent_invocation.py` + one override-store read in `test_tool_binding.py`.

**Local validation evidence (2026-11-28 re-verification round, head
`ab19f5dd5909533fc85a4c65eeb14ac764c4342f`).** Independent re-run of the
merged #2286 wiring, not taken from the implementing round's claims:

- `pytest packages/hive-conductor/backend/tests/test_tool_binding.py
  packages/hive-conductor/backend/tests/test_agent_invocation.py
  packages/hive-conductor/backend/tests/test_agent_materialization.py -q`
  → 65 passed (binding resolver + dispatch-gate + runtime-soul append tests
  all green).
- `pytest packages/hive-conductor/backend/tests -q` → 4655 passed,
  121 skipped (whole backend tree, no cross-suite interference).
- **Red-check re-proven without tree edits**: a scratch driver against the
  real production modules — with a sticky binding `["run_build"]` on
  `ws-1.builder`, `resolve_agent_task("builder", "deploy")` raises
  `ValueError: Capability 'deploy' not valid for builder`; rebinding
  `binding_tools_override` to return `None` (the regression: dispatch
  ignoring the binding) lets the same invoke through, so the dispatch tests
  fail against exactly the regression they name; `[]` vs `None` distinction
  (`narrow to zero` vs `no sticky binding`) asserted on the real store.
- Gates, CI's exact arguments: `uv run ruff check .` clean; `uv run ruff
  format --check .` (3732 files) clean; `python scripts/check-suite-inventory.py`
  ok (21 suites match; required `uv sync --locked --extra dev` in the fresh
  worktree venv first — extension suites otherwise fail collection, which is
  an environment gap, not inventory drift); `uv run python
  scripts/check-reachability.py` clean (1531 production modules, 81
  unreachable — `services.tool_binding` reachable from dispatch).
- AC coverage confirmed against reachable production behavior: AC-1 gate
  refusal (`agent_invocation._capabilities_of` binding override +
  `resolve_agent_task` ValueError); AC-2 `tools: []` wins before persona/
  `defn.capabilities` in both dispatch sites, and `factory.instantiate_agent`
  wires no `tool_executor` at all when `identity.tools` is empty; AC-3
  fragment appended in `_build_runtime_agent`'s upserted soul body;
  AC-4 binding lookup keyed by `workspace_id` + `agent_id`
  (`test_foreign_workspace_binding_does_not_affect_this_roster`); AC-5 UI
  (`PUT /v1/workspaces/{id}/tool-bindings` from `WorkspaceToolBindings.tsx`)
  and API both land in `workspace_authority.update_presentation` →
  `presentation_store()`, the one store dispatch resolvers read; AC-6 the
  four required scenarios are the tests named above.
- Issue's "sandbox NodeRun scope alignment where applicable": not applicable
  as a binding enforcement point — the sandbox executor
  (`hyperlight_executor`) is code-execution isolation, not a tool provider;
  graph NodeRun agent delegation resolves agents through the same container
  agent map built from binding-aware `_build_runtime_agent`, so dispatch
  there already honors bindings via the one runtime path. Persona templates
  are never mutated by bindings (overrides only).

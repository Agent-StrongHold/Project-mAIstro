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

---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/hive-conductor/backend/tests: +37
  tests/: +16
---

# #840 — agent roster authority (hive-conductor + maistro-core)

Implements the #840 design slices on one lane: the bridge stops rebinding
`container.agents`; every `stores.agents` writer moves behind
`services/agent_materialization.py`; the demo seed is scoped to demo mode
while boot materializes the canonical manifest roster; stored definitions
(Forge, chat tools) materialize into the runtime map; and the factory's
`tool_executor` seam is closed with an explicit, real executor.

Slices 1-3 (+16 `tests/`, +21 `packages/hive-conductor/backend/tests`, +0
`packages/maistro-core/tests`): +1 bridge test resolving through the real
`_wire_hierarchy` closure; +6 chat-created-agent tests pinning
dispatchability, the Warden scan verdict in provenance, deterministic upsert
ids, workspace scoping, and fail-closed refusals; +16 gate tests for
`scripts/check-agent-store-writes.py`, including an integration run over
this tree; +11 manifest/boot/seeding tests (global-row equivalence with the
canonical roster, idempotent upsert with stale-row reap, non-dispatchable
stamping without a bridge, the fail-closed no-roster contract, demo/PM-POC
no-ops, and demo-mode-only seeding); +3 dispatch-invariant tests proving
workspace-first precedence, spawn-name resolution, and capability refusals
hold with manifest rows in the store.

Slice 4 (+13 `packages/hive-conductor/backend/tests`): definitions get their
runtime half. +6 service tests for `materialize_runtime` (a real maistro
`Agent` built through the factory's single `instantiate_agent` path with the
identity the row declares, the soul prompt upserted behind the PREAMBLE,
in-place mutation proved against maistro's own `_wire_hierarchy` closure,
replace-on-re-materialize, chat-shaped direct strategy, and the two honest
failure shapes — no-runtime stamping and the refused-definition narrow path
via delegate-without-sub-agents); +4 forge route tests (artifact → runtime
map with the forged strategy, non-dispatchable stamp without a runtime, the
delegate refusal, and idempotent re-forge re-materializing the process-local
runtime half); +2 chat-tool tests (materialization with a bridge plus the
new `agent_chat_created` audit entry, and the non-dispatchable stamp without
one); +1 adapter test pinning that the bridge registers the runtime it built
(container, llm client, real shipped PREAMBLE) on the materialization seam.

Slice 5 (+2 `packages/maistro-core/tests`, +3
`packages/hive-conductor/backend/tests`): the factory's `tool_executor` seam
is closed and pinned. +2 factory tests in `test_factory_tool_executor.py` —
`create_agents(..., tool_executor=...)` reaches agents whose identities
declare tools and forwards through `_run_strategy` into the strategy loop,
and a manifest with declared tools but no executor REFUSES tool calls with
the `Tool '<name>' not available` result (driven through the real react
loop over a FauxProvider — a refusal string, not an exception, never an
execution); +3 dispatcher tests in `test_tool_dispatch.py` for the
`(tool_name, tool_args)` adapter the bridge now passes (unknown names refuse
with the same contract string, known names route to the real tool
functions, unusable arguments return an error result instead of raising).
